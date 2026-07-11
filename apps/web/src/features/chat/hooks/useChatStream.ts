import { useCallback } from 'react'
import {
  ApiError,
  chatMessageStream,
  generateStream,
  refineStream,
} from '../../../lib/api/endpoints'
import type {
  ChatDoneEventPayload,
  ChatMessageEventPayload,
  ChatProfileUpdateEventPayload,
  ChatProposalEventPayload,
  ChatResumeEventPayload,
  CreateChatSessionResponse,
  ProposalStatus,
  StreamDonePayload,
  StreamErrorPayload,
  StreamStagePayload,
} from '../../../lib/api/dto'
import { diffResumeSections } from '../../resume/diffResumeSections'
import { diffResume } from '../../resume/resumeDiff'
import { downloadResumePdf } from '../../resume/downloadResumePdf'
import { useResumeStore } from '../../resume/store/resumeStore'
import { TEMPLATE_REGISTRY } from '../../resume/templates/registry'
import { parseCommand } from '../commands'
import type { ChatCard, ProposalCard } from '../store/chatStore'
import { useChatStore } from '../store/chatStore'
import { useCreateSession } from './useChatSession'

// ADAPTER: routes every non-command message through
// POST /api/chat/sessions/{id}/messages/stream (B6) — intent routing
// (generate vs. refine vs. plain reply) happens server-side now, so this
// hook no longer branches on whether a resume is active. A session is
// created lazily on the first message of a fresh chat (title = a preview of
// that message). If B6's contract ever changes again, this is still the
// single file that needs to change.
//
// GRACEFUL DEGRADATION: if creating a session ever 404s (the chat router
// isn't mounted in this deployment — the same condition SessionSidebar
// treats as "hide the sidebar"), every send/retry for the rest of this page
// load falls back to the v0 /api/generate|refine/stream endpoints directly,
// exactly like F4 before this file existed.

export interface SendOptions {
  model?: string
  /** v4, F3: deterministic shortcut carried by the "Aprovar e gerar" button — routes the
   * turn straight into the approve branch of the Proposal Turn server-side, skipping LLM
   * classification. Ignored server-side when the session has no Pending Proposal. */
  proposalAction?: 'approve'
}

export interface UseChatStreamResult {
  send: (message: string, options?: SendOptions) => Promise<void>
  retry: (message: string, options?: SendOptions) => Promise<void>
  stop: () => void
}

const TITLE_PREVIEW_MAX_LENGTH = 60

type CreateSessionFn = (title?: string) => Promise<CreateChatSessionResponse>

let chatBackendUnavailable = false

/** Test-only escape hatch — resets the module-level fallback flag between tests. */
export function __resetChatBackendAvailability(): void {
  chatBackendUnavailable = false
}

export function useChatStream(): UseChatStreamResult {
  const createSessionMutation = useCreateSession()
  const createSession = createSessionMutation.mutateAsync

  const send = useCallback(
    async (message: string, options: SendOptions = {}) => {
      const trimmed = message.trim()
      if (!trimmed) return

      const command = parseCommand(trimmed)
      if (command) {
        useChatStore.getState().appendUserMessage(trimmed)
        await runCommand(command)
        return
      }

      useChatStore.getState().appendUserMessage(trimmed)
      await runTurn(trimmed, options, createSession)
    },
    [createSession],
  )

  const retry = useCallback(
    async (message: string, options: SendOptions = {}) => {
      await runTurn(message, options, createSession)
    },
    [createSession],
  )

  const stop = useCallback(() => {
    const { streaming } = useChatStore.getState()
    streaming?.abortController?.abort()
    // Synchronous so the UI reflects "stopped" immediately, regardless of how
    // quickly (or whether) the network layer honors the abort.
    useChatStore.getState().finishStreaming()
  }, [])

  return { send, retry, stop }
}

