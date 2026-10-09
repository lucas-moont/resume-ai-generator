import unittest

from app.domain.keywords import extract_jd_keywords as _extract_jd_keywords
from app.domain.keywords import normalize_token
from app.domain.quality import allows_lean_skills as _allows_lean_skills
from app.domain.quality import compressed_companies as _compressed_companies
from app.domain.quality import quality_issues as _quality_issues
from app.domain.schemas import ProposalItem as _ProposalItem
from app.models import ResumeDocument
from app.services.generation_service import enrich_projects_from_sources as _enrich_projects_from_sources


def _strong_resume() -> ResumeDocument:
    return ResumeDocument(
        fullName="Kevvan",
        headline="Senior Fullstack Developer | React & Node.js",
        summary=(
            "Senior fullstack developer with over six years building scalable web "
            "products across React front-ends and Node.js services, focused on clean "
            "architecture, performance, and reliable delivery in cloud environments."
        ),
        skills=["Node.js", "TypeScript", "React", "Next.js", "MongoDB", "AWS", "Docker", "Jest"],
        links=[
            {"label": "LinkedIn", "url": "https://linkedin.com/in/kevvan"},
            {"label": "GitHub", "url": "https://github.com/kevvan"},
        ],
        experience=[
            {
                "company": "Acme",
                "title": "Senior Engineer",
                "start": "2021",
                "end": None,
                "highlights": [
                    "Led migration of the checkout service to Node.js and TypeScript",
                    "Built a React and Next.js dashboard consumed by internal teams",
                    "Designed MongoDB schemas and AWS infrastructure for new features",
                ],
            }
        ],
    )


