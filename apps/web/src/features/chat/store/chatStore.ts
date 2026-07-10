import { create } from 'zustand'

export type ChatRole = 'user' | 'assistant'

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
  sessionId: string | null
  messages: ChatMessage[]
  streaming: StreamingState | null
  appendUserMessage: (content: string) => ChatMessage
  appendAssistantMessage: (content: string, card?: ChatCard) => ChatMessage
  updateStreaming: (partial: Partial<StreamingState>) => void
  finishStreaming: () => void
  reset: () => void
  /** Hydrates from GET /api/chat/sessions/{id} — wired for real in F5. */
  loadSession: (sessionId: string, messages: ChatMessage[]) => void
}

function makeMessageId(): string {
  return `msg_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

const DEFAULT_STREAMING: Omit<StreamingState, 'status'> = {
  step: '',
  progress: 0,
  message: '',
}

export const useChatStore = create<ChatState>()((set) => ({
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
}))

// Exposed for callers that need the current state outside React (e.g.
// useChatStream's SSE loop) without subscribing to re-renders.
export const getChatState = () => useChatStore.getState()
