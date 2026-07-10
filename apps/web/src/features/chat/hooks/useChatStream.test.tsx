import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { __resetChatBackendAvailability, useChatStream } from './useChatStream'
import { useChatStore } from '../store/chatStore'
import { useResumeStore } from '../../resume/store/resumeStore'
import { server } from '../../../test/setup'
import { sseResponse } from '../../../test/msw/sse'
import { makeResume, makeStageEvents } from '../../../test/factories'

beforeEach(() => {
  useChatStore.getState().reset()
  useResumeStore.setState({ resume: null, template: 'modern', locale: 'auto' })
  useResumeStore.temporal.getState().clear()
  __resetChatBackendAvailability()
})

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

function renderChatStream() {
  return renderHook(() => useChatStream(), { wrapper })
}

/** Mocks POST /api/chat/sessions to always create session id 1. */
function mockSessionCreation() {
  server.use(
    http.post('/api/chat/sessions', () =>
      HttpResponse.json({ id: 1, title: 'New chat', createdAt: '2026-07-10T00:00:00Z' }, { status: 201 }),
    ),
  )
}

describe('useChatStream — session + message routing', () => {
  it('creates a session on the first message, then streams to it', async () => {
    const resume = makeResume({ fullName: 'Ada Lovelace' })
    let capturedCreateBody: unknown
    server.use(
      http.post('/api/chat/sessions', async ({ request }) => {
        capturedCreateBody = await request.json()
        return HttpResponse.json({ id: 7, title: 'A job posting', createdAt: '2026-07-10T00:00:00Z' }, { status: 201 })
      }),
    )
    let capturedMessageBody: unknown
    server.use(
      http.post('/api/chat/sessions/7/messages/stream', async ({ request }) => {
        capturedMessageBody = await request.json()
        return sseResponse([
          { event: 'stage', data: { step: 'calling_ai', progress: 40 } },
          { event: 'resume', data: { resume, resumeVersionId: 12 } },
          { event: 'message', data: { content: 'Generated a tailored resume for this job description.' } },
          { event: 'done', data: { progress: 100, messageId: 1, resumeVersionId: 12 } },
        ])
      }),
    )

    const { result } = renderChatStream()
    await result.current.send('Senior backend engineer, distributed systems')

    await waitFor(() => {
      expect(useResumeStore.getState().resume?.fullName).toBe('Ada Lovelace')
    })

    expect(capturedCreateBody).toMatchObject({ title: 'Senior backend engineer, distributed systems' })
    expect(capturedMessageBody).toMatchObject({ message: 'Senior backend engineer, distributed systems' })
    expect(useChatStore.getState().sessionId).toBe(7)

    const messages = useChatStore.getState().messages
    expect(messages[0]).toMatchObject({ role: 'user', content: 'Senior backend engineer, distributed systems' })
    expect(messages[1]).toMatchObject({
      role: 'assistant',
      content: 'Generated a tailored resume for this job description.',
      card: { type: 'resumeUpdated' },
    })
    expect(useChatStore.getState().streaming).toBeNull()
  })

  it('reuses the existing session for a second message instead of creating another one', async () => {
    let createCalls = 0
    server.use(
      http.post('/api/chat/sessions', () => {
        createCalls += 1
        return HttpResponse.json({ id: 1, title: 'x', createdAt: '2026-07-10T00:00:00Z' }, { status: 201 })
      }),
    )
    server.use(
      http.post('/api/chat/sessions/1/messages/stream', () =>
        sseResponse([
          { event: 'message', data: { content: 'Updated your resume.' } },
          { event: 'done', data: { progress: 100, messageId: 2, resumeVersionId: null } },
        ]),
      ),
    )

    const { result } = renderChatStream()
    await result.current.send('First message')
    await result.current.send('Second message')

    expect(createCalls).toBe(1)
    expect(useChatStore.getState().sessionId).toBe(1)
  })

  it('a plain "question" reply (no resume event) still appends the assistant text, without touching resumeStore', async () => {
    mockSessionCreation()
    server.use(
      http.post('/api/chat/sessions/1/messages/stream', () =>
        sseResponse([
          { event: 'message', data: { content: 'Paste a job description to generate a tailored resume.' } },
          { event: 'done', data: { progress: 100, messageId: 3, resumeVersionId: null } },
        ]),
      ),
    )

    const { result } = renderChatStream()
    await result.current.send('hey there')

    expect(useResumeStore.getState().resume).toBeNull()
    const messages = useChatStore.getState().messages
    expect(messages[1]).toMatchObject({
      role: 'assistant',
      content: 'Paste a job description to generate a tailored resume.',
    })
    expect(messages[1].card).toBeUndefined()
  })

  it('reports the stage progress on the store while streaming', async () => {
    mockSessionCreation()
    const resume = makeResume()
    server.use(
      http.post('/api/chat/sessions/1/messages/stream', () =>
        sseResponse([
          { event: 'stage', data: { step: 'calling_ai', progress: 40, message: 'Calling the model' } },
          { event: 'resume', data: { resume, resumeVersionId: 1 }, delayMs: 150 },
          { event: 'message', data: { content: 'Done.' } },
          { event: 'done', data: { progress: 100, messageId: 4, resumeVersionId: 1 } },
        ]),
      ),
    )

    const { result } = renderChatStream()
    const sendPromise = result.current.send('Backend engineer job posting')

    await waitFor(() => {
      expect(useChatStore.getState().streaming).toMatchObject({ step: 'calling_ai', progress: 40 })
    })

    await sendPromise
    expect(useChatStore.getState().streaming).toBeNull()
  })
})

