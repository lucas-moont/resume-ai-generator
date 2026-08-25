import type { ProfileMaster, ResumeDocument, TemplateId } from '../../types/resume'

export interface ModelSuggestion {
  value: string
  label: string
  /** v3 ticket 03 (additive backend change): which provider this suggestion came from.
   * Optional — some fixtures/mocks (and historically the Composer) don't need it; the
   * ModelPicker (ticket 06) is the first consumer that filters on it. */
  provider?: ProviderName
}

export interface ModelsResponse {
  default?: string
  models?: ModelSuggestion[]
}

export interface GithubRepo {
  name: string
  url?: string
}

export interface GithubReposResponse {
  repos?: GithubRepo[]
  warning?: string
}

export interface GenerateRequest {
  job_description: string
  model?: string
  locale?: string
}

export interface RefineRequest {
  resume: ResumeDocument
  message: string
  model?: string
}

export interface ExportPdfRequest {
  resume: ResumeDocument
  template: TemplateId
}

// Payloads carried by the generate/refine SSE streams — same shapes App.tsx
// previously declared locally as StreamStage/StreamDone/StreamError.
export interface StreamStagePayload {
  step: string
  progress?: number
  message?: string
}

export interface StreamDonePayload {
  progress?: number
  resume: ResumeDocument
}

export interface StreamErrorPayload {
  message?: string
}

// --- Chat (B6/F5): POST/GET/DELETE /api/chat/sessions[...] ---

/** v5 ticket 00: discriminates the resume chat from the Profile Analysis area. Optional
 * (not required) so every v1–v4 fixture/mock compiles unchanged until b1 ships it; absent is
 * read as 'resume'. */
export type ChatSessionKind = 'resume' | 'profile_analysis'

export interface ChatSessionSummary {
  id: number
  title: string | null
  updatedAt: string
  activeResumeVersionId: number | null
  /** v5 ticket 00: see ChatSessionKind. Absent ⇒ 'resume' (retrocompatible). */
  kind?: ChatSessionKind
}

export interface ChatSessionListResponse {
  sessions: ChatSessionSummary[]
}

export interface ChatMessageDto {
  id: number
  role: 'user' | 'assistant'
  content: string
  intent: string | null
  resumeVersionId: number | null
  createdAt: string
  /** v2 ticket 10: present (non-null) when this message is linked to a Source Document
   * upload. GET /api/chat/sessions/{id} joins source_documents LIVE, at read time, for its
   * CURRENT status/diffSummary/opsCount — never a stale copy (see ChatMessageSourceDocumentDto). */
  sourceDocument: ChatMessageSourceDocumentDto | null
  /** v4 ticket 00: present (non-null) when this message carries an Improvement Proposal.
   * Same live-join rule as sourceDocument: GET joins improvement_proposals at read time for
   * the CURRENT status/revision — never a stale copy. Optional (not `| null` alone) so v3
   * fixtures/mocks compile unchanged until B6/F5 land. */
  proposal?: ChatMessageProposalDto | null
  /** v5 ticket 00: present (non-null) when this message carries a Profile Analysis. Rebuilt
   * from the message `meta` at read time (rehydration, ticket b5). Optional so v1–v4
   * fixtures/mocks compile unchanged until v5 backend lands. */
  analysis?: ChatMessageAnalysisDto | null
}

/** v2 ticket 10: shape of ChatMessageDto's `sourceDocument` field — mirrors the fields
 * ProfileUpdatedCard (chatStore.ts) needs, minus `type` (the card variant is decided by the
 * caller reconstructing it, not carried on the wire). */
export interface ChatMessageSourceDocumentDto {
  documentId: number
  filename: string
  status: SourceDocumentStatus
  diffSummary: string[]
  opsCount: number
  error: string | null
}

export interface ChatSessionDetailResponse {
  session: ChatSessionSummary
  messages: ChatMessageDto[]
  activeResume: ResumeDocument | null
  /** v4 ticket 00: the session's single Pending Proposal (status 'proposed'), or null.
   * Top-level so the composer/button can rehydrate the state machine without scanning
   * messages. Optional until B6 ships it. */
  pendingProposal?: ChatMessageProposalDto | null
}

