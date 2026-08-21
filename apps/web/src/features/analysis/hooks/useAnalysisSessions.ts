import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createChatSession,
  deleteChatSession,
  getChatSession,
  listChatSessions,
} from '../../../lib/api/endpoints'
import type { ChatMessageDto, CreateChatSessionResponse } from '../../../lib/api/dto'
import { useAnalysisStore, type AnalysisMessage } from '../store/analysisStore'

export const ANALYSIS_SESSIONS_QUERY_KEY = ['analysis-sessions'] as const
export const analysisSessionQueryKey = (sessionId: number) => ['analysis-session', sessionId] as const

/** Lists Profile Analysis sessions (kind='profile_analysis') for the analysis sidebar.
 * `retry: false` mirrors useSessions: if the backend isn't wired up (404), the sidebar hides
 * itself rather than flashing a broken state. */
export function useAnalysisSessions() {
  return useQuery({
    queryKey: ANALYSIS_SESSIONS_QUERY_KEY,
    queryFn: () => listChatSessions('profile_analysis'),
    retry: false,
  })
}

export function useCreateAnalysisSession() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (title?: string): Promise<CreateChatSessionResponse> =>
      createChatSession({ kind: 'profile_analysis', ...(title ? { title } : {}) }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ANALYSIS_SESSIONS_QUERY_KEY })
    },
  })
}

export function useDeleteAnalysisSession() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (sessionId: number) => deleteChatSession(sessionId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ANALYSIS_SESSIONS_QUERY_KEY })
    },
  })
}

/** Rehydrates one analysis message from the session-detail DTO: the `analysis` field (b5's
 * live join from meta) becomes the card; a plain reply / clarifying question has none. */
function toAnalysisMessage(dto: ChatMessageDto): AnalysisMessage {
  return {
    id: String(dto.id),
    role: dto.role,
    content: dto.content,
    createdAt: new Date(dto.createdAt).getTime(),
    ...(dto.role === 'assistant' && dto.analysis != null
      ? { analysis: { items: dto.analysis.items, summary: dto.analysis.summary } }
      : {}),
  }
}

export function useResumeAnalysisSession() {
  const queryClient = useQueryClient()

  const resumeSession = async (sessionId: number): Promise<void> => {
    const detail = await queryClient.fetchQuery({
      queryKey: analysisSessionQueryKey(sessionId),
      queryFn: () => getChatSession(sessionId),
      staleTime: 0,
    })
    useAnalysisStore.getState().loadSession(sessionId, detail.messages.map(toAnalysisMessage))
  }

  const startNewAnalysis = (): void => {
    useAnalysisStore.getState().reset()
  }

  return { resumeSession, startNewAnalysis }
}

/** Boot-time restore of the active analysis session (mirrors useRestoreActiveSession): if a
 * sessionId survived reload but its messages didn't, refetch the conversation. A deleted or
 * unreachable session falls back to a clean empty state. */
export function useRestoreActiveAnalysisSession(): void {
  const queryClient = useQueryClient()

  useEffect(() => {
    const { sessionId, messages } = useAnalysisStore.getState()
    if (sessionId === null || messages.length > 0) return

    let cancelled = false
    queryClient
      .fetchQuery({
        queryKey: analysisSessionQueryKey(sessionId),
        staleTime: 0,
        queryFn: () => getChatSession(sessionId),
      })
      .then((detail) => {
        if (cancelled) return
        useAnalysisStore.getState().loadSession(sessionId, detail.messages.map(toAnalysisMessage))
      })
      .catch(() => {
        if (cancelled) return
        useAnalysisStore.getState().reset()
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
}
