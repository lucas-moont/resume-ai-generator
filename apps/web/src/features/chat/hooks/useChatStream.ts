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
  ChatResumeEventPayload,
  CreateChatSessionResponse,
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
      { message, model: options.model || undefined, locale: locale || undefined, resume: resume || undefined },
      controller.signal,
    )

    let resumeEvent: ChatResumeEventPayload | null = null
    let changedSections: string[] = []
    // undefined (not []) when there's no prior resume to diff against (first
    // generate) — same "nothing honest to show" case as a history reload, so
    // the card falls back to the same label-only rendering for both.
    let resumeDiff: ReturnType<typeof diffResume> | undefined
    let profileUpdateEvent: ChatProfileUpdateEventPayload | null = null
    let assistantText = ''

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
        resumeEvent = data as ChatResumeEventPayload
        const prevResume = useResumeStore.getState().resume
        useResumeStore.getState().setResume(resumeEvent.resume)
        changedSections = diffResumeSections(prevResume, resumeEvent.resume)
        resumeDiff = prevResume ? diffResume(prevResume, resumeEvent.resume) : undefined
      } else if (event === 'message') {
        assistantText = (data as ChatMessageEventPayload).content
      } else if (event === 'profile_update') {
        // The `profile_update` intent (v2, ticket 05) never regenerates the
        // active resume — the Patch Validator applies straight to the Living
        // Profile server-side. No `resume` event fires in the same turn, so
        // this and resumeEvent are mutually exclusive in practice; resumeEvent
        // still wins below if both were ever present, since only one intent
        // fires per turn.
        profileUpdateEvent = data as ChatProfileUpdateEventPayload
      } else if (event === 'done') {
        void (data as ChatDoneEventPayload)
        const card = resumeEvent
          ? { type: 'resumeUpdated' as const, changedSections, diff: resumeDiff }
          : profileUpdateEvent
            ? {
                type: 'profileUpdateApplied' as const,
                profileVersion: profileUpdateEvent.profileVersion,
                summary: profileUpdateEvent.summary,
              }
            : undefined
        useChatStore.getState().appendAssistantMessage(assistantText || 'Done.', card)
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
