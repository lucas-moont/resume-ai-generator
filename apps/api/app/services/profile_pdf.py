from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from app.config import profile_pdf_max_chars, resolve_profile_pdf_path


def _extract_from_reader(reader: PdfReader) -> str:
    parts: list[str] = []
    for page in reader.pages:
        t = page.extract_text()
        if t:
            parts.append(t)
    return "\n".join(parts).strip()


def extract_pdf_plain_text(path: Path) -> str:
    return _extract_from_reader(PdfReader(str(path)))


def extract_pdf_text_from_bytes(data: bytes) -> str:
    """Extract plain text from an in-memory PDF (v5 ticket b4: an uploaded LinkedIn PDF export
    analyzed on the fly, never stored or ingested). Same per-page logic as the path-based
    reader; caller applies ``truncate_for_prompt`` and the no-text check."""
    return _extract_from_reader(PdfReader(BytesIO(data)))


def truncate_for_prompt(text: str) -> str:
    """Caps ``text`` at ``PROFILE_PDF_MAX_CHARS`` so a large PDF excerpt can't blow the LLM's
    context budget. Shared by ``load_profile_pdf_excerpt`` (the v1 Profile.pdf flow) and v2's
    ``services.ingestion.ingest_pdf`` (an arbitrary uploaded PDF) -- same cap, one place."""
    limit = profile_pdf_max_chars()
    if len(text) > limit:
        return text[:limit] + "\n... [truncated for prompt size; raise PROFILE_PDF_MAX_CHARS if needed]"
    return text


def load_profile_pdf_excerpt() -> tuple[str, Path | None, str | None]:
    path = resolve_profile_pdf_path()
    if path is None:
        return "", None, None
    try:
        text = extract_pdf_plain_text(path)
    except Exception as e:
        return "", path, str(e)
    return truncate_for_prompt(text), path, None


def format_profile_pdf_prompt_block(extracted: str, source_name: str) -> str:
    if not extracted.strip():
        return ""
    return f"""Text extracted from profile PDF ({source_name}) — use for wording, extra detail, and alignment with your master JSON. Do not contradict facts in the JSON; if PDF and JSON disagree, trust the JSON.
---
{extracted}
---
"""
