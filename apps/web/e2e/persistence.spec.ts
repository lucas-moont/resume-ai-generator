import { test, expect } from '@playwright/test'
import { mockBaseline } from './support/mocks'
import { sseBody, SSE_HEADERS } from './support/sse'
import { makeResume } from './support/fixtures'

test.describe('Reload persistence', () => {
  test('resume, template, and theme survive a reload; the active session auto-restores the conversation', async ({
    page,
  }) => {
    await mockBaseline(page)
    const resume = makeResume({ fullName: 'Ada Lovelace' })
    const createdAt = new Date().toISOString()

    await page.route('**/api/chat/sessions', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      await route.fulfill({ status: 201, json: { id: 3, title: 'Persisted chat', createdAt } })
    })
    await page.route('**/api/chat/sessions/3/messages/stream', (route) =>
      route.fulfill({
        headers: SSE_HEADERS,
        body: sseBody([
          { event: 'resume', data: { resume, resumeVersionId: 3 } },
          { event: 'message', data: { content: 'Generated a tailored resume for this job description.' } },
          { event: 'done', data: { progress: 100, messageId: 1, resumeVersionId: 3 } },
        ]),
      }),
    )

    await page.goto('/')
    await page.getByLabel('Message', { exact: true }).fill('Backend engineer role')
    await page.getByRole('button', { name: 'Send', exact: true }).click()
    await expect(page.getByText('Ada Lovelace')).toBeVisible()

    await page.getByLabel('Template', { exact: true }).selectOption('classic')
    await page.getByRole('button', { name: /switch to dark mode/i }).click()

    // Simulate the backend now reflecting what was just "persisted" server-side
    // (registered after the earlier /api/chat/sessions route -> takes
    // precedence for GET going forward).
    await page.route('**/api/chat/sessions', async (route) => {
      if (route.request().method() !== 'GET') return route.fallback()
      await route.fulfill({
        json: {
          sessions: [{ id: 3, title: 'Persisted chat', updatedAt: createdAt, activeResumeVersionId: 3 }],
        },
      })
    })
    await page.route('**/api/chat/sessions/3', (route) =>
      route.fulfill({
        json: {
          session: { id: 3, title: 'Persisted chat', updatedAt: createdAt, activeResumeVersionId: 3 },
          messages: [
            {
              id: 1,
              role: 'user',
              content: 'Backend engineer role',
              intent: null,
              resumeVersionId: null,
              createdAt,
            },
            {
              id: 2,
              role: 'assistant',
              content: 'Generated a tailored resume for this job description.',
              intent: 'generate',
              resumeVersionId: 3,
              createdAt,
            },
          ],
          activeResume: resume,
        },
      }),
    )

    await page.reload()

    // Client-persisted state survives the reload.
    await expect(page.getByText('Ada Lovelace')).toBeVisible()
    await expect(page.getByLabel('Template', { exact: true })).toHaveValue('classic')
    await expect(page.getByRole('button', { name: /switch to light mode/i })).toBeVisible()

    // B2: the active session id is persisted too (chatStore's own messages
    // stay ephemeral), so the conversation auto-restores on boot instead of
    // showing an empty chat panel until manually resumed from the sidebar.
    await expect(page.getByText('Backend engineer role')).toBeVisible()
    await expect(page.getByText(/resume updated/i)).toBeVisible()
  })
})
