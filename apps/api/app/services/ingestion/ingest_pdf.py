"""PDF Source Document ingestion (v2 ticket 03, docs/v2-living-profile.md item 2).

Reuses ``app.services.profile_pdf.extract_pdf_plain_text`` -- already generic over an
arbitrary ``Path`` -- against the just-stored upload's ``stored_path`` (not the
``resolve_profile_pdf_path()`` config path the v1 Profile.pdf-refresh flow reads), then the
same ``PROFILE_PDF_MAX_CHARS`` cap via ``truncate_for_prompt``, then LLM extraction. A scanned
PDF with no extractable text (pypdf returns empty) -- or any other unreadable PDF -- raises
``PdfIngestionError`` with an actionable message instead of silently handing the LLM an empty
prompt; the router (routers/profile.py) catches this and marks the Source Document 'failed'
rather than ever returning a 500.
"""

from __future__ import annotations

from pathlib import Path

from app.domain.schemas import ResumeDocument
from app.services.extraction_service import extract_profile_from_text
from app.services.profile_pdf import extract_pdf_plain_text, truncate_for_prompt

_NO_TEXT_MESSAGE = (
    "This PDF has no extractable text (likely a scanned image with no text layer). "
    "Try re-exporting it as a text-based PDF, or upload a .json/.md file instead."
)


class PdfIngestionError(Exception):
    """Raised when a PDF Source Document has no extractable text, or otherwise cannot be
    read. Always non-fatal to the request -- the router catches it and marks the Source
    Document 'failed' with this message (CONTEXT.md: Source Document lifecycle)."""


async def ingest_pdf(path: Path, *, model: str | None = None) -> ResumeDocument:
    try:
        text = extract_pdf_plain_text(path)
    except Exception as e:
        raise PdfIngestionError(
            f"Could not read this PDF: {e}. Try re-exporting it, or upload a .json/.md file instead."
        ) from e

    if not text.strip():
        raise PdfIngestionError(_NO_TEXT_MESSAGE)

    text = truncate_for_prompt(text)
    return await extract_profile_from_text(text, model=model)