export interface CreateChatSessionRequest {
  title?: string
  /** v5 ticket 00: create a Profile Analysis conversation instead of a resume chat. Absent ⇒
   * 'resume' (retrocompatible). Consumed by b1. */
  kind?: ChatSessionKind
}

export interface CreateChatSessionResponse {
  id: number
  title: string | null
  createdAt: string
}

/** v4.1-03 (frozen contract): PATCH /api/chat/sessions/{id} body -- title must be 1..120
 * chars, non-blank, after trimming (enforced server-side; a violation is a 422). */
export interface RenameChatSessionRequest {
  title: string
}

export interface RenameChatSessionResponse {
  id: number
  title: string
  updatedAt: string
}

export interface ChatMessageStreamRequest {
  message: string
  model?: string
  locale?: string
  jobDescription?: string
  /** v2 ticket 11: the client's own in-memory resume (post inline-edit, never persisted),
   * sent whenever `resumeStore` has an active resume — lets a chat `refine` turn start from
   * what the user is actually looking at instead of the last version the server persisted.
   * Ignored server-side by every intent except `refine`. */
  resume?: ResumeDocument
  /** v4 ticket 00: deterministic shortcut carried by the "Aprovar e gerar" button — routes
   * the turn straight into the approve branch of the Proposal Turn, zero LLM classification.
   * Ignored server-side when the session has no Pending Proposal. */
  proposalAction?: 'approve'
}

// Chat-stream-only SSE payloads (stage/error are shared with StreamStagePayload/StreamErrorPayload above).
export interface ChatResumeEventPayload {
  resume: ResumeDocument
  resumeVersionId: number
}

export interface ChatMessageEventPayload {
  content: string
}

export interface ChatDoneEventPayload {
  progress?: number
  messageId: number
  resumeVersionId: number | null
  /** v4 ticket 00: present on any turn that created/revised/approved an Improvement
   * Proposal. See docs/v4-improvement-proposal.md §3.4. */
  proposalId?: number
}

// --- Improvement Proposal (v4, ticket 00) ---
// Contract per docs/v4-improvement-proposal.md §1.2/§3.2/§3.7. Frozen: backend and
// frontend builders implement against these shapes.

export type ProposalSection =
  | 'headline'
  | 'summary'
  | 'experience'
  | 'projects'
  | 'skills'
  | 'education'
  | 'links'
  | 'location'

export type ProposalStatus = 'proposed' | 'approved' | 'superseded' | 'discarded'

/** What a Proposal Item DOES to its section (v6, Relevance Filter). Before v6 every item was
 * implicitly a `rewrite`, so the agent could only swap text for other text — never offer to
 * subtract profile noise that has no bearing on the job. `drop` removes the `targets` outright
 * (backend restricts it to `skills`/`projects`); `compress` keeps a role's employer/title/dates
 * and shrinks it to one bullet (`experience` only). */
export type ProposalOp = 'rewrite' | 'add' | 'drop' | 'compress'

/** One improvement inside an Improvement Proposal (CONTEXT.md: Proposal Item): WHAT
 * changes (section + op + proposed), against WHAT (current excerpt), WHY (rationale anchored
 * in the job description).
 *
 * `op`/`targets` are optional in the DTO rather than required: proposals persisted before v6
 * are served back without them, and the backend defaults a missing `op` to `'rewrite'`. Read
 * them as `item.op ?? 'rewrite'` and `item.targets ?? []`. `targets` holds the literal profile
 * labels an op acts on (skill names, project names, an employer) — the machine-readable half of
 * a removal, whose human-readable half is in `proposed` and in the assistant's prose. */
export interface ProposalItemDto {
  id: number
  section: ProposalSection
  op?: ProposalOp
  current: string | null
  proposed: string
  targets?: string[]
  rationale: string
}

