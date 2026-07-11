import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.async_api import async_playwright

from app.config import TEMPLATES_DIR
from app.models import DEFAULT_TEMPLATE, ResumeDocument
from app.services.html_sanitize import sanitize_resume_for_display
from app.services.llm.resume_json_parser import filter_skills_non_tech_inplace

# packages/resume-templates/ is the single source of truth for template
# identity (templates.json) and styling (resume.css), shared with apps/web
# (imported there via the @resume-templates vite alias / TS path). Resolved
# relative to this file so it works regardless of the process's current
# working directory.
RESUME_TEMPLATES_PACKAGE_DIR = (
    Path(__file__).resolve().parents[4] / "packages" / "resume-templates"
)


def _load_allowed_templates() -> frozenset[str]:
    manifest = json.loads(
        (RESUME_TEMPLATES_PACKAGE_DIR / "templates.json").read_text(encoding="utf-8")
    )
    return frozenset(t["id"] for t in manifest["templates"])


# Derived from templates.json at import time — not hand-mirrored. The web
# registry (apps/web/src/features/resume/templates/registry.ts) derives from
# the same manifest; tests/unit/test_pdf_export_templates.py and
# tests/unit/test_shared_template_source_guard.py assert both sides agree.
_ALLOWED_TEMPLATES = _load_allowed_templates()

_env = Environment(
    loader=FileSystemLoader([str(TEMPLATES_DIR), str(RESUME_TEMPLATES_PACKAGE_DIR)]),
    autoescape=select_autoescape(["html", "xml"]),
)


def _safe_template(template: str | None) -> str:
    key = (template or "").strip().lower()
    return key if key in _ALLOWED_TEMPLATES else DEFAULT_TEMPLATE


async def render_resume_pdf(resume: ResumeDocument, template: str | None = None) -> bytes:
    data = resume.model_dump()
    sanitize_resume_for_display(data)
    filter_skills_non_tech_inplace(data)
    tpl = _env.get_template("resume_print.html")
    html = tpl.render(resume=data, template=_safe_template(template))
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(html, wait_until="networkidle")
        pdf = await page.pdf(
            format="A4",
            print_background=True,
            margin={"top": "12mm", "bottom": "12mm", "left": "12mm", "right": "12mm"},
        )
        await browser.close()
    return pdf
