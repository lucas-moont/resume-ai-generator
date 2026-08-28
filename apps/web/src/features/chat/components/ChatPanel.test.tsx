import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { ChatPanel } from './ChatPanel'
import { server } from '../../../test/setup'
import { renderApp } from '../../../test/render'
import { sseResponse } from '../../../test/msw/sse'
import { makeApproveChainEvents, makeChatTurnEvents, makeProposal, makeResume } from '../../../test/factories'
import { mockAnalysisTurn } from '../../../test/msw/proposalScenarios'
import { __resetChatBackendAvailability } from '../hooks/useChatStream'
import { useChatStore } from '../store/chatStore'
import { useResumeStore } from '../../resume/store/resumeStore'

beforeEach(() => {
  localStorage.clear()
  useResumeStore.setState({ resume: null, template: 'modern', locale: 'auto' })
  useResumeStore.temporal.getState().clear()
  useChatStore.getState().reset()
  __resetChatBackendAvailability()
})

describe('ChatPanel — retry', () => {
  it('clicking Retry on an error card resends the same message', async () => {
    const resume = makeResume({ fullName: 'Retry UI Test' })
    let attempt = 0
    server.use(
      http.post('/api/chat/sessions/1/messages/stream', () => {
        attempt += 1
        if (attempt === 1) return HttpResponse.json({ detail: 'model unavailable' }, { status: 502 })
        return sseResponse(makeChatTurnEvents(resume))
      }),
    )

    const user = userEvent.setup()
    renderApp(<ChatPanel />)

    await user.type(screen.getByLabelText(/^message$/i), 'A flaky job description')
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    const retryButton = await screen.findByRole('button', { name: /retry/i })
    await user.click(retryButton)

    await waitFor(() => {
      expect(useResumeStore.getState().resume?.fullName).toBe('Retry UI Test')
    })
    expect(attempt).toBe(2)
  })
})

describe('ChatPanel — stop', () => {
  it('clicking Stop hides the progress indicator immediately', async () => {
    server.use(
      http.post('/api/chat/sessions/1/messages/stream', () =>
        sseResponse([
          { event: 'done', data: { progress: 100, messageId: 1, resumeVersionId: null }, delayMs: 300 },
        ]),
      ),
    )

    const user = userEvent.setup()
    renderApp(<ChatPanel />)

    await user.type(screen.getByLabelText(/^message$/i), 'A slow job description')
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    const stopButton = await screen.findByRole('button', { name: /^stop$/i })
    await user.click(stopButton)

    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^send$/i })).toBeInTheDocument()
  })
})

describe('ChatPanel — Improvement Proposal approve button (v4, F4)', () => {
  it('clicking "Aprovar e gerar" on the proposal card sends proposalAction: approve in the request body', async () => {
    const proposal = makeProposal({ proposalId: 11, revision: 1 })
    server.use(mockAnalysisTurn(1, proposal, { content: 'Here are my suggestions for this job.' }))

    const user = userEvent.setup()
    renderApp(<ChatPanel />)

    await user.type(screen.getByLabelText(/^message$/i), 'Senior backend engineer JD text')
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    const approveButton = await screen.findByRole('button', { name: /aprovar e gerar/i })

    let capturedBody: Record<string, unknown> | undefined
    server.use(
      http.post('/api/chat/sessions/1/messages/stream', async ({ request }) => {
        capturedBody = (await request.json()) as Record<string, unknown>
        return sseResponse(makeApproveChainEvents(11))
      }),
    )

    await user.click(approveButton)

    await waitFor(() => {
      expect(capturedBody?.proposalAction).toBe('approve')
    })
  })
})

describe('ChatPanel — language translation', () => {
  it('consumes a queued translation into a translate-instruction turn and clears it', async () => {
    let sentMessage: string | undefined
    server.use(
      http.post('/api/chat/sessions/1/messages/stream', async ({ request }) => {
        sentMessage = ((await request.json()) as { message?: string }).message
        return sseResponse(makeChatTurnEvents(makeResume({ locale: 'en' })))
      }),
    )
    renderApp(<ChatPanel />)

    act(() => {
      useChatStore.getState().requestTranslation('en')
    })

    await waitFor(() => expect(sentMessage).toMatch(/traduza.*inglês/i))
    expect(useChatStore.getState().pendingTranslation).toBeNull()
  })
})