/** Chat-stream-only: emitted by the Analysis / adjust / new-JD turns BEFORE the prose
 * `message` bubble that presents it (the card attaches to that next message). */
export interface ChatProposalEventPayload {
  proposalId: number
  status: ProposalStatus
  revision: number
  items: ProposalItemDto[]
}

/** Shape of ChatMessageDto's `proposal` field and ChatSessionDetailResponse's
 * `pendingProposal` — same fields the stream event carries (live-joined at read time). */
export type ChatMessageProposalDto = ChatProposalEventPayload

/** Chat-stream-only: emitted for the `profile_update` intent (v2, ticket 05/09)
 * — the Living Profile changed via chat, source_kind='chat'. Never carried by
 * the legacy generate/refine streams (that intent is chat-only). */
export interface ChatProfileUpdateEventPayload {
  profileVersion: number
  summary: string
}

// --- Profile Analysis (v5, ticket 00) ---
// Contract per docs/v5-profile-analysis.md. Frozen: backend and frontend builders implement
// against these shapes. Read-only advice on a LinkedIn profile — an Analysis never mutates
// the Living Profile nor produces a Resume.

export type AnalysisSection = 'headline' | 'about' | 'experience' | 'skills' | 'completeness'

export type AnalysisPriority = 'alta' | 'média' | 'baixa'

/** One recommendation inside a Profile Analysis (CONTEXT.md: Analysis Item): the target
 * LinkedIn section, the user's current text (optional), the suggested change, WHY (rationale
 * anchored in a LinkedIn best practice / the context given), and a priority. */
export interface AnalysisItemDto {
  section: AnalysisSection
  current: string | null
  suggestion: string
  rationale: string
  priority: AnalysisPriority
}

/** Chat-stream-only: emitted by an Analysis Turn BEFORE the prose `message` bubble that
 * presents it (the card attaches to that next message) — same semantics as
 * ChatProposalEventPayload. Absent on a Clarifying-Question turn, which emits only a
 * `message` bubble. */
export interface ChatAnalysisEventPayload {
  items: AnalysisItemDto[]
  summary: string
}

/** Shape of ChatMessageDto's `analysis` field — same fields the stream event carries,
 * reconstructed from the message `meta` at read time (rehydration, ticket b5). */
export type ChatMessageAnalysisDto = ChatAnalysisEventPayload

// --- Living Profile: Source Documents (v2, F7 — ticket 07) ---
// Contract per docs/v2-living-profile.md item 3 + ticket 04's addendum
// (proposedPatch/diffSummary land in the same 202 response once the merge
// step exists server-side — no polling).

export type SourceDocumentMediaType = 'json' | 'md' | 'pdf'

export type SourceDocumentStatus =
  | 'stored'
  | 'extracted'
  | 'proposed'
  | 'applied'
  | 'rejected'
  | 'failed'

export interface PatchOp {
  op: 'add' | 'replace' | 'remove'
  path: string
  value?: unknown
  reason: string
  confidence: number
  sourceExcerpt: string
}

export interface UploadSourceDocumentResponse {
  documentId: number
  status: SourceDocumentStatus
  proposedPatch?: PatchOp[]
  diffSummary?: string[]
  /** Part of the wire contract (spec item 3) and expected from the backend,
   * but no frontend consumer surfaces it yet — ProfileUpdatedCard only
   * renders diffSummary/opsCount today. Deliberately deferred (ticket 07);
   * see useFileUpload's mapping to SettledUpload, which drops this field. */
  extractedPreview?: unknown
  error?: string
}

export interface ApplySourceDocumentResponse {
  profileVersion: number
  applied: number
  skipped: number
}

// --- Settings: providers/models/keys (v3, ticket 03 backend / ticket 06 frontend) ---
// Shapes per docs/v3-agnostic-settings.md §Backend-2 / app/routers/settings.py.

export type ProviderName = 'claude' | 'gemini' | 'ollama'
export type ProviderMode = 'auto' | ProviderName
export type ProviderAuthMode = 'api_key' | 'cli' | 'local' | 'none'

