import { test, expect } from '@playwright/test'
import { mockBaseline } from './support/mocks'

test.describe('Settings: switch provider + pick a model, Composer reflects it live', () => {
  test('opening settings, switching provider, and picking a model updates the Composer without a reload', async ({
    page,
  }) => {
    await mockBaseline(page)

    // Overrides mockBaseline's /api/models (registered after -> takes precedence): a
    // provider/key change invalidates this shared query, so a call-count increase after the
    // settings mutation is the proof the Composer's own picker refetches without a reload.
    let modelsCalls = 0
    await page.route('**/api/models', (route) => {
      modelsCalls += 1
      return route.fulfill({
        json: {
          default: 'gemini-2.5-flash',
          models: [
            { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash', provider: 'gemini' },
            { value: 'claude-sonnet-5', label: 'Claude Sonnet 5', provider: 'claude' },
            { value: 'claude-haiku-4-5', label: 'Claude Haiku 4.5', provider: 'claude' },
          ],
        },
      })
    })

    let active: string = 'auto'
    let claudeDefaultModel = 'claude-sonnet-5'
    const providersPayload = () => ({
      active,
      providers: [
        {
          name: 'claude',
          available: true,
          auth: 'api_key',
          defaultModel: claudeDefaultModel,
          models: [
            { value: 'claude-sonnet-5', label: 'Claude Sonnet 5' },
            { value: 'claude-haiku-4-5', label: 'Claude Haiku 4.5' },
          ],
        },
        { name: 'gemini', available: false, auth: 'none', defaultModel: 'gemini-2.5-flash', models: [] },
        { name: 'ollama', available: false, auth: 'local', defaultModel: 'llama3.2', models: [] },
      ],
    })

    await page.route('**/api/settings/providers', async (route) => {
      if (route.request().method() === 'GET') return route.fulfill({ json: providersPayload() })
      const body = route.request().postDataJSON() as { provider: string; defaultModel?: string }
      active = body.provider
      if (body.defaultModel) claudeDefaultModel = body.defaultModel
      return route.fulfill({ json: providersPayload() })
    })

    await page.goto('/')

    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    await expect(page.getByRole('dialog', { name: /settings/i })).toBeVisible()

    const modelsCallsBeforeSwitch = modelsCalls
    await page.getByRole('radio', { name: /claude/i }).click()
    await expect(page.getByRole('radio', { name: /claude/i })).toBeChecked()
    // Provider switch invalidates ['models'] -> a fresh GET, proven by the call count moving.
    await expect.poll(() => modelsCalls).toBeGreaterThan(modelsCallsBeforeSwitch)

    await page.getByRole('combobox', { name: /default model/i }).click()
    await page.getByRole('option', { name: /claude haiku 4\.5/i }).click()

    await page.getByRole('button', { name: /close settings/i }).click()
    await expect(page.getByRole('dialog')).not.toBeVisible()

    // Composer's own model picker (ticket 07's Combobox, over the SAME ['models'] query/producer)
    // now offers the claude models too -- reflecting the settings change with no page reload.
    await page.getByRole('combobox', { name: /ai model/i }).click()
    await expect(page.getByRole('option', { name: /claude haiku 4\.5/i })).toBeVisible()
  })
})
