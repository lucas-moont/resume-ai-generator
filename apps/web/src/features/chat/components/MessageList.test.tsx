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
    rerender(<MessageList onRetry={vi.fn()} onSuggestion={vi.fn()} onApproveDocument={vi.fn()} onRejectDocument={vi.fn()} />)

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
    rerender(<MessageList onRetry={vi.fn()} onSuggestion={vi.fn()} onApproveDocument={vi.fn()} onRejectDocument={vi.fn()} />)

    expect(scrollEl.scrollTop).toBe(0) // untouched — no forced scroll
  })
})
