import type {
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
} from './dto'
import { postInit, requestBlob, requestJson, requestStream, requestVoid } from './client'
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
