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

  // v3 ticket 06: unconfigured/first-use defaults for Settings, so a test that never opens
  // SettingsDialog (most of them) never 404s if it happens to mount. Tests that DO exercise
  // Settings override these with their own page.route calls (later registrations win).
  await page.route('**/api/settings/providers', (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return route.fulfill({
      json: {
        active: 'auto',
        providers: [
          { name: 'claude', available: false, auth: 'cli', defaultModel: 'claude-sonnet-5', models: [] },
          { name: 'gemini', available: false, auth: 'none', defaultModel: 'gemini-2.5-flash', models: [] },
          { name: 'ollama', available: false, auth: 'local', defaultModel: 'llama3.2', models: [] },
        ],
      },
    })
  })

  await page.route('**/api/settings/keys', (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return route.fulfill({
      json: {
        keys: [
          { name: 'ANTHROPIC_API_KEY', configured: false, source: null },
          { name: 'GEMINI_API_KEY', configured: false, source: null },
          { name: 'GITHUB_TOKEN', configured: false, source: null },
        ],
      },
    })
  })
}
