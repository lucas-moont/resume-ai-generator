import json
import unittest

from app.domain.schemas import ProposalItem
from app.models import ResumeDocument
from app.services.llm.resume_json_parser import parse_resume_json


class OllamaParserTests(unittest.TestCase):
    def test_normalizes_non_schema_payload_and_keeps_required_fields(self) -> None:
        fallback = ResumeDocument(
            fullName="Kevvan",
            headline="Fullstack Developer",
            summary="Resumo base",
            locale="pt-BR",
        )
        raw = json.dumps(
            {
                "projects": {
                    "data/projects/": [
                        {
                            "name": "Projeto Alpha",
                            "description": "Projeto em Node.js",
                            "stack": ["Node.js", "TypeScript"],
                        }
                    ]
                },
                "locale": {"language": "pt-BR", "labels": True},
            }
        )

        parsed = parse_resume_json(raw, fallback, refine=False)

        self.assertEqual(parsed.fullName, "Kevvan")
        self.assertEqual(parsed.headline, "Fullstack Developer")
        self.assertEqual(parsed.summary, "Resumo base")
        self.assertEqual(parsed.locale, "pt-BR")
        self.assertEqual(len(parsed.projects), 1)
        self.assertEqual(parsed.projects[0].name, "Projeto Alpha")
        self.assertEqual(parsed.projects[0].description, "Projeto em Node.js")

    def test_normalizes_skill_objects_and_education_aliases(self) -> None:
        fallback = ResumeDocument(
            fullName="Kevvan",
            headline="Fullstack Developer",
            summary="Resumo base",
            locale="pt-BR",
        )
        raw = json.dumps(
            {
                "name": "KEVVAN",
                "title": "Resume",
                "skills": [
                    {"skill": "Node.js", "level": "Proficiente"},
                    {"name": "React"},
                ],
                "education": [
                    {"school": "Escola Publica", "course": "Ensino Medio", "date": "2010-2014"}
                ],
            }
        )

        parsed = parse_resume_json(raw, fallback, refine=False)

        # Canonical name is preserved: the LLM must not rename the candidate.
        self.assertEqual(parsed.fullName, "Kevvan")
        self.assertEqual(parsed.headline, "Fullstack Developer")
        # Profile has no skills, so PDF/LLM-sourced skills pass through.
        self.assertEqual(parsed.skills, ["Node.js", "React"])
        self.assertEqual(parsed.education[0].institution, "Escola Publica")
        self.assertEqual(parsed.education[0].degree, "Ensino Medio")
        self.assertEqual(parsed.education[0].end, "2010-2014")

    def test_skills_plain_and_prose_allows_safe_html(self) -> None:
        fallback = ResumeDocument(
            fullName="Kevvan",
            headline="Dev",
            summary="Base",
            locale="pt-BR",
        )
        raw = json.dumps(
            {
                "skills": ['**React**', "'TypeScript'", "`Node.js`"],
                "summary": "Uses **Next.js** daily.",
                "experience": [
                    {
                        "company": "Acme",
                        "title": "Eng",
                        "start": "2020",
                        "end": None,
                        "highlights": ["Built **API** gateway"],
                    }
                ],
            }
        )
        parsed = parse_resume_json(raw, fallback, refine=False)
        self.assertEqual(parsed.skills, ["React", "TypeScript", "Node.js"])
        self.assertEqual(parsed.summary, "Uses <strong>Next.js</strong> daily.")
        self.assertEqual(parsed.experience[0].highlights, ["Built <strong>API</strong> gateway"])

    def test_normalizes_experience_with_null_company(self) -> None:
        fallback = ResumeDocument(
            fullName="Kevvan",
            headline="Fullstack Developer",
            summary="Resumo base",
            locale="pt-BR",
        )
        raw = json.dumps(
            {
                "experience": [
                    {"company": None, "title": "Developer", "start": "2023-01", "highlights": ["Built APIs"]},
                    {"employer": "Acme", "role": "Engineer", "from": "2022-01", "description": "Platform team"},
                ]
            }
        )

        parsed = parse_resume_json(raw, fallback, refine=False)

        self.assertEqual(parsed.experience[0].company, "")
        self.assertEqual(parsed.experience[0].title, "Developer")
        self.assertEqual(parsed.experience[1].company, "Acme")
        self.assertEqual(parsed.experience[1].title, "Engineer")

    def test_extracts_email_alias_and_preserves_canonical_contact(self) -> None:
        seed = ResumeDocument(fullName="", headline="", summary="", locale="pt-BR")
        raw = json.dumps(
            {
                "fullName": "Kevvan",
                "headline": "Dev",
                "summary": "Base",
                "emailAddress": "kevvan@example.com",
            }
        )
        parsed = parse_resume_json(raw, seed, refine=False)
        self.assertEqual(parsed.email, "kevvan@example.com")

        fallback = ResumeDocument(
            fullName="Kevvan",
            headline="Dev",
            summary="Base",
            email="canonical@example.com",
            locale="pt-BR",
        )
        raw2 = json.dumps({"email": "hallucinated@example.com"})
        parsed2 = parse_resume_json(raw2, fallback, refine=False)
        self.assertEqual(parsed2.email, "canonical@example.com")

    def test_preserves_personal_location_and_merges_links_and_skills(self) -> None:
        fallback = ResumeDocument(
            fullName="Kevvan",
            headline="Fullstack Developer",
            summary="Resumo base",
            location="São Paulo, BR",
            links=[
                {"label": "LinkedIn", "url": "https://linkedin.com/in/kevvan"},
                {"label": "GitHub", "url": "https://github.com/kevvan"},
                {"label": "Portfolio", "url": "https://kevvan.dev"},
            ],
            skills=["TypeScript", "React", "Tailwind"],
            locale="pt-BR",
        )
        raw = json.dumps(
            {
                "location": "Remote",
                "links": [{"label": "LinkedIn", "url": "https://linkedin.com/in/kevvan"}],
                "skills": ["English", "React", "Node.js"],
            }
        )

        parsed = parse_resume_json(raw, fallback, refine=False)

        self.assertEqual(parsed.location, "São Paulo, BR")
        self.assertIn("GitHub", [l.label for l in parsed.links])
        self.assertIn("Portfolio", [l.label for l in parsed.links])
        # Profile already lists skills, so only its own skills survive (React matches, reordered
        # first); a skill the model invents ("Node.js") is dropped, and languages are filtered.
        self.assertEqual(parsed.skills[0], "React")
        self.assertIn("TypeScript", parsed.skills)
        self.assertIn("Tailwind", parsed.skills)
        self.assertNotIn("Node.js", parsed.skills)
        self.assertNotIn("English", parsed.skills)

    def test_generate_anchors_structure_to_profile_and_drops_fabrications(self) -> None:
        fallback = ResumeDocument(
            fullName="Lucas Monteiro",
            headline="Full Stack Developer",
            summary="Base summary",
            phone="+55 11 90000-0000",
            skills=["JavaScript", "React", "Node.js"],
            experience=[
                {
                    "company": "SmartHow",
                    "title": "Front-End Developer",
                    "start": "2025",
                    "end": None,
                    "highlights": ["Original bullet"],
                }
            ],
            education=[{"institution": "Cruzeiro do Sul", "degree": "ADS", "end": "2022"}],
            locale="en",
        )
        raw = json.dumps(
            {
                "fullName": "John Doe",
                "phone": "(555) 123-4567",
                "headline": "Senior Full Stack Developer",
                "summary": "Tailored summary for the job.",
                "experience": [
                    {
                        "company": "SmartHow",
                        "title": "Front-End Developer",
                        "start": "2025",
                        "end": "Present",
                        "highlights": ["Rewritten, tailored bullet about React"],
                    },
                    {
                        "company": "TechCorp Solutions",
                        "title": "Senior Engineer",
                        "start": "2019",
                        "highlights": ["Fabricated role"],
                    },
                ],
                "education": [{"institution": "UC Berkeley", "degree": "B.S. CS", "end": "2016"}],
                "skills": ["React", "Python", "Express"],
            }
        )

        parsed = parse_resume_json(raw, fallback, refine=False)

        # Identity is canonical; fabricated name/phone are ignored.
        self.assertEqual(parsed.fullName, "Lucas Monteiro")
        self.assertEqual(parsed.phone, "+55 11 90000-0000")
        # Prose is adopted from the LLM.
        self.assertEqual(parsed.headline, "Senior Full Stack Developer")
        self.assertEqual(parsed.summary, "Tailored summary for the job.")
        # Only the real role remains, with its rewritten bullets; the fabricated one is dropped.
        self.assertEqual(len(parsed.experience), 1)
        self.assertEqual(parsed.experience[0].company, "SmartHow")
        self.assertEqual(parsed.experience[0].highlights, ["Rewritten, tailored bullet about React"])
        # Fabricated education is dropped in favor of the canonical entry.
        self.assertEqual(len(parsed.education), 1)
        self.assertEqual(parsed.education[0].institution, "Cruzeiro do Sul")
        # Invented skills (Python, Express) are dropped; real ones are kept.
        self.assertNotIn("Python", parsed.skills)
        self.assertNotIn("Express", parsed.skills)
        self.assertEqual(parsed.skills[0], "React")
        self.assertIn("JavaScript", parsed.skills)
        self.assertIn("Node.js", parsed.skills)


    def test_generate_does_not_fill_contact_from_tailoring_llm(self) -> None:
        fallback = ResumeDocument(
            fullName="Lucas Monteiro",
            headline="Full Stack Developer",
            summary="Base summary long enough to keep.",
            phone=None,
            email="real@example.com",
            locale="en",
        )
        raw = json.dumps(
            {
                "phone": "(555) 123-4567",
                "email": "fake@doe.com",
                "summary": "Tailored summary.",
            }
        )
        parsed = parse_resume_json(raw, fallback, refine=False)
        # A tailoring pass must never introduce contact details.
        self.assertIsNone(parsed.phone)
        self.assertEqual(parsed.email, "real@example.com")

    def test_generate_falls_back_to_profile_prose_when_no_role_matches(self) -> None:
        fallback = ResumeDocument(
            fullName="Lucas Monteiro",
            headline="Front-End Developer",
            summary="Truthful base summary with enough words to be kept intact.",
            experience=[
                {"company": "SmartHow", "title": "Front-End Developer", "start": "2025", "highlights": ["Real bullet"]}
            ],
            locale="en",
        )
        raw = json.dumps(
            {
                "headline": "Senior Cloud Architect",
                "summary": "Inflated summary with 10+ years and fabricated AWS microservices claims.",
                "experience": [
                    {"company": "TechCorp", "title": "Senior Engineer", "start": "2015", "highlights": ["Fake"]}
                ],
            }
        )
        parsed = parse_resume_json(raw, fallback, refine=False)
        # Model ignored the real role, so its prose is discarded in favor of the profile's.
        self.assertEqual(parsed.headline, "Front-End Developer")
        self.assertEqual(parsed.summary, "Truthful base summary with enough words to be kept intact.")
        self.assertEqual(len(parsed.experience), 1)
        self.assertEqual(parsed.experience[0].company, "SmartHow")
        self.assertEqual(parsed.experience[0].highlights, ["Real bullet"])

    def test_generate_matches_same_company_roles_by_start_date_and_adopts_translated_title(
        self,
    ) -> None:
        # Regression test for two confirmed bugs: (1) same-company roles (two stints at
        # "Savvi") both falling through to the same company-only patch match and duplicating
        # highlights, and (2) the LLM's translated title being discarded in favor of the
        # profile's English one. Matching by company + start date fixes both.
        fallback = ResumeDocument(
            fullName="Lucas Monteiro",
            headline="Full Stack Developer",
            summary="Base summary long enough to keep.",
            experience=[
                {
                    "company": "Savvi",
                    "title": "Full Stack Developer",
                    "start": "2021-06",
                    "end": "2025-04",
                    "highlights": ["Original senior bullet"],
                },
                {
                    "company": "Savvi",
                    "title": "Development Intern",
                    "start": "2021-01",
                    "end": "2021-06",
                    "highlights": ["Original intern bullet"],
                },
            ],
            locale="pt-BR",
        )
        raw = json.dumps(
            {
                "headline": "Desenvolvedor Full Stack",
                "summary": "Resumo adaptado para a vaga.",
                "experience": [
                    {
                        "company": "Savvi",
                        "title": "Desenvolvedor Full Stack",
                        "start": "2021-06",
                        "end": "2025-04",
                        "highlights": ["Liderei o desenvolvimento de um e-commerce"],
                    },
                    {
                        "company": "Savvi",
                        "title": "Estagiário de Desenvolvimento",
                        "start": "2021-01",
                        "end": "2021-06",
                        "highlights": ["Apoiei o desenvolvimento de projetos web para clientes"],
                    },
                ],
            }
        )

        parsed = parse_resume_json(raw, fallback, refine=False)

        self.assertEqual(len(parsed.experience), 2)
        senior, intern = parsed.experience[0], parsed.experience[1]
        # Company/dates stay anchored to the profile.
        self.assertEqual(senior.company, "Savvi")
        self.assertEqual(senior.start, "2021-06")
        self.assertEqual(intern.company, "Savvi")
        self.assertEqual(intern.start, "2021-01")
        # Translated titles are adopted.
        self.assertEqual(senior.title, "Desenvolvedor Full Stack")
        self.assertEqual(intern.title, "Estagiário de Desenvolvimento")
        # Each role keeps its own distinct highlights -- no duplication across same-company roles.
        self.assertEqual(senior.highlights, ["Liderei o desenvolvimento de um e-commerce"])
        self.assertEqual(
            intern.highlights, ["Apoiei o desenvolvimento de projetos web para clientes"]
        )
        self.assertNotEqual(senior.highlights, intern.highlights)


