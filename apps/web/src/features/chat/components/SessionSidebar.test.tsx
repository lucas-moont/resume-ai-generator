import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionSidebar } from './SessionSidebar'
import { server } from '../../../test/setup'
import { renderApp } from '../../../test/render'
import { useChatStore } from '../store/chatStore'
import { useResumeStore } from '../../resume/store/resumeStore'
import { makeResume } from '../../../test/factories'

beforeEach(() => {
  useChatStore.getState().reset()
  useResumeStore.setState({ resume: null, template: 'modern', locale: 'auto' })
  useResumeStore.temporal.getState().clear()
})

describe('SessionSidebar', () => {
  it('lists sessions from the server', async () => {
    server.use(
      http.get('/api/chat/sessions', () =>
        HttpResponse.json({
          sessions: [
            { id: 1, title: 'Backend engineer role', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: 1 },
            { id: 2, title: null, updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null },
          ],
        }),
      ),
    )

    renderApp(<SessionSidebar />)

    expect(await screen.findByText('Backend engineer role')).toBeInTheDocument()
    expect(screen.getByText(/untitled chat/i)).toBeInTheDocument()
  })

  it('renders nothing when the sessions list fails to load (graceful degradation)', async () => {
    server.use(
      http.get('/api/chat/sessions', () => HttpResponse.json({ detail: 'not found' }, { status: 404 })),
    )

    const { container } = renderApp(<SessionSidebar />)

    await waitFor(() => {
      expect(container).toBeEmptyDOMElement()
    })
  })

  it('clicking a session loads its messages and active resume', async () => {
    const resume = makeResume({ fullName: 'Resumed Session Person' })
    server.use(
      http.get('/api/chat/sessions', () =>
        HttpResponse.json({
          sessions: [{ id: 5, title: 'Prior chat', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: 2 }],
        }),
      ),
      http.get('/api/chat/sessions/5', () =>
        HttpResponse.json({
          session: { id: 5, title: 'Prior chat', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: 2 },
          messages: [
            { id: 1, role: 'user', content: 'hi', intent: null, resumeVersionId: null, createdAt: '2026-07-10T00:00:00Z' },
          ],
          activeResume: resume,
        }),
      ),
    )

    const user = userEvent.setup()
    renderApp(<SessionSidebar />)

    await user.click(await screen.findByText('Prior chat'))

    await waitFor(() => {
      expect(useChatStore.getState().sessionId).toBe(5)
    })
    expect(useResumeStore.getState().resume?.fullName).toBe('Resumed Session Person')
  })

  it('"New chat" resets the active session', async () => {
    useChatStore.getState().appendUserMessage('existing message')
    useChatStore.getState().setSessionId(9)
    server.use(http.get('/api/chat/sessions', () => HttpResponse.json({ sessions: [] })))

    const user = userEvent.setup()
    renderApp(<SessionSidebar />)

    await user.click(await screen.findByRole('button', { name: /new chat/i }))

    expect(useChatStore.getState().sessionId).toBeNull()
    expect(useChatStore.getState().messages).toEqual([])
  })

  it('shows a relative timestamp for each session', async () => {
    const fiveMinutesAgo = new Date(Date.now() - 5 * 60_000).toISOString()
    server.use(
      http.get('/api/chat/sessions', () =>
        HttpResponse.json({
          sessions: [{ id: 1, title: 'Backend engineer role', updatedAt: fiveMinutesAgo, activeResumeVersionId: null }],
        }),
      ),
    )

    renderApp(<SessionSidebar />)

    expect(await screen.findByText(/5m ago/i)).toBeInTheDocument()
  })

  describe('delete', () => {
    afterEach(() => {
      vi.restoreAllMocks()
    })

    it('deletes a session after light confirmation', async () => {
      let deleteCalled = false
      server.use(
        http.get('/api/chat/sessions', () =>
          HttpResponse.json({
            sessions: [{ id: 3, title: 'Old chat', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null }],
          }),
        ),
        http.delete('/api/chat/sessions/3', () => {
          deleteCalled = true
          return new HttpResponse(null, { status: 204 })
        }),
      )
      vi.spyOn(window, 'confirm').mockReturnValue(true)

      const user = userEvent.setup()
      renderApp(<SessionSidebar />)

      await user.click(await screen.findByRole('button', { name: /delete old chat/i }))

      await waitFor(() => expect(deleteCalled).toBe(true))
    })

    it('does not delete when the user cancels the confirmation', async () => {
      let deleteCalled = false
      server.use(
        http.get('/api/chat/sessions', () =>
          HttpResponse.json({
            sessions: [{ id: 4, title: 'Keep me', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null }],
          }),
        ),
        http.delete('/api/chat/sessions/4', () => {
          deleteCalled = true
          return new HttpResponse(null, { status: 204 })
        }),
      )
      vi.spyOn(window, 'confirm').mockReturnValue(false)

      const user = userEvent.setup()
      renderApp(<SessionSidebar />)

      await user.click(await screen.findByRole('button', { name: /delete keep me/i }))

      expect(deleteCalled).toBe(false)
      expect(screen.getByText('Keep me')).toBeInTheDocument()
    })

    it('resets the active chat if the deleted session was the one currently open', async () => {
      useChatStore.getState().setSessionId(6)
      useChatStore.getState().appendUserMessage('hi')
      server.use(
        http.get('/api/chat/sessions', () =>
          HttpResponse.json({
            sessions: [{ id: 6, title: 'Current chat', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null }],
          }),
        ),
        http.delete('/api/chat/sessions/6', () => new HttpResponse(null, { status: 204 })),
      )
      vi.spyOn(window, 'confirm').mockReturnValue(true)

      const user = userEvent.setup()
      renderApp(<SessionSidebar />)

      await user.click(await screen.findByRole('button', { name: /delete current chat/i }))

      await waitFor(() => {
        expect(useChatStore.getState().sessionId).toBeNull()
      })
      expect(useChatStore.getState().messages).toEqual([])
    })
  })
})
