import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useRef, useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { Dialog } from './Dialog'

describe('Dialog', () => {
  it('renders nothing when closed', () => {
    render(
      <Dialog open={false} onClose={vi.fn()} title="Untitled">
        <p>content</p>
      </Dialog>,
    )
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('renders with role=dialog, aria-modal, and an accessible name from the title', () => {
    render(
      <Dialog open onClose={vi.fn()} title="Delete this chat?">
        <p>This can't be undone.</p>
      </Dialog>,
    )
    const dialog = screen.getByRole('dialog', { name: 'Delete this chat?' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(screen.getByText("This can't be undone.")).toBeInTheDocument()
  })

  it('closes on Escape', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(
      <Dialog open onClose={onClose} title="Delete this chat?">
        <button type="button">Confirm</button>
      </Dialog>,
    )

    await user.keyboard('{Escape}')

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('Escape still closes when an inner element stops propagation on keydown', async () => {
    const onClose = vi.fn()
    function StopPropagationChild() {
      return (
        <button type="button" onKeyDown={(e) => e.stopPropagation()}>
          Inner
        </button>
      )
    }
    render(
      <Dialog open onClose={onClose} title="Confirm">
        <StopPropagationChild />
      </Dialog>,
    )
    const inner = screen.getByRole('button', { name: 'Inner' })
    inner.focus()
    await userEvent.setup().keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('traps Tab focus inside the dialog, cycling from the last to the first focusable element', async () => {
    const user = userEvent.setup()
    render(
      <Dialog open onClose={vi.fn()} title="Pick one">
        <button type="button">First</button>
        <button type="button">Last</button>
      </Dialog>,
    )

    const first = screen.getByRole('button', { name: 'First' })
    const last = screen.getByRole('button', { name: 'Last' })

    expect(first).toHaveFocus()

    await user.tab()
    expect(last).toHaveFocus()

    await user.tab()
    expect(first).toHaveFocus()

    await user.tab({ shift: true })
    expect(last).toHaveFocus()
  })

  it('returns focus to the triggering element when it closes', async () => {
    const user = userEvent.setup()

    function Harness() {
      const [open, setOpen] = useState(false)
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open
          </button>
          <Dialog open={open} onClose={() => setOpen(false)} title="Confirm">
            <button type="button" onClick={() => setOpen(false)}>
              Close
            </button>
          </Dialog>
        </>
      )
    }

    render(<Harness />)

    const trigger = screen.getByRole('button', { name: 'Open' })
    trigger.focus()
    await user.click(trigger)

    await user.click(screen.getByRole('button', { name: 'Close' }))

    expect(trigger).toHaveFocus()
  })

  it('locks page scroll while open and restores it on close', () => {
    const { rerender } = render(
      <Dialog open onClose={vi.fn()} title="Confirm">
        <p>content</p>
      </Dialog>,
    )
    expect(document.body.style.overflow).toBe('hidden')

    rerender(
      <Dialog open={false} onClose={vi.fn()} title="Confirm">
        <p>content</p>
      </Dialog>,
    )
    expect(document.body.style.overflow).not.toBe('hidden')
  })

  it('wires a provided description into aria-describedby', () => {
    render(
      <Dialog open onClose={vi.fn()} title="Delete this chat?" description="This can't be undone.">
        <button type="button">Confirm</button>
      </Dialog>,
    )
    const dialog = screen.getByRole('dialog', { name: 'Delete this chat?' })
    expect(dialog).toHaveAccessibleDescription("This can't be undone.")
  })

  it('has no accessible description when none is provided', () => {
    render(
      <Dialog open onClose={vi.fn()} title="Pick one">
        <button type="button">OK</button>
      </Dialog>,
    )
    expect(screen.getByRole('dialog')).not.toHaveAccessibleDescription()
  })

  it('focuses the given initialFocusRef element instead of the first focusable one', () => {
    function Harness() {
      const cancelRef = useRef<HTMLButtonElement>(null)
      return (
        <Dialog open onClose={vi.fn()} title="Confirm" initialFocusRef={cancelRef}>
          <button type="button">Delete</button>
          <button type="button" ref={cancelRef}>
            Cancel
          </button>
        </Dialog>
      )
    }
    render(<Harness />)

    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus()
  })
})
