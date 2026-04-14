from pathlib import Path

from pypdf import PdfReader

from app.config import profile_pdf_max_chars, resolve_profile_pdf_path


def extract_pdf_plain_text(path: Path) -> str:
    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        t = page.extract_text()
        if t:
            parts.append(t)
    return "\n".join(parts).strip()


def load_profile_pdf_excerpt() -> tuple[str, Path | None, str | None]:
    path = resolve_profile_pdf_path()
    if path is None:
        return "", None, None
    try:
        text = extract_pdf_plain_text(path)
    except Exception as e:
        return "", path, str(e)
    limit = profile_pdf_max_chars()
    if len(text) > limit:
        text = text[:limit] + "\n... [truncated for prompt size; raise PROFILE_PDF_MAX_CHARS if needed]"
    return text, path, None


def format_profile_pdf_prompt_block(extracted: str, source_name: str) -> str:
    if not extracted.strip():
        return ""
    return f"""Text extracted from profile PDF ({source_name}) — use for wording, extra detail, and alignment with your master JSON. Do not contradict facts in the JSON; if PDF and JSON disagree, trust the JSON.
---
{extracted}
---
"""
