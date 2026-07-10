import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getChatSession, listChatSessions } from '../../../lib/api/endpoints'
import type { ChatMessageDto } from '../../../lib/api/dto'
import { useResumeStore } from '../../resume/store/resumeStore'
import { useChatStore, type ChatMessage } from '../store/chatStore'

export const CHAT_SESSIONS_QUERY_KEY = ['chat-sessions']

/**
 * Lists chat sessions for SessionSidebar. `retry: false` is deliberate: this
 * powers graceful degradation — if the chat backend/router isn't available
 * (e.g. 404) or the request otherwise fails, the sidebar should hide itself
 * immediately rather than retry and flash a broken loading state.
 */
export function useChatSessionsList() {
  return useQuery({
    queryKey: CHAT_SESSIONS_QUERY_KEY,
    queryFn: listChatSessions,
    retry: false,
  })
}

function toChatMessage(dto: ChatMessageDto): ChatMessage {
  return {
    id: String(dto.id),
    role: dto.role,
    content: dto.content,
    createdAt: new Date(dto.createdAt).getTime(),
  }
}

export function useResumeChatSession() {
  const queryClient = useQueryClient()

  const resumeSession = async (sessionId: number): Promise<void> => {
    const detail = await getChatSession(sessionId)
    useChatStore.getState().loadSession(sessionId, detail.messages.map(toChatMessage))
    useResumeStore.getState().setResume(detail.activeResume)
    // The list shows title/updatedAt — keep it fresh for next time it renders.
    await queryClient.invalidateQueries({ queryKey: CHAT_SESSIONS_QUERY_KEY })
  }

  const startNewChat = (): void => {
    useChatStore.getState().reset()
  }

  return { resumeSession, startNewChat }
}
