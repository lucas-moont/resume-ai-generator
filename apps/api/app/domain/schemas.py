from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.locale import DEFAULT_LOCALE, SUPPORTED_LOCALES, normalize_locale

TemplateId = Literal[
    "modern",
    "classic",
    "minimal",
    "compact",
    "ats-plain",
    "two-column-ats",
    "executive",
    "tech",
    "latex-ats",
]
DEFAULT_TEMPLATE: TemplateId = "modern"


class Link(BaseModel):
    label: str
    url: str


class ExperienceItem(BaseModel):
    company: str
    title: str
    location: str | None = None
    start: str = ""
    end: str | None = None
    highlights: list[str] = Field(default_factory=list)
    # Key Technologies (v7): the technologies this role actually used, rendered as one
    # keyword line under the bullets. Plain technology names only -- same content rule as
    # ``skills`` (no HTML, no prose), enforced by ``sanitize_resume_for_display`` and by
    # ``_clean_technology_chip`` in the resume JSON parser. Optional and empty by default:
    # every resume/profile persisted before this field existed keeps loading unchanged, and
    # an empty list simply renders no line (CONTEXT.md: Key Technologies).
    keyTechnologies: list[str] = Field(default_factory=list)


class ProjectItem(BaseModel):
    name: str
    description: str = ""


class EducationItem(BaseModel):
    institution: str
    degree: str
    end: str | None = None
    details: str | None = None


class ResumeDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")

    fullName: str
    headline: str
    location: str | None = None
    email: str | None = None
    phone: str | None = None
    links: list[Link] = Field(default_factory=list)
    summary: str
    experience: list[ExperienceItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    locale: str = "pt-BR"

    @field_validator("locale", mode="before")
    @classmethod
    def _fold_locale_onto_a_supported_one(cls, value: object) -> object:
        """Coerce, never reject: an unsupported locale label becomes a supported one.

        ``locale`` is typed ``str`` rather than a ``Literal`` on purpose. 8 resume versions
        already persisted carry ``en-US`` (an LLM's own invention -- nothing validated this
        field before v6), and a ``Literal`` would make every one of them unloadable, breaking
        rehydration of real chat sessions to fix a cosmetic drift. Folding on the way IN
        normalizes those rows the next time they are read, and keeps the invariant every
        consumer wants: the value is always exactly ``"pt-BR"`` or ``"en"``.

        A value that is not a recognizable variant of either language falls back to the default
        rather than raising -- the document itself is still fine, and refusing to load it over
        its language tag would lose real work.
        """
        folded = normalize_locale(value)
        if folded is not None:
            return folded
        return value if value in SUPPORTED_LOCALES else DEFAULT_LOCALE


class ProfileMaster(ResumeDocument):
    githubUsername: str | None = None


class GenerateRequest(BaseModel):
    job_description: str
    model: str | None = None
    locale: str | None = None


class RefineRequest(BaseModel):
    resume: ResumeDocument
    message: str
    model: str | None = None


class PdfExportRequest(BaseModel):
    resume: ResumeDocument
    template: TemplateId = DEFAULT_TEMPLATE


class GitHubRepoInfo(BaseModel):
    name: str
    full_name: str
    html_url: str
    description: str | None = None
    language: str | None = None
    topics: list[str] = Field(default_factory=list)
    private: bool = False


# v4 (ticket 00): the section vocabulary a Proposal Item may target -- the ResumeDocument
# sections an Analysis is allowed to propose changes to. Anything outside this whitelist is
# dropped by proposal_json_parser (never an error).
ProposalSection = Literal[
    "headline",
    "summary",
    "experience",
    "projects",
    "skills",
    "education",
    "links",
    "location",
]


# v6 (Relevance Filter): the OPERATION a Proposal Item performs on its section. Before v6 every
# item was implicitly a rewrite, which is why the agent could never offer to *subtract* profile
# noise -- it could only swap text for other text. The vocabulary is deliberately small:
#
# - ``rewrite``  -- the pre-v6 behavior and the default: replace ``current`` wording with
#                   ``proposed``. Absent/unknown ``op`` on a persisted item decodes to this, so
#                   proposals stored before v6 keep validating unchanged.
# - ``add``      -- surface something real the profile has but the resume was not showing
#                   (already supported downstream by ``_agreed_skills_text``).
# - ``drop``     -- REMOVE the entities named in ``targets`` from the generated resume because
#                   they have no bearing on THIS job. Only honored for ``skills`` and
#                   ``projects``: dropping an employer/role or a degree would open a timeline
#                   gap, which the Relevance Filter never does (it compresses instead).
# - ``compress`` -- keep the entity (employer, dates, title stay untouched) but give it far less
#                   space: an unrelated role drops to one factual bullet instead of four. This op
#                   is instruction-only -- it reaches the LLM through the APPROVED IMPROVEMENT
#                   PLAN block and needs no anchor support, since the anchor already adopts
#                   whatever (non-empty) highlight list the model returns for a matched role.
ProposalOp = Literal["rewrite", "add", "drop", "compress"]


class ProposalItem(BaseModel):
    """One improvement inside an Improvement Proposal (CONTEXT.md: Proposal Item) -- the
    unit that makes the proposal detailed: WHAT changes (section + proposed), against WHAT
    (current excerpt), and WHY (rationale anchored in the job description).

    ``op``/``targets`` (v6, Relevance Filter) are additive with defaults, so every item written
    before v6 -- including the JSON blobs already sitting in ``improvement_proposals.items`` --
    still validates and still means exactly what it meant then (a rewrite with no targets).

    ``targets`` carries the LITERAL profile labels an ``op`` acts on (skill names, project
    names). It exists instead of parsing them back out of ``current``/``proposed`` prose
    because a drop is matched deterministically downstream (``skill_token``/``entity_key``
    equality, never substring): removing the wrong skill is a worse failure than removing
    nothing, so the target set is never inferred from free text.
    """

    id: int
    section: ProposalSection
    op: ProposalOp = "rewrite"
    current: str | None = None
    proposed: str
    rationale: str
    targets: list[str] = Field(default_factory=list)


# v5 (ticket 00): the LinkedIn profile sections an Analysis Item may target. Anything outside
# this whitelist is dropped by analysis_json_parser (never an error) -- mirrors ProposalSection.
AnalysisSection = Literal[
    "headline",
    "about",
    "experience",
    "skills",
    "completeness",
]

AnalysisPriority = Literal["alta", "média", "baixa"]


class AnalysisItem(BaseModel):
    """One recommendation inside a Profile Analysis (CONTEXT.md: Analysis Item): the target
    LinkedIn section, the user's current text (optional), the suggested change, a rationale
    anchored in a LinkedIn best practice / the context given, and a priority."""

    section: AnalysisSection
    current: str | None = None
    suggestion: str
    rationale: str
    priority: AnalysisPriority


class AnalysisResult(BaseModel):
    """The ``analysis`` outcome of an Analysis Turn: one or more Analysis Items plus a short
    prose summary in the user's locale. Read-only advice -- an Analysis never mutates the
    Living Profile nor produces a Resume."""

    type: Literal["analysis"] = "analysis"
    items: list[AnalysisItem] = Field(default_factory=list)
    summary: str = ""


class AnalysisQuestion(BaseModel):
    """The ``question`` outcome of an Analysis Turn (CONTEXT.md: Clarifying Question): the
    motor asks for the missing context (target role, seniority, audience, goal) instead of
    guessing -- same filosofia as refine.md's ask-instead-of-guessing valve."""

    type: Literal["question"] = "question"
    reply: str


# v5 (ticket b1): discriminates the resume chat from the Profile Analysis area.
ChatSessionKind = Literal["resume", "profile_analysis"]


class CreateChatSessionRequest(BaseModel):
    title: str | None = None
    # v5 (ticket b1): create a Profile Analysis conversation instead of a resume chat. Default
    # 'resume' keeps every pre-v5 caller (which never sent this field) byte-identical.
    kind: ChatSessionKind = "resume"


class ChatMessageRequest(BaseModel):
    message: str
    model: str | None = None
    locale: str | None = None
    jobDescription: str | None = None
    # v2 ticket 11: the client's own in-memory resume (post inline-edit), sent whenever it has
    # an active resume -- lets a chat `refine` turn start from what the user is actually looking
    # at instead of the last version the server persisted. Validated by pydantic like any other
    # field (an invalid shape here is a normal 422, before the stream ever starts). Ignored by
    # every intent except `refine` -- see chat_service.handle_chat_turn.
    resume: ResumeDocument | None = None
    # v4 (ticket 00): deterministic shortcut carried by the "Aprovar e gerar" button -- routes
    # the turn straight into the approve branch of the Proposal Turn with ZERO LLM
    # classification spent. Ignored when the session has no Pending Proposal (the message is
    # then routed normally). See docs/v4-improvement-proposal.md #3.1.
    proposalAction: Literal["approve"] | None = None


class RevertProfileRequest(BaseModel):
    toVersion: int


class RenameChatSessionRequest(BaseModel):
    """v4.1-03 (frozen contract): PATCH /api/chat/sessions/{id} body -- ``title`` must be
    1..120 chars AFTER trimming surrounding whitespace, and non-blank. Validated on the
    trimmed value (not the raw one) so surrounding whitespace never counts against the
    120-char limit, and the trimmed, canonical value is what callers get back."""

    title: str

    @field_validator("title")
    @classmethod
    def _trim_and_validate(cls, v: str) -> str:
        trimmed = v.strip()
        if not (1 <= len(trimmed) <= 120):
            raise ValueError("title must be 1..120 characters after trimming")
        return trimmed


# =============================================================================
# Job Monitor (v7, ticket 01) -- FROZEN CONTRACT
# =============================================================================
# Vocabulary: CONTEXT.md section "Job Monitor (v7)". Wire shapes: docs/v7-job-monitor.md.
# Every type below is additive and has NO consumer yet: nothing in the app imports them, no
# behavior changes. They exist so the backend, the web client and the tests of tickets 02-16
# are all written against ONE agreed interface instead of discovering it three times.
#
# Two families live here, and they do not share a casing convention -- on purpose:
#
#  * DOMAIN types (``RawPosting``, ``BoardQuery``, ``BoardResult``) are internal: they cross the
#    seam between a Job Board adapter and the Scan engine, never HTTP. snake_case, like the rest
#    of the Python code and like the DB columns they end up in.
#  * WIRE types (the ``*Out`` / ``*In`` models) are the JSON of ``/api/jobs``. camelCase, mirroring
#    every contract added since v2 (``ChatSessionSummary.updatedAt``,
#    ``ProviderEntry.defaultModelLockedByEnv``) and matching the TS DTOs in
#    ``apps/web/src/lib/api/dto.ts`` field for field. Query parameters stay snake_case, as the
#    spec writes them (``?max_band=``, ``?include_dismissed=1``).


# The number of applicants as a BAND, never an exact count (CONTEXT.md: Applicant Band).
# LinkedIn is the only board that exposes anything at all -- an exact number up to 100 and
# "over 100" past that -- so the bands are exactly what that page can say, plus ``unknown`` for
# every other board. ``unknown`` NEVER excludes a listing from the user's maximum-applicant
# filter; it only scores neutrally (0.5) in the Visibility Score.
ApplicantBand = Literal["<10", "<25", "<50", "<100", "100+", "unknown"]

# The subset a user may pick as their MAXIMUM (the Search Profile select is
# ``<10 · <25 · <50 · <100 · qualquer``). ``100+`` and ``unknown`` are deliberately not
# offerable: as a cap they would either mean "everything" -- which is what ``None`` already
# says -- or filter on an absence. ``None`` is "qualquer".
MaxApplicantBand = Literal["<10", "<25", "<50", "<100"]

# The user's relationship with a Job Listing (CONTEXT.md: Listing Status). Lives in the Listing
# Memory, not on the listing row, so a ``dismissed`` job stays hidden when a later Scan finds it
# again. ``new`` is only ever the initial state the Scan writes -- see ListingStatusUpdateIn.
ListingStatus = Literal["new", "seen", "applied", "dismissed"]

# How one Job Board fared in one Scan (CONTEXT.md: Scan). A Scan is PARTIAL, never failed, when
# a board blocks or errors: the other boards' results stand and the UI shows a per-board flag.
#   ok      -- the board answered
#   blocked -- the board refused us (429, a challenge page, a login wall)
#   error   -- the board broke (timeout, unparseable payload, adapter bug)
#   skipped -- the board's OWN minimum interval had not elapsed, so we did not call it
BoardStatus = Literal["ok", "blocked", "error", "skipped"]

# What a board ADAPTER itself may report. Narrower than BoardStatus by one value on purpose:
# ``skipped`` is the Scan engine's word, decided from ``min_interval_hours`` BEFORE any adapter
# runs. A provider that could return it would be claiming a scheduling fact it cannot know.
BoardReportedStatus = Literal["ok", "blocked", "error"]

# The Job Boards of v7 (CONTEXT.md: Job Board). Closed on purpose, exactly like ``TemplateId``:
# these ids are persisted in ``search_profile.boards`` and in ``listing_sources.board``, and a
# typo in a PUT body should be a 422, not a board that silently never runs.
#
# Adding a board (the BR portals in the spec's "fora do escopo": Gupy, Programathor, Vagas.com,
# Remotar) is a one-line widening here plus a provider -- safe, since no persisted row can name
# a board that does not exist yet. REMOVING one is the direction that needs care: unlike
# ``ResumeDocument.locale`` (typed ``str`` precisely so 8 already-persisted ``en-US`` rows keep
# loading), these tables are new in v7 and start empty, so the Literal costs nothing today --
# but retiring a board must ship a migration of ``search_profile.boards`` alongside it.
BoardId = Literal[
    "linkedin",
    "indeed",
    "glassdoor",
    "google",
    "remotive",
    "weworkremotely",
    "remoteok",
]

# What the user will accept, as stored in the Search Profile and passed down to every board.
#   any         -- remote or on-site, no preference
#   remote_only -- only postings the board flags as remote
#   onsite_ok   -- on-site/hybrid within the chosen locations is fine (remote still counts)
RemotePreference = Literal["any", "remote_only", "onsite_ok"]

# How often the Job Monitor scans on its own. ``None`` is "off" (on-demand Immediate Scans
# only). Closed to the values the UI offers so the scheduler never sleeps on a number nobody
# chose; the effective interval per board is ``max(this, board.min_interval_hours)``.
ScanIntervalHours = Literal[1, 3, 6, 12, 24]

# Why this Scan ran, and where it is (CONTEXT.md: Scan). ``running`` is the single-flight state:
# at most one Scan exists in it, and a second request while it holds gets a 409 carrying the
# current Scan. There is no ``failed`` -- a Scan where every board broke is still ``done``, with
# every Board Status telling the story.
ScanTrigger = Literal["scheduled", "immediate"]
ScanStatus = Literal["running", "done"]


# --- Domain: the Job Board adapter seam (services/jobboards/, ticket 03) -------------------


class BoardQuery(BaseModel):
    """What the Scan engine asks ONE Job Board for. Built once per Scan from the Search
    Profile, then handed unchanged to every enabled board -- so a board adapter never reads
    the Search Profile itself and stays testable with a literal query."""

    roles: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    remote: RemotePreference = "any"
    # Only postings newer than this. Derived from the scan interval (wide enough to overlap the
    # previous Scan, so nothing falls between two runs), not from the user's interval directly.
    hours_old: int = 24
    # Per board, not per Scan: the cap on how many postings this board should return.
    results_wanted: int = 50


class RawPosting(BaseModel):
    """One posting as ONE board reported it, before dedup, Fit or ranking (the input side of
    CONTEXT.md: Listing Source). Deliberately dumb: an adapter's whole job is to produce these,
    so everything interpretive -- identity, Repost detection, scoring -- happens once in the
    Scan engine instead of seven times in seven adapters."""

    title: str
    company: str
    location: str | None = None
    is_remote: bool = False
    url: str
    # Clean TEXT, never HTML: the boards that serve HTML (Remotive, WWR) run it through
    # ``services/html_sanitize`` in their own adapter. Downstream this feeds both the keyword
    # Fit pass and, verbatim, the One-click Resume's job description.
    description: str = ""
    # Timezone-aware UTC, like every datetime in ``db/tables.py``. ``None`` when the board says
    # nothing -- the recency term then scores as the oldest bucket rather than guessing.
    # A board that exposes only a calendar date resolves to 00:00 UTC of that date: rounding a
    # posting DOWN in freshness can only cost it rank, never inflate it.
    date_posted: datetime | None = None
    # ``None`` (not ``"unknown"``) everywhere but LinkedIn: the distinction is "this board has
    # no such concept" vs "we looked and could not tell". Both become ``unknown`` on the wire.
    applicant_band: ApplicantBand | None = None


class BoardResult(BaseModel):
    """What one Job Board returns for one BoardQuery. Carries its own status because a Scan is
    partial, not failed, when a board blocks: an adapter reports and returns, it never raises
    to abort the Scan (the engine converts an escaping exception into ``error`` anyway)."""

    items: list[RawPosting] = Field(default_factory=list)
    status: BoardReportedStatus = "ok"
    # Human-readable, shown as-is in the BoardStatusBar ("LinkedIn: bloqueado, tentamos no
    # próximo Scan"). Never an exception repr, never a URL with credentials.
    message: str | None = None


# --- Wire: /api/jobs (routers/jobs.py, ticket 09) -------------------------------------------


class ListingSourceOut(BaseModel):
    """One occurrence of a Job Listing on one Job Board (CONTEXT.md: Listing Source). A Job
    Listing always keeps EVERY source link -- both because dedup must not cost the user the
    board they would rather apply on, and because naming the board next to its link is what
    Remotive's and Remote OK's terms require."""

    board: BoardId
    url: str
    datePosted: datetime | None = None
    # What THIS board reported. The listing's own band is the smallest known across its sources
    # (the filter should judge a job by its least crowded posting), so the two can differ.
    applicantBand: ApplicantBand = "unknown"


class JobListingOut(BaseModel):
    """One job found by the latest Scan (CONTEXT.md: Job Listing), deduplicated across boards.

    Ephemeral by design: the list IS the last Scan, so an id here is only valid until the next
    Scan completes. Anything that must outlive a Scan (``status``, the Fit already computed, a
    One-click Resume) lives in the Listing Memory and is reattached by identity.

    ``description`` is the one field the list endpoint omits (fifty full postings is a payload
    nobody reads); ``GET /listings/{id}`` always sets it. ``descriptionWordCount`` is always
    present precisely so the list can pre-disable One-click without carrying the text.
    """

    id: int
    title: str
    company: str
    location: str | None = None
    isRemote: bool = False
    # Clean text. ``None`` means "not included in this response", never "empty posting".
    description: str | None = None
    descriptionWordCount: int = 0
    datePosted: datetime | None = None
    # A listing already known that came back with a newer ``datePosted`` (CONTEXT.md: Repost).
    # Boards do not flag reposts, so this comparison is the only detection -- and it counts as
    # fresh for ranking, because for the applicant it is a fresh queue.
    isRepost: bool = False
    applicantBand: ApplicantBand = "unknown"
    # 0-100. ``fitEstimated`` is true when this is the cheap keyword pass's number rather than
    # the LLM's: only the top N by keyword fit are scored by the model each Scan, and the rest
    # keep an honest estimate instead of a fake precision.
    fitScore: int = 0
    fitEstimated: bool = True
    # 0-100, the ranking key (CONTEXT.md: Visibility Score) -- the SAME scale as fitScore so the
    # two badges sitting side by side can be read against each other. The weights blend
    # normalized terms: 100 * (0.55*(fit/100) + 0.25*recency + 0.20*competition), with the
    # weights and the band table in config.py.
    visibilityScore: float = 0.0
    # The posting's own language, resolved by the Scan (not the user's UI language). Feeds the
    # Locale Authority when this listing becomes a Resume.
    locale: str = DEFAULT_LOCALE
    # From the Listing Memory, not from the Scan row.
    status: ListingStatus = "new"
    # True when the Listing Memory already holds a One-click Resume for this identity -- the
    # detail view then offers "Baixar PDF" / "Regerar" instead of spending an LLM call again.
    hasOneClickResume: bool = False
    sources: list[ListingSourceOut] = Field(default_factory=list)


class JobListingListOut(BaseModel):
    """GET /api/jobs/listings. Wrapped in an object rather than served as a bare array -- the
    same shape discipline as ``{"sessions": [...]}`` and ``{"keys": [...]}`` -- so the response
    can grow a sibling field (a count, the scan it came from) without breaking every client.
    Always ordered by ``visibilityScore`` descending; ``dismissed`` listings appear only with
    ``?include_dismissed=1``."""

    listings: list[JobListingOut] = Field(default_factory=list)


class ListingStatusUpdateIn(BaseModel):
    """PATCH /api/jobs/listings/{id}/status. ``new`` is not settable: it is what a Scan writes
    for an identity with no memory, and "undo a dismiss" is ``seen``, not amnesia."""

    status: Literal["seen", "applied", "dismissed"]


class BoardStatusOut(BaseModel):
    """How one board fared in one Scan. A LIST of these (rather than the ``{board: {...}}`` map
    ``job_scans.board_statuses`` stores) is what goes on the wire: the BoardStatusBar renders
    them in order, and a list keeps that order stable across responses."""

    board: BoardId
    status: BoardStatus
    # Why, when the status is not ``ok`` -- shown verbatim to the user.
    message: str | None = None
    # Postings this board contributed BEFORE dedup, so the numbers explain a partial Scan
    # ("Indeed: 40, LinkedIn: bloqueado") rather than the deduplicated total.
    count: int = 0


class ScanOut(BaseModel):
    """One run of the Job Monitor (CONTEXT.md: Scan). Served by ``GET /scans/current`` while a
    Scan holds the single-flight lock (``boards`` fills in as each board answers, which is what
    the UI polls for), by ``GET /scans/latest`` afterwards, and in the 409 body when an
    Immediate Scan is refused because one is already running."""

    id: int
    startedAt: datetime
    finishedAt: datetime | None = None
    trigger: ScanTrigger
    status: ScanStatus
    boards: list[BoardStatusOut] = Field(default_factory=list)
    listingsFound: int = 0
    listingsScored: int = 0
    # COMPUTED, not persisted: ``finishedAt + interval_hours`` as the scheduler will next wake.
    # ``None`` when the interval is off or this Scan is still running. It lives on the Scan
    # rather than on the Search Profile because "próxima varredura" is a fact about the last
    # run, and the scheduler rereads the interval every loop anyway.
    nextScanAt: datetime | None = None


class SearchProfileIn(BaseModel):
    """PUT /api/jobs/search-profile -- what the user is looking for (CONTEXT.md: Search
    Profile). Distinct from the Profile: the Profile says who you are, this says what you want.
    Seeded from the Profile by ``POST /search-profile/suggest``, then owned by the user, which
    is why every field is sent whole on a PUT rather than patched."""

    roles: list[str] = Field(default_factory=list)
    # Default "Brasil" + "Remote" is applied by the service, not here: an empty list from the
    # user means empty, and only a first-time suggestion invents a value.
    locations: list[str] = Field(default_factory=list)
    remote: RemotePreference = "any"
    # Languages of POSTINGS the user accepts (default pt + en) -- free-form tags matched
    # case-insensitively, deliberately NOT ``SUPPORTED_LOCALES``: a job written in Spanish is a
    # job this user might want, even though the Resume can only be produced in pt-BR or en.
    languages: list[str] = Field(default_factory=list)
    boards: list[BoardId] = Field(default_factory=list)
    # ``None`` is "qualquer" -- no cap. A listing whose band is ``unknown`` passes ANY cap
    # (CONTEXT.md: Applicant Band): an absent number is not evidence of a crowd.
    maxApplicantBand: MaxApplicantBand | None = None
    # ``None`` is off: no scheduled Scan, Immediate Scan still works.
    intervalHours: ScanIntervalHours | None = None


class SearchProfileOut(SearchProfileIn):
    """GET /api/jobs/search-profile and the body of ``POST /search-profile/suggest``.

    ``updatedAt`` is ``None`` for a SUGGESTION -- the one case where this shape describes
    something that was never saved. That is the whole reason the suggest endpoint returns the
    full profile rather than a diff: the form can render it as if it were loaded, and the user
    edits it into existence with a normal PUT.
    """

    updatedAt: datetime | None = None


class BoardOut(BaseModel):
    """One entry of ``GET /api/jobs/boards`` -- the catalog the Search Profile form renders its
    checkboxes from, and the source of the display name a Listing Source chip shows. Served
    from the provider registry rather than hardcoded in the web app so a board added in the
    backend appears in the UI without a frontend change."""

    id: BoardId
    displayName: str
    # The board's OWN floor, independent of the user's interval (Remotive's terms cap us at 4
    # calls a day, hence 6). The Scan uses ``max(user interval, this)`` and marks the board
    # ``skipped`` when it has not elapsed -- which the form shows so a 1h interval does not
    # silently mean 1h for every board.
    minIntervalHours: int = 1
    # Attribution some boards' terms REQUIRE of anyone republishing their listings (Remotive,
    # Remote OK), shown verbatim wherever their results are. ``None`` for a board that asks for
    # nothing. Additive to the ticket-01 contract (ticket 06): it travels with the catalog so a
    # legal obligation lives beside the id it belongs to, instead of as a string the web app
    # would have to remember to keep in sync with the board list.
    attributionNote: str | None = None


class BoardListOut(BaseModel):
    """GET /api/jobs/boards -- same object-wrapping rule as JobListingListOut."""

    boards: list[BoardOut] = Field(default_factory=list)


class OpenInChatOut(BaseModel):
    """POST /api/jobs/listings/{id}/open-in-chat. Creates a normal ``kind='resume'`` session
    seeded with the listing's description and returns nothing but its id: the frontend then
    selects that session and streams a turn exactly as if the user had pasted the posting, so
    the Job Monitor adds NO new path through the chat."""

    sessionId: int
