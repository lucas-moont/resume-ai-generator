import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { ChatPanel } from '../chat/components/ChatPanel'
import { server } from '../../test/setup'
import { renderApp } from '../../test/render'
import { makeUploadResponse } from '../../test/factories'
import { useChatStore } from '../chat/store/chatStore'
import { useResumeStore } from '../resume/store/resumeStore'

function attach(file: File) {
  const input = screen.getByTestId('attachment-input') as HTMLInputElement
  fireEvent.change(input, { target: { files: [file] } })
}

beforeEach(() => {
  localStorage.clear()
  useResumeStore.setState({ resume: null, template: 'modern', locale: 'auto' })
  useResumeStore.temporal.getState().clear()
  useChatStore.getState().reset()
})

describe('Upload flow — happy path across the 3 supported formats', () => {
  it.each([
    ['profile.json', new File(['{"fullName":"Ada"}'], 'profile.json', { type: 'application/json' })],
    ['profile.md', new File(['# Ada Lovelace'], 'profile.md', { type: 'text/markdown' })],
    ['profile.pdf', new File(['%PDF-1.4'], 'profile.pdf', { type: 'application/pdf' })],
  ])('uploading %s shows a ProfileUpdatedCard with the merge summary and approve/reject actions', async (name, file) => {
    server.use(
      http.post('/api/profile/documents', () =>
        HttpResponse.json(makeUploadResponse({ documentId: 1, diffSummary: ['1 new skill: Rust'] }), {
          status: 202,
        }),
      ),
    )

    renderApp(<ChatPanel />)
    attach(file)

    await screen.findByText(/1 new skill: rust/i)
    expect(screen.getByText(name)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /approve/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /reject/i })).toBeInTheDocument()
  })
})

describe('Upload flow — client-side validation', () => {
  it('rejects an unsupported file type before ever calling the API', async () => {
    let called = false
    server.use(
      http.post('/api/profile/documents', () => {
        called = true
        return HttpResponse.json(makeUploadResponse())
      }),
    )

    renderApp(<ChatPanel />)
    attach(new File(['hi'], 'resume.docx'))

    expect(await screen.findByRole('alert')).toHaveTextContent(/resume\.docx/i)
    expect(called).toBe(false)
    expect(screen.queryByText(/profile update proposed/i)).not.toBeInTheDocument()
  })

  it('rejects an oversize file before ever calling the API', async () => {
    let called = false
    server.use(
      http.post('/api/profile/documents', () => {
        called = true
        return HttpResponse.json(makeUploadResponse())
      }),
    )

    renderApp(<ChatPanel />)
    const huge = new File(['x'], 'huge.pdf')
    Object.defineProperty(huge, 'size', { value: 11 * 1024 * 1024 })
    attach(huge)

    expect(await screen.findByRole('alert')).toHaveTextContent(/large/i)
    expect(called).toBe(false)
  })
})

describe('Upload flow — failed extraction', () => {
  it('shows an actionable failed card (e.g. a scanned PDF with no extractable text)', async () => {
    server.use(
      http.post('/api/profile/documents', () =>
        HttpResponse.json(
          {
            documentId: 3,
            status: 'failed',
            error: 'This PDF has no extractable text — try a text-based export.',
          },
          { status: 202 },
        ),
      ),
    )

    renderApp(<ChatPanel />)
    attach(new File(['%PDF-1.4'], 'scanned.pdf', { type: 'application/pdf' }))

    await screen.findByText(/no extractable text/i)
    expect(screen.queryByRole('button', { name: /approve/i })).not.toBeInTheDocument()
  })
})

describe('Upload flow — approve / reject', () => {
  it('approving a proposed merge calls apply and flips the card to applied', async () => {
    server.use(
      http.post('/api/profile/documents', () =>
        HttpResponse.json(makeUploadResponse({ documentId: 8 }), { status: 202 }),
      ),
    )
    let capturedDocumentId: string | undefined
    server.use(
      http.post('/api/profile/documents/:id/apply', ({ params }) => {
        capturedDocumentId = params.id as string
        return HttpResponse.json({ profileVersion: 2, applied: 1, skipped: 0 })
      }),
    )

    const user = userEvent.setup()
    renderApp(<ChatPanel />)
    attach(new File(['{}'], 'profile.json'))

    const approveButton = await screen.findByRole('button', { name: /approve/i })
    await user.click(approveButton)

    await waitFor(() => expect(screen.getByText(/applied to your profile/i)).toBeInTheDocument())
    expect(capturedDocumentId).toBe('8')
    expect(screen.queryByRole('button', { name: /approve/i })).not.toBeInTheDocument()
  })

  it('rejecting a proposed merge calls reject and flips the card to discarded', async () => {
    server.use(
      http.post('/api/profile/documents', () =>
        HttpResponse.json(makeUploadResponse({ documentId: 9 }), { status: 202 }),
      ),
    )
    let capturedDocumentId: string | undefined
    server.use(
      http.post('/api/profile/documents/:id/reject', ({ params }) => {
        capturedDocumentId = params.id as string
        return new HttpResponse(null, { status: 204 })
      }),
    )

    const user = userEvent.setup()
    renderApp(<ChatPanel />)
    attach(new File(['{}'], 'profile.json'))

    const rejectButton = await screen.findByRole('button', { name: /reject/i })
    await user.click(rejectButton)

    await waitFor(() => expect(screen.getByText(/discarded/i)).toBeInTheDocument())
    expect(capturedDocumentId).toBe('9')
  })
})