class AnchorAgreedImprovementsTests(unittest.TestCase):
    """v4 ticket QA-04: the anchor's skill/project restrictions are relaxed ONLY for what the
    user actually approved in an Improvement Proposal (``agreed_improvements``), and ONLY
    when that argument is present at all -- omitting it must reproduce the pre-QA-04 behavior
    byte-for-byte (pinned below by calling the very same patch twice)."""

    def test_agreed_skills_item_admits_a_patch_skill_outside_the_profile(self) -> None:
        fallback = ResumeDocument(
            fullName="Lucas Monteiro",
            headline="Full Stack Developer",
            summary="Base summary long enough to satisfy every unrelated anchor check here.",
            skills=["JavaScript", "React"],
            locale="en",
        )
        raw = json.dumps({"skills": ["React", "FastAPI"]})
        agreed = [
            ProposalItem(
                id=1,
                section="skills",
                proposed="Adicionar experiência com FastAPI ao currículo.",
                rationale="A vaga pede FastAPI.",
            )
        ]

        parsed = parse_resume_json(raw, fallback, refine=False, agreed_improvements=agreed)
        self.assertIn("FastAPI", parsed.skills)

        # Same patch, no agreed_improvements -- current (pre-QA-04) behavior is unchanged.
        parsed_without_plan = parse_resume_json(raw, fallback, refine=False)
        self.assertNotIn("FastAPI", parsed_without_plan.skills)

    def test_agreed_skills_item_does_not_admit_a_skill_it_never_mentions(self) -> None:
        # Adversarial: the LLM pastes in a skill that was never part of the approved plan --
        # it must still be discarded even though agreed_improvements IS present.
        fallback = ResumeDocument(
            fullName="Lucas Monteiro",
            headline="Full Stack Developer",
            summary="Base summary long enough to satisfy every unrelated anchor check here.",
            skills=["JavaScript", "React"],
            locale="en",
        )
        raw = json.dumps({"skills": ["React", "Kubernetes"]})
        agreed = [
            ProposalItem(
                id=1,
                section="skills",
                proposed="Adicionar experiência com FastAPI ao currículo.",
                rationale="A vaga pede FastAPI.",
            )
        ]

        parsed = parse_resume_json(raw, fallback, refine=False, agreed_improvements=agreed)
        self.assertNotIn("Kubernetes", parsed.skills)

    def test_agreed_projects_item_reorders_projects_to_the_patch_order(self) -> None:
        fallback = ResumeDocument(
            fullName="Lucas Monteiro",
            headline="Full Stack Developer",
            summary="Base summary long enough to satisfy every unrelated anchor check here.",
            projects=[
                {"name": "Alpha", "description": "Original alpha description."},
                {"name": "Beta", "description": "Original beta description."},
            ],
            locale="en",
        )
        raw = json.dumps(
            {
                "projects": [
                    {"name": "Beta", "description": "Rewritten beta description for the job."},
                    {"name": "Alpha", "description": "Rewritten alpha description for the job."},
                ]
            }
        )
        agreed = [
            ProposalItem(
                id=1,
                section="projects",
                proposed="Reordenar para destacar o projeto Beta primeiro.",
                rationale="A vaga valoriza o projeto Beta.",
            )
        ]

        parsed = parse_resume_json(raw, fallback, refine=False, agreed_improvements=agreed)
        self.assertEqual([p.name for p in parsed.projects], ["Beta", "Alpha"])
        self.assertEqual(parsed.projects[0].description, "Rewritten beta description for the job.")

        # CHANGED in v6: the approved "projects" item is no longer what unlocks the patch's
        # order. Selection (and therefore ordering, its degenerate case) is now always the
        # LLM's to make within the profile's own set, so the same patch reorders with or
        # without an approved item -- the two branches this used to distinguish collapsed
        # into one. See ProjectSelectionTests for the selection behavior itself.
        parsed_without_item = parse_resume_json(raw, fallback, refine=False)
        self.assertEqual([p.name for p in parsed_without_item.projects], ["Beta", "Alpha"])
        self.assertEqual(
            {p.name for p in parsed.projects}, {p.name for p in parsed_without_item.projects}
        )



