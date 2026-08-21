import { http } from 'msw'
import type { AnalysisItemDto } from '../../lib/api/dto'
import { sseResponse, type MockSseEvent } from './sse'

/** v5 Profile Analysis SSE scenarios, mirroring analysis_service.py's event sequences (b3):
 * an analysis turn emits stage -> analysis (card) -> message (summary) -> done; a
 * clarifying-question / fallback turn emits stage -> message (reply) -> done (no card). */

export function analysisTurnEvents(items: AnalysisItemDto[], summary: string): MockSseEvent[] {
  return [
    { event: 'stage', data: { step: 'analyzing_profile', progress: 40, message: 'Analyzing' } },
    { event: 'analysis', data: { items, summary } },
    { event: 'message', data: { content: summary } },
    { event: 'done', data: { progress: 100, messageId: 2, resumeVersionId: null } },
  ]
}

export function questionTurnEvents(reply: string): MockSseEvent[] {
  return [
    { event: 'stage', data: { step: 'analyzing_profile', progress: 40, message: 'Analyzing' } },
    { event: 'message', data: { content: reply } },
    { event: 'done', data: { progress: 100, messageId: 2, resumeVersionId: null } },
  ]
}

export function mockAnalysisMessageTurn(sessionId: number, items: AnalysisItemDto[], summary: string) {
  return http.post(`/api/chat/sessions/${sessionId}/messages/stream`, () =>
    sseResponse(analysisTurnEvents(items, summary)),
  )
}

export function mockAnalysisQuestionTurn(sessionId: number, reply: string) {
  return http.post(`/api/chat/sessions/${sessionId}/messages/stream`, () =>
    sseResponse(questionTurnEvents(reply)),
  )
}

export function mockAnalysisPdfTurn(sessionId: number, items: AnalysisItemDto[], summary: string) {
  return http.post(`/api/chat/sessions/${sessionId}/analysis/pdf/stream`, () =>
    sseResponse(analysisTurnEvents(items, summary)),
  )
}

export function mockAnalysisErrorTurn(sessionId: number, message: string) {
  return http.post(`/api/chat/sessions/${sessionId}/messages/stream`, () =>
    sseResponse([
      { event: 'stage', data: { step: 'analyzing_profile', progress: 40 } },
      { event: 'error', data: { message } },
    ]),
  )
}

export const SAMPLE_ANALYSIS_ITEMS: AnalysisItemDto[] = [
  {
    section: 'headline',
    current: 'Dev',
    suggestion: 'Desenvolvedor Backend | Python & APIs | Alta disponibilidade',
    rationale: 'Front-load os termos que recruiters buscam.',
    priority: 'alta',
  },
]
