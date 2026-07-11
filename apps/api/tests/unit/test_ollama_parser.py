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

        # Same patch, no approved "projects" item -- profile order is kept (pre-QA-04 behavior).
        parsed_without_item = parse_resume_json(raw, fallback, refine=False)
        self.assertEqual([p.name for p in parsed_without_item.projects], ["Alpha", "Beta"])
        # The SET of projects never changes either way -- only the order.
        self.assertEqual(
            {p.name for p in parsed.projects}, {p.name for p in parsed_without_item.projects}
        )


if __name__ == "__main__":
    unittest.main()
