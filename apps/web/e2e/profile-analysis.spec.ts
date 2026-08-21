import { test, expect } from '@playwright/test'
import type { Page } from '@playwright/test'
import { mockBaseline } from './support/mocks'
import {
  sseBody,
  SSE_HEADERS,
  makeAnalysisItem,
  profileAnalysisEvents,
  profileAnalysisQuestionEvents,
} from './support/sse'

/**
 * v5 Profile Analysis — end-to-end (docs/v5-profile-analysis.md §Testes). 100% mocked via
 * page.route. Covers the two input modes (conversational + PDF), the ask-when-unsure valve,
 * and rehydration on reload.
 */

const SESSION_ID = 501
const CREATED_AT = '2026-08-21T00:00:00Z'

/** Routes create (POST) + list (GET, with or without ?kind) for chat sessions. `*` (not `**`)
 * keeps this off `/sessions/{id}/...` sub-paths. Registered after mockBaseline so it wins. */
async function mockAnalysisSessions(page: Page, sessions: unknown[] = []): Promise<void> {
  await page.route('**/api/chat/sessions*', async (route) => {
    const req = route.request()
    if (req.method() === 'POST') {
      return route.fulfill({
        status: 201,
        json: { id: SESSION_ID, title: null, kind: 'profile_analysis', createdAt: CREATED_AT },
      })
    }
    return route.fulfill({ json: { sessions } })
  })
}

async function enterAnalysisArea(page: Page): Promise<void> {
  await page.goto('/')
  await page.getByRole('tab', { name: 'Análise de Perfil' }).click()
  await expect(page.getByRole('heading', { name: /análise de perfil do linkedin/i })).toBeVisible()
}

test.describe('Profile Analysis (v5)', () => {
  test('conversational: a vague request gets a clarifying question, then an answer yields the analysis card', async ({ page }) => {
    await mockBaseline(page)
    await mockAnalysisSessions(page)

    // Turn 1: no context -> clarifying question (no card).
    await page.route(`**/api/chat/sessions/${SESSION_ID}/messages/stream`, (route) =>
      route.fulfill({
        headers: SSE_HEADERS,
        body: sseBody(profileAnalysisQuestionEvents('Qual é o cargo-alvo e a senioridade?')),
      }),
    )

    await enterAnalysisArea(page)
    await page.getByRole('textbox', { name: /mensagem/i }).fill('melhora meu headline')
    await page.getByRole('button', { name: 'Enviar', exact: true }).click()

    await expect(page.getByText('Qual é o cargo-alvo e a senioridade?')).toBeVisible()
    await expect(page.getByRole('button', { name: /copiar sugestão/i })).toHaveCount(0)

    // Turn 2: with context -> analysis card.
    const summary = 'Seu headline está genérico; priorize palavras-chave de busca.'
    await page.route(`**/api/chat/sessions/${SESSION_ID}/messages/stream`, (route) =>
      route.fulfill({
        headers: SSE_HEADERS,
        body: sseBody(profileAnalysisEvents([makeAnalysisItem()], summary)),
      }),
    )

    await page.getByRole('textbox', { name: /mensagem/i }).fill('sou desenvolvedor backend pleno')
    await page.getByRole('button', { name: 'Enviar', exact: true }).click()

    await expect(page.getByText(summary)).toBeVisible()
    await expect(page.getByText('Headline', { exact: true })).toBeVisible()
    await expect(page.getByText('Alta', { exact: true })).toBeVisible()
    await expect(page.getByText(makeAnalysisItem().suggestion as string)).toBeVisible()
    await expect(page.getByRole('button', { name: /copiar sugestão/i })).toHaveCount(1)
  })

  test('PDF upload streams a full-profile analysis report', async ({ page }) => {
    await mockBaseline(page)
    await mockAnalysisSessions(page)

    const summary = 'Análise completa do seu perfil, seção a seção.'
    await page.route(`**/api/chat/sessions/${SESSION_ID}/analysis/pdf/stream`, (route) =>
      route.fulfill({
        headers: SSE_HEADERS,
        body: sseBody(
          profileAnalysisEvents(
            [makeAnalysisItem(), makeAnalysisItem({ section: 'about', current: null, priority: 'média', suggestion: 'Reescreva o Sobre com um hook.' })],
            summary,
          ),
        ),
      }),
    )

    await enterAnalysisArea(page)
    await page.locator('[data-testid="analysis-pdf-input"]').setInputFiles({
      name: 'linkedin.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.4 fake'),
    })

    await expect(page.getByText('linkedin.pdf')).toBeVisible()
    await expect(page.getByText(summary)).toBeVisible()
    await expect(page.getByText('Headline', { exact: true })).toBeVisible()
    await expect(page.getByText('Sobre', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: /copiar sugestão/i })).toHaveCount(2)
  })

  test('rehydrates the analysis card after a reload', async ({ page }) => {
    await mockBaseline(page)
    await mockAnalysisSessions(page)

    const summary = 'Resumo persistido da análise.'
    await page.route(`**/api/chat/sessions/${SESSION_ID}/messages/stream`, (route) =>
      route.fulfill({ headers: SSE_HEADERS, body: sseBody(profileAnalysisEvents([makeAnalysisItem()], summary)) }),
    )

    await enterAnalysisArea(page)
    await page.getByRole('textbox', { name: /mensagem/i }).fill('sou dev backend, melhora o headline')
    await page.getByRole('button', { name: 'Enviar', exact: true }).click()
    await expect(page.getByText(summary)).toBeVisible()

    // On reload, GET /api/chat/sessions/{id} is the rehydration source of truth.
    await page.route(`**/api/chat/sessions/${SESSION_ID}`, (route) =>
      route.fulfill({
        json: {
          session: { id: SESSION_ID, title: null, updatedAt: CREATED_AT, activeResumeVersionId: null, kind: 'profile_analysis' },
          messages: [
            { id: 1, role: 'user', content: 'sou dev backend, melhora o headline', intent: 'analysis', resumeVersionId: null, createdAt: CREATED_AT },
            {
              id: 2,
              role: 'assistant',
              content: summary,
              intent: 'analysis',
              resumeVersionId: null,
              createdAt: CREATED_AT,
              analysis: { items: [makeAnalysisItem()], summary },
            },
          ],
          activeResume: null,
        },
      }),
    )

    await page.reload()

    // Still in the analysis area (mode persisted); the card is rebuilt from meta.
    await expect(page.getByText(summary)).toBeVisible()
    await expect(page.getByText('Headline', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: /copiar sugestão/i })).toHaveCount(1)
  })
})
