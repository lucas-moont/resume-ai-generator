import { useCallback } from 'react'
import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { ApiError, analysisPdfStream, chatMessageStream } from '../../../lib/api/endpoints'
import type {
  ChatAnalysisEventPayload,
  ChatMessageEventPayload,
  CreateChatSessionResponse,
  StreamErrorPayload,
  StreamStagePayload,
} from '../../../lib/api/dto'
import { useAnalysisStore, type AnalysisCard } from '../store/analysisStore'
import {
  ANALYSIS_SESSIONS_QUERY_KEY,
  analysisSessionQueryKey,
  useCreateAnalysisSession,
} from './useAnalysisSessions'

/** Drives one Analysis Turn (text message OR PDF upload) over the chat SSE stream, updating
 * the analysisStore. Mirrors useChatStream but far simpler: the analysis area is read-only, so
 * there is no resume/proposal state to reconcile — a turn is either an `analysis` card + its
 * summary bubble, or a plain clarifying-question/fallback bubble. */
export interface UseAnalysisStreamResult {
  send: (message: string) => Promise<void>
  sendPdf: (file: File) => Promise<void>
  stop: () => void
}

const TITLE_PREVIEW_MAX_LENGTH = 60

type CreateSessionFn = (title?: string) => Promise<CreateChatSessionResponse>

function titlePreview(message: string): string {
  return message.length > TITLE_PREVIEW_MAX_LENGTH
    ? `${message.slice(0, TITLE_PREVIEW_MAX_LENGTH - 1)}…`
    : message
}

function isAbortError(e: unknown): boolean {
  return e instanceof DOMException && e.name === 'AbortError'
}

function apiErrorText(e: ApiError, fallback: string): string {
  return typeof e.detail === 'string' ? e.detail : fallback
}

async function ensureSession(title: string, createSession: CreateSessionFn): Promise<number> {
  const existing = useAnalysisStore.getState().sessionId
  if (existing !== null) return existing
  const created = await createSession(titlePreview(title))
  useAnalysisStore.getState().setSessionId(created.id)
  return created.id
}

async function runAnalysisTurn(
  input: { message: string } | { pdf: File },
  createSession: CreateSessionFn,
  queryClient: QueryClient,
): Promise<void> {
  const controller = new AbortController()
  useAnalysisStore.getState().updateStreaming({ progress: 5, message: 'Analisando…', abortController: controller })

  const titleSource = 'message' in input ? input.message : input.pdf.name
  let sessionId: number
  try {
    sessionId = await ensureSession(titleSource, createSession)
  } catch (e) {
    const text = e instanceof ApiError ? apiErrorText(e, 'Algo deu errado.') : String(e)
    useAnalysisStore.getState().appendAssistantMessage(text)
    useAnalysisStore.getState().finishStreaming()
    return
  }

  try {
    const events =
      'message' in input
        ? await chatMessageStream(sessionId, { message: input.message }, controller.signal)
        : await analysisPdfStream(sessionId, input.pdf, controller.signal)

    // The `analysis` card event always precedes the `message` bubble it belongs to (b3); hold
    // it here and attach it when the bubble arrives, same "pendingCard" idea as useChatStream.
    let pendingAnalysis: AnalysisCard | undefined

    for await (const { event, data } of events) {
      if (controller.signal.aborted) return

      if (event === 'stage') {
        const s = data as StreamStagePayload
        useAnalysisStore.getState().updateStreaming({
          step: s.step,
          progress: Math.max(5, Math.min(99, Math.round(s.progress ?? 0))),
          message: s.message ?? '',
        })
      } else if (event === 'analysis') {
        const payload = data as ChatAnalysisEventPayload
        pendingAnalysis = { items: payload.items, summary: payload.summary }
      } else if (event === 'message') {
        const content = (data as ChatMessageEventPayload).content
        const analysis = pendingAnalysis
        pendingAnalysis = undefined
        useAnalysisStore.getState().appendAssistantMessage(content, { analysis, animate: true })
      } else if (event === 'done') {
        useAnalysisStore.getState().finishStreaming()
        invalidateSessionCaches(queryClient, sessionId)
        return
      } else if (event === 'error') {
        const err = data as StreamErrorPayload
        throw new Error(err.message || 'Stream failed')
      }
    }
  } catch (e) {
    if (isAbortError(e)) {
      useAnalysisStore.getState().finishStreaming()
      return
    }
    const text = e instanceof ApiError ? apiErrorText(e, 'Algo deu errado.') : String(e)
    useAnalysisStore.getState().appendAssistantMessage(text)
    useAnalysisStore.getState().finishStreaming()
    invalidateSessionCaches(queryClient, sessionId)
  }
}

function invalidateSessionCaches(queryClient: QueryClient, sessionId: number): void {
  void queryClient.invalidateQueries({ queryKey: analysisSessionQueryKey(sessionId) })
  void queryClient.invalidateQueries({ queryKey: ANALYSIS_SESSIONS_QUERY_KEY })
}

export function useAnalysisStream(): UseAnalysisStreamResult {
  const createMutation = useCreateAnalysisSession()
  const createSession = createMutation.mutateAsync
  const queryClient = useQueryClient()

  const send = useCallback(
    async (message: string) => {
      const trimmed = message.trim()
      if (!trimmed) return
      useAnalysisStore.getState().appendUserMessage(trimmed)
      await runAnalysisTurn({ message: trimmed }, createSession, queryClient)
    },
    [createSession, queryClient],
  )

  const sendPdf = useCallback(
    async (file: File) => {
      useAnalysisStore.getState().appendUserMessage(`📎 ${file.name}`)
      await runAnalysisTurn({ pdf: file }, createSession, queryClient)
    },
    [createSession, queryClient],
  )

  const stop = useCallback(() => {
    const { streaming } = useAnalysisStore.getState()
    streaming?.abortController?.abort()
    useAnalysisStore.getState().finishStreaming()
  }, [])

  return { send, sendPdf, stop }
}
