import json
import re
import unittest
from typing import get_args

import pytest

from app.domain.schemas import ResumeDocument, TemplateId
from app.services.pdf_export import (
    _ALLOWED_TEMPLATES,
    RESUME_TEMPLATES_PACKAGE_DIR,
    render_resume_html,
    render_resume_pdf,
)
from tests.factories import make_resume_payload

# The manifest (packages/resume-templates/templates.json) is the single
# source of truth for template identity — apps/web's registry.ts derives from
# the same file. Nothing here is hand-mirrored; this just re-reads the
# manifest independently of pdf_export._load_allowed_templates() to guard
# against that function silently drifting from what it's supposed to load.
_MANIFEST = json.loads(
    (RESUME_TEMPLATES_PACKAGE_DIR / "templates.json").read_text(encoding="utf-8")
)
_EXPECTED_TEMPLATE_IDS = {t["id"] for t in _MANIFEST["templates"]}

# The rendered label element, not the bare words — see
# KeyTechnologiesReachThePrintTemplateTests' docstring for why that distinction matters here.
_KEY_TECH_LABEL_EN = '<span class="exp-tech-label">Key Technologies:</span>'
_KEY_TECH_LABEL_PT = '<span class="exp-tech-label">Tecnologias-chave:</span>'


class PdfExportTemplatesContractTests(unittest.TestCase):
    def test_manifest_has_every_known_template(self) -> None:
        # Guards against a truncated/empty templates.json making every other
        # assertion in this file vacuously true.
        self.assertEqual(
            _EXPECTED_TEMPLATE_IDS,
            {
                "modern",
                "classic",
                "minimal",
                "compact",
                "ats-plain",
                "two-column-ats",
                "executive",
                "tech",
                "latex-ats",
            },
        )

    def test_allowed_templates_matches_the_web_registry(self) -> None:
        self.assertEqual(_ALLOWED_TEMPLATES, _EXPECTED_TEMPLATE_IDS)

    def test_template_id_literal_matches_the_web_registry(self) -> None:
        self.assertEqual(set(get_args(TemplateId)), _EXPECTED_TEMPLATE_IDS)

    def test_shared_resume_css_package_has_a_block_for_every_template(self) -> None:
        css_path = RESUME_TEMPLATES_PACKAGE_DIR / "resume.css"
        self.assertTrue(css_path.is_file(), f"Expected {css_path} to exist")
        css = css_path.read_text(encoding="utf-8")
        for template_id in _EXPECTED_TEMPLATE_IDS:
            self.assertIn(
                f".tpl-{template_id}",
                css,
                f"Missing CSS block for template '{template_id}' in {css_path}",
            )


@pytest.mark.e2e
@pytest.mark.parametrize("template_id", ["ats-plain", "two-column-ats"])
async def test_new_ats_templates_render_a_real_pdf(template_id: str) -> None:
    # The existing test_renders_a_real_pdf_smoke (test_generate_endpoints_compat.py)
    # already covers the "modern" template end-to-end; this covers the two templates
    # added in this change specifically, to prove the shared CSS package + the
    # `.resume-doc` wrapper added to resume_print.html actually render for them too.
    resume = ResumeDocument(**make_resume_payload())
    pdf_bytes = await render_resume_pdf(resume, template_id)
    assert pdf_bytes.startswith(b"%PDF")


@pytest.mark.e2e
async def test_latex_ats_template_renders_a_real_pdf_with_the_key_tech_line() -> None:
    # v7: latex-ats is the first template added together with a new DOM element
    # (.exp-tech), so the smoke test asserts more than "%PDF" — it proves the Key
    # Technologies line actually reaches the print HTML the browser is handed.
    payload = make_resume_payload()
    payload["experience"][0]["keyTechnologies"] = ["React", "PostgreSQL"]
    resume = ResumeDocument(**payload)

    html = render_resume_html(resume, "latex-ats")
    assert _KEY_TECH_LABEL_EN in html or _KEY_TECH_LABEL_PT in html
    assert "PostgreSQL" in html

    pdf_bytes = await render_resume_pdf(resume, "latex-ats")
    assert pdf_bytes.startswith(b"%PDF")


