import json
import unittest

from app.models import ResumeDocument
from app.services.ollama_client import parse_resume_json


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

        self.assertEqual(parsed.fullName, "KEVVAN")
        self.assertEqual(parsed.headline, "Fullstack Developer")
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
        self.assertIn("React", parsed.skills)
        self.assertIn("Node.js", parsed.skills)
        self.assertNotIn("English", parsed.skills)


if __name__ == "__main__":
    unittest.main()
