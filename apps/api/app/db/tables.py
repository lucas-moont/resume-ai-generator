"""SQLite table definitions (SQLModel) -- see docs/v1-chat-experience.md "Modelo de dados
SQLite" (B5). No Alembic yet: v1 is single-user local storage with no data in the field to
migrate; formal migrations become necessary if/when the schema changes after real user data
exists (v2+). `SQLModel.metadata.create_all()` (app/db/engine.py:init_db) is sufficient for
now.

JSON columns are plain TEXT with (de)serialization done in the repository layer (not
SQLite's JSON1 extension) -- keeps the roundtrip explicit and testable against the actual
pydantic models (ProfileMaster/ResumeDocument) rather than trusting a DB-side JSON type.

Three FK-shaped columns are deliberately declared as plain nullable ints WITHOUT a real
ForeignKey constraint:
  - `ProfileVersion.chat_message_id` -- a real FK here would close the cycle
    profile_versions -> chat_messages -> resume_versions -> profile_versions (SQLite cannot
    resolve FK cycles at CREATE TABLE time; SQLAlchemy's usual `use_alter=True` escape hatch
    relies on ALTER TABLE ADD CONSTRAINT, which SQLite's ALTER TABLE does not support).
  - `ChatSession.active_resume_version_id` -- a real FK here would close the classic
    "current pointer" mutual-reference cycle chat_sessions <-> resume_versions
    (chat_sessions.active_resume_version_id -> resume_versions.id and
    resume_versions.session_id -> chat_sessions.id).
  - `ProfileVersion.source_document_id` (v2 ticket 03: the `source_documents` table below) --
    no cycle here, but the same soft-ref treatment is deliberate anyway: a Profile Version is
    permanent, append-only history (CONTEXT.md: Profile Version), while its originating
    Source Document is disposable (a user may delete an upload for privacy, or a future
    retention policy may prune old files). A real FK would either block that deletion or
    (with ON DELETE SET NULL) erase the provenance link entirely; leaving it a soft ref lets
    the Source Document go away while the Profile Version keeps the id as a historical
    breadcrumb, dangling but harmless -- see
    tests/unit/test_source_document_repo.py::TestSourceDocumentSoftRefOrphan for the
    characterization test.
Referential integrity for all three is enforced by the repository layer, not the schema.
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
    source_document_id: int | None = None  # soft ref -- see module docstring
    chat_message_id: int | None = None  # soft ref -- see module docstring
    change_summary: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class SourceDocument(SQLModel, table=True):
    """An uploaded `.json`/`.md`/`.pdf` file carrying professional information (CONTEXT.md:
    Source Document). Lifecycle: stored -> extracted -> proposed -> applied | rejected |
    failed. v2 ticket 03 produces rows up to `extracted` (with `extracted_json` as the
    preview) or `failed` (with an actionable `error`). As of v2 ticket 04, every successful
    extraction is immediately followed -- in the SAME request -- by the Incremental Merge
    pipeline (`services/ingestion/merge_service.py`), so `extracted` is a transient in-request
    state, never the terminal one returned to a caller: a document always settles at
    `proposed` (possibly with an empty proposal), `applied`, `rejected`, or `failed`.
    `proposed_patch`/`diff_summary` are populated together by `mark_proposed` (ticket 04).
    """

    __tablename__ = "source_documents"

    id: int | None = Field(default=None, primary_key=True)
    filename: str
    media_type: str  # 'json' | 'md' | 'pdf'
    sha256: str = Field(unique=True, index=True)  # dedup: re-uploading the same bytes is a no-op
    size_bytes: int
    stored_path: str  # data/uploads/<sha256>.<ext>
    extracted_json: str | None = None  # JSON-serialized ResumeDocument preview
    proposed_patch: str | None = None  # JSON-serialized list[PatchOp] -- ticket 04
    diff_summary: str | None = None  # JSON-serialized list[str] -- ticket 04, alongside proposed_patch
    status: str = "stored"  # 'stored' | 'extracted' | 'proposed' | 'applied' | 'rejected' | 'failed'
    error: str | None = None  # actionable message when status == 'failed'
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
    intent: str | None = None  # 'generate' | 'refine' | 'profile_update' | 'question'
    resume_version_id: int | None = Field(default=None, foreign_key="resume_versions.id")
    meta: str | None = None  # JSON-serialized {model, provider, elapsed_ms, error?}
    created_at: datetime = Field(default_factory=_utcnow)
