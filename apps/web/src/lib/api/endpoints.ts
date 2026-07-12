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
  KeysSettingsResponse,
  KeyUpsertRequest,
  ManagedSecretName,
  ModelsResponse,
  ProvidersSettingsResponse,
  ProvidersSettingsUpdateRequest,
  RefineRequest,
  RenameChatSessionRequest,
  RenameChatSessionResponse,
  SecretKeyEntry,
  UploadSourceDocumentResponse,
} from './dto'
import {
  postInit,
  putInit,
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

/** v4.1-03: PATCH is not one of client.ts's postInit/putInit helpers (POST/PUT only),
 * so this builds the JSON request inline rather than adding a third helper for a single
 * call site. */
export function renameChatSession(sessionId: number, title: string): Promise<RenameChatSessionResponse> {
  const payload: RenameChatSessionRequest = { title }
  return requestJson<RenameChatSessionResponse>(`/api/chat/sessions/${sessionId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
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

export interface UploadSourceDocumentOptions extends MultipartOptions {
  /** v2 ticket 10: the active chat session this upload came from, if any -- lets the backend
   * persist a durable link (chat_messages.meta) so the ProfileUpdatedCard survives a session
   * reload. Omitted (not sent as a field at all) when there is no active session. */
  sessionId?: number
}

export function uploadSourceDocument(
  file: File,
  options: UploadSourceDocumentOptions = {},
): Promise<UploadSourceDocumentResponse> {
  const { sessionId, ...multipartOptions } = options
  const formData = new FormData()
  formData.append('file', file)
  if (sessionId !== undefined) formData.append('sessionId', String(sessionId))
  return requestMultipart<UploadSourceDocumentResponse>('/api/profile/documents', formData, multipartOptions)
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

// --- Settings: providers/models/keys (v3 ticket 06) ---

export function fetchProviderSettings(): Promise<ProvidersSettingsResponse> {
  return requestJson<ProvidersSettingsResponse>('/api/settings/providers')
}

export function updateProviderSettings(
  payload: ProvidersSettingsUpdateRequest,
): Promise<ProvidersSettingsResponse> {
  return requestJson<ProvidersSettingsResponse>('/api/settings/providers', putInit(payload))
}

export function fetchKeySettings(): Promise<KeysSettingsResponse> {
  return requestJson<KeysSettingsResponse>('/api/settings/keys')
}

export function upsertKeySetting(payload: KeyUpsertRequest): Promise<SecretKeyEntry> {
  return requestJson<SecretKeyEntry>('/api/settings/keys', putInit(payload))
}

export function deleteKeySetting(name: ManagedSecretName): Promise<void> {
  return requestVoid(`/api/settings/keys/${name}`, { method: 'DELETE' })
}
