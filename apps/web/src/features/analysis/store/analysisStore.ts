import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import type { AnalysisItemDto } from '../../../lib/api/dto'

/** v5 Profile Analysis area. A deliberately separate, lightweight store from chatStore: the
 * analysis area is read-only (no active resume, no proposal state machine), so it carries only
 * a session id, its messages, and the streaming indicator. Only `sessionId` is persisted (same
 * decision as chatStore); messages rehydrate from the backend on boot. */
export type AnalysisRole = 'user' | 'assistant'

export const ACTIVE_ANALYSIS_SESSION_STORAGE_KEY = 'resume-agent:active-analysis-session'

/** The structured payload of an analysis turn (mirrors ChatMessageAnalysisDto). Absent on a
 * clarifying-question or fallback turn, which is just a text bubble. */
export interface AnalysisCard {
  items: AnalysisItemDto[]
  summary: string
}

export interface AnalysisMessage {
  id: string
  role: AnalysisRole
  content: string
  createdAt: number
  analysis?: AnalysisCard
  /** Ephemeral reveal flag for a bubble just appended by the live stream — never persisted,
   * never set by loadSession (rehydration). */
  animate?: boolean
}

export interface AnalysisStreamingState {
  status: 'streaming'
  step: string
  progress: number
  message: string
  abortController?: AbortController
}

interface AnalysisState {
  sessionId: number | null
  messages: AnalysisMessage[]
  streaming: AnalysisStreamingState | null
  appendUserMessage: (content: string) => AnalysisMessage
  appendAssistantMessage: (
    content: string,
    options?: { analysis?: AnalysisCard; animate?: boolean },
  ) => AnalysisMessage
  updateStreaming: (partial: Partial<AnalysisStreamingState>) => void
  finishStreaming: () => void
  reset: () => void
  loadSession: (sessionId: number, messages: AnalysisMessage[]) => void
  setSessionId: (sessionId: number) => void
}

function makeMessageId(): string {
  return `am_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

const DEFAULT_STREAMING: Omit<AnalysisStreamingState, 'status'> = {
  step: '',
  progress: 0,
  message: '',
}

export const useAnalysisStore = create<AnalysisState>()(
  persist(
    (set) => ({
      sessionId: null,
      messages: [],
      streaming: null,

      appendUserMessage: (content) => {
        const message: AnalysisMessage = {
          id: makeMessageId(),
          role: 'user',
          content,
          createdAt: Date.now(),
        }
        set((state) => ({ messages: [...state.messages, message] }))
        return message
      },

      appendAssistantMessage: (content, options) => {
        const message: AnalysisMessage = {
          id: makeMessageId(),
          role: 'assistant',
          content,
          createdAt: Date.now(),
          ...(options?.analysis ? { analysis: options.analysis } : {}),
          ...(options?.animate ? { animate: true } : {}),
        }
        set((state) => ({ messages: [...state.messages, message] }))
        return message
      },

      updateStreaming: (partial) => {
        set((state) => ({
          streaming: { status: 'streaming', ...DEFAULT_STREAMING, ...state.streaming, ...partial },
        }))
      },

      finishStreaming: () => {
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
      name: ACTIVE_ANALYSIS_SESSION_STORAGE_KEY,
      version: 1,
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ sessionId: state.sessionId }),
    },
  ),
)

export const getAnalysisState = () => useAnalysisStore.getState()
