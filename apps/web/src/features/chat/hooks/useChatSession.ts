import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createChatSession,
  deleteChatSession,
  getChatSession,
  listChatSessions,
} from '../../../lib/api/endpoints'
import type { ChatMessageDto, CreateChatSessionResponse } from '../../../lib/api/dto'
import { useResumeStore } from '../../resume/store/resumeStore'
import { useChatStore, type ChatMessage } from '../store/chatStore'

export const CHAT_SESSIONS_QUERY_KEY = ['chat-sessions'] as const
export const chatSessionQueryKey = (sessionId: number) => ['chat-session', sessionId] as const

/**
 * Lists chat sessions for SessionSidebar. `retry: false` is deliberate: this
 * powers graceful degradation — if the chat backend/router isn't available
 * (e.g. 404) or the request otherwise fails, the sidebar should hide itself
 * immediately rather than retry and flash a broken loading state.
 */
export function useSessions() {
  return useQuery({
    queryKey: CHAT_SESSIONS_QUERY_KEY,
    queryFn: listChatSessions,
    retry: false,
  })
}

/** Reactive session detail (not currently consumed anywhere — resumeSession()
 * below does the one-shot "load and hydrate stores" action via the same
 * query key through queryClient.fetchQuery, so a click doesn't duplicate
 * whatever this hook may have already cached). */
export function useSession(sessionId: number | null) {
  return useQuery({
    queryKey: chatSessionQueryKey(sessionId ?? -1),
    queryFn: () => getChatSession(sessionId as number),
    enabled: sessionId !== null,
  })
}

export function useCreateSession() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (title?: string): Promise<CreateChatSessionResponse> =>
      createChatSession(title ? { title } : {}),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: CHAT_SESSIONS_QUERY_KEY })
    },
  })
}

export function useDeleteSession() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (sessionId: number) => deleteChatSession(sessionId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: CHAT_SESSIONS_QUERY_KEY })
    },
  })
}

function toChatMessage(dto: ChatMessageDto): ChatMessage {
  return {
    id: String(dto.id),
    role: dto.role,
    content: dto.content,
    createdAt: new Date(dto.createdAt).getTime(),
    // We don't have the "before" resume to diff against when loading history,
    // so this just marks that the turn changed the resume at the time
    // (ResumeUpdatedCard renders it with no section list — see the F5 spec:
    // "ganha ResumeUpdatedCard sem diff").
    ...(dto.role === 'assistant' && dto.resumeVersionId !== null
      ? { card: { type: 'resumeUpdated' as const, changedSections: [] } }
      : {}),
  }
}

export function useResumeChatSession() {
  const queryClient = useQueryClient()

  const resumeSession = async (sessionId: number): Promise<void> => {
    const detail = await queryClient.fetchQuery({
      queryKey: chatSessionQueryKey(sessionId),
      queryFn: () => getChatSession(sessionId),
    })
    useChatStore.getState().loadSession(sessionId, detail.messages.map(toChatMessage))
    useResumeStore.getState().setResume(detail.activeResume)
  }

  const startNewChat = (): void => {
    useChatStore.getState().reset()
  }

  return { resumeSession, startNewChat }
}
