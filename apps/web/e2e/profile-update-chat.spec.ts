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

  /**
   * v3 ticket 12 (P3 QA gap): a chat-only profile_update turn's confirmation card used to
   * vanish on a session reload — toChatMessage (useChatSession.ts) only hydrated
   * ProfileUpdatedCard (has sourceDocument) and ResumeUpdatedCard (has resumeVersionId), never
   * this chat-only case, even though `intent` was already on the wire. Reload now degrades
   * honestly to a label-only "Profile updated" (no profileVersion/summary in the history DTO),
   * same pattern as upload-profile-reload.spec.ts for ProfileUpdatedCard.
   */
  test('the profile-updated card survives a session reload, degraded to a label-only confirmation', async ({
    page,
  }) => {
    const resume = makeResume({ fullName: 'Grace Hopper', headline: 'Senior Engineer' })
    await page.addInitScript(
      ([key, value]) => window.localStorage.setItem(key, value as string),
      [RESUME_STORAGE_KEY, resumeStorageValue(resume, 'modern', 'auto')] as const,
    )
    const createdAt = new Date().toISOString()

    await mockBaseline(page)
    await page.route('**/api/chat/sessions', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      await route.fulfill({ status: 201, json: { id: 6, title: 'Profile update', createdAt } })
    })
    await page.route('**/api/chat/sessions/6/messages/stream', (route) =>
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
    await page.getByLabel('Message', { exact: true }).fill('I changed my phone number')
    await page.getByRole('button', { name: 'Send', exact: true }).click()
    await expect(page.getByText(/profile updated to version 4/i)).toBeVisible()

    // Simulate the backend echoing this turn back on reload: only `intent` survives, not the
    // SSE-only profileVersion/summary.
    await page.route('**/api/chat/sessions', async (route) => {
      if (route.request().method() !== 'GET') return route.fallback()
      await route.fulfill({
        json: { sessions: [{ id: 6, title: 'Profile update', updatedAt: createdAt, activeResumeVersionId: null }] },
      })
    })
    await page.route('**/api/chat/sessions/6', (route) =>
      route.fulfill({
        json: {
          session: { id: 6, title: 'Profile update', updatedAt: createdAt, activeResumeVersionId: null, locale: null, jobDescription: null, createdAt },
          messages: [
            { id: 1, role: 'user', content: 'I changed my phone number', intent: null, resumeVersionId: null, createdAt, sourceDocument: null },
            {
              id: 2,
              role: 'assistant',
              content: "I've updated your profile. Want me to regenerate your resume with this change?",
              intent: 'profile_update',
              resumeVersionId: null,
              createdAt,
              sourceDocument: null,
            },
          ],
          activeResume: resume,
        },
      }),
    )

    await page.reload()

    // Degraded but present — never gone, never plain text.
    await expect(page.getByText('Profile updated')).toBeVisible()
    await expect(page.getByText(/version 4/i)).not.toBeVisible()
  })
})