class AnchorRelevanceFilterTests(unittest.TestCase):
    """v6 (Relevance Filter): an approved ``op="drop"`` item is the ONLY thing that lets the
    anchor shrink the profile's own set of skills/projects.

    Before v6 the anchor was no-drop by construction -- its skill tail pass re-appended every
    profile skill the LLM left out, and its project loop iterated the profile's set -- so a
    resume tailored for a backend job still carried the candidate's whole analytics stack no
    matter what the LLM decided. Every test here that passes ``agreed_improvements`` also asserts
    the SAME patch with the argument omitted keeps the pre-v6 behavior, so "never invent" and
    "never omit" stay separable rather than re-fused by a later change.
    """

    def _profile(self) -> ResumeDocument:
        return ResumeDocument(
            fullName="Lucas Monteiro",
            headline="Full Stack Developer",
            summary="Base summary long enough to satisfy every unrelated anchor check here.",
            skills=[
                "Python",
                "FastAPI",
                "PostgreSQL",
                "React",
                "TypeScript",
                "Docker",
                "Google Analytics",
                "Power BI",
            ],
            locale="en",
        )

    def _drop_skills(self, *targets: str) -> list[ProposalItem]:
        return [
            ProposalItem(
                id=1,
                section="skills",
                op="drop",
                current=", ".join(targets),
                proposed="Remover ferramentas de analytics da lista de skills.",
                targets=list(targets),
                rationale="A vaga não menciona analytics ou BI em nenhum requisito.",
            )
        ]

    def test_approved_skill_drop_removes_it_even_though_the_llm_returned_it(self) -> None:
        # The adversarial case, and the one the user actually reported: the LLM re-emits the
        # noise. The drop has to win over BOTH the patch and the tail pass.
        fallback = self._profile()
        raw = json.dumps({"skills": ["Python", "FastAPI", "Google Analytics", "Power BI"]})
        agreed = self._drop_skills("Google Analytics", "Power BI")

        parsed = parse_resume_json(raw, fallback, refine=False, agreed_improvements=agreed)

        self.assertNotIn("Google Analytics", parsed.skills)
        self.assertNotIn("Power BI", parsed.skills)
        self.assertIn("Python", parsed.skills)
        self.assertIn("Docker", parsed.skills)  # untargeted profile skill still returns

    def test_approved_skill_drop_survives_the_tail_pass_when_the_llm_omitted_it(self) -> None:
        # The regression that made the bug invisible: the LLM does the right thing, and the tail
        # pass silently undoes it.
        fallback = self._profile()
        raw = json.dumps({"skills": ["Python", "FastAPI", "PostgreSQL", "Docker"]})
        agreed = self._drop_skills("Google Analytics", "Power BI")

        parsed = parse_resume_json(raw, fallback, refine=False, agreed_improvements=agreed)
        self.assertNotIn("Google Analytics", parsed.skills)

        parsed_without_plan = parse_resume_json(raw, fallback, refine=False)
        self.assertIn("Google Analytics", parsed_without_plan.skills)

    def test_drop_matches_the_exact_label_not_a_substring_of_it(self) -> None:
        # "Analytics" must survive a drop aimed at "Google Analytics": the target set is matched
        # by skill_token equality, never by the substring blob the *admit* direction uses.
        fallback = ResumeDocument(
            fullName="Lucas Monteiro",
            headline="Full Stack Developer",
            summary="Base summary long enough to satisfy every unrelated anchor check here.",
            skills=["Python", "FastAPI", "PostgreSQL", "React", "Analytics", "Google Analytics"],
            locale="en",
        )
        raw = json.dumps({"skills": ["Python", "FastAPI"]})

        parsed = parse_resume_json(
            raw, fallback, refine=False, agreed_improvements=self._drop_skills("Google Analytics")
        )

        self.assertNotIn("Google Analytics", parsed.skills)
        self.assertIn("Analytics", parsed.skills)

    def test_drop_is_abandoned_wholesale_when_it_would_leave_too_few_skills(self) -> None:
        # MIN_SKILLS_AFTER_DROPS: a resume with 2 skills is worse than one carrying some noise,
        # and the fallback is all-or-nothing so the outcome stays explainable.
        fallback = ResumeDocument(
            fullName="Lucas Monteiro",
            headline="Full Stack Developer",
            summary="Base summary long enough to satisfy every unrelated anchor check here.",
            skills=["Python", "FastAPI", "Google Analytics", "Power BI"],
            locale="en",
        )
        raw = json.dumps({"skills": ["Python", "FastAPI"]})

        parsed = parse_resume_json(
            raw,
            fallback,
            refine=False,
            agreed_improvements=self._drop_skills("Google Analytics", "Power BI"),
        )

        self.assertIn("Google Analytics", parsed.skills)
        self.assertIn("Power BI", parsed.skills)

    def test_approved_project_drop_removes_the_project_from_the_set(self) -> None:
        fallback = ResumeDocument(
            fullName="Lucas Monteiro",
            headline="Full Stack Developer",
            summary="Base summary long enough to satisfy every unrelated anchor check here.",
            projects=[
                {"name": "Trading API", "description": "Low-latency order routing in Python."},
                {"name": "Marketing Dashboard", "description": "GA4 funnels in Looker Studio."},
            ],
            locale="en",
        )
        raw = json.dumps({"projects": [{"name": "Trading API", "description": "Order routing."}]})
        agreed = [
            ProposalItem(
                id=1,
                section="projects",
                op="drop",
                current="Marketing Dashboard",
                proposed="Remover o projeto Marketing Dashboard.",
                targets=["Marketing Dashboard"],
                rationale="A vaga é de engenharia backend e não menciona marketing.",
            )
        ]

        parsed = parse_resume_json(raw, fallback, refine=False, agreed_improvements=agreed)
        self.assertEqual([p.name for p in parsed.projects], ["Trading API"])

        # This test originally also asserted that WITHOUT the plan the project survived. That
        # stopped being the drop's doing once project selection was honored (v6): here the LLM
        # simply did not select it, which is now enough on its own. What the approved drop still
        # adds is a veto that outranks selection -- pinned by
        # ProjectSelectionTests::test_an_approved_drop_still_removes_a_project_the_llm_selected,
        # where the model DOES select the dropped project and it is removed anyway.
        selected_it_back = json.dumps(
            {
                "projects": [
                    {"name": "Marketing Dashboard", "description": "GA4 funnels."},
                    {"name": "Trading API", "description": "Order routing."},
                ]
            }
        )
        without_plan = parse_resume_json(selected_it_back, fallback, refine=False)
        self.assertIn("Marketing Dashboard", [p.name for p in without_plan.projects])
        with_plan = parse_resume_json(
            selected_it_back, fallback, refine=False, agreed_improvements=agreed
        )
        self.assertNotIn("Marketing Dashboard", [p.name for p in with_plan.projects])

    def test_dropping_every_project_never_promotes_a_fabricated_one(self) -> None:
        # The `else` branch of the projects block is the PDF/seed passthrough. A drop that empties
        # the set must not fall into it, or the anchor's guarantee inverts: real projects out,
        # invented one in.
        fallback = ResumeDocument(
            fullName="Lucas Monteiro",
            headline="Full Stack Developer",
            summary="Base summary long enough to satisfy every unrelated anchor check here.",
            projects=[{"name": "Marketing Dashboard", "description": "GA4 funnels."}],
            locale="en",
        )
        raw = json.dumps({"projects": [{"name": "Invented Project", "description": "Not real."}]})
        agreed = [
            ProposalItem(
                id=1,
                section="projects",
                op="drop",
                current="Marketing Dashboard",
                proposed="Remover o projeto Marketing Dashboard.",
                targets=["Marketing Dashboard"],
                rationale="A vaga é de engenharia backend e não menciona marketing.",
            )
        ]

        parsed = parse_resume_json(raw, fallback, refine=False, agreed_improvements=agreed)
        self.assertEqual(parsed.projects, [])

    def test_no_approved_drop_can_remove_an_employer_or_a_degree(self) -> None:
        # The Relevance Filter never opens a timeline gap: an experience/education drop item is
        # simply inert in the anchor (the prompt is what compresses an off-topic role instead).
        fallback = ResumeDocument(
            fullName="Lucas Monteiro",
            headline="Full Stack Developer",
            summary="Base summary long enough to satisfy every unrelated anchor check here.",
            experience=[
                {
                    "company": "Savvi",
                    "title": "Full Stack Developer",
                    "start": "2023-01",
                    "end": None,
                    "highlights": ["Built the billing service in Python."],
                }
            ],
            education=[{"institution": "UFU", "degree": "Systems Analysis", "end": "2022"}],
            locale="en",
        )
        raw = json.dumps({"experience": [], "education": []})
        agreed = [
            ProposalItem(
                id=1,
                section="experience",
                op="drop",
                current="Savvi",
                proposed="Remover a experiência na Savvi.",
                targets=["Savvi"],
                rationale="A vaga não tem relação com o trabalho feito lá.",
            ),
            ProposalItem(
                id=2,
                section="education",
                op="drop",
                current="UFU",
                proposed="Remover a formação.",
                targets=["UFU"],
                rationale="A vaga não pede diploma.",
            ),
        ]

        parsed = parse_resume_json(raw, fallback, refine=False, agreed_improvements=agreed)

        self.assertEqual([e.company for e in parsed.experience], ["Savvi"])
        self.assertEqual([e.institution for e in parsed.education], ["UFU"])

    def test_a_rewrite_item_never_drops_anything_even_naming_targets(self) -> None:
        # Only `op == "drop"` subtracts. A rewrite that happens to carry targets (or a pre-v6
        # item, which decodes to a rewrite with none) leaves the set alone.
        fallback = self._profile()
        raw = json.dumps({"skills": ["Python", "FastAPI"]})
        agreed = [
            ProposalItem(
                id=1,
                section="skills",
                current="Google Analytics",
                proposed="Reordenar as skills priorizando Python e FastAPI.",
                targets=["Google Analytics"],
                rationale="A vaga pede Python e FastAPI em primeiro lugar.",
            )
        ]

        parsed = parse_resume_json(raw, fallback, refine=False, agreed_improvements=agreed)
        self.assertIn("Google Analytics", parsed.skills)


