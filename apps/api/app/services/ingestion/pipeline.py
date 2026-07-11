"""The Source Document ingestion pipeline (ticket 04 prefactor): the HTTP-agnostic orchestration
that used to be inlined in routers/profile.py's ``upload_document`` handler -- size/type
validation, dedup, storage, DB insert, format-specific extraction, and the Incremental Merge
proposal, all as one seam testable with plain bytes+metadata in, a ``SourceDocument`` row out
(no HTTP, no FastAPI ``UploadFile``).

``ingest_upload`` raises three exceptions for the request-shaped rejections that must persist
NOTHING at all -- ``UploadTooLargeError`` (413), ``UnsupportedMediaTypeError`` (415),
``InvalidSourceDocumentError`` (422, a malformed/schema-invalid `.json`) -- routers/documents.py
maps each to its status code. Every OTHER failure (LLM extraction, merge adjudication) is
non-fatal by design and already reflected in the returned row's ``status='failed'``, never
raised: the upload itself succeeded, so the router still responds 202 (see module docstring
history in routers/profile.py's former ``upload_document``, ticket 03/04).
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlmodel import Session

from app.config import max_upload_bytes
from app.db.tables import SourceDocument
from app.repositories import source_document_repo
from app.services.ingestion.ingest_json import JsonIngestionError, ingest_json
from app.services.ingestion.ingest_markdown import ingest_markdown
from app.services.ingestion.ingest_pdf import ingest_pdf
from app.services.ingestion.merge_service import propose_merge, resolve_profile_for_merge
from app.services.ingestion.storage import compute_sha256, store_upload
from app.services.secret_redaction import redact_secrets

_MEDIA_TYPE_BY_EXT = {"json": "json", "md": "md", "markdown": "md", "pdf": "pdf"}


class UploadTooLargeError(Exception):
    """Maps to 413 at the router. Carries the byte limit for the message."""

    def __init__(self, limit: int) -> None:
        super().__init__(f"File exceeds the {limit} byte upload limit")
        self.limit = limit


class UnsupportedMediaTypeError(Exception):
    """Maps to 415 at the router: filename extension isn't `.json`/`.md`/`.pdf`."""

    def __init__(self) -> None:
        super().__init__("Unsupported file type -- upload a .json, .md, or .pdf file")


class InvalidSourceDocumentError(Exception):
    """Maps to 422 at the router: wraps a ``JsonIngestionError``'s message unchanged."""


def _media_type_from_filename(filename: str | None) -> str | None:
    if not filename or "." not in filename:
        return None
    ext = filename.rsplit(".", 1)[-1].lower()
    return _MEDIA_TYPE_BY_EXT.get(ext)


async def _propose_merge_or_fail(
    session: Session, row: SourceDocument, resume, model_override: str | None
) -> SourceDocument:
    """Runs the Incremental Merge pipeline (``services/ingestion/merge_service.py``) for a
    just-extracted Source Document, for ALL THREE formats -- unlike ingestion (json is
    LLM-free, md/pdf are not), Adjudication is a separate call gated purely by whether the
    Deterministic Diff found anything new or divergent. Any failure here (a broken active
    profile, an unreachable LLM) marks the document 'failed' with an actionable, redacted
    message rather than ever surfacing as a 500 -- the same non-fatal treatment ticket 03
    established for extraction failures; the file and its ``extractedPreview`` are already
    safely persisted by the time this runs.
    """
    try:
        profile = resolve_profile_for_merge(session)
        proposal = await propose_merge(profile, resume, model=model_override)
    except Exception as e:
        row = source_document_repo.mark_failed(
            session, row, error=redact_secrets(f"Could not build a merge proposal: {e}")
        )
        session.commit()
        return row

    row = source_document_repo.mark_proposed(
        session,
        row,
        proposed_patch=json.dumps([op.model_dump() for op in proposal.ops]),
        diff_summary=json.dumps(proposal.diff_summary),
    )
    session.commit()
    return row


async def ingest_upload(
    session: Session,
    *,
    filename: str | None,
    content: bytes,
    model_override: str | None,
) -> SourceDocument:
    """bytes + filename metadata in, a settled (or dedup-shortcut) ``SourceDocument`` row out --
    the pipeline's one public seam (pre-agreed test seam, ticket 04). Raises
    ``UploadTooLargeError`` / ``UnsupportedMediaTypeError`` / ``InvalidSourceDocumentError`` for
    the three request-shaped rejections that must not persist a row or a file at all; see the
    module docstring for why every other failure instead comes back as a 'failed' row.

    `.json` is validated deterministically (no LLM); `.md`/`.pdf` go through LLM extraction
    instead. The file and its DB row are persisted FIRST for `.md`/`.pdf` (`status='stored'`,
    then `'extracted'`), since extraction can fail for reasons that have nothing to do with the
    upload being bad (a scanned PDF with no text layer, a flaky provider).
    """
    limit = max_upload_bytes()
    if len(content) > limit:
        raise UploadTooLargeError(limit)

    media_type = _media_type_from_filename(filename)
    if media_type is None:
        raise UnsupportedMediaTypeError()

    sha256 = compute_sha256(content)
    existing = source_document_repo.get_by_sha256(session, sha256)
    if existing is not None:
        return existing

    if media_type == "json":
        try:
            resume = ingest_json(content)
        except JsonIngestionError as e:
            raise InvalidSourceDocumentError(str(e)) from e

        stored_path = store_upload(content, sha256=sha256, ext="json")
        row = source_document_repo.insert(
            session,
            filename=filename or "upload.json",
            media_type="json",
            sha256=sha256,
            size_bytes=len(content),
            stored_path=stored_path,
            status="extracted",
            extracted_json=resume.model_dump_json(),
        )
        session.commit()
        return await _propose_merge_or_fail(session, row, resume, model_override)

    # .md / .pdf: persist first (status='stored'), then attempt LLM-based extraction -- any
    # failure there becomes status='failed', never raised (see module docstring).
    stored_path = store_upload(content, sha256=sha256, ext=media_type)
    row = source_document_repo.insert(
        session,
        filename=filename or f"upload.{media_type}",
        media_type=media_type,
        sha256=sha256,
        size_bytes=len(content),
        stored_path=stored_path,
        status="stored",
    )
    session.commit()

    try:
        if media_type == "md":
            resume = await ingest_markdown(content, model=model_override)
        else:
            resume = await ingest_pdf(Path(stored_path), model=model_override)
    except Exception as e:
        row = source_document_repo.mark_failed(session, row, error=redact_secrets(str(e)))
        session.commit()
        return row

    row = source_document_repo.mark_extracted(session, row, extracted_json=resume.model_dump_json())
    session.commit()
    return await _propose_merge_or_fail(session, row, resume, model_override)
