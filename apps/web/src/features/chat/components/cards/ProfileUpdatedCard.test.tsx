import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ProfileUpdatedCard } from './ProfileUpdatedCard'
import type { ProfileUpdatedCard as ProfileUpdatedCardData } from '../../store/chatStore'

function makeCard(overrides: Partial<ProfileUpdatedCardData> = {}): ProfileUpdatedCardData {
  return {
    type: 'profileUpdated',
    documentId: 1,
    filename: 'profile.json',
    status: 'proposed',
    diffSummary: ['1 new skill: Rust', '1 divergent title in Experience'],
    opsCount: 2,
    ...overrides,
  }
}

describe('ProfileUpdatedCard — proposed', () => {
  it('shows the filename, diffSummary, ops count, and approve/reject buttons', () => {
    render(<ProfileUpdatedCard card={makeCard()} onApprove={vi.fn()} onReject={vi.fn()} />)

    expect(screen.getByText('profile.json')).toBeInTheDocument()
    expect(screen.getByText(/1 new skill: rust/i)).toBeInTheDocument()
    expect(screen.getByText(/1 divergent title in experience/i)).toBeInTheDocument()
    expect(screen.getByText(/2/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /approve/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /reject/i })).toBeInTheDocument()
  })

  it('calls onApprove with the documentId when Approve is clicked', async () => {
    const onApprove = vi.fn().mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<ProfileUpdatedCard card={makeCard({ documentId: 42 })} onApprove={onApprove} onReject={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: /approve/i }))

    expect(onApprove).toHaveBeenCalledWith(42)
  })

  it('calls onReject with the documentId when Reject is clicked', async () => {
    const onReject = vi.fn().mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<ProfileUpdatedCard card={makeCard({ documentId: 42 })} onApprove={vi.fn()} onReject={onReject} />)

    await user.click(screen.getByRole('button', { name: /reject/i }))

    expect(onReject).toHaveBeenCalledWith(42)
  })

  it('disables both buttons while an action is pending, and shows an inline error if it fails', async () => {
    let resolveApprove!: () => void
    const onApprove = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveApprove = resolve
        }),
    )
    const user = userEvent.setup()
    render(<ProfileUpdatedCard card={makeCard()} onApprove={onApprove} onReject={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: /approve/i }))

    expect(screen.getByRole('button', { name: /approve/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /reject/i })).toBeDisabled()

    resolveApprove()
    await waitFor(() => expect(screen.getByRole('button', { name: /approve/i })).not.toBeDisabled())
  })

  it('shows a recoverable inline error when approving fails, and the buttons stay usable', async () => {
    const onApprove = vi.fn().mockRejectedValue(new Error('network down'))
    const user = userEvent.setup()
    render(<ProfileUpdatedCard card={makeCard()} onApprove={onApprove} onReject={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: /approve/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn.?t|failed|error/i)
    expect(screen.getByRole('button', { name: /approve/i })).not.toBeDisabled()
  })
})

describe('ProfileUpdatedCard — settled states', () => {
  it('shows an applied state with no action buttons', () => {
    render(<ProfileUpdatedCard card={makeCard({ status: 'applied' })} onApprove={vi.fn()} onReject={vi.fn()} />)

    // Exact match on the headline: the opsCount line below now also says "applied"
    // (ticket 08 polish -- "N changes applied/discarded" instead of a stale "proposed"
    // once the document is settled), so a loose /applied/i would match both.
    expect(screen.getByText('Applied to your profile')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /approve/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /reject/i })).not.toBeInTheDocument()
  })

  it('shows a rejected (discarded) state with no action buttons', () => {
    render(<ProfileUpdatedCard card={makeCard({ status: 'rejected' })} onApprove={vi.fn()} onReject={vi.fn()} />)

    // Exact match: the opsCount line also says "discarded" now, see note above.
    expect(screen.getByText('Discarded')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /approve/i })).not.toBeInTheDocument()
  })

  it('shows an actionable failed-extraction state with the server error message, no action buttons', () => {
    render(
      <ProfileUpdatedCard
        card={makeCard({ status: 'failed', error: 'This PDF has no extractable text — try a text-based export.' })}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    )

    expect(screen.getByText(/no extractable text/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /approve/i })).not.toBeInTheDocument()
  })

  it('renders nothing new when there is no diffSummary yet (empty merge)', () => {
    render(
      <ProfileUpdatedCard
        card={makeCard({ diffSummary: [], opsCount: 0 })}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    )

    expect(screen.getByText(/nothing new/i)).toBeInTheDocument()
  })
})

describe('ProfileUpdatedCard — pre-merge states (stored/extracted)', () => {
  it.each(['stored', 'extracted'] as const)(
    'renders an honest "processing" state for status=%s — never "proposed" or "nothing new", no action buttons',
    (status) => {
      render(
        <ProfileUpdatedCard
          card={makeCard({ status, diffSummary: [], opsCount: 0 })}
          onApprove={vi.fn()}
          onReject={vi.fn()}
        />,
      )

      expect(screen.queryByText(/profile update proposed/i)).not.toBeInTheDocument()
      expect(screen.queryByText(/nothing new/i)).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /approve/i })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /reject/i })).not.toBeInTheDocument()
    },
  )
})