class LocaleAuthorityTests(unittest.TestCase):
    """v6: when the caller has authority over the language, the LLM's own claim never wins.

    Before v6 ``patch["locale"]`` was adopted unconditionally in BOTH directions — so a model
    that decided to answer in the wrong language also got to relabel the document as that
    language, leaving nothing downstream able to tell a mistake from a choice. 8 resume versions
    in the local DB ended up labelled ``en-US``, which is not even a locale this app writes.
    """

    def _profile(self) -> ResumeDocument:
        return ResumeDocument(
            fullName="Lucas Monteiro",
            headline="Full Stack Developer",
            summary="Base summary long enough to satisfy every unrelated anchor check here.",
            skills=["Python", "FastAPI"],
            locale="pt-BR",
        )

    def test_generate_pins_the_locale_the_server_resolved(self) -> None:
        raw = json.dumps({"headline": "Full Stack Developer", "locale": "en"})
        parsed = parse_resume_json(raw, self._profile(), refine=False, expected_locale="pt-BR")
        self.assertEqual(parsed.locale, "pt-BR")

    def test_generate_without_an_expected_locale_still_follows_the_llm(self) -> None:
        # Additive: omitting the argument reproduces pre-v6 behavior exactly.
        raw = json.dumps({"headline": "Full Stack Developer", "locale": "en"})
        parsed = parse_resume_json(raw, self._profile(), refine=False)
        self.assertEqual(parsed.locale, "en")

    def test_refine_pins_the_document_language_when_the_caller_says_so(self) -> None:
        # The 13-of-14 case measured in the local DB: an instruction that never mentioned
        # language, and the model quietly switched it.
        current = self._profile()
        raw = json.dumps({"headline": "Full Stack Developer", "locale": "en-US"})
        parsed = parse_resume_json(raw, current, refine=True, expected_locale="pt-BR")
        self.assertEqual(parsed.locale, "pt-BR")

    def test_refine_can_still_translate_when_no_locale_is_pinned(self) -> None:
        # refine_service passes None when the instruction WAS about language, so "traduz para
        # inglês" must keep working — the pin is a licence check, not a freeze.
        raw = json.dumps({"headline": "Full Stack Developer", "locale": "en"})
        parsed = parse_resume_json(raw, self._profile(), refine=True, expected_locale=None)
        self.assertEqual(parsed.locale, "en")

    def test_an_invented_locale_label_never_survives_the_parse(self) -> None:
        # Even with no authority asserted, the schema folds it: en-US is not a locale here.
        raw = json.dumps({"headline": "Full Stack Developer", "locale": "en-US"})
        parsed = parse_resume_json(raw, self._profile(), refine=True)
        self.assertEqual(parsed.locale, "en")