class QualityGuardTests(unittest.TestCase):
    def test_extract_jd_keywords_is_stack_agnostic(self) -> None:
        jd = "Looking for GraphQL, PostgreSQL, Kubernetes and CI/CD experience."
        keywords = _extract_jd_keywords(jd)
        self.assertIn("graphql", keywords)
        self.assertIn("postgresql", keywords)
        self.assertIn("kubernetes", keywords)
        self.assertIn("cicd", keywords)

    def test_extract_jd_keywords_ignores_sentence_punctuation(self) -> None:
        jd = (
            "Optimize applications for maximum speed and scalability. Write maintainable "
            "code and adhere to best practices. Work with modern libraries."
        )
        keywords = _extract_jd_keywords(jd)
        for junk in ("scalability", "practices", "libraries", "applications"):
            self.assertNotIn(junk, keywords)

    def test_reports_issues_for_a_weak_resume(self) -> None:
        resume = ResumeDocument(
            fullName="Kevvan",
            headline="Fullstack Developer",
            summary="Resumo",
            skills=["JavaScript"],
            links=[{"label": "LinkedIn", "url": "https://linkedin.com/in/kevvan"}],
        )
        jd = "Senior Fullstack com Node.js, TypeScript, React, Next.js e MongoDB."
        issues = _quality_issues(resume, jd)
        self.assertTrue(any("summary" in i.lower() for i in issues))
        self.assertTrue(any("technologies" in i.lower() for i in issues))
        self.assertTrue(any("at least two useful links" in i for i in issues))
        self.assertTrue(any("key job terms" in i for i in issues))

    def test_flags_weak_bullet_openers(self) -> None:
        resume = _strong_resume()
        resume.experience[0].highlights = [
            "Responsible for the checkout service and its Node.js codebase daily",
            "Worked on the React dashboard used by internal teams every week",
            "Handled MongoDB schemas and AWS infrastructure for several features",
        ]
        jd = "Node.js TypeScript React Next.js MongoDB AWS Docker"
        issues = _quality_issues(resume, jd)
        self.assertTrue(any("weak openers" in i for i in issues))

    def test_flags_em_dashes_in_the_prose(self) -> None:
        resume = _strong_resume()
        resume.experience[0].highlights[0] = (
            "Led migration of the checkout service to Node.js — cutting deploy friction"
        )
        issues = _quality_issues(resume, "Node.js React")
        self.assertTrue(any("dash" in i for i in issues), issues)

    def test_flags_a_spaced_en_dash_but_not_a_date_range(self) -> None:
        resume = _strong_resume()
        resume.summary = resume.summary + " Worked across 2019–2021 platform rewrites."
        self.assertFalse(any("dash" in i for i in _quality_issues(resume, "Node.js React")))
        resume.summary = resume.summary + " Built tooling – mostly internal."
        self.assertTrue(any("dash" in i for i in _quality_issues(resume, "Node.js React")))

    def test_flags_cover_letter_clauses_that_address_the_posting(self) -> None:
        for tail in (
            "exactly the kind of cross-stack collaboration this role calls for.",
            "aligned with what your team needs.",
            "experiência alinhada ao que esta vaga exige.",
            "exatamente o tipo de colaboração que a vaga pede.",
        ):
            resume = _strong_resume()
            resume.experience[0].highlights[1] = (
                "Built a React and Next.js dashboard consumed by internal teams, " + tail
            )
            issues = _quality_issues(resume, "Node.js React")
            self.assertTrue(any("cover letter" in i for i in issues), (tail, issues))

    def test_does_not_mistake_ordinary_bullets_for_posting_references(self) -> None:
        resume = _strong_resume()
        resume.experience[0].highlights[0] = (
            "Reduced API calls for the checkout page and was promoted to the role of Tech Lead"
        )
        issues = _quality_issues(resume, "Node.js React")
        self.assertFalse(any("cover letter" in i for i in issues), issues)

    def test_passes_for_a_strong_tailored_resume(self) -> None:
        jd = "Node.js TypeScript React Next.js MongoDB AWS Docker"
        self.assertEqual(_quality_issues(_strong_resume(), jd), [])

    def test_enriches_short_project_descriptions_from_markdown(self) -> None:
        resume = ResumeDocument(
            fullName="Kevvan",
            headline="Senior Fullstack",
            summary="Resumo",
            projects=[{"name": "sample-saas", "description": "Internal metrics dashboard"}],
        )
        md_entries = [
            {
                "slug": "sample-saas",
                "frontmatter": {"name": "sample-saas"},
                "body": "Internal SaaS dashboard built with React and Node.js, with role-based access and analytics.",
            }
        ]
        enriched = _enrich_projects_from_sources(resume, md_entries, [])
        self.assertIn("React", enriched.projects[0].description)


if __name__ == "__main__":
    unittest.main()


class LeanSkillsTests(unittest.TestCase):
    """v6 (Relevance Filter): the skills-count check only ever pushes UPWARD, so once the user
    approves dropping their irrelevant skills it fires on the intended result and hands the
    auto-improve refine pass an instruction to re-inflate the list. ``allows_lean_skills`` is
    what stops the quality gate from undoing the subtraction one step after the anchor honored it.
    """

    def _drop_item(self, section: str = "skills") -> _ProposalItem:
        return _ProposalItem(
            id=1,
            section=section,
            op="drop",
            current="Google Analytics",
            proposed="Remover Google Analytics da lista de skills.",
            targets=["Google Analytics"],
            rationale="A vaga não menciona analytics em nenhum requisito.",
        )

    def _lean_resume(self) -> ResumeDocument:
        resume = _strong_resume()
        return resume.model_copy(update={"skills": ["Node.js", "TypeScript", "React"]})

    def test_a_lean_skills_list_is_an_issue_by_default(self) -> None:
        issues = _quality_issues(self._lean_resume(), "We need a Node.js developer.")
        self.assertTrue(any("aim for 8-16" in issue for issue in issues))

    def test_an_approved_skill_drop_suppresses_the_lean_skills_issue(self) -> None:
        issues = _quality_issues(
            self._lean_resume(), "We need a Node.js developer.", allow_lean_skills=True
        )
        self.assertFalse(any("aim for 8-16" in issue for issue in issues))

    def test_allows_lean_skills_only_for_an_approved_skills_drop(self) -> None:
        self.assertTrue(_allows_lean_skills([self._drop_item()]))
        # A drop in another section says nothing about the skills list.
        self.assertFalse(_allows_lean_skills([self._drop_item(section="projects")]))
        # A pre-v6 item decodes to a rewrite, which never subtracts.
        self.assertFalse(
            _allows_lean_skills(
                [
                    _ProposalItem(
                        id=1,
                        section="skills",
                        current="React",
                        proposed="Priorizar React na lista.",
                        rationale="A vaga pede React.",
                    )
                ]
            )
        )
        self.assertFalse(_allows_lean_skills(None))
        self.assertFalse(_allows_lean_skills([]))


