import { test, expect } from '@playwright/test'
import { mockBaseline } from './support/mocks'
import { makeResume, RESUME_STORAGE_KEY, resumeStorageValue } from './support/fixtures'

test.describe('Switching templates never hits the network', () => {
  test('toolbar select and chat command both switch instantly with zero disallowed requests', async ({
    page,
  }) => {
    const resume = makeResume()
    await page.addInitScript(
      ([key, value]) => window.localStorage.setItem(key, value as string),
      [RESUME_STORAGE_KEY, resumeStorageValue(resume, 'modern', 'auto')] as const,
    )

    await mockBaseline(page)

    const disallowed: string[] = []
    const guard = async (route: import('@playwright/test').Route) => {
      disallowed.push(route.request().url())
      await route.abort()
    }
    // Anything that would mean a template switch went to the network instead
    // of staying client-side (registered after mockBaseline -> takes
    // precedence for the overlapping /api/chat/sessions pattern).
    await page.route('**/api/chat/sessions', async (route) => {
      if (route.request().method() === 'GET') return route.fulfill({ json: { sessions: [] } })
      await guard(route)
    })
    await page.route('**/api/chat/sessions/*/messages/stream', guard)
    await page.route('**/api/generate/stream', guard)
    await page.route('**/api/refine/stream', guard)

    await page.goto('/')
    await expect(page.getByText(resume.fullName)).toBeVisible()

    // Via the toolbar.
    await page.getByLabel('Template', { exact: true }).selectOption('ats-plain')
    await expect(page.locator('.tpl-ats-plain')).toBeVisible()

    // Via a chat command (never a chat message).
    await page.getByLabel('Message', { exact: true }).fill('use the classic template')
    await page.getByRole('button', { name: 'Send', exact: true }).click()
    await expect(page.getByLabel('Template', { exact: true })).toHaveValue('classic')
    await expect(page.locator('.tpl-classic')).toBeVisible()
    await expect(page.getByText(/switched to the classic template/i)).toBeVisible()

    expect(disallowed).toEqual([])
  })
})
