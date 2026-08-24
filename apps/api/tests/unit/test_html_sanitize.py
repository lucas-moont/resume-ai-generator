import unittest

from app.services.html_sanitize import (
    markdown_bold_to_html,
    sanitize_plain_text,
    sanitize_resume_for_display,
    sanitize_rich_html,
)


class HtmlSanitizeTests(unittest.TestCase):
    def test_markdown_bold_becomes_strong(self) -> None:
        self.assertEqual(
            markdown_bold_to_html("Hello **world**"),
            "Hello <strong>world</strong>",
        )

    def test_sanitize_rich_drops_script_keeps_strong(self) -> None:
        dirty = 'Intro <script>alert(1)</script> and <strong>OK</strong>'
        clean = sanitize_rich_html(dirty)
        self.assertNotIn("script", clean.lower())
        self.assertIn("<strong>OK</strong>", clean)

    def test_sanitize_plain_strips_all_tags(self) -> None:
        self.assertEqual(
            sanitize_plain_text('<em>x</em> Name'),
            "x Name",
        )

    def test_resume_dict_sanitizes_nested(self) -> None:
        d = {
            "fullName": "A",
            "headline": "**Lead**",
            "summary": "x",
            "skills": ["**Go**"],
            "experience": [
                {
                    "company": "C",
                    "title": "T",
                    "start": "1",
                    "end": None,
                    "highlights": ["**Ship** it"],
                }
            ],
            "projects": [{"name": "**P**", "description": "d"}],
            "education": [{"institution": "I", "degree": "D", "end": None, "details": "**Note**"}],
            "links": [],
            "locale": "pt-BR",
        }
        sanitize_resume_for_display(d)
        self.assertEqual(d["headline"], "<strong>Lead</strong>")
        self.assertEqual(d["skills"], ["Go"])
        self.assertEqual(d["experience"][0]["highlights"], ["<strong>Ship</strong> it"])
        self.assertEqual(d["projects"][0]["name"], "<strong>P</strong>")
        self.assertEqual(d["projects"][0]["description"], "d")
        self.assertEqual(d["education"][0]["details"], "<strong>Note</strong>")


if __name__ == "__main__":
    unittest.main()


class KeyTechnologiesSanitizationTests(unittest.TestCase):
    """``keyTechnologies`` (v7) is a keyword line, so it takes the PLAIN treatment ``skills``
    gets, not the rich-HTML subset ``highlights`` gets. Emphasis inside a comma-separated
    technology run has nothing to mark up, and letting tags through would put markup into the
    text an ATS parser reads.
    """

    def test_tags_are_stripped_not_kept_as_emphasis(self) -> None:
        data = {
            "experience": [
                {
                    "company": "Acme",
                    "title": "Dev",
                    "highlights": ["Shipped <strong>the thing</strong>"],
                    "keyTechnologies": ["<strong>React</strong>", "Docker"],
                }
            ]
        }
        sanitize_resume_for_display(data)
        # highlights keep the allowed emphasis...
        self.assertIn("<strong>", data["experience"][0]["highlights"][0])
        # ...keyTechnologies does not.
        self.assertEqual(["React", "Docker"], data["experience"][0]["keyTechnologies"])

    def test_a_script_tag_cannot_survive(self) -> None:
        data = {
            "experience": [
                {
                    "company": "Acme",
                    "title": "Dev",
                    "keyTechnologies": ["<script>alert(1)</script>React"],
                }
            ]
        }
        sanitize_resume_for_display(data)
        joined = " ".join(data["experience"][0]["keyTechnologies"])
        self.assertNotIn("script", joined.lower())

    def test_entries_that_sanitize_to_nothing_are_dropped(self) -> None:
        data = {
            "experience": [
                {
                    "company": "Acme",
                    "title": "Dev",
                    "keyTechnologies": ["<br>", "React", 42, None],
                }
            ]
        }
        sanitize_resume_for_display(data)
        self.assertEqual(["React"], data["experience"][0]["keyTechnologies"])
