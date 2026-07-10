import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

export type ChatRole = 'user' | 'assistant'

/** Only `sessionId` is persisted here — messages/streaming stay ephemeral
 * (F5 decision); B2 restores the full conversation on boot by refetching
 * from the backend, not by caching it locally. */
export const ACTIVE_SESSION_STORAGE_KEY = 'resume-agent:active-session'

export interface ResumeUpdatedCard {
  type: 'resumeUpdated'
  changedSections: string[]
}

export interface ErrorCard {
  type: 'error'
  message: string
  /** The original user message text, resent verbatim when the user hits Retry. */
  retryMessage: string
}

export type ChatCard = ResumeUpdatedCard | ErrorCard

export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  createdAt: number
  card?: ChatCard
}

export interface StreamingState {
  status: 'streaming'
  step: string
  progress: number
  message: string
  abortController?: AbortController
}

interface ChatState {
  sessionId: number | null
  messages: ChatMessage[]
  streaming: StreamingState | null
  appendUserMessage: (content: string) => ChatMessage
  appendAssistantMessage: (content: string, card?: ChatCard) => ChatMessage
  updateStreaming: (partial: Partial<StreamingState>) => void
  finishStreaming: () => void
  reset: () => void
  /** Hydrates from GET /api/chat/sessions/{id} (F5: SessionSidebar "resume"). */
  loadSession: (sessionId: number, messages: ChatMessage[]) => void
  /** Sets just the session id — used right after POST /api/chat/sessions
   * creates a session for the FIRST message of a fresh chat, without
   * touching the user message already appended locally. */
  setSessionId: (sessionId: number) => void
}

function makeMessageId(): string {
  return `msg_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

const DEFAULT_STREAMING: Omit<StreamingState, 'status'> = {
  step: '',
  progress: 0,
  message: '',
}

export const useChatStore = create<ChatState>()(
  persist(
    (set) => ({
      sessionId: null,
      messages: [],
      streaming: null,

      appendUserMessage: (content) => {
        const message: ChatMessage = {
          id: makeMessageId(),
          role: 'user',
          content,
          createdAt: Date.now(),
        }
        set((state) => ({ messages: [...state.messages, message] }))
        return message
      },

      appendAssistantMessage: (content, card) => {
        const message: ChatMessage = {
          id: makeMessageId(),
          role: 'assistant',
          content,
          createdAt: Date.now(),
          ...(card ? { card } : {}),
        }
        set((state) => ({ messages: [...state.messages, message] }))
        return message
      },

      updateStreaming: (partial) => {
        set((state) => ({
          streaming: {
            status: 'streaming',
            ...DEFAULT_STREAMING,
            ...state.streaming,
            ...partial,
          },
        }))
      },

      finishStreaming: () => {
        // Abort in-flight requests aren't cancelled here — callers that own the
        // AbortController (useChatStream) are responsible for calling .abort()
        // before finishing if that's the reason the turn is ending.
        set({ streaming: null })
      },

      reset: () => {
        set({ sessionId: null, messages: [], streaming: null })
      },

      loadSession: (sessionId, messages) => {
        set({ sessionId, messages, streaming: null })
      },

      setSessionId: (sessionId) => {
        set({ sessionId })
      },
    }),
    {
      name: ACTIVE_SESSION_STORAGE_KEY,
      version: 1,
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ sessionId: state.sessionId }),
    },
  ),
)

// Exposed for callers that need the current state outside React (e.g.
// useChatStream's SSE loop) without subscribing to re-renders.
export const getChatState = () => useChatStore.getState()
