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
