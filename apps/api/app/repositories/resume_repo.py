"""Repository for resume_versions (B5; consumed by B6's chat endpoints)."""

from __future__ import annotations

from sqlmodel import Session

from app.db.tables import ResumeVersion


def insert_version(
    session: Session,
    *,
    data: str,
    session_id: int | None = None,
    parent_version_id: int | None = None,
    profile_version_id: int | None = None,
    model_used: str | None = None,
    provider_used: str | None = None,
) -> ResumeVersion:
    row = ResumeVersion(
        data=data,
        session_id=session_id,
        parent_version_id=parent_version_id,
        profile_version_id=profile_version_id,
        model_used=model_used,
        provider_used=provider_used,
    )
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def get(session: Session, version_id: int) -> ResumeVersion | None:
    return session.get(ResumeVersion, version_id)
