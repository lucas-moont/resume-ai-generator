import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MessageList } from './MessageList'
import { useChatStore } from '../store/chatStore'

function renderMessageList(overrides: Partial<Parameters<typeof MessageList>[0]> = {}) {
  return render(
    <MessageList
      onRetry={vi.fn()}
      onSuggestion={vi.fn()}
      onApproveDocument={vi.fn()}
      onRejectDocument={vi.fn()}
      onApproveProposal={vi.fn()}
      {...overrides}
    />,
  )
}

beforeEach(() => {
  useChatStore.getState().reset()
})

function mockScrollMetrics(el: HTMLElement, { scrollHeight, clientHeight, scrollTop }: {
  scrollHeight: number
  clientHeight: number
  scrollTop: number
}) {
  Object.defineProperty(el, 'scrollHeight', { value: scrollHeight, configurable: true })
  Object.defineProperty(el, 'clientHeight', { value: clientHeight, configurable: true })
  Object.defineProperty(el, 'scrollTop', { value: scrollTop, writable: true, configurable: true })
}

describe('MessageList', () => {
  it('shows the empty state when there are no messages and nothing is streaming', () => {
    renderMessageList()
    expect(screen.getByText(/let's build your resume/i)).toBeInTheDocument()
  })

  it('renders user and assistant messages in order', () => {
    useChatStore.getState().appendUserMessage('Hello')
    useChatStore.getState().appendAssistantMessage('Hi there')

    renderMessageList()

    expect(screen.getByText('Hello')).toBeInTheDocument()
    expect(screen.getByText('Hi there')).toBeInTheDocument()
  })

  it('renders a ProfileUpdatedCard for an assistant message carrying one, wired to the approve/reject callbacks', async () => {
    const onApproveDocument = vi.fn().mockResolvedValue(undefined)
    useChatStore.getState().appendAssistantMessage('Uploaded profile.json', {
      type: 'profileUpdated',
      documentId: 7,
      filename: 'profile.json',
      status: 'proposed',
      diffSummary: ['1 new skill'],
      opsCount: 1,
    })

    renderMessageList({ onApproveDocument })

    const approveButton = screen.getByRole('button', { name: /approve/i })
    approveButton.click()

    await act(async () => {
      await Promise.resolve()
    })
    expect(onApproveDocument).toHaveBeenCalledWith(7, expect.any(String))
  })

  it('renders a ProfileUpdateAppliedCard for an assistant message carrying one (chat profile_update, no action buttons)', () => {
    useChatStore.getState().appendAssistantMessage('Updated your profile.', {
      type: 'profileUpdateApplied',
      profileVersion: 3,
      summary: 'Updated phone number.',
    })

    renderMessageList()

    expect(screen.getByText(/version 3/i)).toBeInTheDocument()
    expect(screen.getByText(/updated phone number\./i)).toBeInTheDocument()
  })

  it('auto-scrolls to the bottom when pinned and a new message arrives', () => {
    useChatStore.getState().appendUserMessage('first')
    const { rerender } = renderMessageList()

    const scrollEl = screen.getByTestId('message-list-scroll')
    mockScrollMetrics(scrollEl, { scrollHeight: 1000, clientHeight: 400, scrollTop: 0 })
    // Near the bottom already (default pinned state) -> a scroll event confirms it.
    Object.defineProperty(scrollEl, 'scrollTop', { value: 620, writable: true, configurable: true })
    fireEvent.scroll(scrollEl)

    act(() => {
      useChatStore.getState().appendAssistantMessage('second')
    })
    rerender(
      <MessageList
        onRetry={vi.fn()}
        onSuggestion={vi.fn()}
        onApproveDocument={vi.fn()}
        onRejectDocument={vi.fn()}
        onApproveProposal={vi.fn()}
      />,
    )

    expect(scrollEl.scrollTop).toBe(1000) // scrolled to scrollHeight
  })

  it('does NOT force-scroll when the user has scrolled up to read history', () => {
    useChatStore.getState().appendUserMessage('first')
    const { rerender } = renderMessageList()

    const scrollEl = screen.getByTestId('message-list-scroll')
    mockScrollMetrics(scrollEl, { scrollHeight: 1000, clientHeight: 400, scrollTop: 0 })
    // Far from the bottom (distance = 1000 - 0 - 400 = 600 > threshold).
    fireEvent.scroll(scrollEl)

    act(() => {
      useChatStore.getState().appendAssistantMessage('second')
    })
    rerender(
      <MessageList
        onRetry={vi.fn()}
        onSuggestion={vi.fn()}
        onApproveDocument={vi.fn()}
        onRejectDocument={vi.fn()}
        onApproveProposal={vi.fn()}
      />,
    )

    expect(scrollEl.scrollTop).toBe(0) // untouched — no forced scroll
  })
})

describe('MessageList — Improvement Proposal card + button rule (v4, F4)', () => {
  it('shows the approve button only on the latest message whose card matches the pending proposal', () => {
    useChatStore.getState().appendAssistantMessage('Here are my suggestions.', {
      type: 'proposal',
      proposalId: 11,
      status: 'proposed',
      revision: 1,
      itemsCount: 3,
    })
    useChatStore.getState().appendAssistantMessage('Ajustei a proposta.', {
      type: 'proposal',
      proposalId: 11,
      status: 'proposed',
      revision: 2,
      itemsCount: 3,
    })
    useChatStore.getState().setPendingProposalId(11)

    renderMessageList()

    expect(screen.getAllByRole('button', { name: /aprovar e gerar/i })).toHaveLength(1)
    expect(screen.getByText(/revisão 2/i)).toBeInTheDocument()
  })

  it('renders no approve button once the pending proposal has been approved', () => {
    useChatStore.getState().appendAssistantMessage('Here are my suggestions.', {
      type: 'proposal',
      proposalId: 11,
      status: 'approved',
      revision: 1,
      itemsCount: 3,
    })
    useChatStore.getState().setPendingProposalId(null)

    renderMessageList()

    expect(screen.queryByRole('button', { name: /aprovar e gerar/i })).not.toBeInTheDocument()
    expect(screen.getByText(/aplicada — currículo gerado/i)).toBeInTheDocument()
  })

  it('clicking the approve button invokes onApproveProposal', () => {
    useChatStore.getState().appendAssistantMessage('Here are my suggestions.', {
      type: 'proposal',
      proposalId: 11,
      status: 'proposed',
      revision: 1,
      itemsCount: 3,
    })
    useChatStore.getState().setPendingProposalId(11)
    const onApproveProposal = vi.fn()

    renderMessageList({ onApproveProposal })
    screen.getByRole('button', { name: /aprovar e gerar/i }).click()

    expect(onApproveProposal).toHaveBeenCalledTimes(1)
  })
})

describe('MessageList — analyzing_job typing indicator (v4, F4)', () => {
  it('shows a typing indicator instead of ProgressCard while streaming.step is analyzing_job', () => {
    useChatStore.getState().updateStreaming({ step: 'analyzing_job', progress: 20, message: '' })

    renderMessageList()

    expect(screen.getByRole('status', { name: /digitando/i })).toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })

  it('keeps ProgressCard (with its progressbar) for generation steps', () => {
    useChatStore.getState().updateStreaming({ step: 'calling_ai', progress: 40, message: '' })

    renderMessageList()

    expect(screen.getByRole('progressbar')).toBeInTheDocument()
    expect(screen.queryByRole('status', { name: /digitando/i })).not.toBeInTheDocument()
  })

  it('shows the typing indicator (not ProgressCard) during the pre-first-stage window, before any real step is known (design gate P3)', () => {
    // Mirrors useChatStream's optimistic updateStreaming() call, which sets progress/message
    // but leaves `step` unset — the real first step (analyzing_job vs. preparing_context)
    // isn't known until the server's first `stage` event arrives.
    useChatStore.getState().updateStreaming({ progress: 5, message: 'Starting…' })

    renderMessageList()

    expect(screen.getByRole('status', { name: /digitando/i })).toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })
})
