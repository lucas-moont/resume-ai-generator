"""Repository for profile_versions (B5).

As of v2 ticket 01, the DB's active version (highest ``version`` row here) is the primary
source every reader goes through -- see app/services/profile_resolution.py, which falls back
to disk only when this table is empty. Callers own the transaction (commit/rollback);
functions here only add/flush so multiple calls on the same Session compose into one
transaction.
"""

from __future__ import annotations

from sqlmodel import Session, select

from app.db.tables import ProfileVersion


def get_active(session: Session) -> ProfileVersion | None:
    """The active profile version is the one with the highest `version` number."""
    return session.exec(
        select(ProfileVersion).order_by(ProfileVersion.version.desc()).limit(1)
    ).first()


def get_by_version(session: Session, version: int) -> ProfileVersion | None:
    return session.exec(select(ProfileVersion).where(ProfileVersion.version == version)).first()


def list_versions(session: Session) -> list[ProfileVersion]:
    """Full version history, newest first (history is append-only -- see CONTEXT.md's
    "Profile Version" -- so this ordering doubles as reverse-chronological)."""
    return list(session.exec(select(ProfileVersion).order_by(ProfileVersion.version.desc())).all())


def insert_version(
    session: Session,
    *,
    data: str,
    source_kind: str,
    patch: str | None = None,
    source_document_id: int | None = None,
    chat_message_id: int | None = None,
    change_summary: str | None = None,
) -> ProfileVersion:
    """Inserts a new profile version with ``version = MAX(version) + 1``.

    The MAX() lookup and the insert happen against the same Session, so two sequential calls
    without an intervening commit never compute the same next version (autoflush makes the
    first insert visible to the second call's SELECT).
    """
    current_max = session.exec(
        select(ProfileVersion.version).order_by(ProfileVersion.version.desc()).limit(1)
    ).first()
    row = ProfileVersion(
        version=(current_max or 0) + 1,
        data=data,
        patch=patch,
        source_kind=source_kind,
        source_document_id=source_document_id,
        chat_message_id=chat_message_id,
        change_summary=change_summary,
    )
    session.add(row)
    session.flush()
    session.refresh(row)
    return row
