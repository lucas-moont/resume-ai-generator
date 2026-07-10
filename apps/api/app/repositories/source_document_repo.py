"""Repository for source_documents (v2 ticket 03 -- "Ingestao e Source Documents").

Same convention as the other repositories here: callers own the transaction (commit/
rollback); functions only add/flush so multiple calls on the same Session compose into one
transaction. See app/db/tables.py's module docstring for why
`ProfileVersion.source_document_id` is a soft ref (no real FK) to this table -- `delete()`
below is safe to call even when a profile_versions row still points at the id being removed.
"""

from __future__ import annotations

from sqlmodel import Session, select

from app.db.tables import SourceDocument


def insert(
    session: Session,
    *,
    filename: str,
    media_type: str,
    sha256: str,
    size_bytes: int,
    stored_path: str,
    status: str = "stored",
    extracted_json: str | None = None,
    error: str | None = None,
) -> SourceDocument:
    row = SourceDocument(
        filename=filename,
        media_type=media_type,
        sha256=sha256,
        size_bytes=size_bytes,
        stored_path=stored_path,
        status=status,
        extracted_json=extracted_json,
        error=error,
    )
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def get(session: Session, document_id: int) -> SourceDocument | None:
    return session.get(SourceDocument, document_id)


def get_by_sha256(session: Session, sha256: str) -> SourceDocument | None:
    return session.exec(select(SourceDocument).where(SourceDocument.sha256 == sha256)).first()


def list_all(session: Session) -> list[SourceDocument]:
    """Full upload history, newest first."""
    return list(
        session.exec(
            select(SourceDocument).order_by(
                SourceDocument.created_at.desc(), SourceDocument.id.desc()
            )
        ).all()
    )


def mark_extracted(session: Session, row: SourceDocument, *, extracted_json: str) -> SourceDocument:
    row.status = "extracted"
    row.extracted_json = extracted_json
    row.error = None
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def mark_failed(session: Session, row: SourceDocument, *, error: str) -> SourceDocument:
    row.status = "failed"
    row.error = error
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def mark_proposed(
    session: Session, row: SourceDocument, *, proposed_patch: str, diff_summary: str
) -> SourceDocument:
    """v2 ticket 04: the Incremental Merge pipeline ran and produced a (possibly empty)
    proposal -- ``proposed_patch``/``diff_summary`` are JSON-serialized (``list[PatchOp]`` /
    ``list[str]`` respectively), always written even when empty (an upload identical to the
    active profile still reaches 'proposed', just with an empty proposal)."""
    row.status = "proposed"
    row.proposed_patch = proposed_patch
    row.diff_summary = diff_summary
    row.error = None
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def mark_applied(session: Session, row: SourceDocument) -> SourceDocument:
    row.status = "applied"
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def mark_rejected(session: Session, row: SourceDocument) -> SourceDocument:
    row.status = "rejected"
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def delete(session: Session, row: SourceDocument) -> None:
    session.delete(row)
    session.flush()
