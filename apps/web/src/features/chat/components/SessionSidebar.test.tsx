import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
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
    it('opens a ConfirmDialog (not window.confirm) with focus on the safe Cancel button', async () => {
      server.use(
        http.get('/api/chat/sessions', () =>
          HttpResponse.json({
            sessions: [{ id: 3, title: 'Old chat', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null }],
          }),
        ),
      )

      const user = userEvent.setup()
      renderApp(<SessionSidebar />)

      await user.click(await screen.findByRole('button', { name: /delete old chat/i }))

      expect(screen.getByRole('dialog', { name: /delete old chat/i })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus()
    })

    it('deletes a session after confirming in the dialog', async () => {
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

      const user = userEvent.setup()
      renderApp(<SessionSidebar />)

      await user.click(await screen.findByRole('button', { name: /delete old chat/i }))
      await user.click(screen.getByRole('button', { name: 'Delete' }))

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

      const user = userEvent.setup()
      renderApp(<SessionSidebar />)

      await user.click(await screen.findByRole('button', { name: /delete keep me/i }))
      await user.click(screen.getByRole('button', { name: 'Cancel' }))

      expect(deleteCalled).toBe(false)
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
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

      const user = userEvent.setup()
      renderApp(<SessionSidebar />)

      await user.click(await screen.findByRole('button', { name: /delete current chat/i }))
      await user.click(screen.getByRole('button', { name: 'Delete' }))

      await waitFor(() => {
        expect(useChatStore.getState().sessionId).toBeNull()
      })
      expect(useChatStore.getState().messages).toEqual([])
    })
  })

  describe('rename (v4.1-03)', () => {
    it('shows a pencil button per session, matching the delete button pattern', async () => {
      server.use(
        http.get('/api/chat/sessions', () =>
          HttpResponse.json({
            sessions: [{ id: 3, title: 'Old title', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null }],
          }),
        ),
      )

      renderApp(<SessionSidebar />)

      expect(await screen.findByRole('button', { name: /rename old title/i })).toBeInTheDocument()
    })

    it('clicking the pencil enters inline edit: an accessible, focused input replaces the title', async () => {
      server.use(
        http.get('/api/chat/sessions', () =>
          HttpResponse.json({
            sessions: [{ id: 3, title: 'Old title', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null }],
          }),
        ),
      )

      const user = userEvent.setup()
      renderApp(<SessionSidebar />)

      await user.click(await screen.findByRole('button', { name: /rename old title/i }))

      const input = screen.getByRole('textbox', { name: /rename old title/i })
      expect(input).toHaveFocus()
      expect(input).toHaveValue('Old title')
    })

    it('Enter confirms the rename: PATCHes the title and the list reflects it without a reload', async () => {
      let capturedBody: unknown
      // Stateful GET (rather than a fixed fixture): asserts the invalidated list actually
      // refetches from the server and picks up the renamed title, not just a client-side echo.
      let currentTitle = 'Old title'
      server.use(
        http.get('/api/chat/sessions', () =>
          HttpResponse.json({
            sessions: [{ id: 3, title: currentTitle, updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null }],
          }),
        ),
        http.patch('/api/chat/sessions/3', async ({ request }) => {
          capturedBody = await request.json()
          currentTitle = 'New title'
          return HttpResponse.json({ id: 3, title: currentTitle, updatedAt: '2026-07-10T00:05:00Z' })
        }),
      )

      const user = userEvent.setup()
      renderApp(<SessionSidebar />)

      await user.click(await screen.findByRole('button', { name: /rename old title/i }))
      const input = screen.getByRole('textbox', { name: /rename old title/i })
      await user.clear(input)
      await user.type(input, 'New title{Enter}')

      expect(capturedBody).toEqual({ title: 'New title' })
      await waitFor(() => {
        expect(screen.getByText('New title')).toBeInTheDocument()
      })
      expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    })

    it('Escape cancels without saving, and focus returns to the pencil button', async () => {
      let patchCalled = false
      server.use(
        http.get('/api/chat/sessions', () =>
          HttpResponse.json({
            sessions: [{ id: 3, title: 'Kept title', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null }],
          }),
        ),
        http.patch('/api/chat/sessions/3', () => {
          patchCalled = true
          return HttpResponse.json({ id: 3, title: 'Should not happen', updatedAt: '2026-07-10T00:05:00Z' })
        }),
      )

      const user = userEvent.setup()
      renderApp(<SessionSidebar />)

      await user.click(await screen.findByRole('button', { name: /rename kept title/i }))
      const input = screen.getByRole('textbox', { name: /rename kept title/i })
      await user.type(input, ' extra')
      await user.keyboard('{Escape}')

      expect(patchCalled).toBe(false)
      expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
      expect(screen.getByText('Kept title')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /rename kept title/i })).toHaveFocus()
    })

    it('blur confirms the rename when the value changed', async () => {
      let patchCalled = false
      let currentTitle = 'Old title'
      server.use(
        http.get('/api/chat/sessions', () =>
          HttpResponse.json({
            sessions: [{ id: 3, title: currentTitle, updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null }],
          }),
        ),
        http.patch('/api/chat/sessions/3', () => {
          patchCalled = true
          currentTitle = 'Blurred title'
          return HttpResponse.json({ id: 3, title: currentTitle, updatedAt: '2026-07-10T00:05:00Z' })
        }),
      )

      const user = userEvent.setup()
      renderApp(<SessionSidebar />)

      await user.click(await screen.findByRole('button', { name: /rename old title/i }))
      const input = screen.getByRole('textbox', { name: /rename old title/i })
      await user.clear(input)
      await user.type(input, 'Blurred title')
      await user.tab()

      expect(patchCalled).toBe(true)
      await waitFor(() => {
        expect(screen.getByText('Blurred title')).toBeInTheDocument()
      })
    })

    it('blur does not save when the value is unchanged', async () => {
      let patchCalled = false
      server.use(
        http.get('/api/chat/sessions', () =>
          HttpResponse.json({
            sessions: [{ id: 3, title: 'Unchanged title', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null }],
          }),
        ),
        http.patch('/api/chat/sessions/3', () => {
          patchCalled = true
          return HttpResponse.json({ id: 3, title: 'Unchanged title', updatedAt: '2026-07-10T00:05:00Z' })
        }),
      )

      const user = userEvent.setup()
      renderApp(<SessionSidebar />)

      await user.click(await screen.findByRole('button', { name: /rename unchanged title/i }))
      await user.tab()

      expect(patchCalled).toBe(false)
    })

    it('does not allow saving an empty title — Enter on a blank input reverts to the original', async () => {
      let patchCalled = false
      server.use(
        http.get('/api/chat/sessions', () =>
          HttpResponse.json({
            sessions: [{ id: 3, title: 'Original title', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null }],
          }),
        ),
        http.patch('/api/chat/sessions/3', () => {
          patchCalled = true
          return HttpResponse.json({ id: 3, title: '', updatedAt: '2026-07-10T00:05:00Z' })
        }),
      )

      const user = userEvent.setup()
      renderApp(<SessionSidebar />)

      await user.click(await screen.findByRole('button', { name: /rename original title/i }))
      const input = screen.getByRole('textbox', { name: /rename original title/i })
      await user.clear(input)
      await user.keyboard('{Enter}')

      expect(patchCalled).toBe(false)
      expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
      expect(screen.getByText('Original title')).toBeInTheDocument()
    })

    it('renaming the currently active session updates only the list, without reloading messages or resetting the chat', async () => {
      useChatStore.getState().setSessionId(3)
      useChatStore.getState().appendUserMessage('keep me')
      let currentTitle = 'Old title'
      server.use(
        http.get('/api/chat/sessions', () =>
          HttpResponse.json({
            sessions: [{ id: 3, title: currentTitle, updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null }],
          }),
        ),
        http.patch('/api/chat/sessions/3', () => {
          currentTitle = 'Renamed active chat'
          return HttpResponse.json({ id: 3, title: currentTitle, updatedAt: '2026-07-10T00:05:00Z' })
        }),
      )

      const user = userEvent.setup()
      renderApp(<SessionSidebar />)

      await user.click(await screen.findByRole('button', { name: /rename old title/i }))
      const input = screen.getByRole('textbox', { name: /rename old title/i })
      await user.clear(input)
      await user.type(input, 'Renamed active chat{Enter}')

      await waitFor(() => {
        expect(screen.getByText('Renamed active chat')).toBeInTheDocument()
      })
      expect(useChatStore.getState().sessionId).toBe(3)
      expect(useChatStore.getState().messages).toHaveLength(1)
      expect(useChatStore.getState().messages[0].content).toBe('keep me')
    })
  })
})
