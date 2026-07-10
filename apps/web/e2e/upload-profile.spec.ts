import { test, expect } from '@playwright/test'
import { mockBaseline } from './support/mocks'

test.describe('Upload a profile document (Living Profile)', () => {
  test('attaching a file shows a proposed merge card; approving it confirms the change', async ({ page }) => {
    await mockBaseline(page)

    await page.route('**/api/profile/documents', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      await route.fulfill({
        status: 202,
        json: {
          documentId: 5,
          status: 'proposed',
          proposedPatch: [
            {
              op: 'add',
              path: '/skills/-',
              value: 'Rust',
              reason: 'New skill found in the uploaded document.',
              confidence: 0.92,
              sourceExcerpt: 'Proficient in Rust and systems programming.',
            },
          ],
          diffSummary: ['1 new skill: Rust'],
          extractedPreview: { skills: ['Rust'] },
        },
      })
    })

    let appliedDocumentId: string | undefined
    await page.route('**/api/profile/documents/*/apply', async (route) => {
      appliedDocumentId = route.request().url().match(/documents\/(\d+)\/apply/)?.[1]
      await route.fulfill({ json: { profileVersion: 2, applied: 1, skipped: 0 } })
    })

    await page.goto('/')

    await page.getByTestId('attachment-input').setInputFiles({
      name: 'profile.json',
      mimeType: 'application/json',
      buffer: Buffer.from('{"fullName":"Ada Lovelace"}'),
    })

    await expect(page.getByText(/1 new skill: rust/i)).toBeVisible()
    await expect(page.getByText('profile.json', { exact: true })).toBeVisible()

    await page.getByRole('button', { name: 'Approve', exact: true }).click()

    await expect(page.getByText(/applied to your profile/i)).toBeVisible()
    expect(appliedDocumentId).toBe('5')
    await expect(page.getByRole('button', { name: 'Approve', exact: true })).not.toBeVisible()
  })

  test('rejecting a proposed merge marks it discarded', async ({ page }) => {
    await mockBaseline(page)

    await page.route('**/api/profile/documents', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      await route.fulfill({
        status: 202,
        json: {
          documentId: 6,
          status: 'proposed',
          proposedPatch: [],
          diffSummary: ['1 divergent title in Experience'],
        },
      })
    })
    await page.route('**/api/profile/documents/*/reject', async (route) => {
      await route.fulfill({ status: 204, body: '' })
    })

    await page.goto('/')

    await page.getByTestId('attachment-input').setInputFiles({
      name: 'notes.md',
      mimeType: 'text/markdown',
      buffer: Buffer.from('# Ada Lovelace\n\nSenior Engineer'),
    })

    await expect(page.getByText(/1 divergent title/i)).toBeVisible()
    await page.getByRole('button', { name: 'Reject', exact: true }).click()

    await expect(page.getByText(/discarded/i)).toBeVisible()
  })

  test('an unsupported file type is rejected client-side with no request made', async ({ page }) => {
    await mockBaseline(page)

    let called = false
    await page.route('**/api/profile/documents', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      called = true
      await route.fulfill({ json: { documentId: 1, status: 'proposed' } })
    })

    await page.goto('/')

    await page.getByTestId('attachment-input').setInputFiles({
      name: 'resume.docx',
      mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      buffer: Buffer.from('not a supported format'),
    })

    await expect(page.getByRole('alert')).toContainText(/resume\.docx/i)
    expect(called).toBe(false)
  })
})
