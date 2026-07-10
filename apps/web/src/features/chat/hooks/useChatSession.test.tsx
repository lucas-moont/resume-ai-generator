import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import type { ReactNode } from 'react'
import { useChatSessionsList, useResumeChatSession } from './useChatSession'
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

describe('useChatSessionsList', () => {
  it('resolves the sessions list (default handler: empty)', async () => {
    const { result } = renderHook(() => useChatSessionsList(), { wrapper })

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

    const { result } = renderHook(() => useChatSessionsList(), { wrapper })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(calls).toBe(1)
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