describe('useChatStream — errors and retry', () => {
  it('appends an error card with a retry message when session creation fails (non-404)', async () => {
    server.use(
      http.post('/api/chat/sessions', () => HttpResponse.json({ detail: 'db unavailable' }, { status: 500 })),
    )

    const { result } = renderChatStream()
    await result.current.send('A job description that will fail')

    const assistantMsg = useChatStore.getState().messages.find((m) => m.role === 'assistant')
    expect(assistantMsg?.card).toMatchObject({
      type: 'error',
      retryMessage: 'A job description that will fail',
    })
  })

  it('appends an error card with a retry message on stream failure', async () => {
    mockSessionCreation()
    server.use(
      http.post('/api/chat/sessions/1/messages/stream', () =>
        HttpResponse.json({ detail: 'model unavailable' }, { status: 502 }),
      ),
    )

    const { result } = renderChatStream()
    await result.current.send('A job description that will fail')

    const messages = useChatStore.getState().messages
    const assistantMsg = messages.find((m) => m.role === 'assistant')
    expect(assistantMsg?.card).toMatchObject({
      type: 'error',
      retryMessage: 'A job description that will fail',
    })
    expect(useChatStore.getState().streaming).toBeNull()
  })

  it('retry resends the same message and can succeed the second time', async () => {
    mockSessionCreation()
    const resume = makeResume({ fullName: 'Retry Success' })
    let attempt = 0
    server.use(
      http.post('/api/chat/sessions/1/messages/stream', () => {
        attempt += 1
        if (attempt === 1) return HttpResponse.json({ detail: 'model unavailable' }, { status: 502 })
        return sseResponse([
          { event: 'resume', data: { resume, resumeVersionId: 1 } },
          { event: 'message', data: { content: 'Generated a tailored resume for this job description.' } },
          { event: 'done', data: { progress: 100, messageId: 5, resumeVersionId: 1 } },
        ])
      }),
    )

    const { result } = renderChatStream()
    await result.current.send('Flaky job description')
    expect(useChatStore.getState().messages.at(-1)?.card?.type).toBe('error')

    await result.current.retry('Flaky job description')

    await waitFor(() => {
      expect(useResumeStore.getState().resume?.fullName).toBe('Retry Success')
    })
    expect(attempt).toBe(2)
  })
})

