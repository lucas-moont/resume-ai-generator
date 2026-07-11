import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AssistantMessage } from './AssistantMessage'
import { useChatStore, type ChatMessage } from '../store/chatStore'

function makeMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: 'msg_1',
    role: 'assistant',
    content: 'Hello',
    createdAt: Date.now(),
    ...overrides,
  }
}

function renderMessage(message: ChatMessage, overrides: Partial<Parameters<typeof AssistantMessage>[0]> = {}) {
  return render(
    <AssistantMessage
      message={message}
      onRetry={vi.fn()}
      onApproveDocument={vi.fn()}
      onRejectDocument={vi.fn()}
      onApproveProposal={vi.fn()}
      isLatestPendingProposal={false}
      {...overrides}
    />,
  )
}

let matchMediaSpy: ReturnType<typeof vi.spyOn> | undefined

function mockReducedMotion(matches: boolean) {
  matchMediaSpy = vi.spyOn(window, 'matchMedia').mockImplementation((query: string) => ({
    matches,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }))
}

beforeEach(() => {
  useChatStore.getState().reset()
})

afterEach(() => {
  matchMediaSpy?.mockRestore()
  matchMediaSpy = undefined
  vi.useRealTimers()
})

describe('AssistantMessage — progressive reveal', () => {
  it('renders full content immediately for a message with no animate flag (rehydration)', () => {
    renderMessage(makeMessage({ content: 'Line one\nLine two', animate: undefined }))
    expect(screen.getByText(/line one/i)).toBeInTheDocument()
    expect(screen.getByText(/line two/i)).toBeInTheDocument()
  })

  it('reveals an animated message line by line rather than all at once', () => {
    vi.useFakeTimers()
    renderMessage(makeMessage({ content: 'Line one\nLine two\nLine three', animate: true }))

    // Nothing revealed yet on first paint.
    expect(screen.queryByText(/line one/i)).not.toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(90)
    })
    expect(screen.getByText(/line one/i)).toBeInTheDocument()
    expect(screen.queryByText(/line two/i)).not.toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(180)
    })
    expect(screen.getByText(/line two/i)).toBeInTheDocument()
    expect(screen.getByText(/line three/i)).toBeInTheDocument()
  })

  it('respects prefers-reduced-motion by rendering the full content immediately, even when animate is true', () => {
    mockReducedMotion(true)
    renderMessage(makeMessage({ content: 'Line one\nLine two', animate: true }))

    expect(screen.getByText(/line one/i)).toBeInTheDocument()
    expect(screen.getByText(/line two/i)).toBeInTheDocument()
  })
})

describe('AssistantMessage — proposal card dispatch', () => {
  it('renders a ProposalCard for a proposal card, wired to onApproveProposal and isLatestPendingProposal', async () => {
    const onApproveProposal = vi.fn()
    renderMessage(
      makeMessage({
        card: { type: 'proposal', proposalId: 11, status: 'proposed', revision: 1, itemsCount: 3 },
      }),
      { onApproveProposal, isLatestPendingProposal: true },
    )

    const button = screen.getByRole('button', { name: /aprovar e gerar/i })
    button.click()
    expect(onApproveProposal).toHaveBeenCalledTimes(1)
  })

  it('does not render the approve button when isLatestPendingProposal is false', () => {
    renderMessage(
      makeMessage({
        card: { type: 'proposal', proposalId: 11, status: 'proposed', revision: 1, itemsCount: 3 },
      }),
      { isLatestPendingProposal: false },
    )

    expect(screen.queryByRole('button', { name: /aprovar e gerar/i })).not.toBeInTheDocument()
  })
})
