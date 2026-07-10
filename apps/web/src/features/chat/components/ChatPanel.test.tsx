import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { ChatPanel } from './ChatPanel'
import { server } from '../../../test/setup'
import { renderApp } from '../../../test/render'
import { sseResponse } from '../../../test/msw/sse'
import { makeChatTurnEvents, makeResume } from '../../../test/factories'
import { useChatStore } from '../store/chatStore'
import { useResumeStore } from '../../resume/store/resumeStore'

beforeEach(() => {
  localStorage.clear()
  useResumeStore.setState({ resume: null, template: 'modern', locale: 'auto' })
  useResumeStore.temporal.getState().clear()
  useChatStore.getState().reset()
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
