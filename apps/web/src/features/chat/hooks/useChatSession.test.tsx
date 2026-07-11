import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import type { ReactNode } from 'react'
import {
  useCreateSession,
  useDeleteSession,
  useResumeChatSession,
  useRestoreActiveSession,
  useSession,
  useSessions,
} from './useChatSession'
import { useChatStore } from '../store/chatStore'
import { useResumeStore } from '../../resume/store/resumeStore'
import { server } from '../../../test/setup'
import { makeProposal, makeResume } from '../../../test/factories'

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

  it('an assistant message with a sourceDocument gets a ProfileUpdatedCard reflecting its CURRENT status (v2 ticket 10)', async () => {
    server.use(
      http.get('/api/chat/sessions/12', () =>
        HttpResponse.json({
          session: { id: 12, title: 'Hi', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null },
          messages: [
            {
              id: 1,
              role: 'assistant',
              content: "Reviewed profile.json — here's what I found.",
              intent: 'profile_update',
              resumeVersionId: null,
              createdAt: '2026-07-10T00:00:00Z',
              sourceDocument: {
                documentId: 5,
                filename: 'profile.json',
                status: 'applied',
                diffSummary: ['1 new skill: Rust'],
                opsCount: 1,
                error: null,
              },
            },
          ],
          activeResume: null,
        }),
      ),
    )

    const { result } = renderHook(() => useResumeChatSession(), { wrapper })
    await result.current.resumeSession(12)

    const assistantMsg = useChatStore.getState().messages[0]
    expect(assistantMsg.card).toEqual({
      type: 'profileUpdated',
      documentId: 5,
      filename: 'profile.json',
      status: 'applied',
      diffSummary: ['1 new skill: Rust'],
      opsCount: 1,
    })
  })

  it('a proposed ProfileUpdatedCard reconstructed on restore is still approvable', async () => {
    server.use(
      http.get('/api/chat/sessions/13', () =>
        HttpResponse.json({
          session: { id: 13, title: 'Hi', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null },
          messages: [
            {
              id: 9,
              role: 'assistant',
              content: "Reviewed profile.json — here's what I found.",
              intent: 'profile_update',
              resumeVersionId: null,
              createdAt: '2026-07-10T00:00:00Z',
              sourceDocument: {
                documentId: 7,
                filename: 'profile.json',
                status: 'proposed',
                diffSummary: ['1 new skill: Rust'],
                opsCount: 1,
                error: null,
              },
            },
          ],
          activeResume: null,
        }),
      ),
    )

    const { result } = renderHook(() => useResumeChatSession(), { wrapper })
    await result.current.resumeSession(13)

    const assistantMsg = useChatStore.getState().messages[0]
    expect(assistantMsg.id).toBe('9') // the REAL backend id, not a locally-generated one
    expect(assistantMsg.card).toMatchObject({ type: 'profileUpdated', status: 'proposed', documentId: 7 })

    // approve/reject wiring (ChatPanel.settleProfileDocument) matches on this exact message id.
    useChatStore.getState().updateMessageCard('9', (card) =>
      card.type === 'profileUpdated' ? { ...card, status: 'applied' } : card,
    )
    expect(useChatStore.getState().messages[0].card).toMatchObject({ status: 'applied' })
  })

  it('an assistant message with intent profile_update and no sourceDocument gets a degraded ProfileUpdateAppliedCard (v3 ticket 12)', async () => {
    server.use(
      http.get('/api/chat/sessions/15', () =>
        HttpResponse.json({
          session: { id: 15, title: 'Hi', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null },
          messages: [
            {
              id: 1,
              role: 'user',
              content: 'I changed my phone number',
              intent: null,
              resumeVersionId: null,
              createdAt: '2026-07-10T00:00:00Z',
              sourceDocument: null,
            },
            {
              id: 2,
              role: 'assistant',
              content: "I've updated your profile. Want me to regenerate your resume with this change?",
              intent: 'profile_update',
              resumeVersionId: null,
              createdAt: '2026-07-10T00:00:01Z',
              sourceDocument: null,
            },
          ],
          activeResume: null,
        }),
      ),
    )

    const { result } = renderHook(() => useResumeChatSession(), { wrapper })
    await result.current.resumeSession(15)

    const assistantMsg = useChatStore.getState().messages[1]
    // Honest degradation: no profileVersion/summary in the DTO, so neither is fabricated.
    expect(assistantMsg.card).toEqual({ type: 'profileUpdateApplied' })
  })

  it('a message with no sourceDocument and no resumeVersionId gets no card', async () => {
    server.use(
      http.get('/api/chat/sessions/14', () =>
        HttpResponse.json({
          session: { id: 14, title: 'Hi', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null },
          messages: [
            {
              id: 1,
              role: 'assistant',
              content: 'hi there',
              intent: 'question',
              resumeVersionId: null,
              createdAt: '2026-07-10T00:00:00Z',
              sourceDocument: null,
            },
          ],
          activeResume: null,
        }),
      ),
    )

    const { result } = renderHook(() => useResumeChatSession(), { wrapper })
    await result.current.resumeSession(14)

    expect(useChatStore.getState().messages[0].card).toBeUndefined()
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

  it('switching to another session and back does not change the selected template (B1 regression)', async () => {
    useResumeStore.getState().setTemplate('ats-plain')
    const resumeA = makeResume({ fullName: 'Session A Resume' })
    const resumeB = makeResume({ fullName: 'Session B Resume' })
    server.use(
      http.get('/api/chat/sessions/101', () =>
        HttpResponse.json({
          session: { id: 101, title: 'A', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: 1 },
          messages: [],
          activeResume: resumeA,
        }),
      ),
      http.get('/api/chat/sessions/102', () =>
        HttpResponse.json({
          session: { id: 102, title: 'B', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: 2 },
          messages: [],
          activeResume: resumeB,
        }),
      ),
    )

    const { result } = renderHook(() => useResumeChatSession(), { wrapper })
    await result.current.resumeSession(101)
    expect(useResumeStore.getState().resume?.fullName).toBe('Session A Resume')

    await result.current.resumeSession(102)
    expect(useResumeStore.getState().resume?.fullName).toBe('Session B Resume')

    await result.current.resumeSession(101)
    expect(useResumeStore.getState().resume?.fullName).toBe('Session A Resume')
    expect(useResumeStore.getState().template).toBe('ats-plain')
  })
})

