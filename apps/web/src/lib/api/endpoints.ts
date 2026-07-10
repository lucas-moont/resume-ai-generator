import type {
  ApplySourceDocumentResponse,
  ChatMessageStreamRequest,
  ChatSessionDetailResponse,
  ChatSessionListResponse,
  CreateChatSessionRequest,
  CreateChatSessionResponse,
  ExportPdfRequest,
  GenerateRequest,
  GithubReposResponse,
  ModelsResponse,
  RefineRequest,
  UploadSourceDocumentResponse,
} from './dto'
import {
  postInit,
  requestBlob,
  requestJson,
  requestMultipart,
  requestStream,
  requestVoid,
  type MultipartOptions,
} from './client'
import { parseSseStream, type SseEvent } from './sse'

export { ApiError } from './client'

export function fetchModels(): Promise<ModelsResponse> {
  return requestJson<ModelsResponse>('/api/models')
}

export function fetchGithubRepos(): Promise<GithubReposResponse> {
  return requestJson<GithubReposResponse>('/api/github/repos')
}

export function exportPdf(payload: ExportPdfRequest): Promise<Blob> {
  return requestBlob('/api/export/pdf', postInit(payload))
}

export async function generateStream(
  payload: GenerateRequest,
  signal?: AbortSignal,
): Promise<AsyncGenerator<SseEvent>> {
  const response = await requestStream('/api/generate/stream', postInit(payload, signal))
  return parseSseStream(response)
}

export async function refineStream(
  payload: RefineRequest,
  signal?: AbortSignal,
): Promise<AsyncGenerator<SseEvent>> {
  const response = await requestStream('/api/refine/stream', postInit(payload, signal))
  return parseSseStream(response)
}

// --- Chat (B6/F5) ---

export function createChatSession(
  payload: CreateChatSessionRequest = {},
): Promise<CreateChatSessionResponse> {
  return requestJson<CreateChatSessionResponse>('/api/chat/sessions', postInit(payload))
}

export function listChatSessions(): Promise<ChatSessionListResponse> {
  return requestJson<ChatSessionListResponse>('/api/chat/sessions')
}

export function getChatSession(sessionId: number): Promise<ChatSessionDetailResponse> {
  return requestJson<ChatSessionDetailResponse>(`/api/chat/sessions/${sessionId}`)
}

export function deleteChatSession(sessionId: number): Promise<void> {
  return requestVoid(`/api/chat/sessions/${sessionId}`, { method: 'DELETE' })
}

export async function chatMessageStream(
  sessionId: number,
  payload: ChatMessageStreamRequest,
  signal?: AbortSignal,
): Promise<AsyncGenerator<SseEvent>> {
  const response = await requestStream(
    `/api/chat/sessions/${sessionId}/messages/stream`,
    postInit(payload, signal),
  )
  return parseSseStream(response)
}

// --- Living Profile: Source Documents (v2, F7) ---

export function uploadSourceDocument(
  file: File,
  options: MultipartOptions = {},
): Promise<UploadSourceDocumentResponse> {
  const formData = new FormData()
  formData.append('file', file)
  return requestMultipart<UploadSourceDocumentResponse>('/api/profile/documents', formData, options)
}

export function applySourceDocument(
  documentId: number,
  ops?: number[],
): Promise<ApplySourceDocumentResponse> {
  return requestJson<ApplySourceDocumentResponse>(
    `/api/profile/documents/${documentId}/apply`,
    postInit({ ops }),
  )
}

export function rejectSourceDocument(documentId: number): Promise<void> {
  return requestVoid(`/api/profile/documents/${documentId}/reject`, { method: 'POST' })
}