async function runCommand(command: NonNullable<ReturnType<typeof parseCommand>>): Promise<void> {
  if (command.kind === 'switch-template') {
    useResumeStore.getState().setTemplate(command.templateId)
    const def = TEMPLATE_REGISTRY.find((t) => t.id === command.templateId)
    useChatStore
      .getState()
      .appendAssistantMessage(`Switched to the ${def?.label ?? command.templateId} template.`)
    return
  }

  // command.kind === 'export-pdf'
  const { resume, template } = useResumeStore.getState()
  if (!resume) {
    useChatStore
      .getState()
      .appendAssistantMessage("There's no resume yet to export — generate one first.")
    return
  }
  try {
    await downloadResumePdf(resume, template)
    useChatStore.getState().appendAssistantMessage('Your PDF is downloading now.')
  } catch (e) {
    const message = e instanceof ApiError ? apiErrorText(e, 'PDF export failed') : String(e)
    useChatStore
      .getState()
      .appendAssistantMessage(message, { type: 'error', message, retryMessage: 'export pdf' })
  }
}

function apiErrorText(e: ApiError, fallback: string): string {
  return typeof e.detail === 'string' ? e.detail : fallback
}

/** The `proposal` SSE event's `status` is the broader ProposalStatus (includes
 * `discarded`, "reservado (sem UI na v4)" per spec §1.3) — a live `proposal` frame only
 * ever carries `proposed` in practice; this narrows defensively rather than trusting that. */
function toProposalCardStatus(status: ProposalStatus): ProposalCard['status'] {
  return status === 'approved' || status === 'superseded' ? status : 'proposed'
}

/** Scans every message currently in the store for a `proposal` card matching `predicate`
 * and rewrites it via `update` (v4, F3 — supersede-on-new_jd / approve-on-resume). */
function markProposalCards(
  predicate: (card: ProposalCard) => boolean,
  update: (card: ProposalCard) => ProposalCard,
): void {
  const { messages, updateMessageCard } = useChatStore.getState()
  for (const m of messages) {
    if (m.card?.type === 'proposal' && predicate(m.card)) {
      updateMessageCard(m.id, (card) => (card.type === 'proposal' ? update(card) : card))
    }
  }
}

function isAbortError(e: unknown): boolean {
  return e instanceof DOMException && e.name === 'AbortError'
}

function titlePreview(message: string): string {
  return message.length > TITLE_PREVIEW_MAX_LENGTH
    ? `${message.slice(0, TITLE_PREVIEW_MAX_LENGTH - 1)}…`
    : message
}

/** Returns the active session id, creating one (titled from this message) if this is a fresh chat. */
async function ensureSession(message: string, createSession: CreateSessionFn): Promise<number> {
  const existing = useChatStore.getState().sessionId
  if (existing !== null) return existing
  const created = await createSession(titlePreview(message))
  useChatStore.getState().setSessionId(created.id)
  return created.id
}