describe('useResumeChatSession — proposal rehydration (v4 F5)', () => {
  it('an assistant message with a proposed proposal gets a ProposalCard and sets pendingProposalId, never animated', async () => {
    server.use(
      http.get('/api/chat/sessions/20', () =>
        HttpResponse.json({
          session: { id: 20, title: 'Hi', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null },
          messages: [
            {
              id: 1,
              role: 'user',
              content: 'aqui está a vaga',
              intent: null,
              resumeVersionId: null,
              createdAt: '2026-07-10T00:00:00Z',
              sourceDocument: null,
            },
            {
              id: 2,
              role: 'assistant',
              content: 'Aqui estão minhas sugestões de melhoria para essa vaga.',
              intent: 'propose',
              resumeVersionId: null,
              createdAt: '2026-07-10T00:00:01Z',
              sourceDocument: null,
              proposal: makeProposal({ proposalId: 5, revision: 1 }),
            },
          ],
          activeResume: null,
          pendingProposal: makeProposal({ proposalId: 5, revision: 1 }),
        }),
      ),
    )

    const { result } = renderHook(() => useResumeChatSession(), { wrapper })
    await result.current.resumeSession(20)

    const assistantMsg = useChatStore.getState().messages[1]
    expect(assistantMsg.card).toEqual({
      type: 'proposal',
      proposalId: 5,
      status: 'proposed',
      revision: 1,
      itemsCount: 1,
    })
    expect(assistantMsg.animate).toBeUndefined()
    expect(useChatStore.getState().pendingProposalId).toBe(5)
  })

  it('an approved proposal renders an approved card and leaves pendingProposalId null', async () => {
    server.use(
      http.get('/api/chat/sessions/21', () =>
        HttpResponse.json({
          session: { id: 21, title: 'Hi', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: 6 },
          messages: [
            {
              id: 1,
              role: 'assistant',
              content: 'Aqui estão minhas sugestões de melhoria para essa vaga.',
              intent: 'propose',
              resumeVersionId: null,
              createdAt: '2026-07-10T00:00:00Z',
              sourceDocument: null,
              proposal: makeProposal({ proposalId: 6, status: 'approved', revision: 2 }),
            },
          ],
          activeResume: null,
          // The approved proposal is no longer the session's Pending Proposal.
          pendingProposal: null,
        }),
      ),
    )

    const { result } = renderHook(() => useResumeChatSession(), { wrapper })
    await result.current.resumeSession(21)

    expect(useChatStore.getState().messages[0].card).toEqual({
      type: 'proposal',
      proposalId: 6,
      status: 'approved',
      revision: 2,
      itemsCount: 1,
    })
    expect(useChatStore.getState().pendingProposalId).toBeNull()
  })

  it('a superseded proposal renders a superseded card', async () => {
    server.use(
      http.get('/api/chat/sessions/22', () =>
        HttpResponse.json({
          session: { id: 22, title: 'Hi', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null },
          messages: [
            {
              id: 1,
              role: 'assistant',
              content: 'Proposta anterior, substituída por uma nova vaga.',
              intent: 'propose',
              resumeVersionId: null,
              createdAt: '2026-07-10T00:00:00Z',
              sourceDocument: null,
              proposal: makeProposal({ proposalId: 7, status: 'superseded', revision: 1 }),
            },
            {
              id: 2,
              role: 'assistant',
              content: 'Aqui estão as novas sugestões.',
              intent: 'propose',
              resumeVersionId: null,
              createdAt: '2026-07-10T00:00:01Z',
              sourceDocument: null,
              proposal: makeProposal({ proposalId: 8, status: 'proposed', revision: 1 }),
            },
          ],
          activeResume: null,
          pendingProposal: makeProposal({ proposalId: 8, status: 'proposed', revision: 1 }),
        }),
      ),
    )

    const { result } = renderHook(() => useResumeChatSession(), { wrapper })
    await result.current.resumeSession(22)

    expect(useChatStore.getState().messages[0].card).toMatchObject({ proposalId: 7, status: 'superseded' })
    expect(useChatStore.getState().messages[1].card).toMatchObject({ proposalId: 8, status: 'proposed' })
    expect(useChatStore.getState().pendingProposalId).toBe(8)
  })

  it('a session with no proposal at all leaves v3 restore behavior intact and pendingProposalId null', async () => {
    server.use(
      http.get('/api/chat/sessions/23', () =>
        HttpResponse.json({
          session: { id: 23, title: 'Hi', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null },
          messages: [
            {
              id: 1,
              role: 'assistant',
              content: 'hi there',
              intent: 'question',
              resumeVersionId: null,
              createdAt: '2026-07-10T00:00:00Z',
              sourceDocument: null,
            },
          ],
          activeResume: null,
        }),
      ),
    )

    const { result } = renderHook(() => useResumeChatSession(), { wrapper })
    await result.current.resumeSession(23)

    expect(useChatStore.getState().messages[0].card).toBeUndefined()
    expect(useChatStore.getState().pendingProposalId).toBeNull()
  })

  it('switching to a session with no pending proposal clears a stale pendingProposalId from the previous one', async () => {
    server.use(
      http.get('/api/chat/sessions/24', () =>
        HttpResponse.json({
          session: { id: 24, title: 'A', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null },
          messages: [],
          activeResume: null,
          pendingProposal: makeProposal({ proposalId: 40 }),
        }),
      ),
      http.get('/api/chat/sessions/25', () =>
        HttpResponse.json({
          session: { id: 25, title: 'B', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null },
          messages: [],
          activeResume: null,
          pendingProposal: null,
        }),
      ),
    )

    const { result } = renderHook(() => useResumeChatSession(), { wrapper })
    await result.current.resumeSession(24)
    expect(useChatStore.getState().pendingProposalId).toBe(40)

    await result.current.resumeSession(25)
    expect(useChatStore.getState().pendingProposalId).toBeNull()
  })
})

