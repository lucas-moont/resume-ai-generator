import { test, expect } from '@playwright/test'
import { mockBaseline } from './support/mocks'
import { sseBody, SSE_HEADERS } from './support/sse'
import { makeResume, RESUME_STORAGE_KEY, resumeStorageValue } from './support/fixtures'

// jsdom (Vitest) can't simulate real contenteditable caret/selection behavior
// — see .scratch/v2-living-profile/issues/06-spike-contenteditable.md's
// Answer section (d). These specs cover exactly what that spike flagged as
// Playwright-only: real per-keystroke typing order, the SSE-mid-typing race,
// and the naive/controlled-reintroduction regression guard.

async function seedResume(page: import('@playwright/test').Page, overrides = {}) {
  const resume = makeResume(overrides)
  await page.addInitScript(
    ([key, value]) => window.localStorage.setItem(key, value as string),
    [RESUME_STORAGE_KEY, resumeStorageValue(resume, 'modern', 'auto')] as const,
  )
  return resume
}

test.describe('Inline editing — commit on blur/Enter', () => {
  test('typing into a plain field commits on blur and persists to localStorage', async ({ page }) => {
    await seedResume(page, { fullName: 'Ada Lovelace' })
    await mockBaseline(page)
    await page.goto('/')

    await page.getByRole('button', { name: 'Edit inline' }).click()

    const nameField = page.locator('[data-field="fullName"]')
    await nameField.click()
    await page.keyboard.press('Control+A')
    await page.keyboard.type('Grace Hopper')
    await page.locator('[data-field="headline"]').click() // blur by focusing elsewhere

    await expect(nameField).toHaveText('Grace Hopper')

    // Read localStorage directly rather than reloading: addInitScript's seed
    // re-runs on every navigation/reload in this context, so a reload here
    // would just re-seed the ORIGINAL fullName back over the edit — that's
    // a property of addInitScript, not a persistence bug in the app.
    const persisted = await page.evaluate(
      (key) => JSON.parse(window.localStorage.getItem(key) ?? '{}'),
      'resume-agent:resume',
    )
    expect(persisted.state.resume.fullName).toBe('Grace Hopper')
  })

  test('Enter commits a plain field without inserting a newline', async ({ page }) => {
    await seedResume(page, { fullName: 'Ada Lovelace' })
    await mockBaseline(page)
    await page.goto('/')

    await page.getByRole('button', { name: 'Edit inline' }).click()

    const nameField = page.locator('[data-field="fullName"]')
    await nameField.click()
    await page.keyboard.press('Control+A')
    await page.keyboard.type('Katherine Johnson')
    await page.keyboard.press('Enter')

    await expect(nameField).toHaveText('Katherine Johnson')
    await expect(nameField).not.toBeFocused()
  })
})

test.describe('Inline editing — regression guard against the naive/controlled pattern', () => {
  test('rapid real typing lands in the correct order (would read reversed under the naive pattern)', async ({
    page,
  }) => {
    await seedResume(page, { fullName: 'Ada Lovelace' })
    await mockBaseline(page)
    await page.goto('/')

    await page.getByRole('button', { name: 'Edit inline' }).click()

    const nameField = page.locator('[data-field="fullName"]')
    await nameField.click()
    await page.keyboard.press('End')
    // A real per-key delay is load-bearing here — see the spike's Answer (a):
    // the naive/controlled bug (value re-flowed into children on every
    // keystroke) only reproduces when React actually gets to reconcile
    // between keystrokes, which pressSequentially's inter-key delay forces.
    await page.keyboard.type('HelloWorld123', { delay: 60 })
    await page.locator('[data-field="headline"]').click()

    // Correct (gated) order: appended after the existing name. Under the
    // naive pattern this comes back reversed ("321dlroWolleH...").
    await expect(nameField).toHaveText('Ada LovelaceHelloWorld123')
  })
})

