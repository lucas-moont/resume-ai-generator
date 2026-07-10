import { useCallback } from 'react'
import { ApiError, generateStream, refineStream } from '../../../lib/api/endpoints'
import type { StreamDonePayload, StreamErrorPayload, StreamStagePayload } from '../../../lib/api/dto'
import { diffResumeSections } from '../../resume/diffResumeSections'
import { downloadResumePdf } from '../../resume/downloadResumePdf'
import { useResumeStore } from '../../resume/store/resumeStore'
import { TEMPLATE_REGISTRY } from '../../resume/templates/registry'
import { parseCommand } from '../commands'
import { useChatStore } from '../store/chatStore'

// ADAPTER: while apps/api's chat backend (B6) doesn't exist, this hook routes
// to the existing v0 endpoints — no active resume -> /api/generate/stream,
// active resume -> /api/refine/stream. When B6 ships, only this file changes
// (to POST /api/chat/sessions/{id}/messages/stream); chatStore, commands.ts
// and every chat component are unaffected.

export interface SendOptions {
  model?: string
}

export interface UseChatStreamResult {
  send: (message: string, options?: SendOptions) => Promise<void>
  retry: (message: string, options?: SendOptions) => Promise<void>
  stop: () => void
}

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

async function runTurn(message: string, options: SendOptions): Promise<void> {
  const { resume, locale } = useResumeStore.getState()
  const controller = new AbortController()
  useChatStore.getState().updateStreaming({
    step: 'preparing_context',
    progress: 5,
    message: 'Starting…',
    abortController: controller,
  })

  try {
    const events = resume
      ? await refineStream(
          { resume, message, model: options.model || undefined },
          controller.signal,
        )
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
        const text = prevResume ? "I've updated your resume." : "I've generated your resume."
        useChatStore.getState().appendAssistantMessage(text, { type: 'resumeUpdated', changedSections })
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
