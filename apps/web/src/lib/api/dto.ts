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