class ProjectSelectionTests(unittest.TestCase):
    """v6: the LLM SELECTS which of the profile's projects appear; it still cannot add one.

    Until v6 the anchor appended every project the model left out, so a resume carried the whole
    inventory no matter how little of it spoke to the job -- "keep only the relevant ones, at most
    4" in the prompt was overruled downstream. Projects are the showcase section: five entries,
    three of them study exercises, bury the two that argue for the role.

    Omitting a real project is curation; inventing one is a lie. These tests pin that the anchor
    now distinguishes the two, and that the "model ignored the profile" floor still holds.
    """

    def _profile(self) -> ResumeDocument:
        return ResumeDocument(
            fullName="Lucas Monteiro",
            headline="Full Stack Developer",
            summary="Base summary long enough to satisfy every unrelated anchor check here.",
            projects=[
                {"name": "GymPass API Clone", "description": "Study project, Node.js."},
                {"name": "Daily Diet", "description": "Study project, REST API."},
                {"name": "Space Tourism Website", "description": "Study project, front-end."},
                {"name": "AI Document Creation", "description": "Ports & Adapters, Next.js."},
                {"name": "AI Video Editor", "description": "Remotion, Next.js 14, Zustand."},
            ],
            locale="en",
        )

    def test_the_llm_may_ship_a_subset_of_the_profile_projects(self) -> None:
        raw = json.dumps(
            {
                "projects": [
                    {"name": "AI Video Editor", "description": "Browser video editor in Remotion."},
                    {"name": "AI Document Creation", "description": "Multi-source AI extraction."},
                ]
            }
        )
        parsed = parse_resume_json(raw, self._profile(), refine=False)

        self.assertEqual(
            [p.name for p in parsed.projects], ["AI Video Editor", "AI Document Creation"]
        )
        self.assertNotIn("Daily Diet", [p.name for p in parsed.projects])

    def test_a_selected_project_keeps_its_identity_and_adopts_the_rewritten_description(self) -> None:
        raw = json.dumps(
            {"projects": [{"name": "AI Video Editor", "description": "Tailored write-up."}]}
        )
        parsed = parse_resume_json(raw, self._profile(), refine=False)

        self.assertEqual([p.name for p in parsed.projects], ["AI Video Editor"])
        self.assertEqual(parsed.projects[0].description, "Tailored write-up.")

    def test_an_invented_project_is_still_discarded_while_selecting(self) -> None:
        # The guarantee that must survive the new freedom: selection is from the profile only.
        raw = json.dumps(
            {
                "projects": [
                    {"name": "AI Video Editor", "description": "Real one."},
                    {"name": "Kubernetes Platform Migration", "description": "Never happened."},
                ]
            }
        )
        parsed = parse_resume_json(raw, self._profile(), refine=False)

        self.assertEqual([p.name for p in parsed.projects], ["AI Video Editor"])

    def test_the_same_profile_project_named_twice_is_taken_once(self) -> None:
        raw = json.dumps(
            {
                "projects": [
                    {"name": "AI Video Editor", "description": "First."},
                    {"name": "ai video editor", "description": "Duplicate, different casing."},
                ]
            }
        )
        parsed = parse_resume_json(raw, self._profile(), refine=False)

        self.assertEqual([p.name for p in parsed.projects], ["AI Video Editor"])
        self.assertEqual(parsed.projects[0].description, "First.")

    def test_matching_nothing_keeps_the_profile_intact_rather_than_emptying_it(self) -> None:
        # The floor. No match means the model ignored the candidate (the same signal the
        # experience block reads as a generic template), not that it curated down to zero.
        raw = json.dumps({"projects": [{"name": "Some Template Project", "description": "x"}]})
        parsed = parse_resume_json(raw, self._profile(), refine=False)

        self.assertEqual(len(parsed.projects), 5)

    def test_an_omitted_projects_key_keeps_the_profile_intact(self) -> None:
        # Distinct from "selected none": the model said nothing about projects at all.
        raw = json.dumps({"headline": "Full Stack Developer"})
        parsed = parse_resume_json(raw, self._profile(), refine=False)

        self.assertEqual(len(parsed.projects), 5)

    def test_an_approved_drop_still_removes_a_project_the_llm_selected(self) -> None:
        # Drop outranks selection: the user vetoed it, so re-selecting it changes nothing.
        raw = json.dumps(
            {
                "projects": [
                    {"name": "Daily Diet", "description": "Study project."},
                    {"name": "AI Video Editor", "description": "Real one."},
                ]
            }
        )
        agreed = [
            ProposalItem(
                id=1,
                section="projects",
                op="drop",
                current="Daily Diet",
                proposed="Remover o projeto Daily Diet.",
                targets=["Daily Diet"],
                rationale="A vaga é sênior e o projeto é um exercício de estudo.",
            )
        ]
        parsed = parse_resume_json(raw, self._profile(), refine=False, agreed_improvements=agreed)

        self.assertEqual([p.name for p in parsed.projects], ["AI Video Editor"])