class CompressedRoleQualityTests(unittest.TestCase):
    """A COMPRESS item licenses one short factual bullet. The thin-bullet / 'add 3-5
    highlights' checks exist to catch a lazy draft of a *relevant* role; firing them on the
    compressed one spends a whole extra LLM call re-inflating what the user asked to shrink.
    """

    def _compress_item(self) -> _ProposalItem:
        return _ProposalItem(
            id=1,
            section="experience",
            op="compress",
            current="Agência XYZ",
            proposed="Reduzir a experiência na Agência XYZ a um bullet.",
            targets=["Agência XYZ"],
            rationale="A vaga é de backend; o trabalho lá foi de marketing digital.",
        )

    def _resume_with_compressed_role(self) -> ResumeDocument:
        data = _strong_resume().model_dump()
        data["experience"].append(
            {
                "company": "Agência XYZ",
                "title": "Marketing intern",
                "start": "2018",
                "end": "2019",
                "highlights": ["Supported campaign reporting."],
            }
        )
        return ResumeDocument.model_validate(data)

    def test_compressed_companies_reads_experience_compress_targets(self) -> None:
        keys = _compressed_companies([self._compress_item()])
        self.assertEqual(keys, frozenset({normalize_token("Agência XYZ")}))
        self.assertEqual(_compressed_companies(None), frozenset())
        self.assertEqual(_compressed_companies([]), frozenset())

    def test_a_short_bullet_on_an_uncompressed_role_is_still_an_issue(self) -> None:
        resume = _strong_resume()
        resume.experience[0].highlights = [
            "Led checkout.",
            "Built a React and Next.js dashboard consumed by internal teams",
            "Designed MongoDB schemas and AWS infrastructure for new features",
        ]
        jd = "Node.js TypeScript React Next.js MongoDB AWS Docker"
        issues = _quality_issues(resume, jd)
        self.assertTrue(any("thin experience bullets" in issue for issue in issues))

    def test_a_short_bullet_on_a_compressed_role_is_not_an_issue(self) -> None:
        resume = self._resume_with_compressed_role()
        jd = "Node.js TypeScript React Next.js MongoDB AWS Docker"
        issues = _quality_issues(
            resume, jd, compressed_companies=_compressed_companies([self._compress_item()])
        )
        self.assertFalse(any("thin experience bullets" in issue for issue in issues))
        self.assertFalse(any("most recent role" in issue for issue in issues))


_JD = "Node.js TypeScript React Next.js MongoDB AWS Docker"


def _with_summary(summary: str) -> ResumeDocument:
    resume = _strong_resume()
    resume.summary = summary
    return resume


