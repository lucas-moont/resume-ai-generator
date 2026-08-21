import { renderHook, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it } from 'vitest'
import { useAnalysisStream } from './useAnalysisStream'
import { useAnalysisStore } from '../store/analysisStore'
import { server } from '../../../test/setup'
import {
  SAMPLE_ANALYSIS_ITEMS,
  mockAnalysisErrorTurn,
  mockAnalysisMessageTurn,
  mockAnalysisPdfTurn,
  mockAnalysisQuestionTurn,
} from '../../../test/msw/analysisScenarios'

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

beforeEach(() => {
  useAnalysisStore.getState().reset()
  // Default create -> id 1 (baseline handler already does this, but be explicit for the stream mocks).
  server.use(
    http.post('/api/chat/sessions', () =>
      HttpResponse.json({ id: 1, title: null, kind: 'profile_analysis', createdAt: '2026-08-21T00:00:00Z' }, { status: 201 }),
    ),
  )
})

describe('useAnalysisStream', () => {
  it('a text turn appends the user message and an assistant message carrying the analysis card', async () => {
    server.use(mockAnalysisMessageTurn(1, SAMPLE_ANALYSIS_ITEMS, 'Resumo da análise.'))
    const { result } = renderHook(() => useAnalysisStream(), { wrapper })

    await act(async () => {
      await result.current.send('melhora meu headline, área backend')
    })

    await waitFor(() => expect(useAnalysisStore.getState().messages).toHaveLength(2))
    const [userMsg, assistantMsg] = useAnalysisStore.getState().messages
    expect(userMsg.role).toBe('user')
    expect(assistantMsg.role).toBe('assistant')
    expect(assistantMsg.content).toBe('Resumo da análise.')
    expect(assistantMsg.analysis?.items[0].section).toBe('headline')
    expect(useAnalysisStore.getState().sessionId).toBe(1)
    expect(useAnalysisStore.getState().streaming).toBeNull()
  })

  it('a clarifying-question turn appends a plain bubble with no analysis card', async () => {
    server.use(mockAnalysisQuestionTurn(1, 'Qual é o cargo-alvo?'))
    const { result } = renderHook(() => useAnalysisStream(), { wrapper })

    await act(async () => {
      await result.current.send('melhora meu headline')
    })

    await waitFor(() => expect(useAnalysisStore.getState().messages).toHaveLength(2))
    const assistantMsg = useAnalysisStore.getState().messages[1]
    expect(assistantMsg.content).toBe('Qual é o cargo-alvo?')
    expect(assistantMsg.analysis).toBeUndefined()
  })

  it('a PDF turn streams a full analysis from the pdf endpoint', async () => {
    server.use(mockAnalysisPdfTurn(1, SAMPLE_ANALYSIS_ITEMS, 'Análise do PDF.'))
    const { result } = renderHook(() => useAnalysisStream(), { wrapper })

    await act(async () => {
      await result.current.sendPdf(new File(['%PDF-1.4'], 'linkedin.pdf', { type: 'application/pdf' }))
    })

    await waitFor(() => expect(useAnalysisStore.getState().messages).toHaveLength(2))
    const [userMsg, assistantMsg] = useAnalysisStore.getState().messages
    expect(userMsg.content).toContain('linkedin.pdf')
    expect(assistantMsg.analysis?.summary).toBe('Análise do PDF.')
  })

  it('an error event surfaces a message and clears streaming (no crash)', async () => {
    server.use(mockAnalysisErrorTurn(1, 'LLM indisponível'))
    const { result } = renderHook(() => useAnalysisStream(), { wrapper })

    await act(async () => {
      await result.current.send('oi')
    })

    await waitFor(() => expect(useAnalysisStore.getState().streaming).toBeNull())
    const messages = useAnalysisStore.getState().messages
    expect(messages[messages.length - 1].content).toContain('LLM indisponível')
  })
})
