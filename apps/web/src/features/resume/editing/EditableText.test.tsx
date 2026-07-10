import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { EditableText } from './EditableText'
import { useResumeStore } from '../store/resumeStore'
import { makeResume } from '../../../test/factories'

function resetStore() {
  useResumeStore.setState({ resume: makeResume(), validationIssues: [] })
  useResumeStore.temporal.getState().clear()
}

describe('EditableText — read-only mode (editable=false)', () => {
  beforeEach(resetStore)

  it('renders plain text without a contenteditable attribute', () => {
    render(<EditableText path="fullName" value="Ada Lovelace" mode="plain" editable={false} />)
    const node = screen.getByText('Ada Lovelace')
    expect(node).not.toHaveAttribute('contenteditable')
  })

  it('renders rich content sanitized, without a contenteditable attribute', () => {
    render(
      <EditableText
        path="headline"
        value='<strong>Bold</strong><script>alert(1)</script>'
        mode="rich"
        as="p"
        editable={false}
      />,
    )
    const node = screen.getByText('Bold', { selector: 'strong' })
    expect(node.parentElement).not.toHaveAttribute('contenteditable')
    expect(node.parentElement?.innerHTML).toBe('<strong>Bold</strong>')
  })
})

describe('EditableText — editable mode', () => {
  beforeEach(resetStore)

  it('renders a contenteditable node', () => {
    render(<EditableText path="fullName" value="Ada Lovelace" mode="plain" editable />)
    const node = screen.getByText('Ada Lovelace')
    expect(node).toHaveAttribute('contenteditable', 'true')
  })

  it('syncs DOM content from the value prop on mount', () => {
    render(<EditableText path="fullName" value="Ada Lovelace" mode="plain" editable />)
    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument()
  })

  it('skips resync while the node has real focus (anti-caret-jump gate)', () => {
    const { rerender } = render(<EditableText path="fullName" value="Ada Lovelace" mode="plain" editable />)
    const node = screen.getByText('Ada Lovelace')

    act(() => {
      node.focus()
      node.textContent = 'Ada Lovelace is typing'
    })
    expect(document.activeElement).toBe(node)

    // An external update (e.g. an SSE resume event) arrives while focused —
    // the gated effect must leave the in-progress edit alone.
    rerender(<EditableText path="fullName" value="Someone Else Entirely" mode="plain" editable />)

    expect(node.textContent).toBe('Ada Lovelace is typing')
  })

  it('resyncs immediately when the node is NOT focused', () => {
    const { rerender } = render(<EditableText path="fullName" value="Ada Lovelace" mode="plain" editable />)
    rerender(<EditableText path="fullName" value="Grace Hopper" mode="plain" editable />)
    expect(screen.getByText('Grace Hopper')).toBeInTheDocument()
  })

  it('commits on blur (plain field), writing through fieldPaths into the store', () => {
    render(<EditableText path="fullName" value="Ada Lovelace" mode="plain" editable />)
    const node = screen.getByText('Ada Lovelace')

    act(() => {
      node.textContent = 'Grace Hopper'
      fireEvent.blur(node)
    })

    expect(useResumeStore.getState().resume?.fullName).toBe('Grace Hopper')
  })

  it('commits on blur (rich field), sanitizing innerHTML through the shared allowlist', () => {
    render(<EditableText path="headline" value="Engineer" mode="rich" as="p" editable />)
    const node = screen.getByText('Engineer')

    act(() => {
      node.innerHTML = '<strong>Staff</strong> <script>alert(1)</script>Engineer'
      fireEvent.blur(node)
    })

    expect(useResumeStore.getState().resume?.headline).toBe('<strong>Staff</strong> Engineer')
  })

  it('does not commit (no-op) when the content is unchanged at blur time', () => {
    render(<EditableText path="fullName" value="Ada Lovelace" mode="plain" editable />)
    const node = screen.getByText('Ada Lovelace')
    const before = useResumeStore.getState().resume

    act(() => {
      fireEvent.blur(node)
    })

    expect(useResumeStore.getState().resume).toBe(before)
  })

  it('Enter commits a plain field by blurring it (does not insert a newline)', () => {
    render(<EditableText path="fullName" value="Ada Lovelace" mode="plain" editable />)
    const node = screen.getByText('Ada Lovelace')
    node.focus()

    act(() => {
      node.textContent = 'Grace Hopper'
      fireEvent.keyDown(node, { key: 'Enter' })
    })

    expect(document.activeElement).not.toBe(node)
    expect(useResumeStore.getState().resume?.fullName).toBe('Grace Hopper')
  })

  it('Enter does NOT blur a rich field (multi-line content is allowed)', () => {
    render(<EditableText path="headline" value="Engineer" mode="rich" as="p" editable />)
    const node = screen.getByText('Engineer')
    node.focus()

    fireEvent.keyDown(node, { key: 'Enter' })

    expect(document.activeElement).toBe(node)
  })

  it('sanitizes pasted rich HTML before inserting it (keeps only the allowlist)', () => {
    document.execCommand = vi.fn()
    render(<EditableText path="headline" value="Engineer" mode="rich" as="p" editable />)
    const node = screen.getByText('Engineer')

    fireEvent.paste(node, {
      clipboardData: {
        getData: (type: string) => (type === 'text/html' ? '<b>bold</b><script>alert(1)</script>' : ''),
      },
    })

    expect(document.execCommand).toHaveBeenCalledWith('insertHTML', false, '<b>bold</b>')
  })

  it('strips all markup from pasted plain text', () => {
    document.execCommand = vi.fn()
    render(<EditableText path="fullName" value="Ada Lovelace" mode="plain" editable />)
    const node = screen.getByText('Ada Lovelace')

    fireEvent.paste(node, {
      clipboardData: {
        getData: (type: string) => (type === 'text/plain' ? '<b>Grace</b>' : ''),
      },
    })

    expect(document.execCommand).toHaveBeenCalledWith('insertText', false, 'Grace')
  })
})
