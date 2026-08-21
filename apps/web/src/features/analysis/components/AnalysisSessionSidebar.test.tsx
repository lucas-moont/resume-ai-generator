import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { AnalysisSessionSidebar } from './AnalysisSessionSidebar'
import { server } from '../../../test/setup'
import { renderApp } from '../../../test/render'
import { useAnalysisStore } from '../store/analysisStore'

beforeEach(() => {
  useAnalysisStore.getState().reset()
})

describe('AnalysisSessionSidebar', () => {
  it('lists Profile Analysis sessions from the server (filtered by kind)', async () => {
    let requestedUrl = ''
    server.use(
      http.get('/api/chat/sessions', ({ request }) => {
        requestedUrl = request.url
        return HttpResponse.json({
          sessions: [
            { id: 1, title: 'Meu LinkedIn', updatedAt: '2026-08-20T00:00:00Z', activeResumeVersionId: null, kind: 'profile_analysis' },
            { id: 2, title: null, updatedAt: '2026-08-20T00:00:00Z', activeResumeVersionId: null, kind: 'profile_analysis' },
          ],
        })
      }),
    )

    renderApp(<AnalysisSessionSidebar />)

    expect(await screen.findByText('Meu LinkedIn')).toBeInTheDocument()
    expect(screen.getByText(/análise sem título/i)).toBeInTheDocument()
    expect(requestedUrl).toContain('kind=profile_analysis')
  })

  it('hides itself when the list fails to load (graceful degradation)', async () => {
    server.use(http.get('/api/chat/sessions', () => HttpResponse.json({ detail: 'x' }, { status: 404 })))
    const { container } = renderApp(<AnalysisSessionSidebar />)
    await waitFor(() => expect(container).toBeEmptyDOMElement())
  })

  it('"+ Nova análise" creates a profile_analysis session and makes it active', async () => {
    let createdKind: string | undefined
    server.use(
      http.get('/api/chat/sessions', () => HttpResponse.json({ sessions: [] })),
      http.post('/api/chat/sessions', async ({ request }) => {
        const body = (await request.json()) as { kind?: string }
        createdKind = body.kind
        return HttpResponse.json({ id: 7, title: null, kind: 'profile_analysis', createdAt: '2026-08-20T00:00:00Z' }, { status: 201 })
      }),
      http.get('/api/chat/sessions/7', () =>
        HttpResponse.json({
          session: { id: 7, title: null, updatedAt: '2026-08-20T00:00:00Z', activeResumeVersionId: null, kind: 'profile_analysis' },
          messages: [],
          activeResume: null,
        }),
      ),
    )

    const user = userEvent.setup()
    renderApp(<AnalysisSessionSidebar />)

    await user.click(await screen.findByRole('button', { name: /nova análise/i }))

    expect(createdKind).toBe('profile_analysis')
    await waitFor(() => expect(useAnalysisStore.getState().sessionId).toBe(7))
  })

  it('selecting a session rehydrates its messages and analysis card', async () => {
    server.use(
      http.get('/api/chat/sessions', () =>
        HttpResponse.json({
          sessions: [{ id: 5, title: 'Prévia', updatedAt: '2026-08-20T00:00:00Z', activeResumeVersionId: null, kind: 'profile_analysis' }],
        }),
      ),
      http.get('/api/chat/sessions/5', () =>
        HttpResponse.json({
          session: { id: 5, title: 'Prévia', updatedAt: '2026-08-20T00:00:00Z', activeResumeVersionId: null, kind: 'profile_analysis' },
          messages: [
            { id: 1, role: 'user', content: 'melhora meu headline', intent: 'analysis', resumeVersionId: null, createdAt: '2026-08-20T00:00:00Z' },
            {
              id: 2,
              role: 'assistant',
              content: 'Resumo da análise.',
              intent: 'analysis',
              resumeVersionId: null,
              createdAt: '2026-08-20T00:00:01Z',
              analysis: {
                items: [{ section: 'headline', current: 'Dev', suggestion: 'Melhor headline', rationale: 'Keywords', priority: 'alta' }],
                summary: 'Resumo da análise.',
              },
            },
          ],
          activeResume: null,
        }),
      ),
    )

    const user = userEvent.setup()
    renderApp(<AnalysisSessionSidebar />)
    await user.click(await screen.findByText('Prévia'))

    await waitFor(() => expect(useAnalysisStore.getState().sessionId).toBe(5))
    const messages = useAnalysisStore.getState().messages
    expect(messages).toHaveLength(2)
    expect(messages[1].analysis?.items[0].section).toBe('headline')
  })

  it('deletes a session after confirming', async () => {
    let deleteCalled = false
    server.use(
      http.get('/api/chat/sessions', () =>
        HttpResponse.json({
          sessions: [{ id: 3, title: 'Antiga', updatedAt: '2026-08-20T00:00:00Z', activeResumeVersionId: null, kind: 'profile_analysis' }],
        }),
      ),
      http.delete('/api/chat/sessions/3', () => {
        deleteCalled = true
        return new HttpResponse(null, { status: 204 })
      }),
    )

    const user = userEvent.setup()
    renderApp(<AnalysisSessionSidebar />)

    await user.click(await screen.findByRole('button', { name: /excluir antiga/i }))
    await user.click(screen.getByRole('button', { name: 'Excluir' }))

    await waitFor(() => expect(deleteCalled).toBe(true))
  })
})
