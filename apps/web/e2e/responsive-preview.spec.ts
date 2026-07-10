import { test, expect } from '@playwright/test'
import { mockBaseline } from './support/mocks'
import { sseBody, SSE_HEADERS } from './support/sse'
import { makeResume } from './support/fixtures'

test.describe('Responsive preview (B3)', () => {
  test('the A4 page scales to fit a narrow viewport instead of overflowing/clipping', async ({ page }) => {
    await page.setViewportSize({ width: 400, height: 800 })
    await mockBaseline(page)
    const resume = makeResume({ fullName: 'Ada Lovelace' })

    await page.route('**/api/chat/sessions', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      await route.fulfill({ status: 201, json: { id: 3, title: 'x', createdAt: new Date().toISOString() } })
    })
    await page.route('**/api/chat/sessions/3/messages/stream', (route) =>
      route.fulfill({
        headers: SSE_HEADERS,
        body: sseBody([
          { event: 'resume', data: { resume, resumeVersionId: 3 } },
          { event: 'message', data: { content: 'Generated.' } },
          { event: 'done', data: { progress: 100, messageId: 1, resumeVersionId: 3 } },
        ]),
      }),
    )

    await page.goto('/')
    await page.getByLabel('Message', { exact: true }).fill('Backend engineer role')
    await page.getByRole('button', { name: 'Send', exact: true }).click()
    await page.getByText(/resume updated/i).waitFor()

    await page.getByRole('tab', { name: 'Preview' }).click()
    await expect(page.getByText('Ada Lovelace')).toBeVisible()

    const wrap = page.locator('.print-preview-wrap')
    const overflow = await wrap.evaluate((el) => el.scrollWidth - el.clientWidth)
    // A couple of px of rounding slack; the pre-fix bug overflowed by ~400px.
    expect(overflow).toBeLessThanOrEqual(2)

    // The scaled page itself must be fully within the visible viewport,
    // not just "not causing scroll" (belt and suspenders for the same bug).
    const pageBox = await page.locator('.print-scale').boundingBox()
    expect(pageBox).not.toBeNull()
    expect(pageBox!.x).toBeGreaterThanOrEqual(0)
    expect(pageBox!.x + pageBox!.width).toBeLessThanOrEqual(400)
  })
})
