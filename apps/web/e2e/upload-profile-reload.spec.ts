import { test, expect } from '@playwright/test'
import { mockBaseline } from './support/mocks'
import { sseBody, SSE_HEADERS } from './support/sse'

/**
 * v2 ticket 10 ("Durabilidade do ProfileUpdatedCard"): an upload's ProfileUpdatedCard used to
 * be a client-only synthetic message — a session reload lost it entirely. As of this ticket,
 * the backend links the upload to its originating chat session (`sessionId` sent with the
 * upload) and GET /api/chat/sessions/{id} echoes back a `sourceDocument` field the frontend
 * reconstructs the SAME card from (see useChatSession.ts's toChatMessage / lib/api/dto.ts's
 * ChatMessageSourceDocumentDto) — proposed stays approvable across the reload.
 */
test.describe('ProfileUpdatedCard survives a session reload (v2 ticket 10)', () => {
  const createdAt = new Date().toISOString()

  test('upload -> reload -> the proposed card is still approvable -> approve', async ({ page }) => {
    await mockBaseline(page)

    await page.route('**/api/chat/sessions', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      await route.fulfill({ status: 201, json: { id: 20, title: 'Living Profile', createdAt } })
    })
    await page.route('**/api/chat/sessions/20/messages/stream', (route) =>
      route.fulfill({
        headers: SSE_HEADERS,
        body: sseBody([{ event: 'message', data: { content: 'Hi! How can I help?' } }, { event: 'done', data: { progress: 100, messageId: 1, resumeVersionId: null } }]),
      }),
    )

    let capturedUploadBody = ''
    await page.route('**/api/profile/documents', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      capturedUploadBody = route.request().postData() ?? ''
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

    await page.goto('/')
    await page.getByLabel('Message', { exact: true }).fill('hi there')
    await page.getByRole('button', { name: 'Send', exact: true }).click()
    await expect(page.getByText('Hi! How can I help?')).toBeVisible()

    await page.getByTestId('attachment-input').setInputFiles({
      name: 'profile.json',
      mimeType: 'application/json',
      buffer: Buffer.from('{"fullName":"Ada Lovelace"}'),
    })
    await expect(page.getByText(/1 new skill: rust/i)).toBeVisible()
    // The upload sent the active session's id, so the backend can persist the durable link.
    expect(capturedUploadBody).toContain('name="sessionId"')
    expect(capturedUploadBody).toContain('20')

    // Simulate the backend now reflecting what ticket 10's link persisted: a session restore
    // reconstructs the SAME proposed card from `sourceDocument`, not plain text.
    await page.route('**/api/chat/sessions', async (route) => {
      if (route.request().method() !== 'GET') return route.fallback()
      await route.fulfill({
        json: { sessions: [{ id: 20, title: 'Living Profile', updatedAt: createdAt, activeResumeVersionId: null }] },
      })
    })
    await page.route('**/api/chat/sessions/20', (route) =>
      route.fulfill({
        json: {
          session: { id: 20, title: 'Living Profile', updatedAt: createdAt, activeResumeVersionId: null, locale: null, jobDescription: null, createdAt },
          messages: [
            { id: 1, role: 'user', content: 'hi there', intent: null, resumeVersionId: null, createdAt, sourceDocument: null },
            { id: 2, role: 'assistant', content: 'Hi! How can I help?', intent: 'question', resumeVersionId: null, createdAt, sourceDocument: null },
            {
              id: 3,
              role: 'assistant',
              content: "Reviewed profile.json — here's what I found.",
              intent: 'profile_update',
              resumeVersionId: null,
              createdAt,
              sourceDocument: {
                documentId: 5,
                filename: 'profile.json',
                status: 'proposed',
                diffSummary: ['1 new skill: Rust'],
                opsCount: 1,
                error: null,
              },
            },
          ],
          activeResume: null,
        },
      }),
    )

    let appliedDocumentId: string | undefined
    await page.route('**/api/profile/documents/*/apply', async (route) => {
      appliedDocumentId = route.request().url().match(/documents\/(\d+)\/apply/)?.[1]
      await route.fulfill({ json: { profileVersion: 2, applied: 1, skipped: 0 } })
    })

    await page.reload()

    // Still reconstructed as a proposed, approvable card — never plain text, never gone.
    await expect(page.getByText(/1 new skill: rust/i)).toBeVisible()
    await expect(page.getByText('profile.json', { exact: true })).toBeVisible()
    const approveButton = page.getByRole('button', { name: 'Approve', exact: true })
    await expect(approveButton).toBeVisible()

    await approveButton.click()

    await expect(page.getByText(/applied to your profile/i)).toBeVisible()
    expect(appliedDocumentId).toBe('5')
  })
})
