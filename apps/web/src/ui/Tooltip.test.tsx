import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Tooltip } from './Tooltip'

describe('Tooltip', () => {
  it('shows the tip on focus and hides it on blur', async () => {
    const user = userEvent.setup()
    render(
      <>
        <Tooltip label="Undo (Ctrl+Z)">
          <button type="button" aria-label="Undo">
            ↶
          </button>
        </Tooltip>
        <button type="button">elsewhere</button>
      </>,
    )

    expect(screen.queryByText('Undo (Ctrl+Z)')).not.toBeInTheDocument()

    await user.tab() // focus the Undo trigger
    expect(screen.getByRole('button', { name: 'Undo' })).toHaveFocus()
    expect(screen.getByText('Undo (Ctrl+Z)')).toBeInTheDocument()

    await user.tab() // move focus away
    expect(screen.queryByText('Undo (Ctrl+Z)')).not.toBeInTheDocument()
  })

  it('shows on hover after a short delay and hides on mouse leave', async () => {
    const user = userEvent.setup()
    render(
      <Tooltip label="Settings">
        <button type="button" aria-label="Settings">
          ⚙
        </button>
      </Tooltip>,
    )

    const trigger = screen.getByRole('button', { name: 'Settings' })
    await user.hover(trigger)
    // Not immediate — a hover has a small reveal delay.
    expect(screen.queryByText('Settings')).not.toBeInTheDocument()
    expect(await screen.findByText('Settings')).toBeInTheDocument()

    await user.unhover(trigger)
    expect(screen.queryByText('Settings')).not.toBeInTheDocument()
  })

  it('keeps the trigger keyboard-accessible via aria-label and preserves its onClick', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    render(
      <Tooltip label="Remove document">
        <button type="button" aria-label="Remove" onClick={onClick}>
          ✕
        </button>
      </Tooltip>,
    )

    await user.click(screen.getByRole('button', { name: 'Remove' }))
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('marks the tip aria-hidden so it does not double-announce the labelled control', async () => {
    const user = userEvent.setup()
    render(
      <Tooltip label="Settings">
        <button type="button" aria-label="Settings">
          ⚙
        </button>
      </Tooltip>,
    )

    await user.tab()
    expect(screen.getByText('Settings')).toHaveAttribute('aria-hidden', 'true')
  })
})
