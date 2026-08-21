import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { AnalysisComposer } from './AnalysisComposer'
import { server } from '../../../test/setup'
import { renderApp } from '../../../test/render'
import { useAnalysisStore } from '../store/analysisStore'
import {
  SAMPLE_ANALYSIS_ITEMS,
  mockAnalysisMessageTurn,
  mockAnalysisPdfTurn,
} from '../../../test/msw/analysisScenarios'

beforeEach(() => {
  useAnalysisStore.getState().reset()
  server.use(
    http.post('/api/chat/sessions', () =>
      HttpResponse.json({ id: 1, title: null, kind: 'profile_analysis', createdAt: '2026-08-21T00:00:00Z' }, { status: 201 }),
    ),
  )
})

describe('AnalysisComposer', () => {
  it('sends a typed request and shows the resulting analysis turn', async () => {
    server.use(mockAnalysisMessageTurn(1, SAMPLE_ANALYSIS_ITEMS, 'Resumo.'))
    const user = userEvent.setup()
    renderApp(<AnalysisComposer />)

    await user.type(screen.getByRole('textbox', { name: /mensagem/i }), 'melhora meu headline')
    await user.click(screen.getByRole('button', { name: 'Enviar' }))

    await waitFor(() => expect(useAnalysisStore.getState().messages).toHaveLength(2))
    expect(useAnalysisStore.getState().messages[1].analysis?.items[0].section).toBe('headline')
  })

  it('Enter submits (Shift+Enter would not)', async () => {
    server.use(mockAnalysisMessageTurn(1, SAMPLE_ANALYSIS_ITEMS, 'Resumo.'))
    const user = userEvent.setup()
    renderApp(<AnalysisComposer />)

    await user.type(screen.getByRole('textbox', { name: /mensagem/i }), 'melhora meu headline{Enter}')

    await waitFor(() => expect(useAnalysisStore.getState().messages).toHaveLength(2))
  })

  it('does not send an empty message', async () => {
    const user = userEvent.setup()
    renderApp(<AnalysisComposer />)
    // Send button is disabled with an empty draft.
    expect(screen.getByRole('button', { name: 'Enviar' })).toBeDisabled()
    await user.keyboard('{Enter}')
    expect(useAnalysisStore.getState().messages).toHaveLength(0)
  })

  it('uploading a PDF streams a full-profile analysis', async () => {
    server.use(mockAnalysisPdfTurn(1, SAMPLE_ANALYSIS_ITEMS, 'Análise do PDF.'))
    const user = userEvent.setup()
    renderApp(<AnalysisComposer />)

    const input = screen.getByTestId('analysis-pdf-input')
    await user.upload(input, new File(['%PDF-1.4'], 'linkedin.pdf', { type: 'application/pdf' }))

    await waitFor(() => expect(useAnalysisStore.getState().messages).toHaveLength(2))
    expect(useAnalysisStore.getState().messages[0].content).toContain('linkedin.pdf')
    expect(useAnalysisStore.getState().messages[1].analysis?.summary).toBe('Análise do PDF.')
  })
})
