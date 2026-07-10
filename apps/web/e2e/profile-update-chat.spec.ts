import { test, expect } from '@playwright/test'
import { mockBaseline } from './support/mocks'
import { sseBody, SSE_HEADERS } from './support/sse'
import { makeResume, RESUME_STORAGE_KEY, resumeStorageValue } from './support/fixtures'

test.describe('Chat profile_update intent (Living Profile, v2 ticket 09)', () => {
  test('"I changed my phone number" shows a profile-updated card and leaves the active resume untouched', async ({
    page,
  }) => {
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
        json: { id: 3, title: 'Profile update', createdAt: new Date().toISOString() },
      })
    })
    await page.route('**/api/chat/sessions/3/messages/stream', (route) =>
      route.fulfill({
        headers: SSE_HEADERS,
        body: sseBody([
          { event: 'profile_update', data: { profileVersion: 4, summary: 'Updated phone number.' } },
          {
            event: 'message',
            data: { content: "I've updated your profile. Want me to regenerate your resume with this change?" },
          },
          { event: 'done', data: { progress: 100, messageId: 2, resumeVersionId: null } },
        ]),
      }),
    )

    await page.goto('/')
    await expect(page.getByText('Senior Engineer')).toBeVisible() // pre-existing resume rendered

    await page.getByLabel('Message', { exact: true }).fill('I changed my phone number')
    await page.getByRole('button', { name: 'Send', exact: true }).click()

    await expect(page.getByText(/profile updated to version 4/i)).toBeVisible()
    await expect(page.getByText(/updated phone number\./i)).toBeVisible()
    await expect(page.getByText(/want me to regenerate/i)).toBeVisible()

    // The active resume is untouched — same headline, no resumeUpdated card.
    await expect(page.getByText('Senior Engineer')).toBeVisible()
    await expect(page.getByText(/resume updated/i)).not.toBeVisible()
  })
})
