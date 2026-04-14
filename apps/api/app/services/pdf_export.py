from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.async_api import async_playwright

from app.config import TEMPLATES_DIR
from app.models import ResumeDocument
from app.services.html_sanitize import sanitize_resume_for_display
from app.services.ollama_client import filter_skills_non_tech_inplace

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


async def render_resume_pdf(resume: ResumeDocument) -> bytes:
    data = resume.model_dump()
    sanitize_resume_for_display(data)
    filter_skills_non_tech_inplace(data)
    tpl = _env.get_template("resume_print.html")
    html = tpl.render(resume=data)
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
