import type { Page } from '@playwright/test'

/**
 * Baseline mocks every flow needs regardless of what it's specifically
 * testing: the model list (Composer's picker) and an empty sessions list
 * (SessionSidebar) so nothing 404s or hangs waiting on a real backend.
 * Tests override /api/chat/sessions and the message-stream endpoint for
 * their specific scenario with an additional page.route call (later
 * registrations take precedence in Playwright).
 */
export async function mockBaseline(page: Page): Promise<void> {
  await page.route('**/api/models', (route) =>
    route.fulfill({
      json: {
        default: 'gemini-2.5-flash',
        models: [{ value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' }],
      },
    }),
  )

  await page.route('**/api/chat/sessions', (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return route.fulfill({ json: { sessions: [] } })
  })
}