export interface ProviderCatalogModel {
  value: string
  label: string
}

export interface ProviderEntry {
  name: ProviderName
  available: boolean
  auth: ProviderAuthMode
  defaultModel: string
  /** v3 ticket 11 (additive): true when `defaultModel` is pinned by this provider's own env
   * var (`defaultModelEnvVar`, e.g. `CLAUDE_MODEL`) — config.py's env-wins precedence means a
   * PUT changing it 200s but has no effect until that var is unset. */
  defaultModelLockedByEnv: boolean
  defaultModelEnvVar: string
  models: ProviderCatalogModel[]
}

export interface ProvidersSettingsResponse {
  active: ProviderMode
  /** v3 ticket 11 (additive): same "env pins it, PUT is a no-op" signal as
   * ProviderEntry.defaultModelLockedByEnv, for `active` itself (`AI_PROVIDER`). */
  activeLockedByEnv: boolean
  activeEnvVar: string
  providers: ProviderEntry[]
}

export interface ProvidersSettingsUpdateRequest {
  provider: ProviderMode
  defaultModel?: string
}

/** The three keys PUT/DELETE /api/settings/keys manages — mirrors the backend's
 * settings_service.MANAGED_SECRET_NAMES (the single source of truth there). */
export type ManagedSecretName = 'ANTHROPIC_API_KEY' | 'GEMINI_API_KEY' | 'GITHUB_TOKEN' // pragma: allowlist secret
export type SecretSource = 'env' | 'keychain' | null // pragma: allowlist secret

export interface SecretKeyEntry {
  name: ManagedSecretName
  configured: boolean
  source: SecretSource
}

export interface KeysSettingsResponse {
  keys: SecretKeyEntry[]
}

export interface KeyUpsertRequest {
  name: ManagedSecretName
  /** Write-only: never populated from a server response — only ever sent, never received. */
  value: string
}

// --- Profile: GitHub username (v4.1 follow-up — manual githubUsername config) ---

/** GET /api/profile returns the resolved Living Profile as-is (routers/profile.py's
 * `get_profile`) — same shape as ProfileMaster, no separate wrapper. */
export type ProfileResponse = ProfileMaster

export interface UpdateGithubUsernameRequest {
  githubUsername: string | null
}

export interface UpdateGithubUsernameResponse {
  profileVersion: number
  githubUsername: string | null
}

// --- Job Monitor (v7, ticket 01) — FROZEN CONTRACT ---
// Vocabulary: CONTEXT.md section "Job Monitor (v7)". Wire shapes: docs/v7-job-monitor.md §Backend-6.
// Mirrors the `*Out`/`*In` pydantic models in apps/api/app/domain/schemas.py field for field.
// Additive and unconsumed: no client, no store, no component reads these yet — tickets 11-15 do.
//
// The backend's domain types (RawPosting / BoardQuery / BoardResult) deliberately have NO
// counterpart here. They cross the seam between a Job Board adapter and the Scan engine and
// never reach HTTP, so a copy in `lib/api` would be a shape the frontend can neither receive
// nor send.
//
// Dates are ISO 8601 strings on the wire (pydantic serializes the backend's timezone-aware UTC
// datetimes), same as `ChatSessionSummary.updatedAt`.

/** The number of applicants as a BAND, never an exact count (CONTEXT.md: Applicant Band).
 * LinkedIn is the only board that exposes anything — an exact number up to 100, "over 100"
 * past that — so the bands are what that page can say, plus `'unknown'` for every other board.
 * `'unknown'` never excludes a listing from the user's cap; it only scores neutrally. */
export type ApplicantBand = '<10' | '<25' | '<50' | '<100' | '100+' | 'unknown'

/** The subset a user may pick as their MAXIMUM (the select is `<10 · <25 · <50 · <100 ·
 * qualquer`). `'100+'`/`'unknown'` are not offerable: as a cap they would mean "everything",
 * which `null` already says. */
export type MaxApplicantBand = '<10' | '<25' | '<50' | '<100'

