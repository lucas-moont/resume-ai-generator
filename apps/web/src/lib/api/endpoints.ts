import type {
  ExportPdfRequest,
  GenerateRequest,
  GithubReposResponse,
  ModelsResponse,
  RefineRequest,
} from './dto'
import { postInit, requestBlob, requestJson, requestStream } from './client'
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