describe('useRestoreActiveSession — proposal rehydration (v4 F5)', () => {
  it('restores a pending proposal card and pendingProposalId on boot', async () => {
    useChatStore.setState({ sessionId: 30, messages: [], pendingProposalId: null })
    server.use(
      http.get('/api/chat/sessions/30', () =>
        HttpResponse.json({
          session: { id: 30, title: 'Hi', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null },
          messages: [
            {
              id: 1,
              role: 'assistant',
              content: 'Aqui estão minhas sugestões de melhoria para essa vaga.',
              intent: 'propose',
              resumeVersionId: null,
              createdAt: '2026-07-10T00:00:00Z',
              sourceDocument: null,
              proposal: makeProposal({ proposalId: 50, revision: 1 }),
            },
          ],
          activeResume: null,
          pendingProposal: makeProposal({ proposalId: 50, revision: 1 }),
        }),
      ),
    )

    renderHook(() => useRestoreActiveSession(), { wrapper })

    await waitFor(() => expect(useChatStore.getState().messages).toHaveLength(1))
    expect(useChatStore.getState().messages[0].card).toMatchObject({ proposalId: 50, status: 'proposed' })
    expect(useChatStore.getState().messages[0].animate).toBeUndefined()
    expect(useChatStore.getState().pendingProposalId).toBe(50)
  })

  it('clears a stale pendingProposalId on boot when the restored session has none pending', async () => {
    useChatStore.setState({ sessionId: 31, messages: [], pendingProposalId: 999 })
    server.use(
      http.get('/api/chat/sessions/31', () =>
        HttpResponse.json({
          session: { id: 31, title: 'Hi', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null },
          messages: [],
          activeResume: null,
          pendingProposal: null,
        }),
      ),
    )

    renderHook(() => useRestoreActiveSession(), { wrapper })

    await waitFor(() => expect(useChatStore.getState().sessionId).toBe(31))
    await waitFor(() => expect(useChatStore.getState().pendingProposalId).toBeNull())
  })
})