async function runTurn(
  message: string,
  options: SendOptions,
  createSession: CreateSessionFn,
): Promise<void> {
  const controller = new AbortController()
  useChatStore.getState().updateStreaming({
    step: 'preparing_context',
    progress: 5,
    message: 'Starting…',
    abortController: controller,
  })

  if (chatBackendUnavailable) {
    await runLegacyTurn(message, options, controller)
    return
  }

  let sessionId: number
  try {
    sessionId = await ensureSession(message, createSession)
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      chatBackendUnavailable = true
      await runLegacyTurn(message, options, controller)
      return
    }
    const text = e instanceof ApiError ? apiErrorText(e, 'Something went wrong.') : String(e)
    useChatStore
      .getState()
      .appendAssistantMessage(text, { type: 'error', message: text, retryMessage: message })
    useChatStore.getState().finishStreaming()
    return
  }

  try {
    const { locale, resume } = useResumeStore.getState()
    const events = await chatMessageStream(
      sessionId,
      // v2 ticket 11: carries the client's own in-memory resume (post inline-edit, never
      // persisted) so a chat `refine` turn starts from what the user is actually looking at
      // instead of the last version the server persisted. `resume` is `null` until one is
      // ever generated -- `|| undefined` keeps that out of the JSON body entirely rather than
      // serializing a `"resume": null` the backend would just treat as "no override" anyway.
      {
        message,
        model: options.model || undefined,
        locale: locale || undefined,
        resume: resume || undefined,
        proposalAction: options.proposalAction,
      },
      controller.signal,
    )

    // v4, F3 turn loop (spec §3.3, the only breaking contract change): a turn can emit N
    // `message` events now, each one a complete, final bubble appended IMMEDIATELY (not
    // buffered until `done` like the old single-message v3 contract). Card-bearing events
    // (resume/proposal/profile_update) don't append anything themselves — they set
    // `pendingCard`, which attaches to whichever `message` bubble comes next.
    //
    // v3 compat: some v3 turns emit their lone card-bearing event AFTER the message event
    // (see the profile_update-after-message regression test) — in that case there's no
    // "next" message left to attach to. `lastCardlessMessageId` tracks the most recent
    // bubble in THIS turn that doesn't have a card yet, so `done` can retrofit the
    // leftover pendingCard onto it instead of opening a second bubble. Only when no such
    // bubble exists (no message ever fired) does `done` fall back to a synthetic bubble —
    // this is what makes 1 message + 1 card-event, in EITHER order, always collapse into
    // exactly one bubble, matching v3's old buffered behavior byte-for-byte.
    let pendingCard: ChatCard | undefined
    let lastCardlessMessageId: string | undefined

    for await (const { event, data } of events) {
      if (controller.signal.aborted) return

      if (event === 'stage') {
        const s = data as StreamStagePayload
        useChatStore.getState().updateStreaming({
          step: s.step,
          progress: Math.max(5, Math.min(99, Math.round(s.progress ?? 0))),
          message: s.message ?? '',
        })
      } else if (event === 'resume') {
        const payload = data as ChatResumeEventPayload
        const prevResume = useResumeStore.getState().resume
        useResumeStore.getState().setResume(payload.resume)
        const changedSections = diffResumeSections(prevResume, payload.resume)
        const resumeDiff = prevResume ? diffResume(prevResume, payload.resume) : undefined
        pendingCard = { type: 'resumeUpdated', changedSections, diff: resumeDiff }

        // v4: a `resume` event while a proposal is pending means this turn just approved
        // and generated from it (spec §2 "ramo approve") — mark its card(s) approved and
        // clear the pending state so the "Aprovar e gerar" button (F4) disappears.
        const { pendingProposalId } = useChatStore.getState()
        if (pendingProposalId !== null) {
          markProposalCards(
            (card) => card.proposalId === pendingProposalId && card.status === 'proposed',
            (card) => ({ ...card, status: 'approved' }),
          )
          useChatStore.getState().setPendingProposalId(null)
        }
      } else if (event === 'proposal') {
        const payload = data as ChatProposalEventPayload
        // A different proposalId than any existing card means a fresh Analysis
        // superseded the old pending one (new_jd) — mark those old cards superseded.
        // The same id (adjust) is just a revision bump; older cards with that id are
        // left alone (F4's button-visibility rule, keyed on revision, handles that).
        markProposalCards(
          (card) => card.proposalId !== payload.proposalId && card.status === 'proposed',
          (card) => ({ ...card, status: 'superseded' }),
        )
        useChatStore.getState().setPendingProposalId(payload.proposalId)
        pendingCard = {
          type: 'proposal',
          proposalId: payload.proposalId,
          status: toProposalCardStatus(payload.status),
          revision: payload.revision,
          itemsCount: payload.items.length,
        }
      } else if (event === 'message') {
        const content = (data as ChatMessageEventPayload).content
        const card = pendingCard
        pendingCard = undefined
        const appended = useChatStore.getState().appendAssistantMessage(content, card, { animate: true })
        lastCardlessMessageId = card ? undefined : appended.id
      } else if (event === 'profile_update') {
        // The `profile_update` intent (v2, ticket 05) never regenerates the
        // active resume — the Patch Validator applies straight to the Living
        // Profile server-side. No `resume` event fires in the same turn, so
        // this and the resume branch above are mutually exclusive in practice.
        const payload = data as ChatProfileUpdateEventPayload
        pendingCard = {
          type: 'profileUpdateApplied',
          profileVersion: payload.profileVersion,
          summary: payload.summary,
        }
      } else if (event === 'done') {
        void (data as ChatDoneEventPayload)
        if (pendingCard) {
          if (lastCardlessMessageId) {
            useChatStore.getState().setMessageCard(lastCardlessMessageId, pendingCard)
          } else {
            useChatStore.getState().appendAssistantMessage('Done.', pendingCard)
          }
        }
        useChatStore.getState().finishStreaming()
        return
      } else if (event === 'error') {
        const err = data as StreamErrorPayload
        throw new Error(err.message || 'Stream failed')
      }
    }
  } catch (e) {
    if (isAbortError(e)) {
      useChatStore.getState().finishStreaming()
      return
    }
    const text = e instanceof ApiError ? apiErrorText(e, 'Something went wrong.') : String(e)
    useChatStore
      .getState()
      .appendAssistantMessage(text, { type: 'error', message: text, retryMessage: message })
    useChatStore.getState().finishStreaming()
  }
}

