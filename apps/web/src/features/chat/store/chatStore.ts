import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import type { SourceDocumentStatus } from '../../../lib/api/dto'
import type { ResumeFieldChange } from '../../resume/resumeDiff'

export type ChatRole = 'user' | 'assistant'

/** Only `sessionId` is persisted here — messages/streaming stay ephemeral
 * (F5 decision); B2 restores the full conversation on boot by refetching
 * from the backend, not by caching it locally. */
export const ACTIVE_SESSION_STORAGE_KEY = 'resume-agent:active-session'

export interface ResumeUpdatedCard {
  type: 'resumeUpdated'
  changedSections: string[]
  /** Structured before/after per changed section (ticket 09) — omitted when
   * there's no "before" to diff against (history reload from GET
   * /api/chat/sessions/{id}, which only carries `resumeVersionId`, not the
   * two full documents): the card then degrades honestly to the
   * label-only rendering instead of fabricating a diff. */
  diff?: ResumeFieldChange[]
}

export interface ErrorCard {
  type: 'error'
  message: string
  /** The original user message text, resent verbatim when the user hits Retry. */
  retryMessage: string
}

export interface ProfileUpdatedCard {
  type: 'profileUpdated'
  documentId: number
  filename: string
  status: SourceDocumentStatus
  diffSummary: string[]
  opsCount: number
  error?: string
}

/** Confirmation card for the `profile_update` chat intent (v2, ticket 05/09)
 * — distinct from ProfileUpdatedCard (upload-driven, proposed/needs approval):
 * a chat-driven profile update is already applied by the time the SSE event
 * lands, so there's no approve/reject step here, just profileVersion + summary.
 * Both fields are optional (v3 ticket 12): a history reload only carries the
 * message's `intent`, not the profileVersion/summary the live SSE event had —
 * the card then degrades honestly to a label-only rendering, same idea as
 * ResumeUpdatedCard's optional `diff` above. */
export interface ProfileUpdateAppliedCard {
  type: 'profileUpdateApplied'
  profileVersion?: number
  summary?: string
}

/** Card for the `proposal` SSE event (v4, F3) — mirrors ChatProposalEventPayload minus the
 * full `items` list (the prose message already describes them; spec §5: "Items completos
 * NÃO vivem no card"). `status` tracks the live state machine: a new (different) proposalId
 * supersedes older proposed cards; the matching id going through `resume` marks it approved. */
export interface ProposalCard {
  type: 'proposal'
  proposalId: number
  status: 'proposed' | 'approved' | 'superseded'
  revision: number
  itemsCount: number
  /** Furo 3A: the language detected from the posting, pre-filling the approval step's language
   * picker. Optional — a card rehydrated from a proposal persisted before this may lack it. */
  detectedLocale?: string
}

export type ChatCard =
  | ResumeUpdatedCard
  | ErrorCard
  | ProfileUpdatedCard
  | ProfileUpdateAppliedCard
  | ProposalCard

export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  createdAt: number
  card?: ChatCard
  /** Ephemeral reveal flag (v4, F3): true only for a bubble just appended live by the
   * current stream — never set by `loadSession` (rehydration) and never persisted (only
   * `sessionId` survives to localStorage; see `partialize` below). */
  animate?: boolean
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
  /** The session's single Pending Proposal id (v4, F3), or null. Set by the `proposal`
   * SSE event, cleared when `resume` approves it. Mirrors ChatSessionDetailResponse's
   * top-level `pendingProposal` on rehydration (F5), kept here as just the id since the
   * button/card logic only needs to match it against card.proposalId. */
  pendingProposalId: number | null
  appendUserMessage: (content: string) => ChatMessage
  appendAssistantMessage: (content: string, card?: ChatCard, options?: { animate?: boolean }) => ChatMessage
  /** Replaces a message's card in place (e.g. a ProfileUpdatedCard moving
   * proposed -> applied|rejected after the user acts on it). No-op if the
   * message id isn't found, OR if it doesn't have a card yet (use
   * setMessageCard for that). */
  updateMessageCard: (messageId: string, updater: (card: ChatCard) => ChatCard) => void
  /** Attaches (or replaces) a message's card unconditionally — unlike updateMessageCard,
   * works even when the message doesn't have one yet (v4, F3: the turn loop's done-time
   * retrofit of a card-bearing event that arrived after its message already appended).
   * No-op if the message id isn't found. */
  setMessageCard: (messageId: string, card: ChatCard) => void
  updateStreaming: (partial: Partial<StreamingState>) => void
  finishStreaming: () => void
  reset: () => void
  /** Hydrates from GET /api/chat/sessions/{id} (F5: SessionSidebar "resume"). */
  loadSession: (sessionId: number, messages: ChatMessage[]) => void
  /** Sets just the session id — used right after POST /api/chat/sessions
   * creates a session for the FIRST message of a fresh chat, without
   * touching the user message already appended locally. */
  setSessionId: (sessionId: number) => void
  /** Sets or clears the session's Pending Proposal id (v4, F3). */
  setPendingProposalId: (pendingProposalId: number | null) => void
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
      pendingProposalId: null,

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

      appendAssistantMessage: (content, card, options) => {
        const message: ChatMessage = {
          id: makeMessageId(),
          role: 'assistant',
          content,
          createdAt: Date.now(),
          ...(card ? { card } : {}),
          ...(options?.animate ? { animate: true } : {}),
        }
        set((state) => ({ messages: [...state.messages, message] }))
        return message
      },

      updateMessageCard: (messageId, updater) => {
        set((state) => ({
          messages: state.messages.map((m) =>
            m.id === messageId && m.card ? { ...m, card: updater(m.card) } : m,
          ),
        }))
      },

      setMessageCard: (messageId, card) => {
        set((state) => ({
          messages: state.messages.map((m) => (m.id === messageId ? { ...m, card } : m)),
        }))
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
        set({ sessionId: null, messages: [], streaming: null, pendingProposalId: null })
      },

      loadSession: (sessionId, messages) => {
        set({ sessionId, messages, streaming: null })
      },

      setSessionId: (sessionId) => {
        set({ sessionId })
      },

      setPendingProposalId: (pendingProposalId) => {
        set({ pendingProposalId })
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
