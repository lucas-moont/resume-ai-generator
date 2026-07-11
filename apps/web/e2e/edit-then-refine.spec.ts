import { test, expect } from '@playwright/test'
import { mockBaseline } from './support/mocks'
import { sseBody, SSE_HEADERS } from './support/sse'
import { makeResume, RESUME_STORAGE_KEY, resumeStorageValue } from './support/fixtures'

// v2-era debt (F4), closed here alongside the diff-visual work: an inline
// edit must actually reach the chat refine turn — useChatStream forwards
// resumeStore's current (possibly hand-edited, never persisted) resume in
// the request body precisely so a refine starts from what's on screen, not
// the last version the server saved.
test.describe('Edit inline, then refine via chat (v3 ticket 09, F4 debt)', () => {
  test('the edited field is carried in the refine request body, and the response updates the preview + card', async ({
    page,
  }) => {
    const resume = makeResume({ fullName: 'Ada Lovelace', headline: 'Senior Software Engineer' })
    await page.addInitScript(
      ([key, value]) => window.localStorage.setItem(key, value as string),
      [RESUME_STORAGE_KEY, resumeStorageValue(resume, 'modern', 'auto')] as const,
    )
    await mockBaseline(page)
    await page.route('**/api/chat/sessions', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      await route.fulfill({ status: 201, json: { id: 3, title: 'Refine', createdAt: new Date().toISOString() } })
    })

    let capturedBody: { resume?: { fullName?: string; headline?: string } } | undefined
    const updated = makeResume({ fullName: 'Margaret Hamilton', headline: 'Staff Engineer' })
    await page.route('**/api/chat/sessions/3/messages/stream', async (route) => {
      capturedBody = route.request().postDataJSON()
      await route.fulfill({
        headers: SSE_HEADERS,
        body: sseBody([
          { event: 'resume', data: { resume: updated, resumeVersionId: 3 } },
          { event: 'message', data: { content: 'Updated your resume.' } },
          { event: 'done', data: { progress: 100, messageId: 1, resumeVersionId: 3 } },
        ]),
      })
    })

    await page.goto('/')
    await page.getByRole('button', { name: 'Edit inline' }).click()

    const nameField = page.locator('[data-field="fullName"]')
    await nameField.click()
    await page.keyboard.press('Control+A')
    await page.keyboard.type('Margaret Hamilton')
    await page.locator('[data-field="headline"]').click() // blur, commits the edit
    await expect(nameField).toHaveText('Margaret Hamilton')

    await page.getByLabel('Message', { exact: true }).fill('Make my title senior')
    await page.getByRole('button', { name: 'Send', exact: true }).click()

    // Scoped to the preview: ResumeUpdatedCard's diff panel also shows this
    // exact "after" text (see refine.spec.ts's identical scoping).
    await expect(page.getByLabel('Preview', { exact: true }).getByText('Staff Engineer', { exact: true })).toBeVisible()
    await expect(page.getByText(/resume updated/i)).toBeVisible()

    expect(capturedBody?.resume?.fullName).toBe('Margaret Hamilton')
    // The un-edited field was still forwarded as-is (the whole client resume
    // travels together, not just the touched field).
    expect(capturedBody?.resume?.headline).toBe('Senior Software Engineer')
  })
})
