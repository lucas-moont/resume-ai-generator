import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useChatStream } from './useChatStream'
import { useChatStore } from '../store/chatStore'
import { useResumeStore } from '../../resume/store/resumeStore'
import { server } from '../../../test/setup'
import { sseResponse } from '../../../test/msw/sse'
import { makeResume, makeStageEvents } from '../../../test/factories'

beforeEach(() => {
  useChatStore.getState().reset()
  useResumeStore.setState({ resume: null, template: 'modern', locale: 'auto' })
  useResumeStore.temporal.getState().clear()
})

describe('useChatStream — routing (adapter)', () => {
  it('sends to /api/generate/stream when there is no active resume, and appends a resumeUpdated card', async () => {
    const resume = makeResume({ fullName: 'Ada Lovelace' })
    let capturedBody: unknown
    server.use(
      http.post('/api/generate/stream', async ({ request }) => {
        capturedBody = await request.json()
        return sseResponse(makeStageEvents(resume))
      }),
    )

    const { result } = renderHook(() => useChatStream())
    await result.current.send('Senior backend engineer, distributed systems')

    await waitFor(() => {
      expect(useResumeStore.getState().resume?.fullName).toBe('Ada Lovelace')
    })

    expect(capturedBody).toMatchObject({ job_description: 'Senior backend engineer, distributed systems' })
    const messages = useChatStore.getState().messages
    expect(messages[0]).toMatchObject({ role: 'user', content: 'Senior backend engineer, distributed systems' })
    expect(messages[1]).toMatchObject({ role: 'assistant', card: { type: 'resumeUpdated' } })
    expect(useChatStore.getState().streaming).toBeNull()
  })

  it('sends to /api/refine/stream when a resume is already active', async () => {
    const existing = makeResume({ fullName: 'Grace Hopper' })
    useResumeStore.getState().setResume(existing)
    const updated = { ...existing, headline: 'Staff Engineer' }
    let capturedBody: unknown
    server.use(
      http.post('/api/refine/stream', async ({ request }) => {
        capturedBody = await request.json()
        return sseResponse(makeStageEvents(updated))
      }),
    )

    const { result } = renderHook(() => useChatStream())
    await result.current.send('Update my headline to Staff Engineer')

    await waitFor(() => {
      expect(useResumeStore.getState().resume?.headline).toBe('Staff Engineer')
    })
    expect(capturedBody).toMatchObject({ resume: existing, message: 'Update my headline to Staff Engineer' })
  })

  it('reports the stage progress on the store while streaming', async () => {
    const resume = makeResume()
    server.use(
      http.post('/api/generate/stream', () =>
        sseResponse([
          { event: 'stage', data: { step: 'calling_ai', progress: 40, message: 'Calling the model' } },
          { event: 'done', data: { progress: 100, resume }, delayMs: 150 },
        ]),
      ),
    )

    const { result } = renderHook(() => useChatStream())
    const sendPromise = result.current.send('Backend engineer job posting')

    await waitFor(() => {
      expect(useChatStore.getState().streaming).toMatchObject({ step: 'calling_ai', progress: 40 })
    })

    await sendPromise
    expect(useChatStore.getState().streaming).toBeNull()
  })
})

describe('useChatStream — errors and retry', () => {
  it('appends an error card with a retry message on stream failure', async () => {
    server.use(
      http.post('/api/generate/stream', () =>
        HttpResponse.json({ detail: 'model unavailable' }, { status: 502 }),
      ),
    )

    const { result } = renderHook(() => useChatStream())
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
    const resume = makeResume({ fullName: 'Retry Success' })
    let attempt = 0
    server.use(
      http.post('/api/generate/stream', () => {
        attempt += 1
        if (attempt === 1) return HttpResponse.json({ detail: 'model unavailable' }, { status: 502 })
        return sseResponse(makeStageEvents(resume))
      }),
    )

    const { result } = renderHook(() => useChatStream())
    await result.current.send('Flaky job description')
    expect(useChatStore.getState().messages.at(-1)?.card?.type).toBe('error')

    await result.current.retry('Flaky job description')

    await waitFor(() => {
      expect(useResumeStore.getState().resume?.fullName).toBe('Retry Success')
    })
    expect(attempt).toBe(2)
  })
})

describe('useChatStream — stop', () => {
  it('stop() aborts the in-flight request and resets streaming immediately', async () => {
    // MSW's mocked ReadableStream doesn't actually tear down when the client
    // aborts (see F1 report) — a short delay keeps this test fast regardless;
    // what's under test is the store's immediate synchronous "stopped" state,
    // not real network cancellation.
    server.use(
      http.post('/api/generate/stream', () =>
        sseResponse([{ event: 'done', data: { progress: 100, resume: makeResume() }, delayMs: 100 }]),
      ),
    )

    const { result } = renderHook(() => useChatStream())
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
    const { result } = renderHook(() => useChatStream())

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

    const { result } = renderHook(() => useChatStream())
    await result.current.send('export pdf')

    const messages = useChatStore.getState().messages
    expect(messages.at(-1)?.content).toMatch(/downloading/i)
    expect(clickSpy).toHaveBeenCalled()

    clickSpy.mockRestore()
  })

  it('export-pdf command with no active resume reports there is nothing to export', async () => {
    const { result } = renderHook(() => useChatStream())
    await result.current.send('export pdf')

    const messages = useChatStore.getState().messages
    expect(messages.at(-1)?.content).toMatch(/generate one first/i)
  })
})
