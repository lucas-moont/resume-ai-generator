import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import type { ReactNode } from 'react'
import {
  useCreateSession,
  useDeleteSession,
  useResumeChatSession,
  useSession,
  useSessions,
} from './useChatSession'
import { useChatStore } from '../store/chatStore'
import { useResumeStore } from '../../resume/store/resumeStore'
import { server } from '../../../test/setup'
import { makeResume } from '../../../test/factories'

beforeEach(() => {
  useChatStore.getState().reset()
  useResumeStore.setState({ resume: null, template: 'modern', locale: 'auto' })
  useResumeStore.temporal.getState().clear()
})

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

describe('useSessions', () => {
  it('resolves the sessions list (default handler: empty)', async () => {
    const { result } = renderHook(() => useSessions(), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual({ sessions: [] })
  })

  it('does not retry on failure — the query settles to an error after exactly one request', async () => {
    let calls = 0
    server.use(
      http.get('/api/chat/sessions', () => {
        calls += 1
        return HttpResponse.json({ detail: 'not found' }, { status: 404 })
      }),
    )

    const { result } = renderHook(() => useSessions(), { wrapper })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(calls).toBe(1)
  })
})

describe('useSession', () => {
  it('is disabled (does not fetch) when sessionId is null', () => {
    const { result } = renderHook(() => useSession(null), { wrapper })
    expect(result.current.fetchStatus).toBe('idle')
  })

  it('fetches the session detail when given an id', async () => {
    server.use(
      http.get('/api/chat/sessions/3', () =>
        HttpResponse.json({
          session: { id: 3, title: 'Hi', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null },
          messages: [],
          activeResume: null,
        }),
      ),
    )

    const { result } = renderHook(() => useSession(3), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.session.id).toBe(3)
  })
})

describe('useCreateSession', () => {
  it('creates a session and invalidates the sessions list', async () => {
    server.use(
      http.post('/api/chat/sessions', () =>
        HttpResponse.json({ id: 9, title: 'New one', createdAt: '2026-07-10T00:00:00Z' }, { status: 201 }),
      ),
    )

    const { result } = renderHook(() => useCreateSession(), { wrapper })
    const created = await result.current.mutateAsync('New one')

    expect(created).toEqual({ id: 9, title: 'New one', createdAt: '2026-07-10T00:00:00Z' })
  })
})

describe('useDeleteSession', () => {
  it('deletes a session', async () => {
    server.use(http.delete('/api/chat/sessions/9', () => new HttpResponse(null, { status: 204 })))

    const { result } = renderHook(() => useDeleteSession(), { wrapper })
    await expect(result.current.mutateAsync(9)).resolves.toBeUndefined()
  })
})

describe('useResumeChatSession', () => {
  it('resumeSession loads the session messages into chatStore and the active resume into resumeStore', async () => {
    const resume = makeResume({ fullName: 'Loaded From Session' })
    server.use(
      http.get('/api/chat/sessions/7', () =>
        HttpResponse.json({
          session: { id: 7, title: 'Hi', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: 3 },
          messages: [
            { id: 1, role: 'user', content: 'hello', intent: null, resumeVersionId: null, createdAt: '2026-07-10T00:00:00Z' },
            { id: 2, role: 'assistant', content: 'hi there', intent: 'question', resumeVersionId: null, createdAt: '2026-07-10T00:00:01Z' },
          ],
          activeResume: resume,
        }),
      ),
    )

    const { result } = renderHook(() => useResumeChatSession(), { wrapper })
    await result.current.resumeSession(7)

    expect(useChatStore.getState().sessionId).toBe(7)
    expect(useChatStore.getState().messages).toHaveLength(2)
    expect(useChatStore.getState().messages[0]).toMatchObject({ role: 'user', content: 'hello' })
    expect(useResumeStore.getState().resume?.fullName).toBe('Loaded From Session')
  })

  it('an assistant message with a resumeVersionId gets a ResumeUpdatedCard with no section diff', async () => {
    const resume = makeResume()
    server.use(
      http.get('/api/chat/sessions/11', () =>
        HttpResponse.json({
          session: { id: 11, title: 'Hi', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: 4 },
          messages: [
            { id: 1, role: 'user', content: 'a job description', intent: null, resumeVersionId: null, createdAt: '2026-07-10T00:00:00Z' },
            {
              id: 2,
              role: 'assistant',
              content: 'Generated a tailored resume for this job description.',
              intent: 'generate',
              resumeVersionId: 4,
              createdAt: '2026-07-10T00:00:01Z',
            },
          ],
          activeResume: resume,
        }),
      ),
    )

    const { result } = renderHook(() => useResumeChatSession(), { wrapper })
    await result.current.resumeSession(11)

    const assistantMsg = useChatStore.getState().messages[1]
    expect(assistantMsg.card).toEqual({ type: 'resumeUpdated', changedSections: [] })
  })

  it('resumeSession clears the resume when the session has none active', async () => {
    useResumeStore.getState().setResume(makeResume({ fullName: 'Stale Resume From Another Session' }))
    server.use(
      http.get('/api/chat/sessions/8', () =>
        HttpResponse.json({
          session: { id: 8, title: null, updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null },
          messages: [],
          activeResume: null,
        }),
      ),
    )

    const { result } = renderHook(() => useResumeChatSession(), { wrapper })
    await result.current.resumeSession(8)

    expect(useResumeStore.getState().resume).toBeNull()
  })

  it('startNewChat resets chatStore', () => {
    useChatStore.getState().appendUserMessage('something')
    useChatStore.getState().setSessionId(1)

    const { result } = renderHook(() => useResumeChatSession(), { wrapper })
    result.current.startNewChat()

    expect(useChatStore.getState().sessionId).toBeNull()
    expect(useChatStore.getState().messages).toEqual([])
  })
})
