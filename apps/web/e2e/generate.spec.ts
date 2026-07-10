import { test, expect } from '@playwright/test'
import { mockBaseline } from './support/mocks'
import { sseBody, SSE_HEADERS } from './support/sse'
import { makeResume } from './support/fixtures'

test.describe('Generate a resume', () => {
  test('pasting a job description in a fresh chat creates a session and renders the resume', async ({ page }) => {
    await mockBaseline(page)

    let sessionCreateBody: unknown
    await page.route('**/api/chat/sessions', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      sessionCreateBody = route.request().postDataJSON()
      await new Promise((r) => setTimeout(r, 150)) // observable "in-flight" window
      await route.fulfill({
        status: 201,
        json: { id: 1, title: 'Senior backend role', createdAt: new Date().toISOString() },
      })
    })

    const resume = makeResume({ fullName: 'Grace Hopper' })
    await page.route('**/api/chat/sessions/1/messages/stream', (route) =>
      route.fulfill({
        headers: SSE_HEADERS,
        body: sseBody([
          { event: 'stage', data: { step: 'calling_ai', progress: 40, message: 'Calling the model' } },
          { event: 'resume', data: { resume, resumeVersionId: 1 } },
          { event: 'message', data: { content: 'Generated a tailored resume for this job description.' } },
          { event: 'done', data: { progress: 100, messageId: 1, resumeVersionId: 1 } },
        ]),
      }),
    )

    await page.goto('/')
    await page
      .getByLabel('Message', { exact: true })
      .fill('Senior backend role, distributed systems, 5+ years Python.')
    await page.getByRole('button', { name: 'Send', exact: true }).click()

    // Session creation is deliberately delayed above so this is a reliable
    // (non-racy) window to observe the in-flight streaming UI.
    await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeVisible()

    await expect(page.getByText('Grace Hopper')).toBeVisible()
    await expect(page.getByText(/resume updated/i)).toBeVisible()
    expect(sessionCreateBody).toMatchObject({
      title: expect.stringContaining('Senior backend role'),
    })
  })

  test('pasting a job description in a fresh chat creates a session and renders the resume @real', async ({
    page,
  }) => {
    await page.goto('/')
    await page
      .getByLabel('Message', { exact: true })
      .fill(
        'Senior Backend Engineer — distributed systems team. Own service reliability, design ' +
          'APIs used by millions of requests/day. Strong Python, Kubernetes, PostgreSQL required.',
      )
    await page.getByRole('button', { name: 'Send', exact: true }).click()

    await expect(page.getByText(/resume updated|generated/i)).toBeVisible({ timeout: 60_000 })
  })
})
