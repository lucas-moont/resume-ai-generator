import { test, expect } from '@playwright/test'
import { mockBaseline } from './support/mocks'
import { makeResume, RESUME_STORAGE_KEY, resumeStorageValue } from './support/fixtures'

test.describe('Export PDF', () => {
  test('the toolbar button sends {resume, template} and triggers a browser download', async ({ page }) => {
    const resume = makeResume()
    await page.addInitScript(
      ([key, value]) => window.localStorage.setItem(key, value as string),
      [RESUME_STORAGE_KEY, resumeStorageValue(resume, 'classic', 'auto')] as const,
    )

    await mockBaseline(page)

    let capturedBody: unknown
    await page.route('**/api/export/pdf', async (route) => {
      capturedBody = route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        headers: {
          'Content-Type': 'application/pdf',
          'Content-Disposition': 'attachment; filename="resume.pdf"',
        },
        body: Buffer.from('%PDF-1.4 fake pdf content'),
      })
    })

    await page.goto('/')
    await expect(page.getByText(resume.fullName)).toBeVisible()

    const downloadPromise = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Download PDF', exact: true }).click()
    const download = await downloadPromise

    expect(capturedBody).toMatchObject({ template: 'classic' })
    expect((capturedBody as { resume?: { fullName?: string } }).resume?.fullName).toBe(resume.fullName)
    expect(download.suggestedFilename()).toMatch(/_CV\.pdf$/)
  })

  test('generating then downloading produces a real PDF from the real backend @real', async ({ page }) => {
    await page.goto('/')
    await page
      .getByLabel('Message', { exact: true })
      .fill(
        'Senior Backend Engineer — distributed systems team. Own service reliability, design ' +
          'APIs used by millions of requests/day. Strong Python, Kubernetes, PostgreSQL required.',
      )
    await page.getByRole('button', { name: 'Send', exact: true }).click()
    await expect(page.getByText(/resume updated|generated/i)).toBeVisible({ timeout: 60_000 })

    const downloadPromise = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Download PDF', exact: true }).click()
    const download = await downloadPromise

    expect(download.suggestedFilename()).toMatch(/_CV\.pdf$/)
  })
})
