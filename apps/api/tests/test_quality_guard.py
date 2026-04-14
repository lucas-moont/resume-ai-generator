import unittest

from app.main import _enrich_projects_from_sources, _quality_issues
from app.models import ResumeDocument


class QualityGuardTests(unittest.TestCase):
    def test_reports_missing_core_stack_and_links(self) -> None:
        resume = ResumeDocument(
            fullName="Kevvan",
            headline="Fullstack Developer",
            summary="Resumo",
            skills=["JavaScript"],
            links=[{"label": "LinkedIn", "url": "https://linkedin.com/in/kevvan"}],
        )
        jd = "Senior Fullstack com Node.js, TypeScript, React, Next.js e MongoDB."
        issues = _quality_issues(resume, jd)
        self.assertTrue(any("Missing core job skills" in i for i in issues))
        self.assertTrue(any("at least two useful links" in i for i in issues))

    def test_passes_when_stack_and_links_are_present(self) -> None:
        resume = ResumeDocument(
            fullName="Kevvan",
            headline="Senior Fullstack",
            summary="Resumo",
            skills=["Node.js", "TypeScript", "React", "Next.js", "MongoDB"],
            links=[
                {"label": "LinkedIn", "url": "https://linkedin.com/in/kevvan"},
                {"label": "GitHub", "url": "https://github.com/kevvan"},
            ],
        )
        jd = "Node.js TypeScript React Next.js MongoDB"
        self.assertEqual(_quality_issues(resume, jd), [])

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
