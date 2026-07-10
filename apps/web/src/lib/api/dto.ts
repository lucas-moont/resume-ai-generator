import type { ResumeDocument, TemplateId } from '../../types/resume'

export interface ModelSuggestion {
  value: string
  label: string
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
}

export interface ChatSessionDetailResponse {
  session: ChatSessionSummary
  messages: ChatMessageDto[]
  activeResume: ResumeDocument | null
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
}

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
