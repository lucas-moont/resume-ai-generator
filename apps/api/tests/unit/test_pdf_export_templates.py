import unittest
from typing import get_args

import pytest

from app.domain.schemas import ResumeDocument, TemplateId
from app.services.pdf_export import _ALLOWED_TEMPLATES, RESUME_TEMPLATES_PACKAGE_DIR, render_resume_pdf
from tests.factories import make_resume_payload

# Single source of truth mirrored by hand on the web side:
# apps/web/src/features/resume/templates/registry.ts (TEMPLATE_IDS / registry.test.ts
# asserts this exact same set). If you add/remove a template, update both sides.
_EXPECTED_TEMPLATE_IDS = {
    "modern",
    "classic",
    "minimal",
    "compact",
    "ats-plain",
    "two-column-ats",
}


class PdfExportTemplatesContractTests(unittest.TestCase):
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