/** The user's relationship with a Job Listing (CONTEXT.md: Listing Status). Kept in the Listing
 * Memory, so a `'dismissed'` job stays hidden when a later Scan finds it again. */
export type ListingStatus = 'new' | 'seen' | 'applied' | 'dismissed'

/** How one Job Board fared in one Scan. A Scan is PARTIAL, never failed, when a board blocks:
 * `'blocked'` = the board refused us, `'error'` = the board or the adapter broke, `'skipped'` =
 * that board's own minimum interval had not elapsed, so it was not called at all. */
export type BoardStatus = 'ok' | 'blocked' | 'error' | 'skipped'

/** The Job Boards of v7 (CONTEXT.md: Job Board). Closed like `TemplateId`: these ids are
 * persisted server-side and a typo should fail loudly. Widening it (the BR portals are out of
 * scope for v7) is safe; retiring a board needs a backend migration. */
export type BoardId =
  | 'linkedin'
  | 'indeed'
  | 'glassdoor'
  | 'google'
  | 'remotive'
  | 'weworkremotely'
  | 'remoteok'

/** What the user will accept: `'remote_only'` keeps only postings the board flags remote;
 * `'onsite_ok'` allows on-site/hybrid within the chosen locations (remote still counts). */
export type RemotePreference = 'any' | 'remote_only' | 'onsite_ok'

/** How often the Job Monitor scans on its own; `null` (off) still allows an Immediate Scan.
 * The effective interval per board is `max(this, board.minIntervalHours)`. */
export type ScanIntervalHours = 1 | 3 | 6 | 12 | 24

export type ScanTrigger = 'scheduled' | 'immediate'

/** `'running'` is the single-flight state: at most one Scan holds it, and a second Immediate
 * Scan request meanwhile gets a 409 carrying that Scan. There is no `'failed'` — a Scan where
 * every board broke is still `'done'`, with the Board Statuses telling the story. */
export type ScanStatus = 'running' | 'done'

/** One occurrence of a Job Listing on one Job Board (CONTEXT.md: Listing Source). Every source
 * link is kept: dedup must not cost the user the board they would rather apply on, and naming
 * the board beside its link is what Remotive's and Remote OK's terms require. */
export interface ListingSourceDto {
  board: BoardId
  url: string
  datePosted: string | null
  /** What THIS board reported. The listing's own band is the smallest known across its
   * sources, so the two can differ. */
  applicantBand: ApplicantBand
}

/** One job found by the latest Scan (CONTEXT.md: Job Listing), deduplicated across boards.
 *
 * Ephemeral: the list IS the last Scan, so `id` is only valid until the next Scan completes.
 * What outlives a Scan (`status`, the Fit already computed, a One-click Resume) lives in the
 * Listing Memory and is reattached by identity.
 *
 * `description` is `null` in the LIST response (fifty full postings is a payload nobody reads)
 * and always a string from `GET /listings/{id}`. `descriptionWordCount` is always present, so
 * a card can pre-disable One-click without carrying the text. */
export interface JobListingDto {
  id: number
  title: string
  company: string
  location: string | null
  isRemote: boolean
  /** `null` means "not included in this response", never "empty posting". */
  description: string | null
  descriptionWordCount: number
  datePosted: string | null
  /** A known listing that came back with a newer `datePosted` (CONTEXT.md: Repost). Boards do
   * not flag reposts, so this is the only detection — and it ranks as fresh, because for the
   * applicant it is a fresh queue. */
  isRepost: boolean
  applicantBand: ApplicantBand
  /** 0–100. `fitEstimated` is true when this is the cheap keyword pass's number rather than the
   * LLM's: only the top N by keyword fit are scored by the model each Scan. */
  fitScore: number
  fitEstimated: boolean
  /** 0–100, the ranking key (CONTEXT.md: Visibility Score) — the same scale as `fitScore` so
   * the two badges can be read against each other. */
  visibilityScore: number
  /** The POSTING's language, not the UI's. */
  locale: string
  status: ListingStatus
  /** True when the Listing Memory already holds a One-click Resume for this identity — the
   * detail view then offers "Baixar PDF" / "Regerar" instead of spending an LLM call. */
  hasOneClickResume: boolean
  sources: ListingSourceDto[]
}

