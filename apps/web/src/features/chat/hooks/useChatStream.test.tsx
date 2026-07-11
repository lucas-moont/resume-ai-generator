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
import {
  makeApproveChainEvents,
  makeProfileUpdateTurnEvents,
  makeProposal,
  makeResume,
  makeStageEvents,
} from '../../../test/factories'
import {
  mockAdjustTurn,
  mockAnalysisTurn,
  mockApproveChain,
  mockNewJdTurn,
  mockQuestionTurn,
} from '../../../test/msw/proposalScenarios'

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

describe('useChatStream — resume diff (ticket 09)', () => {
  it('attaches a structured before/after diff to the resumeUpdated card when a prior resume existed', async () => {
    mockSessionCreation()
    const prev = makeResume({ fullName: 'Ada Lovelace', headline: 'Engineer' })
    useResumeStore.getState().setResume(prev)
    const next = { ...prev, headline: 'Senior Engineer' }
    server.use(
      http.post('/api/chat/sessions/1/messages/stream', () =>
        sseResponse([
          { event: 'resume', data: { resume: next, resumeVersionId: 2 } },
          { event: 'message', data: { content: 'Updated your resume.' } },
          { event: 'done', data: { progress: 100, messageId: 1, resumeVersionId: 2 } },
        ]),
      ),
    )

    const { result } = renderChatStream()
    await result.current.send('Make it senior')

    const assistantMsg = useChatStore.getState().messages.find((m) => m.role === 'assistant')
    expect(assistantMsg?.card).toMatchObject({
      type: 'resumeUpdated',
      diff: [{ key: 'headline', label: 'headline', before: 'Engineer', after: 'Senior Engineer' }],
    })
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

describe('useChatStream — template is a sticky global preference (B1 regression)', () => {
  it('a resume event during a refine does not change the selected template', async () => {
    mockSessionCreation()
    useResumeStore.getState().setTemplate('ats-plain')
    const resume = makeResume({ fullName: 'Refined Person' })
    server.use(
      http.post('/api/chat/sessions/1/messages/stream', () =>
        sseResponse([
          { event: 'resume', data: { resume, resumeVersionId: 1 } },
          { event: 'message', data: { content: 'Updated your resume.' } },
          { event: 'done', data: { progress: 100, messageId: 1, resumeVersionId: 1 } },
        ]),
      ),
    )

    const { result } = renderChatStream()
    await result.current.send('Make it punchier')

    await waitFor(() => {
      expect(useResumeStore.getState().resume?.fullName).toBe('Refined Person')
    })
    expect(useResumeStore.getState().template).toBe('ats-plain')
  })
})

describe('useChatStream — profile_update (Living Profile via chat, v2 ticket 09)', () => {
  it('a profile_update event mid-stream (between stage and message) shows a profile card and leaves the active resume untouched', async () => {
    mockSessionCreation()
    const activeResume = makeResume({ fullName: 'Untouched Person', headline: 'Staff Engineer' })
    useResumeStore.getState().setResume(activeResume)
    server.use(
      http.post('/api/chat/sessions/1/messages/stream', () =>
        sseResponse(makeProfileUpdateTurnEvents({ profileVersion: 3, summary: 'Updated phone number.' })),
      ),
    )

    const { result } = renderChatStream()
    await result.current.send('I changed my phone number')

    expect(useResumeStore.getState().resume).toEqual(activeResume)

    const assistantMsg = useChatStore.getState().messages.find((m) => m.role === 'assistant')
    expect(assistantMsg?.card).toEqual({
      type: 'profileUpdateApplied',
      profileVersion: 3,
      summary: 'Updated phone number.',
    })
    expect(assistantMsg?.content).toMatch(/regenerate/i)
    expect(useChatStore.getState().streaming).toBeNull()
  })

  it('a profile_update event positioned after the message event (before done) is still picked up, with no resume event ever touching the resumeStore', async () => {
    mockSessionCreation()
    server.use(
      http.post('/api/chat/sessions/1/messages/stream', () =>
        sseResponse([
          { event: 'stage', data: { step: 'calling_ai', progress: 40 } },
          { event: 'message', data: { content: 'Updated your profile.' } },
          { event: 'profile_update', data: { profileVersion: 5, summary: 'Added a certification.' } },
          { event: 'done', data: { progress: 100, messageId: 9, resumeVersionId: null } },
        ]),
      ),
    )

    const { result } = renderChatStream()
    await result.current.send('add my AWS certification')

    const assistantMsg = useChatStore.getState().messages.find((m) => m.role === 'assistant')
    expect(assistantMsg?.card).toEqual({
      type: 'profileUpdateApplied',
      profileVersion: 5,
      summary: 'Added a certification.',
    })
    expect(useResumeStore.getState().resume).toBeNull()
    expect(useChatStore.getState().streaming).toBeNull()
  })
})

describe('useChatStream — sends the client-supplied resume for refine (v2 ticket 11)', () => {
  it('carries resumeStore.getState().resume in the payload when a resume is active', async () => {
    mockSessionCreation()
    const editedResume = makeResume({ fullName: 'Inline-Edited Person', summary: 'Edited but not yet persisted.' })
    useResumeStore.getState().setResume(editedResume)
    let capturedBody: Record<string, unknown> | undefined
    server.use(
      http.post('/api/chat/sessions/1/messages/stream', async ({ request }) => {
        capturedBody = (await request.json()) as Record<string, unknown>
        return sseResponse([
          { event: 'resume', data: { resume: editedResume, resumeVersionId: 2 } },
          { event: 'message', data: { content: 'Updated your resume.' } },
          { event: 'done', data: { progress: 100, messageId: 1, resumeVersionId: 2 } },
        ])
      }),
    )

    const { result } = renderChatStream()
    await result.current.send('Make the summary punchier.')

    expect(capturedBody?.resume).toEqual(editedResume)
  })

  it('omits the resume field entirely when there is no active resume', async () => {
    mockSessionCreation()
    let capturedBody: Record<string, unknown> | undefined
    server.use(
      http.post('/api/chat/sessions/1/messages/stream', async ({ request }) => {
        capturedBody = (await request.json()) as Record<string, unknown>
        return sseResponse([
          { event: 'message', data: { content: 'Paste a job description to generate a tailored resume.' } },
          { event: 'done', data: { progress: 100, messageId: 1, resumeVersionId: null } },
        ])
      }),
    )

    const { result } = renderChatStream()
    await result.current.send('hey there')

    expect(capturedBody).not.toHaveProperty('resume')
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

describe('useChatStream — Improvement Proposal turns (v4, F3)', () => {
  it('an Analysis turn appends one bubble carrying the proposal card, animated, and sets pendingProposalId', async () => {
    mockSessionCreation()
    const proposal = makeProposal({ proposalId: 11, revision: 1 })
    server.use(mockAnalysisTurn(1, proposal, { content: 'Here are my suggestions for this job.' }))

    const { result } = renderChatStream()
    await result.current.send('Senior backend engineer JD text')

    const assistantMsg = useChatStore.getState().messages.find((m) => m.role === 'assistant')
    expect(assistantMsg).toMatchObject({
      content: 'Here are my suggestions for this job.',
      animate: true,
      card: { type: 'proposal', proposalId: 11, status: 'proposed', revision: 1, itemsCount: proposal.items.length },
    })
    expect(useChatStore.getState().pendingProposalId).toBe(11)
    expect(useChatStore.getState().streaming).toBeNull()
  })

  it('an adjust turn appends a new bubble with the revised card and leaves the original card untouched', async () => {
    mockSessionCreation()
    const original = makeProposal({ proposalId: 11, revision: 1 })
    server.use(mockAnalysisTurn(1, original))
    const { result } = renderChatStream()
    await result.current.send('Senior backend engineer JD text')

    const revised = makeProposal({ proposalId: 11, revision: 2 })
    server.use(mockAdjustTurn(1, revised, { content: 'Ajustei a proposta conforme pedido.' }))
    await result.current.send('Please tone down the headline')

    const assistantMessages = useChatStore.getState().messages.filter((m) => m.role === 'assistant')
    expect(assistantMessages).toHaveLength(2)
    expect(assistantMessages[0].card).toMatchObject({ proposalId: 11, revision: 1, status: 'proposed' })
    expect(assistantMessages[1]).toMatchObject({
      content: 'Ajustei a proposta conforme pedido.',
      card: { type: 'proposal', proposalId: 11, status: 'proposed', revision: 2 },
    })
    expect(useChatStore.getState().pendingProposalId).toBe(11)
  })

  it('a new_jd turn supersedes the old proposal card and appends a new one with a different proposalId', async () => {
    mockSessionCreation()
    const original = makeProposal({ proposalId: 11, revision: 1 })
    server.use(mockAnalysisTurn(1, original))
    const { result } = renderChatStream()
    await result.current.send('Senior backend engineer JD text')

    const fresh = makeProposal({ proposalId: 12, revision: 1 })
    server.use(mockNewJdTurn(1, fresh, { content: 'Notei uma nova vaga colada.' }))
    await result.current.send('Actually here is a different job posting')

    const assistantMessages = useChatStore.getState().messages.filter((m) => m.role === 'assistant')
    expect(assistantMessages).toHaveLength(2)
    expect(assistantMessages[0].card).toMatchObject({ proposalId: 11, status: 'superseded' })
    expect(assistantMessages[1]).toMatchObject({
      content: 'Notei uma nova vaga colada.',
      card: { type: 'proposal', proposalId: 12, status: 'proposed', revision: 1 },
    })
    expect(useChatStore.getState().pendingProposalId).toBe(12)
  })

  it('a question turn appends a plain reply with no card and leaves the pending proposal untouched', async () => {
    mockSessionCreation()
    const original = makeProposal({ proposalId: 11, revision: 1 })
    server.use(mockAnalysisTurn(1, original))
    const { result } = renderChatStream()
    await result.current.send('Senior backend engineer JD text')

    server.use(mockQuestionTurn(1, 11, { content: 'Essa sugestão já leva em conta sua experiência.' }))
    await result.current.send('Why did you suggest that?')

    const assistantMessages = useChatStore.getState().messages.filter((m) => m.role === 'assistant')
    expect(assistantMessages).toHaveLength(2)
    expect(assistantMessages[1]).toMatchObject({ content: 'Essa sugestão já leva em conta sua experiência.' })
    expect(assistantMessages[1].card).toBeUndefined()
    expect(useChatStore.getState().pendingProposalId).toBe(11)
    expect(assistantMessages[0].card).toMatchObject({ proposalId: 11, status: 'proposed' })
  })

  it('an approve chain appends the confirmation bubble then the final bubble with the resumeUpdated card, in order, and marks the proposal card approved', async () => {
    mockSessionCreation()
    const proposal = makeProposal({ proposalId: 11, revision: 1 })
    server.use(mockAnalysisTurn(1, proposal))
    const { result } = renderChatStream()
    await result.current.send('Senior backend engineer JD text')

    const resume = makeResume({ fullName: 'Approved Person' })
    server.use(
      mockApproveChain(1, 11, {
        resume,
        resumeVersionId: 9,
        confirmContent: 'Vou gerar o currículo com essas melhorias…',
        finalContent: 'Currículo atualizado com as melhorias aprovadas!',
      }),
    )
    await result.current.send('Aprovar e gerar', { proposalAction: 'approve' })

    const assistantMessages = useChatStore.getState().messages.filter((m) => m.role === 'assistant')
    expect(assistantMessages).toHaveLength(3)
    expect(assistantMessages[1].content).toBe('Vou gerar o currículo com essas melhorias…')
    expect(assistantMessages[1].card).toBeUndefined()
    expect(assistantMessages[2]).toMatchObject({
      content: 'Currículo atualizado com as melhorias aprovadas!',
      card: { type: 'resumeUpdated' },
    })
    expect(assistantMessages[0].card).toMatchObject({ proposalId: 11, status: 'approved' })
    expect(useChatStore.getState().pendingProposalId).toBeNull()
    expect(useResumeStore.getState().resume?.fullName).toBe('Approved Person')
  })

  it('threads proposalAction: approve in the request body', async () => {
    mockSessionCreation()
    const proposal = makeProposal({ proposalId: 11, revision: 1 })
    server.use(mockAnalysisTurn(1, proposal))
    const { result } = renderChatStream()
    await result.current.send('Senior backend engineer JD text')

    let capturedBody: Record<string, unknown> | undefined
    server.use(
      http.post('/api/chat/sessions/1/messages/stream', async ({ request }) => {
        capturedBody = (await request.json()) as Record<string, unknown>
        return sseResponse(makeApproveChainEvents(11))
      }),
    )
    await result.current.send('Aprovar e gerar', { proposalAction: 'approve' })

    expect(capturedBody?.proposalAction).toBe('approve')
  })
})