/** Fallback path (F4-era behavior) when the chat backend isn't available: no-resume
 * -> generate/stream, active resume -> refine/stream, with a client-invented
 * assistant reply (these endpoints don't have a "message" event).
 *
 * No `profile_update` handling here, deliberately: that intent (v2, ticket 05)
 * is classified server-side by the chat service alone — /api/generate/stream
 * and /api/refine/stream never emit it, so there's nothing to dispatch on in
 * this fallback path. */
async function runLegacyTurn(
  message: string,
  options: SendOptions,
  controller: AbortController,
): Promise<void> {
  try {
    const { resume, locale } = useResumeStore.getState()
    const events = resume
      ? await refineStream({ resume, message, model: options.model || undefined }, controller.signal)
      : await generateStream(
          { job_description: message, model: options.model || undefined, locale: locale || undefined },
          controller.signal,
        )

    for await (const { event, data } of events) {
      if (controller.signal.aborted) return

      if (event === 'stage') {
        const s = data as StreamStagePayload
        useChatStore.getState().updateStreaming({
          step: s.step,
          progress: Math.max(5, Math.min(99, Math.round(s.progress ?? 0))),
          message: s.message ?? '',
        })
      } else if (event === 'done') {
        const d = data as StreamDonePayload
        const prevResume = useResumeStore.getState().resume
        useResumeStore.getState().setResume(d.resume)
        const changedSections = diffResumeSections(prevResume, d.resume)
        const diff = prevResume ? diffResume(prevResume, d.resume) : undefined
        const text = prevResume ? "I've updated your resume." : "I've generated your resume."
        useChatStore.getState().appendAssistantMessage(text, { type: 'resumeUpdated', changedSections, diff })
        useChatStore.getState().finishStreaming()
        return
      } else if (event === 'error') {
        const err = data as StreamErrorPayload
        throw new Error(err.message || 'Stream failed')
      }
    }
  } catch (e) {
    if (isAbortError(e)) {
      useChatStore.getState().finishStreaming()
      return
    }
    const text = e instanceof ApiError ? apiErrorText(e, 'Something went wrong.') : String(e)
    useChatStore
      .getState()
      .appendAssistantMessage(text, { type: 'error', message: text, retryMessage: message })
    useChatStore.getState().finishStreaming()
  }
}
