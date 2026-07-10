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

// Ticket 12 (QA gate v2): re-attaching bytes the backend dedupes by sha256 used to append a
// SECOND ProfileUpdatedCard for the same documentId, leaving two live Approve/Reject pairs for
// one Source Document.
describe('Upload flow — duplicate upload (backend dedup by sha256)', () => {
  it('re-uploading the same file, which the backend resolves to an existing documentId, updates the existing card instead of adding a second one', async () => {
    let callCount = 0
    server.use(
      http.post('/api/profile/documents', () => {
        callCount += 1
        return HttpResponse.json(
          makeUploadResponse({ documentId: 12, diffSummary: [`upload #${callCount}`] }),
          { status: 202 },
        )
      }),
    )

    renderApp(<ChatPanel />)
    const file = new File(['{"fullName":"Ada"}'], 'profile.json', { type: 'application/json' })

    attach(file)
    await screen.findByText('upload #1')

    attach(file)
    await waitFor(() => expect(screen.getByText('upload #2')).toBeInTheDocument())

    expect(callCount).toBe(2)
    expect(screen.queryByText('upload #1')).not.toBeInTheDocument()
    expect(screen.getAllByText('profile.json')).toHaveLength(1)
    expect(screen.getAllByRole('button', { name: /approve/i })).toHaveLength(1)
  })
})

// Ticket 12 safety net: a settle (approve/reject) that 409s because the document was already
// settled elsewhere (e.g. the OTHER stale duplicate card, or a concurrent tab) used to leave the
// card stuck showing "proposed" with live buttons and a generic "Something went wrong" error --
// an invitation to retry forever. It must instead resync to the real status, no reload needed.
describe('Upload flow — settle conflict (409 safety net)', () => {
  it('approving a document that was already applied elsewhere syncs the card to applied with an honest message, not a generic retry error', async () => {
    server.use(
      http.post('/api/profile/documents', () =>
        HttpResponse.json(makeUploadResponse({ documentId: 15 }), { status: 202 }),
      ),
    )
    server.use(
      http.post('/api/profile/documents/:id/apply', () =>
        HttpResponse.json(
          { detail: "Source Document 15 is 'applied', not 'proposed' -- nothing to apply" },
          { status: 409 },
        ),
      ),
    )

    const user = userEvent.setup()
    renderApp(<ChatPanel />)
    attach(new File(['{}'], 'profile.json'))

    const approveButton = await screen.findByRole('button', { name: /approve/i })
    await user.click(approveButton)

    await waitFor(() => expect(screen.getByText('Applied to your profile')).toBeInTheDocument())
    expect(screen.getByRole('alert')).toHaveTextContent(/already applied/i)
    expect(screen.queryByRole('button', { name: /approve/i })).not.toBeInTheDocument()
    expect(screen.queryByText(/something went wrong/i)).not.toBeInTheDocument()
  })

  it('rejecting a document that was already rejected elsewhere syncs the card to discarded with an honest message', async () => {
    server.use(
      http.post('/api/profile/documents', () =>
        HttpResponse.json(makeUploadResponse({ documentId: 16 }), { status: 202 }),
      ),
    )
    server.use(
      http.post('/api/profile/documents/:id/reject', () =>
        HttpResponse.json(
          { detail: "Source Document 16 is 'rejected', not 'proposed' -- nothing to reject" },
          { status: 409 },
        ),
      ),
    )

    const user = userEvent.setup()
    renderApp(<ChatPanel />)
    attach(new File(['{}'], 'profile.json'))

    const rejectButton = await screen.findByRole('button', { name: /reject/i })
    await user.click(rejectButton)

    await waitFor(() => expect(screen.getByText('Discarded')).toBeInTheDocument())
    expect(screen.getByRole('alert')).toHaveTextContent(/already discarded/i)
    expect(screen.queryByRole('button', { name: /reject/i })).not.toBeInTheDocument()
  })
})
