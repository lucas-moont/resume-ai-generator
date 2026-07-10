import { test, expect } from '@playwright/test'
import { mockBaseline } from './support/mocks'
import { sseBody, SSE_HEADERS } from './support/sse'
import { makeResume, RESUME_STORAGE_KEY, resumeStorageValue } from './support/fixtures'

test.describe('Refine an active resume via chat', () => {
  test('a follow-up message updates the preview and shows a resume-updated card', async ({ page }) => {
    const resume = makeResume({ fullName: 'Grace Hopper', headline: 'Senior Engineer' })
    await page.addInitScript(
      ([key, value]) => window.localStorage.setItem(key, value as string),
      [RESUME_STORAGE_KEY, resumeStorageValue(resume, 'modern', 'auto')] as const,
    )

    await mockBaseline(page)
    await page.route('**/api/chat/sessions', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      await route.fulfill({
        status: 201,
        json: { id: 2, title: 'Refine', createdAt: new Date().toISOString() },
      })
    })
    const updated = makeResume({ fullName: 'Grace Hopper', headline: 'Staff Engineer' })
    await page.route('**/api/chat/sessions/2/messages/stream', (route) =>
      route.fulfill({
        headers: SSE_HEADERS,
        body: sseBody([
          { event: 'resume', data: { resume: updated, resumeVersionId: 2 } },
          { event: 'message', data: { content: 'Atualizei seu currículo.' } },
          { event: 'done', data: { progress: 100, messageId: 2, resumeVersionId: 2 } },
        ]),
      }),
    )

    await page.goto('/')
    await expect(page.getByText('Senior Engineer')).toBeVisible() // pre-existing resume rendered

    await page.getByLabel('Message', { exact: true }).fill('Update my title to Staff Engineer')
    await page.getByRole('button', { name: 'Send', exact: true }).click()

    await expect(page.getByText('Staff Engineer', { exact: true })).toBeVisible()
    await expect(page.getByText(/resume updated/i)).toBeVisible()
  })
})