test.describe('Inline editing — external update mid-typing (SSE race)', () => {
  test('an SSE resume update mid-edit leaves the focused field alone; local edit wins on blur', async ({ page }) => {
    await seedResume(page, { fullName: 'Ada Lovelace', summary: 'Original summary.' })
    await mockBaseline(page)
    await page.route('**/api/chat/sessions', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      await route.fulfill({ status: 201, json: { id: 9, title: 'Refine', createdAt: new Date().toISOString() } })
    })
    const updated = makeResume({ fullName: 'Grace Hopper', summary: 'SSE overwrote this summary.' })
    await page.route('**/api/chat/sessions/9/messages/stream', async (route) => {
      // Deliberate delay so the mid-typing window is real, not a race that
      // happens to resolve before the next keystroke.
      await new Promise((resolve) => setTimeout(resolve, 400))
      await route.fulfill({
        headers: SSE_HEADERS,
        body: sseBody([
          { event: 'resume', data: { resume: updated, resumeVersionId: 9 } },
          { event: 'message', data: { content: 'Updated.' } },
          { event: 'done', data: { progress: 100, messageId: 1, resumeVersionId: 9 } },
        ]),
      })
    })

    await page.goto('/')
    await page.getByRole('button', { name: 'Edit inline' }).click()

    // Realistic ordering: sending a message necessarily focuses the Composer
    // first (clicking Send while a resume field is focused would just blur
    // it — that's not a race, that's a normal commit). The reachable race is
    // the user going BACK into the preview to fix something WHILE a
    // previously-sent turn is still in flight — so Send fires first, then
    // the summary field is focused, and only THEN does the delayed SSE event
    // land while it's held.
    // Set up BEFORE the triggering click, so there's no window where the
    // (mocked, delayed) response could resolve before we start waiting for it.
    const responsePromise = page.waitForResponse((resp) => resp.url().includes('/messages/stream'))
    await page.getByLabel('Message', { exact: true }).fill('Tighten this up')
    await page.getByRole('button', { name: 'Send', exact: true }).click()

    const summaryField = page.locator('[data-field="summary"]')
    await summaryField.click()
    await page.keyboard.press('Control+A')
    await page.keyboard.type('User is actively typing this', { delay: 40 })

    // Condition-based, not a fixed time window: wait for the actual network
    // round-trip to finish before asserting, so this stays robust even if a
    // cold/contended dev server makes the mock's 400ms delay take much
    // longer in wall-clock time than usual.
    await responsePromise
    await expect(page.locator('[data-field="fullName"]')).toHaveText('Grace Hopper')

    // The focused summary field must still show the user's in-progress text
    // — the external update was gated out while it had focus.
    await expect(summaryField).toHaveText('User is actively typing this')

    // Now blur: the local edit commits over whatever the SSE had for this
    // one field (last-editor-wins), while fullName keeps the SSE's value.
    await page.locator('[data-field="fullName"]').click()
    await expect(summaryField).toHaveText('User is actively typing this')
    await expect(page.locator('[data-field="fullName"]')).toHaveText('Grace Hopper')
  })
})

test.describe('Inline editing — export reflects the edit', () => {
  test('editing a field inline then exporting PDF sends the edited value', async ({ page }) => {
    const resume = await seedResume(page, { fullName: 'Ada Lovelace' })
    await mockBaseline(page)

    let capturedBody: unknown
    await page.route('**/api/export/pdf', async (route) => {
      capturedBody = route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/pdf', 'Content-Disposition': 'attachment; filename="resume.pdf"' },
        body: Buffer.from('%PDF-1.4 fake pdf content'),
      })
    })

    await page.goto('/')
    await page.getByRole('button', { name: 'Edit inline' }).click()

    const nameField = page.locator('[data-field="fullName"]')
    await nameField.click()
    await page.keyboard.press('Control+A')
    await page.keyboard.type('Margaret Hamilton')
    await page.locator('[data-field="headline"]').click()
    await expect(nameField).toHaveText('Margaret Hamilton')

    const downloadPromise = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Download PDF', exact: true }).click()
    await downloadPromise

    expect((capturedBody as { resume?: { fullName?: string } }).resume?.fullName).toBe('Margaret Hamilton')
    expect((capturedBody as { resume?: { headline?: string } }).resume?.headline).toBe(resume.headline)
  })
})