@pytest.mark.e2e
@pytest.mark.parametrize("template_id", ["executive", "tech"])
async def test_new_manifest_templates_render_a_real_pdf(template_id: str) -> None:
    # Ticket 08: executive and tech, added via the manifest + new .tpl-* CSS
    # blocks only (no changes to resume_print.html) — proves the `:has()`
    # skills-reorder trick in tech and the centered single-column layout in
    # executive both still render into a real PDF end-to-end.
    resume = ResumeDocument(**make_resume_payload())
    pdf_bytes = await render_resume_pdf(resume, template_id)
    assert pdf_bytes.startswith(b"%PDF")


class ContactFieldsReachEveryTemplateTests(unittest.TestCase):
    """Every template must have somewhere for the contact fields — phone especially — to land.

    Written after a real report that "the templates have no room for a phone number". They did:
    resume_print.html emits it in both the single-column contact bar and the two-column sidebar,
    and every template shows one of the two. But NOTHING guarded that, and the guard is not
    obvious to add — resume.css hides `.contact-bar` by DEFAULT (line ~102) and each template
    opts back into exactly one of the two surfaces. A template that opted into neither, or a
    `display: none` added to the wrong selector, would silently drop the candidate's phone,
    email and location from the PDF with no test going red and nothing visible in review.
    """

    _CONTACT_SURFACES = ("contact-bar", "sidebar")

    def _css(self) -> str:
        return (RESUME_TEMPLATES_PACKAGE_DIR / "resume.css").read_text(encoding="utf-8")

    def _rule_bodies(self, css: str, template_id: str, surface: str) -> list[str]:
        """Bodies of the rules whose selector ends in ``.tpl-<id> ... .<surface>``.

        Anchored with ``\\s*$`` on the selector so a descendant rule (e.g.
        ``.tpl-modern .sidebar .side-title``) is not mistaken for a rule about the surface
        itself — that distinction is the whole point of the assertion below.
        """
        pattern = re.compile(
            rf"([^{{}}]*\.tpl-{re.escape(template_id)}\b[^,{{}}]*\.{re.escape(surface)}\s*)\{{([^{{}}]*)\}}"
        )
        return [m.group(2) for m in pattern.finditer(css)]

    def _is_visible(self, css: str, template_id: str, surface: str) -> bool:
        bodies = self._rule_bodies(css, template_id, surface)
        declared = [
            m.group(1)
            for body in bodies
            for m in [re.search(r"display:\s*([a-z-]+)", body)]
            if m
        ]
        if declared:
            # The template states a display for this surface; the last one wins in CSS order.
            return declared[-1] != "none"
        # No display of its own: it inherits the base rule for that surface. `.contact-bar` is
        # hidden there and `.sidebar` is not, so a template must opt IN to the contact bar but
        # only has to refrain from hiding the sidebar.
        if surface == "contact-bar":
            return False
        return not any("display: none" in b for b in bodies)

    def test_the_print_template_emits_phone_email_and_location(self) -> None:
        resume = ResumeDocument(**make_resume_payload(phone="+55 11 91234-5678"))
        html = render_resume_html(resume, "modern")

        self.assertIn("+55 11 91234-5678", html)
        self.assertIn(resume.email, html)
        self.assertIn(resume.location, html)

    def test_phone_is_emitted_in_both_contact_surfaces(self) -> None:
        # Both surfaces carry it, because which one is visible is a CSS decision per template.
        # If a refactor ever leaves the phone in only one, half the templates lose it.
        resume = ResumeDocument(**make_resume_payload(phone="+55 11 91234-5678"))
        html = render_resume_html(resume, "modern")
        self.assertEqual(html.count("+55 11 91234-5678"), 2, "expected the phone in the contact bar AND the sidebar")

    def test_a_missing_phone_leaves_no_empty_contact_slot(self) -> None:
        # The flip side: the field is conditional, so an absent phone must not render a stray
        # bullet/label. Guards against someone "fixing" the report by making it unconditional.
        resume = ResumeDocument(**make_resume_payload(phone=None))
        html = render_resume_html(resume, "modern")
        self.assertNotIn("Telefone", html)
        self.assertNotIn(">Phone<", html)

    def test_every_template_shows_at_least_one_contact_surface(self) -> None:
        css = self._css()
        for template_id in sorted(_EXPECTED_TEMPLATE_IDS):
            visible = [s for s in self._CONTACT_SURFACES if self._is_visible(css, template_id, s)]
            self.assertTrue(
                visible,
                f"template '{template_id}' hides both the contact bar and the sidebar, so the "
                "phone/email/location never reach the page",
            )

    def test_the_detector_would_catch_a_template_hiding_both_surfaces(self) -> None:
        # A guard is worthless if it cannot fail. Feeds the checker a CSS variant that hides
        # both surfaces for one template and asserts it reports that template as broken.
        broken = self._css() + (
            "\n.resume-doc .page.tpl-modern .contact-bar { display: none; }"
            "\n.resume-doc .page.tpl-modern .sidebar { display: none; }\n"
        )
        self.assertFalse(self._is_visible(broken, "modern", "contact-bar"))
        self.assertFalse(self._is_visible(broken, "modern", "sidebar"))
        # ...and that it still passes the templates it should.
        self.assertTrue(self._is_visible(broken, "classic", "contact-bar"))


