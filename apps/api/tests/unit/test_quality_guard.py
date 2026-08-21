import unittest

from app.domain.keywords import extract_jd_keywords as _extract_jd_keywords
from app.domain.quality import allows_lean_skills as _allows_lean_skills
from app.domain.quality import quality_issues as _quality_issues
from app.domain.schemas import ProposalItem as _ProposalItem
from app.models import ResumeDocument
from app.services.generation_service import enrich_projects_from_sources as _enrich_projects_from_sources


def _strong_resume() -> ResumeDocument:
    return ResumeDocument(
        fullName="Kevvan",
        headline="Senior Fullstack Developer — React & Node.js",
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