export interface JobListingListResponse {
  listings: JobListingDto[]
}

/** PATCH /api/jobs/listings/{id}/status. `'new'` is not settable: it is what a Scan writes for
 * an identity with no memory, and "undo a dismiss" is `'seen'`, not amnesia. */
export interface ListingStatusUpdateRequest {
  status: Exclude<ListingStatus, 'new'>
}

/** How one board fared in one Scan. A list (not the `{board: {...}}` map the backend stores)
 * so BoardStatusBar renders them in a stable order. */
export interface BoardStatusDto {
  board: BoardId
  status: BoardStatus
  /** Why, when the status is not `'ok'` — shown verbatim ("LinkedIn: bloqueado, tentamos no
   * próximo Scan"). */
  message: string | null
  /** Postings this board contributed BEFORE dedup, so the numbers explain a partial Scan. */
  count: number
}

/** One run of the Job Monitor (CONTEXT.md: Scan). `GET /scans/current` serves it while the Scan
 * holds the single-flight lock — `boards` fills in as each board answers, which is what the UI
 * polls for — `GET /scans/latest` afterwards, and it is also the 409 body when an Immediate
 * Scan is refused. */
export interface ScanDto {
  id: number
  startedAt: string
  finishedAt: string | null
  trigger: ScanTrigger
  status: ScanStatus
  boards: BoardStatusDto[]
  listingsFound: number
  listingsScored: number
  /** COMPUTED, not stored: when the scheduler will next wake. `null` when the interval is off
   * or this Scan is still running. */
  nextScanAt: string | null
}

/** PUT /api/jobs/search-profile — what the user is looking for (CONTEXT.md: Search Profile).
 * Distinct from the Profile: the Profile says who you are, this says what you want. Sent whole
 * on every save rather than patched, because the user owns it outright once suggested. */
export interface SearchProfileUpdateRequest {
  roles: string[]
  locations: string[]
  remote: RemotePreference
  /** Languages of POSTINGS the user accepts (default pt + en) — deliberately not the resume's
   * supported locales: a posting in Spanish may still be one this user wants. */
  languages: string[]
  boards: BoardId[]
  /** `null` is "qualquer" — no cap. A listing whose band is `'unknown'` passes any cap. */
  maxApplicantBand: MaxApplicantBand | null
  /** `null` is off: no scheduled Scan; Immediate Scan still works. */
  intervalHours: ScanIntervalHours | null
}

/** GET /api/jobs/search-profile, and the body of `POST /search-profile/suggest`.
 *
 * `updatedAt` is `null` for a SUGGESTION — the one case where this shape describes something
 * never saved. That is why suggest returns the whole profile rather than a diff: the form
 * renders it as if loaded, and the user edits it into existence with a normal PUT. */
export interface SearchProfileDto extends SearchProfileUpdateRequest {
  updatedAt: string | null
}

/** One entry of `GET /api/jobs/boards` — the catalog the Search Profile form builds its
 * checkboxes from, and where a Listing Source chip gets its display name. Served from the
 * backend's provider registry, so a board added there shows up without a frontend change. */
export interface BoardDto {
  id: BoardId
  displayName: string
  /** The board's OWN floor, independent of the user's interval (Remotive's terms cap us at 4
   * calls a day, hence 6). A board below it is marked `'skipped'` for that Scan. */
  minIntervalHours: number
}

export interface BoardListResponse {
  boards: BoardDto[]
}

/** POST /api/jobs/listings/{id}/open-in-chat. Creates a normal `kind: 'resume'` session seeded
 * with the listing's description; the frontend selects it and streams a turn exactly as if the
 * user had pasted the posting, so the Job Monitor adds no new path through the chat. */
export interface OpenInChatResponse {
  sessionId: number
}
