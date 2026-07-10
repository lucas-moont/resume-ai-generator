"""SQLite table definitions (SQLModel) -- see docs/v1-chat-experience.md "Modelo de dados
SQLite" (B5). No Alembic yet: v1 is single-user local storage with no data in the field to
migrate; formal migrations become necessary if/when the schema changes after real user data
exists (v2+). `SQLModel.metadata.create_all()` (app/db/engine.py:init_db) is sufficient for
now.

JSON columns are plain TEXT with (de)serialization done in the repository layer (not
SQLite's JSON1 extension) -- keeps the roundtrip explicit and testable against the actual
pydantic models (ProfileMaster/ResumeDocument) rather than trusting a DB-side JSON type.

Two FK-shaped columns are deliberately declared as plain nullable ints WITHOUT a real
ForeignKey constraint, to avoid circular foreign-key dependencies that SQLite cannot resolve
at CREATE TABLE time (SQLAlchemy's usual `use_alter=True` escape hatch for FK cycles relies on
ALTER TABLE ADD CONSTRAINT, which SQLite's ALTER TABLE does not support):
  - `ProfileVersion.chat_message_id` -- a real FK here would close the cycle
    profile_versions -> chat_messages -> resume_versions -> profile_versions.
  - `ChatSession.active_resume_version_id` -- a real FK here would close the classic
    "current pointer" mutual-reference cycle chat_sessions <-> resume_versions
    (chat_sessions.active_resume_version_id -> resume_versions.id and
    resume_versions.session_id -> chat_sessions.id).
Referential integrity for these two is enforced by the repository layer, not the schema --
the same treatment already agreed for `source_document_id` (a real FK deferred to v2, when
the source_documents table exists).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProfileVersion(SQLModel, table=True):
    __tablename__ = "profile_versions"

    id: int | None = Field(default=None, primary_key=True)
    version: int = Field(unique=True, index=True)
    data: str  # JSON-serialized ProfileMaster
    patch: str | None = None  # JSON-serialized patch, when source_kind implies one (e.g. chat)
    source_kind: str  # 'seed_disk' | 'upload' | 'chat' | 'manual' | 'revert'
    source_document_id: int | None = None  # FK deferred to v2's source_documents table
    chat_message_id: int | None = None  # soft ref -- see module docstring
    change_summary: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class ChatSession(SQLModel, table=True):
    __tablename__ = "chat_sessions"

    id: int | None = Field(default=None, primary_key=True)
    title: str | None = None
    job_description: str | None = None
    locale: str | None = None
    active_resume_version_id: int | None = None  # soft ref -- see module docstring
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class ResumeVersion(SQLModel, table=True):
    __tablename__ = "resume_versions"

    id: int | None = Field(default=None, primary_key=True)
    # SET NULL (not CASCADE): deleting a chat_session must not delete its resume_versions --
    # they survive, just decoupled from the deleted session (see chat_repo.delete_session's
    # test invariant).
    session_id: int | None = Field(
        default=None, foreign_key="chat_sessions.id", ondelete="SET NULL"
    )
    parent_version_id: int | None = Field(default=None, foreign_key="resume_versions.id")
    profile_version_id: int | None = Field(default=None, foreign_key="profile_versions.id")
    data: str  # JSON-serialized ResumeDocument
    # No template_id here (v2 ticket 01 dropped it -- see docs/v2-living-profile.md's
    # "Dívida herdada"): the frontend never sent a real per-version choice in v1, and product
    # settled template as a global sticky user preference (like theme), not per-resume-version.
    # app/db/engine.py's init_db() drops the column ad-hoc for any v1 DB that still has it.
    model_used: str | None = None
    provider_used: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_messages"

    id: int | None = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="chat_sessions.id", ondelete="CASCADE")
    role: str  # 'user' | 'assistant'
    content: str
    intent: str | None = None  # 'generate' | 'refine' | 'question'
    resume_version_id: int | None = Field(default=None, foreign_key="resume_versions.id")
    meta: str | None = None  # JSON-serialized {model, provider, elapsed_ms, error?}
    created_at: datetime = Field(default_factory=_utcnow)