describe('useChatStream — graceful degradation (chat backend unavailable)', () => {
  it('falls back to /api/generate/stream when session creation 404s, and stays in fallback mode', async () => {
    server.use(
      http.post('/api/chat/sessions', () => HttpResponse.json({ detail: 'not found' }, { status: 404 })),
    )
    const resume = makeResume({ fullName: 'Legacy Fallback' })
    let generateCalls = 0
    server.use(
      http.post('/api/generate/stream', () => {
        generateCalls += 1
        return sseResponse(makeStageEvents(resume))
      }),
    )

    const { result } = renderChatStream()
    await result.current.send('A job description')

    await waitFor(() => {
      expect(useResumeStore.getState().resume?.fullName).toBe('Legacy Fallback')
    })
    expect(useChatStore.getState().sessionId).toBeNull() // never created — fell back before that
    expect(generateCalls).toBe(1)

    // A second message should skip trying /api/chat/sessions again entirely
    // (onUnhandledRequest: 'error' would throw if it did — no handler is
    // registered for a 2nd POST /api/chat/sessions in this test) and go
    // straight to refine/stream (a resume is now active).
    server.use(
      http.post('/api/refine/stream', () => sseResponse(makeStageEvents({ ...resume, headline: 'Updated' }))),
    )
    await result.current.send('Update the headline')

    await waitFor(() => {
      expect(useResumeStore.getState().resume?.headline).toBe('Updated')
    })
  })
})

describe('useChatStream — stop', () => {
  it('stop() aborts the in-flight request and resets streaming immediately', async () => {
    mockSessionCreation()
    // MSW's mocked ReadableStream doesn't actually tear down when the client
    // aborts (see F1 report) — a short delay keeps this test fast regardless;
    // what's under test is the store's immediate synchronous "stopped" state,
    // not real network cancellation.
    server.use(
      http.post('/api/chat/sessions/1/messages/stream', () =>
        sseResponse([{ event: 'done', data: { progress: 100, messageId: 6, resumeVersionId: null }, delayMs: 100 }]),
      ),
    )

    const { result } = renderChatStream()
    const abortSpy = vi.spyOn(AbortController.prototype, 'abort')
    const sendPromise = result.current.send('A slow job description')

    await waitFor(() => {
      expect(useChatStore.getState().streaming).not.toBeNull()
    })

    result.current.stop()

    expect(useChatStore.getState().streaming).toBeNull()
    expect(abortSpy).toHaveBeenCalled()

    abortSpy.mockRestore()
    await sendPromise
  })
})

describe('useChatStream — client-side commands (no network)', () => {
  it('switches the template locally without hitting the network', async () => {
    const { result } = renderChatStream()

    await result.current.send('use the classic template')

    expect(useResumeStore.getState().template).toBe('classic')
    const messages = useChatStore.getState().messages
    expect(messages[0]).toMatchObject({ role: 'user', content: 'use the classic template' })
    expect(messages[1]).toMatchObject({ role: 'assistant' })
    expect(messages[1].content).toMatch(/classic/i)
  })

  it('export-pdf command calls exportPdf and reports success without going through the chat stream endpoints', async () => {
    useResumeStore.getState().setResume(makeResume({ fullName: 'PDF Export Test' }))
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    const { result } = renderChatStream()
    await result.current.send('export pdf')

    const messages = useChatStore.getState().messages
    expect(messages.at(-1)?.content).toMatch(/downloading/i)
    expect(clickSpy).toHaveBeenCalled()

    clickSpy.mockRestore()
  })

  it('export-pdf command with no active resume reports there is nothing to export', async () => {
    const { result } = renderChatStream()
    await result.current.send('export pdf')

    const messages = useChatStore.getState().messages
    expect(messages.at(-1)?.content).toMatch(/generate one first/i)
  })
})
