import type { ResumeDocument, TemplateId } from '../../types/resume'

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

export interface ChatSessionSummary {
  id: number
  title: string | null
  updatedAt: string
  activeResumeVersionId: number | null
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
}

export interface CreateChatSessionResponse {
  id: number
  title: string | null
  createdAt: string
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

/** One improvement inside an Improvement Proposal (CONTEXT.md: Proposal Item): WHAT
 * changes (section + proposed), against WHAT (current excerpt), WHY (rationale anchored
 * in the job description). */
export interface ProposalItemDto {
  id: number
  section: ProposalSection
  current: string | null
  proposed: string
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
