import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createChatSession,
  deleteChatSession,
  getChatSession,
  listChatSessions,
} from '../../../lib/api/endpoints'
import type {
  ChatMessageDto,
  ChatMessageSourceDocumentDto,
  CreateChatSessionResponse,
} from '../../../lib/api/dto'
import { useResumeStore } from '../../resume/store/resumeStore'
import { useChatStore, type ChatMessage, type ProfileUpdatedCard } from '../store/chatStore'

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

/** v2 ticket 10: reconstructs the ProfileUpdatedCard a document-upload assistant message had
 * live, from `dto.sourceDocument` (GET /api/chat/sessions/{id} joins source_documents live, at
 * read time, for its CURRENT status/diffSummary/opsCount — never a stale copy). Takes the
 * non-null shape directly -- the `!= null` guard lives at the call site (toChatMessage below),
 * which also deliberately tolerates the field being absent entirely, not just explicit null,
 * for resilience against any older/incomplete mock payload. */
function toProfileUpdatedCard(sourceDocument: ChatMessageSourceDocumentDto): ProfileUpdatedCard {
  return {
    type: 'profileUpdated',
    documentId: sourceDocument.documentId,
    filename: sourceDocument.filename,
    status: sourceDocument.status,
    diffSummary: sourceDocument.diffSummary,
    opsCount: sourceDocument.opsCount,
    ...(sourceDocument.error !== null ? { error: sourceDocument.error } : {}),
  }
}

function toChatMessage(dto: ChatMessageDto): ChatMessage {
  return {
    id: String(dto.id),
    role: dto.role,
    content: dto.content,
    createdAt: new Date(dto.createdAt).getTime(),
    ...(dto.role === 'assistant' && dto.sourceDocument != null
      ? { card: toProfileUpdatedCard(dto.sourceDocument) }
      : // A chat-only `profile_update` turn (no upload behind it) never carries a
        // sourceDocument -- ChatMessageDto only has `intent` for it, not the profileVersion/
        // summary the live SSE event had, so the card degrades honestly to a label-only
        // rendering (v3 ticket 12; see ProfileUpdateAppliedCard's own fallback).
        dto.role === 'assistant' && dto.intent === 'profile_update'
        ? { card: { type: 'profileUpdateApplied' as const } }
        : // We don't have the "before" resume to diff against when loading history, so this just
          // marks that the turn changed the resume at the time (ResumeUpdatedCard renders it with
          // no section list — see the F5 spec: "ganha ResumeUpdatedCard sem diff").
          dto.role === 'assistant' && dto.resumeVersionId !== null
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

/** B2: on boot, if a sessionId survived a reload (chatStore persists just
 * that field — see ACTIVE_SESSION_STORAGE_KEY) but its messages didn't
 * (by design — they're ephemeral), refetch the full conversation so the
 * chat panel doesn't show a misleading empty state while the sidebar/preview
 * already reflect the restored session. A 404/error (the session was
 * deleted, or the backend isn't reachable) falls back to a clean empty
 * state — reset() also clears the persisted id, so this doesn't retry
 * forever on a dead session. */
export function useRestoreActiveSession(): void {
  const queryClient = useQueryClient()

  useEffect(() => {
    const { sessionId, messages } = useChatStore.getState()
    if (sessionId === null || messages.length > 0) return

    let cancelled = false
    queryClient
      .fetchQuery({
        queryKey: chatSessionQueryKey(sessionId),
        queryFn: () => getChatSession(sessionId),
      })
      .then((detail) => {
        if (cancelled) return
        useChatStore.getState().loadSession(sessionId, detail.messages.map(toChatMessage))
        useResumeStore.getState().setResume(detail.activeResume)
      })
      .catch(() => {
        if (cancelled) return
        useChatStore.getState().reset()
      })

    return () => {
      cancelled = true
    }
    // Boot-time only: intentionally runs once, not on every sessionId change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
}