if __name__ == "__main__":
    unittest.main()


class KeyTechnologiesAnchorTests(unittest.TestCase):
    """The Key Technologies line (v7) gets the same anti-fabrication guarantee as ``skills``.

    A technology named under a real employer is a claim a recruiter can interview against, so the
    anchor admits one only if the candidate already claims it somewhere: the Profile's global
    ``skills`` list, or that role's own stored ``keyTechnologies``.
    """

    def _profile(self, **overrides: object) -> ResumeDocument:
        base: dict = {
            "fullName": "Lucas Monteiro",
            "headline": "Full Stack Developer",
            "summary": "Base summary",
            "skills": ["JavaScript", "React", "PostgreSQL", "Docker", "TypeScript"],
            "experience": [
                {
                    "company": "SmartHow",
                    "title": "Front-End Developer",
                    "start": "2025",
                    "end": None,
                    "highlights": ["Original bullet"],
                }
            ],
            "locale": "en",
        }
        base.update(overrides)
        return ResumeDocument(**base)

    def _generated(self, key_technologies: object, profile: ResumeDocument | None = None) -> ResumeDocument:
        fallback = profile if profile is not None else self._profile()
        raw = json.dumps(
            {
                "headline": "Senior Full Stack Developer",
                "summary": "Tailored summary.",
                "experience": [
                    {
                        "company": "SmartHow",
                        "title": "Front-End Developer",
                        "start": "2025",
                        "highlights": ["Rewritten bullet"],
                        "keyTechnologies": key_technologies,
                    }
                ],
                "skills": ["React"],
            }
        )
        return parse_resume_json(raw, fallback, refine=False)

    def test_technologies_the_profile_claims_survive_in_the_models_order(self) -> None:
        parsed = self._generated(["PostgreSQL", "React"])
        self.assertEqual(["PostgreSQL", "React"], parsed.experience[0].keyTechnologies)

    def test_a_technology_absent_from_the_profile_is_discarded(self) -> None:
        # "Kubernetes" appears nowhere in the profile — admitting it would put a credential on
        # the resume that the candidate never claimed.
        parsed = self._generated(["React", "Kubernetes"])
        self.assertEqual(["React"], parsed.experience[0].keyTechnologies)

    def test_matching_is_case_and_punctuation_aware_and_returns_the_profiles_casing(self) -> None:
        # skill_token matching, same as the skills anchor: the model's "postgresql" is the
        # profile's "PostgreSQL", and that canonical casing is what reaches the page.
        parsed = self._generated(["postgresql", "typescript"])
        self.assertEqual(["PostgreSQL", "TypeScript"], parsed.experience[0].keyTechnologies)

    def test_duplicates_collapse(self) -> None:
        parsed = self._generated(["React", "react", "REACT"])
        self.assertEqual(["React"], parsed.experience[0].keyTechnologies)

    def test_a_role_may_claim_its_own_stored_technology_even_if_it_is_not_a_global_skill(self) -> None:
        profile = self._profile(
            experience=[
                {
                    "company": "SmartHow",
                    "title": "Front-End Developer",
                    "start": "2025",
                    "highlights": ["Original bullet"],
                    "keyTechnologies": ["Terraform"],
                }
            ]
        )
        parsed = self._generated(["Terraform", "React"], profile=profile)
        self.assertEqual(["Terraform", "React"], parsed.experience[0].keyTechnologies)

    def test_all_fabricated_leaves_the_profiles_own_technologies_intact(self) -> None:
        # Mirrors the highlights rule: only a NON-EMPTY anchored result is adopted, so a model
        # that emitted nothing usable cannot wipe real stored data.
        profile = self._profile(
            experience=[
                {
                    "company": "SmartHow",
                    "title": "Front-End Developer",
                    "start": "2025",
                    "highlights": ["Original bullet"],
                    "keyTechnologies": ["Terraform"],
                }
            ]
        )
        parsed = self._generated(["Kubernetes", "Rust"], profile=profile)
        self.assertEqual(["Terraform"], parsed.experience[0].keyTechnologies)

    def test_an_omitted_field_leaves_the_profiles_own_technologies_intact(self) -> None:
        profile = self._profile(
            experience=[
                {
                    "company": "SmartHow",
                    "title": "Front-End Developer",
                    "start": "2025",
                    "highlights": ["Original bullet"],
                    "keyTechnologies": ["Terraform"],
                }
            ]
        )
        raw = json.dumps(
            {
                "headline": "Senior Full Stack Developer",
                "summary": "Tailored summary.",
                "experience": [
                    {
                        "company": "SmartHow",
                        "title": "Front-End Developer",
                        "start": "2025",
                        "highlights": ["Rewritten bullet"],
                    }
                ],
                "skills": ["React"],
            }
        )
        parsed = parse_resume_json(raw, profile, refine=False)
        self.assertEqual(["Terraform"], parsed.experience[0].keyTechnologies)

    def test_a_comma_separated_string_is_accepted_as_the_line_it_describes(self) -> None:
        # The prompt calls this a "line" and the template renders it as one, so models emit a
        # single string often enough that losing it wholesale would be the wrong failure.
        parsed = self._generated("React, PostgreSQL; Docker")
        self.assertEqual(["React", "PostgreSQL", "Docker"], parsed.experience[0].keyTechnologies)

    def test_a_slash_inside_a_real_name_is_not_a_separator(self) -> None:
        profile = self._profile(skills=["CI/CD", "React", "Docker", "TypeScript"])
        parsed = self._generated("CI/CD, React", profile=profile)
        self.assertEqual(["CI/CD", "React"], parsed.experience[0].keyTechnologies)

    def test_objects_and_alias_keys_are_folded_in(self) -> None:
        raw = json.dumps(
            {
                "headline": "Senior Full Stack Developer",
                "summary": "Tailored summary.",
                "experience": [
                    {
                        "company": "SmartHow",
                        "title": "Front-End Developer",
                        "start": "2025",
                        "highlights": ["Rewritten bullet"],
                        "key_technologies": [{"name": "React"}, "Docker"],
                    }
                ],
                "skills": ["React"],
            }
        )
        parsed = parse_resume_json(raw, self._profile(), refine=False)
        self.assertEqual(["React", "Docker"], parsed.experience[0].keyTechnologies)

    def test_spoken_languages_and_soft_skills_never_reach_the_line(self) -> None:
        profile = self._profile(skills=["React", "Docker", "TypeScript", "PostgreSQL"])
        parsed = self._generated(["React", "English", "Leadership"], profile=profile)
        self.assertEqual(["React"], parsed.experience[0].keyTechnologies)

    def test_an_approved_skill_drop_also_prunes_the_line(self) -> None:
        # A technology the user just approved removing from the resume must not survive by
        # reappearing under a job. The floor (MIN_SKILLS_AFTER_DROPS) is respected via the same
        # single decision the skills list uses — 5 profile skills minus 1 leaves 4, so the drop
        # applies rather than being abandoned.
        profile = self._profile()
        raw = json.dumps(
            {
                "headline": "Senior Full Stack Developer",
                "summary": "Tailored summary.",
                "experience": [
                    {
                        "company": "SmartHow",
                        "title": "Front-End Developer",
                        "start": "2025",
                        "highlights": ["Rewritten bullet"],
                        "keyTechnologies": ["Docker", "React"],
                    }
                ],
                "skills": ["React"],
            }
        )
        agreed = [
            ProposalItem(
                id=1,
                section="skills",
                op="drop",
                targets=["Docker"],
                proposed="Remove Docker — the posting is front-end only",
                rationale="Not asked for by this posting",
            )
        ]
        parsed = parse_resume_json(raw, profile, refine=False, agreed_improvements=agreed)
        self.assertNotIn("Docker", parsed.skills)
        self.assertEqual(["React"], parsed.experience[0].keyTechnologies)

    def test_a_seed_extraction_passes_technologies_through(self) -> None:
        # A nameless profile means we are extracting from a PDF: the LLM output IS the real data,
        # so there is no canonical profile to anchor against and the lookup gate is skipped.
        seed = ResumeDocument(fullName="", headline="", summary="", locale="en")
        raw = json.dumps(
            {
                "fullName": "Ana Costa",
                "headline": "Backend Developer",
                "summary": "From the PDF.",
                "experience": [
                    {
                        "company": "Acme",
                        "title": "Backend Developer",
                        "start": "2021",
                        "highlights": ["Built the API"],
                        "keyTechnologies": ["Go", "Kafka"],
                    }
                ],
            }
        )
        parsed = parse_resume_json(raw, seed, refine=False)
        self.assertEqual(["Go", "Kafka"], parsed.experience[0].keyTechnologies)
