"""SQLite table definitions (SQLModel) -- see docs/v1-chat-experience.md "Modelo de dados
SQLite" (B5). No Alembic yet: v1 is single-user local storage with no data in the field to
migrate; formal migrations become necessary if/when the schema changes after real user data
exists (v2+). `SQLModel.metadata.create_all()` (app/db/engine.py:init_db) is sufficient for
now.

JSON columns are plain TEXT with (de)serialization done in the repository layer (not
SQLite's JSON1 extension) -- keeps the roundtrip explicit and testable against the actual
pydantic models (ProfileMaster/ResumeDocument) rather than trusting a DB-side JSON type.

These FK-shaped columns are deliberately declared as plain nullable ints WITHOUT a real
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
  - `ChatMessage.meta`'s `sourceDocumentId` key (v2 ticket 10, JSON-encoded, not a real
    column) -- when an upload names the chat session it came from, a durable assistant
    ChatMessage is persisted with `meta: {"sourceDocumentId": <SourceDocument.id>}`, so its
    ProfileUpdatedCard survives a session reload instead of reverting to plain text (see
    app/services/chat_service.py's `link_upload_to_session`, moved there in ticket 04's router
    split since it is chat-domain logic). Deliberately the SAME soft-ref treatment
    as the three above, for the same reason as `source_document_id`: the Source Document may
    be deleted independently of the chat history that references it. This key alone is
    persisted -- NEVER a copy of `status` -- so there is only one source of truth: GET
    /api/chat/sessions/{id} joins `source_documents` LIVE, at read time, for whatever the
    CURRENT status/diffSummary/opsCount is (routers/chat.py's `_source_document_link_dict`);
    apply/reject never need to touch this message. A dangling `sourceDocumentId` (the
    document was deleted) simply resolves to no `sourceDocument` on that message, same as any
    other message with no such reference.
  - `ListingMemory.resume_version_id` (v7 ticket 02: the Job Monitor's One-click Resume) --
    the same treatment as `ProfileVersion.source_document_id` and for the same reason, one
    step further: the Listing Memory is the ONLY durable thing the Job Monitor keeps (its
    `job_listings` rows are truncated and rewritten by every Scan), while the resume_version
    it points at is an ordinary Resume the user may prune -- and, unlike everything else in
    the memory, that row is written by the generation pipeline in a DIFFERENT transaction
    than the Scan's. A real FK would make the memory's durability hostage to the Resume's:
    either blocking a deletion the user is entitled to, or (ON DELETE SET NULL) silently
    turning "One-click Resume already generated" into "never generated" and buying a second
    LLM call. Dangling here means exactly what it means for a Source Document: the resume is
    gone, `hasOneClickResume` resolves to false, the Listing Status and Fit Score survive.
    `ImprovementProposal.resume_version_id` (v4) is soft for the same reason.
Referential integrity for all of them is enforced by the repository layer, not the schema.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel

from app.domain.locale import DEFAULT_LOCALE


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
    # v5 (ticket b1): discriminates the resume chat ('resume') from the Profile Analysis area
    # ('profile_analysis'). Default preserves every v1-v4 session; a pre-v5 on-disk DB is
    # backfilled to 'resume' by migrations._add_missing_chat_sessions_kind_column.
    kind: str = Field(default="resume", index=True)
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


class AppSettings(SQLModel, table=True):
    """Non-sensitive runtime preferences (v3 ticket 01: config lazy prefactor) -- provider
    choice, default model, and any future UI-configurable preference. Read/written via
    app/repositories/app_settings_repo.py and resolved call-time (env -> app_settings ->
    hardcoded default) by app/config.py's ``get_runtime_config()``.

    API keys NEVER land here -- only in the OS keychain (app/services/secret_store.py). See
    CONTEXT.md / docs/v3-agnostic-settings.md Backend-1/Backend-2 for the precedence rule.
    """

    __tablename__ = "app_settings"

    key: str = Field(primary_key=True)
    value: str  # JSON-encoded
    updated_at: datetime = Field(default_factory=_utcnow)


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_messages"

    id: int | None = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="chat_sessions.id", ondelete="CASCADE")
    role: str  # 'user' | 'assistant'
    content: str
    intent: str | None = None  # 'generate' | 'refine' | 'profile_update' | 'question'
    resume_version_id: int | None = Field(default=None, foreign_key="resume_versions.id")
    meta: str | None = None  # JSON-serialized {model, provider, elapsed_ms, error?, sourceDocumentId?}
    created_at: datetime = Field(default_factory=_utcnow)


class ImprovementProposal(SQLModel, table=True):
    """An Improvement Proposal (v4 -- CONTEXT.md: Improvement Proposal, Proposal Item): the
    LLM's Analysis of Profile vs. a pasted job description, as a list of per-section changes
    the user converses over (approve / adjust / question / new JD) before generation runs.
    Lifecycle enforced entirely by app/repositories/proposal_repo.py, never here or in a
    router: 'proposed' -> 'approved' | 'superseded' (a newer Analysis or New JD replaces the
    pending one) | 'discarded' (reserved, no UI path in v4). Same CASCADE-on-session-delete
    treatment as ChatMessage.session_id above -- a proposal has no meaning once its chat
    session is gone.

    ``session_id`` is NULLABLE as of v7 ticket 10 (CONTEXT.md: One-click Resume -- the one
    exception to "no Resume without an approved proposal", where the proposal is auto-approved
    as produced). A One-click's Analysis is a real, itemized, auditable proposal; what it does
    not have is a conversation, and inventing a hidden chat session to hang it on would put a
    session in the sidebar that the user never opened. Rows written by the chat still always
    carry one -- `db/migrations.py`'s
    `_relax_improvement_proposals_session_id_to_nullable` is what lets an on-disk DB accept
    the NULL.
    """

    __tablename__ = "improvement_proposals"

    id: int | None = Field(default=None, primary_key=True)
    session_id: int | None = Field(default=None, foreign_key="chat_sessions.id", ondelete="CASCADE")
    # The JD that produced this Analysis -- source of truth for approve. Since v6 this holds
    # EITHER a real pasted posting OR a Target Brief (app/domain/baseline_brief.py), the synthetic
    # stand-in a Baseline Resume request runs on, so a no-posting request reuses this one pipeline
    # instead of a parallel path that would skip the Proposal. Use ``is_target_brief`` to tell them
    # apart -- notably, never read the output language off a brief: it is English prompt text.
    job_description: str
    items: str  # JSON-serialized list[ProposalItem] (app/domain/schemas.py)
    revision: int = 1  # +1 each `adjust` turn (items replaced in place, never appended)
    status: str = "proposed"  # 'proposed' | 'approved' | 'superseded' | 'discarded'
    resume_version_id: int | None = None  # soft ref, filled by mark_approved -- see module docstring
    model_used: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


# =============================================================================
# Job Monitor (v7, ticket 02)
# =============================================================================
# Vocabulary: CONTEXT.md section "Job Monitor (v7)". Wire shapes: the FROZEN CONTRACT block at
# the end of app/domain/schemas.py (ticket 01). Column values that mirror one of that block's
# ``Literal`` aliases are typed here as plain ``str`` -- the same discipline every table above
# follows (``ProfileVersion.source_kind``, ``SourceDocument.status``) -- with the alias named in
# the comment: the Literal is the HTTP boundary's job, and a DB column typed by it would make a
# row written by an older build unloadable the day the alias narrows.
#
# The read/write path for all five tables is app/repositories/jobs_repo.py.


# The Search Profile's only primary key -- see SearchProfile's docstring.
SEARCH_PROFILE_ID = 1


class SearchProfile(SQLModel, table=True):
    """What the single local user is looking for (CONTEXT.md: Search Profile) -- distinct from
    the Profile: the Profile says who you are, this says what you want.

    Exactly one row, and the primary key says so: ``id`` defaults to ``SEARCH_PROFILE_ID``
    rather than to an autoincrement, so a second insert collides on the PK instead of quietly
    creating a second Search Profile the Scan would have to choose between. The app is
    single-user and local (spec: "Single-user, local"), so this is not a users table waiting to
    happen -- when it becomes one, the singleton default is the thing to remove.

    A row exists only once the user saves: ``POST /search-profile/suggest`` builds a suggestion
    from the Profile without persisting it (``SearchProfileOut.updatedAt is None`` is precisely
    that state), and a Scan with no row here has nothing to search for.
    """

    __tablename__ = "search_profile"

    id: int = Field(default=SEARCH_PROFILE_ID, primary_key=True)
    roles: str = "[]"  # JSON-serialized list[str] -- target roles
    locations: str = "[]"  # JSON-serialized list[str] (the service seeds "Brasil" + "Remote")
    remote: str = "any"  # RemotePreference: 'any' | 'remote_only' | 'onsite_ok'
    # JSON-serialized list[str]: languages of POSTINGS the user accepts (default pt + en).
    # Deliberately not SUPPORTED_LOCALES -- a posting in Spanish may still be a job they want.
    languages: str = "[]"
    boards: str = "[]"  # JSON-serialized list[BoardId] -- the boards switched ON
    # MaxApplicantBand ('<10' | '<25' | '<50' | '<100'); NULL is "qualquer" (no cap). A listing
    # whose band is 'unknown' passes ANY cap: an absent number is not evidence of a crowd.
    max_applicant_band: str | None = None
    # ScanIntervalHours (1 | 3 | 6 | 12 | 24); NULL is off -- Immediate Scans still work.
    interval_hours: int | None = None
    updated_at: datetime = Field(default_factory=_utcnow)


class JobScan(SQLModel, table=True):
    """One run of the Job Monitor across the enabled boards (CONTEXT.md: Scan). Append-only
    history: unlike ``job_listings``, scan rows are never truncated -- they are what
    ``GET /scans/latest`` and the "next scan" computation read.

    There is no ``failed`` status. A Scan where every board blocked is still ``done``, with
    ``board_statuses`` telling the story: a Scan is partial, never failed. ``status='running'``
    is the single-flight state -- at most one such row exists at a time, and an Immediate Scan
    requested while it holds gets a 409 carrying this row.
    """

    __tablename__ = "job_scans"

    id: int | None = Field(default=None, primary_key=True)
    started_at: datetime = Field(default_factory=_utcnow, index=True)
    finished_at: datetime | None = None
    trigger: str  # ScanTrigger: 'scheduled' | 'immediate'
    status: str = Field(default="running", index=True)  # ScanStatus: 'running' | 'done'
    # JSON-serialized {board_id: {"status": BoardStatus, "message": str|None, "count": int}}.
    # A MAP here and a LIST (BoardStatusOut[]) on the wire, deliberately: the map is how the
    # engine fills it in as each board answers (keyed, order-free, idempotent per board), the
    # list is how the BoardStatusBar renders it (stable order across responses).
    board_statuses: str = "{}"
    listings_found: int = 0  # deduplicated Job Listings written by this Scan
    listings_scored: int = 0  # of those, how many the LLM scored (the rest keep an estimate)


class JobListing(SQLModel, table=True):
    """One job found by the LATEST Scan (CONTEXT.md: Job Listing), deduplicated across boards
    by ``identity_key``.

    EPHEMERAL, and that is the whole design: the list IS the last Scan, so this table is
    truncated and rewritten in one transaction whenever a Scan completes
    (``jobs_repo.replace_listings``). A listing id is therefore only valid until the next Scan
    finishes -- anything that must outlive one (the user's status, the Fit already computed,
    the One-click Resume) lives in ``listing_memory``, keyed by ``identity_key``, and is
    reattached by the next Scan.

    ``scan_id`` is a REAL foreign key (unlike the soft refs in the module docstring): both rows
    are written by the same Scan transaction, there is no cycle, and a listing genuinely has no
    meaning without the Scan that found it -- so ON DELETE CASCADE is the honest behavior. That
    also makes deleting a scan row a supported way to drop its listings, though the normal path
    is ``replace_listings``.
    """

    __tablename__ = "job_listings"
    # SQLite reuses the rowid of a deleted row, and this table is emptied by every Scan -- so
    # without AUTOINCREMENT the FIRST listing of each Scan is handed id 1 again and a listing id
    # the UI captured a moment ago silently resolves to a DIFFERENT job (one-clicking a resume
    # for the wrong posting). AUTOINCREMENT keeps a high-water mark in ``sqlite_sequence``, so a
    # stale id resolves to nothing and the endpoint 404s, which is the honest answer for an id
    # the latest Scan no longer has. Ignored by non-SQLite dialects.
    __table_args__ = {"sqlite_autoincrement": True}

    id: int | None = Field(default=None, primary_key=True)
    scan_id: int = Field(foreign_key="job_scans.id", ondelete="CASCADE", index=True)
    # normalize(company) + "|" + normalize(title) -- app/domain/listing_identity.py (ticket 03).
    # Indexed, not unique: uniqueness within a Scan is the engine's dedup invariant, and making
    # it a DB constraint would turn a dedup bug into a 500 on an otherwise good Scan.
    identity_key: str = Field(index=True)
    title: str
    company: str
    location: str | None = None
    is_remote: bool = False
    description: str = ""  # clean TEXT, never HTML (services/html_sanitize runs in the adapter)
    # Precomputed because the LIST endpoint omits ``description`` (fifty full postings is a
    # payload nobody reads) but the card still has to pre-disable One-click on a short posting.
    description_word_count: int = 0
    date_posted: datetime | None = None  # aware UTC; NULL scores as the oldest recency bucket
    # A listing already in the memory that came back with a newer ``date_posted`` (CONTEXT.md:
    # Repost). Boards do not flag reposts, so this comparison is the only detection.
    is_repost: bool = False
    # ApplicantBand -- the SMALLEST known band across this listing's sources (judge a job by
    # its least crowded posting). 'unknown' when no source reported one.
    applicant_band: str = "unknown"
    fit_score: int = 0  # 0-100 (CONTEXT.md: Fit Score)
    fit_estimated: bool = True  # True = the cheap keyword pass's number, not the LLM's
    visibility_score: float = Field(default=0.0, index=True)  # 0-100, the ranking key
    # The POSTING's language, not the UI's -- feeds the Locale Authority when this listing
    # becomes a Resume. Same ``str`` (not a Literal) as ``ResumeDocument.locale``.
    locale: str = DEFAULT_LOCALE


class ListingSource(SQLModel, table=True):
    """One occurrence of a Job Listing on one Job Board (CONTEXT.md: Listing Source). A Job
    Listing always keeps EVERY source link: dedup must not cost the user the board they would
    rather apply on, and naming the board next to its link is what Remotive's and Remote OK's
    terms require.

    Same ephemerality and the same real FK as ``job_listings`` -- ON DELETE CASCADE is the DB's
    safety net, but ``jobs_repo.replace_listings`` deletes these rows explicitly first anyway,
    so the ORM's identity map never keeps a source whose listing is gone.
    """

    __tablename__ = "listing_sources"
    # Same no-rowid-reuse rule as ``job_listings`` above, for the same reason.
    __table_args__ = {"sqlite_autoincrement": True}

    id: int | None = Field(default=None, primary_key=True)
    listing_id: int = Field(foreign_key="job_listings.id", ondelete="CASCADE", index=True)
    board: str  # BoardId: 'linkedin' | 'indeed' | ... (schemas.py's frozen Literal)
    url: str
    date_posted: datetime | None = None  # what THIS board reported
    applicant_band: str = "unknown"  # ApplicantBand as THIS board reported it


class ListingMemory(SQLModel, table=True):
    """What the Job Monitor remembers about a job ACROSS Scans (CONTEXT.md: Listing Memory),
    keyed by ``identity_key`` -- the counterpart to ``job_listings``' ephemerality and the only
    durable state the Monitor owns.

    Holds exactly the three things that must survive a Scan: the Listing Status (so a
    ``dismissed`` job stays hidden when a later Scan finds it again), the Fit Score already
    computed (so the LLM is not paid twice for the same posting -- ``fit_description_hash`` is
    what tells a genuine Repost with a rewritten description from the same text coming back),
    and the One-click Resume already generated (``resume_version_id``, a soft ref -- see the
    module docstring).

    A job never seen again simply keeps its memory unused: rows are never garbage-collected,
    because "unused" and "the user dismissed this six months ago" are the same row, and only
    the second one matters when the job is reposted.
    """

    __tablename__ = "listing_memory"

    id: int | None = Field(default=None, primary_key=True)
    identity_key: str = Field(unique=True, index=True)
    # ListingStatus: 'new' -> 'seen' -> 'applied' | 'dismissed'. 'new' is only ever what a Scan
    # writes for an identity with no memory; "undo a dismiss" is 'seen', never back to 'new'.
    status: str = "new"
    fit_score: int | None = None  # the LLM's number, if this listing ever reached stage 2
    # sha256 of the description that produced ``fit_score``. A Repost whose description changed
    # invalidates the score (rescore); the same text coming back does not.
    fit_description_hash: str | None = None
    resume_version_id: int | None = None  # soft ref -- see module docstring
    first_seen_at: datetime = Field(default_factory=_utcnow)
    last_seen_at: datetime = Field(default_factory=_utcnow)
    # When ``status`` last actually CHANGED (not when the row was last touched by a Scan) --
    # a Scan reattaching the memory bumps ``last_seen_at`` only.
    status_changed_at: datetime = Field(default_factory=_utcnow)
