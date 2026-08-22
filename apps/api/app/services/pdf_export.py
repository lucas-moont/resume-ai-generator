import asyncio
import json
import sys
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


async def _render_html_to_pdf(html: str) -> bytes:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(html, wait_until="networkidle")
        # Margins come from the @page rule in resume_print.html — passing
        # them here too conflicts with the stylesheet's @page and breaks
        # Chromium's pagination of the grid-layout templates.
        pdf = await page.pdf(format="A4", print_background=True)
        await browser.close()
    return pdf


def _render_html_to_pdf_in_thread(html: str) -> bytes:
    # Playwright launches Chromium via asyncio subprocesses, which the
    # SelectorEventLoop uvicorn uses on Windows doesn't implement
    # (NotImplementedError). Render on a dedicated loop that supports them.
    loop_factory = asyncio.ProactorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        return runner.run(_render_html_to_pdf(html))


def render_resume_html(resume: ResumeDocument, template: str | None = None) -> str:
    """The print HTML exactly as ``render_resume_pdf`` hands it to the browser.

    Extracted as its own seam so a test can assert on what the print template actually emits
    (e.g. that a contact field reaches the page) without paying for a headless-Chromium render
    and then having to read the field back out of PDF bytes. ``render_resume_pdf`` is now a thin
    wrapper over it, so the two can never drift.
    """
    data = resume.model_dump()
    sanitize_resume_for_display(data)
    filter_skills_non_tech_inplace(data)
    tpl = _env.get_template("resume_print.html")
    return tpl.render(resume=data, template=_safe_template(template))


async def render_resume_pdf(resume: ResumeDocument, template: str | None = None) -> bytes:
    html = render_resume_html(resume, template)
    return await asyncio.to_thread(_render_html_to_pdf_in_thread, html)
