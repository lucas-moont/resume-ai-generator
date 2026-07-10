import { useCallback } from 'react'
import { ApiError, chatMessageStream, createChatSession } from '../../../lib/api/endpoints'
import type {
  ChatDoneEventPayload,
  ChatMessageEventPayload,
  ChatResumeEventPayload,
  StreamErrorPayload,
  StreamStagePayload,
} from '../../../lib/api/dto'
import { diffResumeSections } from '../../resume/diffResumeSections'
import { downloadResumePdf } from '../../resume/downloadResumePdf'
import { useResumeStore } from '../../resume/store/resumeStore'
import { TEMPLATE_REGISTRY } from '../../resume/templates/registry'
import { parseCommand } from '../commands'
import { useChatStore } from '../store/chatStore'

// ADAPTER: routes every non-command message through
// POST /api/chat/sessions/{id}/messages/stream (B6) — intent routing
// (generate vs. refine vs. plain reply) happens server-side now, so this
// hook no longer branches on whether a resume is active. A session is
// created lazily on the first message of a fresh chat (title = a preview of
// that message). If B6's contract ever changes again, this is still the
// single file that needs to change.

export interface SendOptions {
  model?: string
}

export interface UseChatStreamResult {
  send: (message: string, options?: SendOptions) => Promise<void>
  retry: (message: string, options?: SendOptions) => Promise<void>
  stop: () => void
}

const TITLE_PREVIEW_MAX_LENGTH = 60

export function useChatStream(): UseChatStreamResult {
  const send = useCallback(async (message: string, options: SendOptions = {}) => {
    const trimmed = message.trim()
    if (!trimmed) return

    const command = parseCommand(trimmed)
    if (command) {
      useChatStore.getState().appendUserMessage(trimmed)
      await runCommand(command)
      return
    }

    useChatStore.getState().appendUserMessage(trimmed)
    await runTurn(trimmed, options)
  }, [])

  const retry = useCallback(async (message: string, options: SendOptions = {}) => {
    await runTurn(message, options)
  }, [])

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
async function ensureSession(message: string): Promise<number> {
  const existing = useChatStore.getState().sessionId
  if (existing !== null) return existing
  const created = await createChatSession({ title: titlePreview(message) })
  useChatStore.getState().setSessionId(created.id)
  return created.id
}

async function runTurn(message: string, options: SendOptions): Promise<void> {
  const controller = new AbortController()
  useChatStore.getState().updateStreaming({
    step: 'preparing_context',
    progress: 5,
    message: 'Starting…',
    abortController: controller,
  })

  try {
    const sessionId = await ensureSession(message)
    const { locale } = useResumeStore.getState()
    const events = await chatMessageStream(
      sessionId,
      { message, model: options.model || undefined, locale: locale || undefined },
      controller.signal,
    )

    let resumeEvent: ChatResumeEventPayload | null = null
    let changedSections: string[] = []
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
      } else if (event === 'message') {
        assistantText = (data as ChatMessageEventPayload).content
      } else if (event === 'done') {
        void (data as ChatDoneEventPayload)
        useChatStore
          .getState()
          .appendAssistantMessage(
            assistantText || 'Done.',
            resumeEvent ? { type: 'resumeUpdated', changedSections } : undefined,
          )
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