class SummaryVoiceTests(unittest.TestCase):
    """The summary is a short positioning statement in implied first person: it opens with a noun
    phrase, never talks about the candidate with a pronoun or a self-description verb, and leaves
    project anecdotes to the experience bullets."""

    _GOOD_PT = (
        "Desenvolvedor Full Stack com 6 anos de experiência em React, Next.js e TypeScript, com "
        "foco em produtos web com IA. Experiência com Node.js, NestJS, Python e PostgreSQL em "
        "arquiteturas multi-tenant, processamento assíncrono e integrações com cloud."
    )

    def _voice_issue(self, resume: ResumeDocument) -> bool:
        return any("first-person" in i for i in _quality_issues(resume, _JD))

    def _anecdote_issue(self, resume: ResumeDocument) -> bool:
        return any("anecdote" in i for i in _quality_issues(resume, _JD))

    def test_flags_the_self_described_methodology_with_a_pr_count(self) -> None:
        resume = _with_summary(
            "Desenvolvedor Full Stack com 6 anos de experiência em React e Node.js. Sou adepto de "
            "spec driven design, separando tarefas complexas em pequenas tarefas, como a migração "
            "complexa que dividi em 13 PRs."
        )
        self.assertTrue(self._voice_issue(resume))
        self.assertTrue(self._anecdote_issue(resume))

    def test_flags_a_linkedin_about_copied_into_the_summary(self) -> None:
        resume = _with_summary(
            "Desenvolvedor Full Stack com mais de 6 anos de experiência em React e Node.js. Ao "
            "longo da minha experiência, construí aplicações altamente interativas e APIs. Gosto "
            "de transformar problemas complexos em software simples de usar."
        )
        self.assertTrue(self._voice_issue(resume))

    def test_flags_english_first_person(self) -> None:
        for summary in (
            "Full stack developer with six years of React and Node.js experience. I build "
            "scalable products and care about clean architecture and reliable delivery.",
            "Full stack developer with six years of React and Node.js experience. My focus is "
            "scalable products, clean architecture and reliable delivery in the cloud.",
            "Full stack developer with six years of React and Node.js experience. I'm focused on "
            "scalable products, clean architecture and reliable delivery in the cloud.",
        ):
            self.assertTrue(self._voice_issue(_with_summary(summary)), summary)

    def test_a_noun_phrase_summary_passes(self) -> None:
        resume = _with_summary(self._GOOD_PT)
        self.assertFalse(self._voice_issue(resume))
        self.assertFalse(self._anecdote_issue(resume))

    def test_a_past_action_verb_proof_and_an_impact_metric_pass(self) -> None:
        resume = _with_summary(
            self._GOOD_PT + " Liderei a migração da plataforma de pagamentos para eventos, "
            "reduzindo a latência p95 em 40% para mais de 1M usuários."
        )
        self.assertFalse(self._voice_issue(resume))
        self.assertFalse(self._anecdote_issue(resume))

    def test_io_and_ci_cd_are_not_the_pronoun_i(self) -> None:
        resume = _with_summary(
            "Backend engineer with six years building I/O heavy services in Node.js and Go, "
            "owning CI/CD pipelines, observability and AWS infrastructure for payment products."
        )
        self.assertFalse(self._voice_issue(resume))

    def test_flags_process_counts(self) -> None:
        for count in ("13 PRs", "200 commits", "3 repositórios", "40 tickets", "12 pull requests"):
            resume = _with_summary(self._GOOD_PT + f" Entregou a versão 6 em {count}.")
            self.assertTrue(self._anecdote_issue(resume), count)

    def test_flags_filler_claims_and_worked_examples(self) -> None:
        for tail in (
            " Adepto de clean code e arquitetura hexagonal.",
            " Apaixonado por tecnologia e inovação.",
            " Passionate about developer experience.",
            " Por exemplo, o editor de vídeo construído com Remotion.",
        ):
            resume = _with_summary(self._GOOD_PT + tail)
            self.assertTrue(self._anecdote_issue(resume), tail)

    def test_flags_a_summary_over_ninety_words(self) -> None:
        long_summary = " ".join([self._GOOD_PT] * 3)
        self.assertGreater(len(long_summary.split()), 90)
        self.assertTrue(self._anecdote_issue(_with_summary(long_summary)))

    def test_html_emphasis_does_not_hide_a_pronoun(self) -> None:
        resume = _with_summary(
            "Desenvolvedor Full Stack com 6 anos de experiência em React e Node.js, com foco em "
            "produtos web. <strong>Sou</strong> especialista em interfaces complexas e performance."
        )
        self.assertTrue(self._voice_issue(resume))