class KeyTechnologiesReachThePrintTemplateTests(unittest.TestCase):
    """The Key Technologies line (v7) is emitted by the ONE shared print template, so it must
    behave the same for every template id — and, crucially, must be absent when the field is
    empty. Every resume persisted before the field existed has it empty, so a line that rendered
    unconditionally would put a dangling "Key Technologies:" label on all of them.

    Assertions anchor on the rendered ``<span class="exp-tech-label">`` rather than on the bare
    words: ``resume_print.html`` inlines the whole of ``resume.css``, whose comments discuss
    ``.exp-tech`` and "Key Technologies" by name, so a substring check against the full document
    is always true and would make every test here vacuous.
    """

    def test_an_empty_key_technologies_list_renders_no_line(self) -> None:
        resume = ResumeDocument(**make_resume_payload())
        self.assertEqual([], resume.experience[0].keyTechnologies)
        html = render_resume_html(resume, "latex-ats")
        self.assertNotIn('<div class="exp-tech">', html)
        self.assertNotIn(_KEY_TECH_LABEL_EN, html)
        self.assertNotIn(_KEY_TECH_LABEL_PT, html)

    def test_the_label_follows_the_document_locale(self) -> None:
        payload = make_resume_payload()
        payload["experience"][0]["keyTechnologies"] = ["React"]

        payload["locale"] = "pt-BR"
        html = render_resume_html(ResumeDocument(**payload), "latex-ats")
        self.assertIn(_KEY_TECH_LABEL_PT, html)
        self.assertNotIn(_KEY_TECH_LABEL_EN, html)

        payload["locale"] = "en"
        html = render_resume_html(ResumeDocument(**payload), "latex-ats")
        self.assertIn(_KEY_TECH_LABEL_EN, html)
        self.assertNotIn(_KEY_TECH_LABEL_PT, html)

    def test_each_technology_is_its_own_node_with_no_literal_commas(self) -> None:
        # The separators are painted by CSS (.exp-tech-list li::after) so the comma never
        # becomes part of the text a user edits inline, and an ATS reads clean tokens.
        payload = make_resume_payload()
        payload["experience"][0]["keyTechnologies"] = ["React", "PostgreSQL"]
        html = render_resume_html(ResumeDocument(**payload), "latex-ats")
        self.assertIn("<li>React</li>", html)
        self.assertIn("<li>PostgreSQL</li>", html)
        self.assertNotIn("React,", html)

    def test_the_line_reaches_every_template_not_just_latex_ats(self) -> None:
        # The DOM is template-independent by design (CONTEXT.md: Template) — the element is
        # emitted for all of them and CSS decides how it looks. A future change that scoped the
        # markup to one template would break that invariant silently.
        payload = make_resume_payload()
        payload["experience"][0]["keyTechnologies"] = ["React"]
        resume = ResumeDocument(**payload)
        for template_id in sorted(_EXPECTED_TEMPLATE_IDS):
            with self.subTest(template=template_id):
                self.assertIn(_KEY_TECH_LABEL_EN, render_resume_html(resume, template_id))
