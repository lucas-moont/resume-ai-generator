import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ProposalCard } from './ProposalCard'
import { useChatStore, type ProposalCard as ProposalCardData } from '../../store/chatStore'
import { useResumeStore } from '../../../resume/store/resumeStore'

function makeCard(overrides: Partial<ProposalCardData> = {}): ProposalCardData {
  return { type: 'proposal', proposalId: 1, status: 'proposed', revision: 1, itemsCount: 3, ...overrides }
}

beforeEach(() => {
  useChatStore.getState().reset()
  useResumeStore.getState().setLocale('auto')
})

describe('ProposalCard', () => {
  it('shows the approve button when it is the latest pending proposal', () => {
    render(<ProposalCard card={makeCard()} showApproveButton onApprove={vi.fn()} />)
    expect(screen.getByRole('button', { name: /aprovar e gerar/i })).toBeInTheDocument()
  })

  it('hides the approve button when showApproveButton is false', () => {
    render(<ProposalCard card={makeCard()} showApproveButton={false} onApprove={vi.fn()} />)
    expect(screen.queryByRole('button', { name: /aprovar e gerar/i })).not.toBeInTheDocument()
  })

  it('calls onApprove when the button is clicked', async () => {
    const onApprove = vi.fn()
    const user = userEvent.setup()
    render(<ProposalCard card={makeCard()} showApproveButton onApprove={onApprove} />)

    await user.click(screen.getByRole('button', { name: /aprovar e gerar/i }))

    expect(onApprove).toHaveBeenCalledTimes(1)
  })

  it('disables the approve button while a turn is streaming', () => {
    useChatStore.getState().updateStreaming({ step: 'preparing_context', progress: 10, message: '' })
    render(<ProposalCard card={makeCard()} showApproveButton onApprove={vi.fn()} />)

    expect(screen.getByRole('button', { name: /aprovar e gerar/i })).toBeDisabled()
  })

  it('never renders the button for an approved card, even if the caller passes showApproveButton', () => {
    render(<ProposalCard card={makeCard({ status: 'approved' })} showApproveButton onApprove={vi.fn()} />)

    expect(screen.getByText(/aplicada — currículo gerado/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /aprovar e gerar/i })).not.toBeInTheDocument()
  })

  it('never renders the button for a superseded card, even if the caller passes showApproveButton', () => {
    render(<ProposalCard card={makeCard({ status: 'superseded' })} showApproveButton onApprove={vi.fn()} />)

    expect(screen.getByText(/substituída/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /aprovar e gerar/i })).not.toBeInTheDocument()
  })

  it('pre-fills the language picker with the proposal\'s detected locale', () => {
    // The approval step confirms "Vou gerar em [...]", pre-filled with the language detected
    // from the posting, so an English-title/Portuguese-body posting stops silently generating
    // in the wrong language.
    render(<ProposalCard card={makeCard({ detectedLocale: 'en' })} showApproveButton onApprove={vi.fn()} />)
    expect(screen.getByRole('combobox', { name: /idioma/i })).toHaveValue('en')
  })

  it('writes the chosen language to the resume store so the approve turn generates in it', async () => {
    const user = userEvent.setup()
    render(<ProposalCard card={makeCard({ detectedLocale: 'pt-BR' })} showApproveButton onApprove={vi.fn()} />)

    await user.selectOptions(screen.getByRole('combobox', { name: /idioma/i }), 'en')

    expect(useResumeStore.getState().locale).toBe('en')
  })

  it('has no language picker when the approve button is hidden', () => {
    render(<ProposalCard card={makeCard({ detectedLocale: 'en' })} showApproveButton={false} onApprove={vi.fn()} />)
    expect(screen.queryByRole('combobox', { name: /idioma/i })).not.toBeInTheDocument()
  })

  it('shows the revision number only when revision > 1', () => {
    const { rerender } = render(
      <ProposalCard card={makeCard({ revision: 1 })} showApproveButton={false} onApprove={vi.fn()} />,
    )
    expect(screen.queryByText(/revisão/i)).not.toBeInTheDocument()

    rerender(<ProposalCard card={makeCard({ revision: 3 })} showApproveButton={false} onApprove={vi.fn()} />)
    expect(screen.getByText(/revisão 3/i)).toBeInTheDocument()
  })
})
