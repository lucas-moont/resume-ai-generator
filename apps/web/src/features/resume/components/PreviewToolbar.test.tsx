import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { PreviewToolbar } from './PreviewToolbar'
import { useResumeStore } from '../store/resumeStore'
import { useEditModeStore } from '../store/editModeStore'
import { useChatStore } from '../../chat/store/chatStore'
import { makeResume } from '../../../test/factories'

function reset(resumeOverrides: Record<string, unknown> | null = {}) {
  useResumeStore.setState({
    resume: resumeOverrides ? makeResume(resumeOverrides) : null,
    validationIssues: [],
  })
  useResumeStore.temporal.getState().clear()
  useEditModeStore.setState({ isEditing: false })
  useChatStore.setState({ streaming: null, pendingTranslation: null })
}

describe('PreviewToolbar — pencil toggle', () => {
  beforeEach(() => reset())

  it('toggles edit mode on click', async () => {
    const user = userEvent.setup()
    render(<PreviewToolbar />)

    const toggle = screen.getByRole('button', { name: /edit/i })
    expect(useEditModeStore.getState().isEditing).toBe(false)

    await user.click(toggle)
    expect(useEditModeStore.getState().isEditing).toBe(true)

    await user.click(toggle)
    expect(useEditModeStore.getState().isEditing).toBe(false)
  })

  it('is disabled with an explanatory tooltip while a response is streaming', () => {
    useChatStore.setState({
      streaming: { status: 'streaming', step: 'calling_ai', progress: 40, message: 'Thinking…' },
    })
    render(<PreviewToolbar />)

    const toggle = screen.getByRole('button', { name: /edit/i })
    expect(toggle).toBeDisabled()
    expect(toggle).toHaveAttribute('title', expect.stringMatching(/streaming/i))
  })

  it('re-enables once streaming finishes', () => {
    useChatStore.setState({
      streaming: { status: 'streaming', step: 'calling_ai', progress: 40, message: 'Thinking…' },
    })
    const { rerender } = render(<PreviewToolbar />)
    expect(screen.getByRole('button', { name: /edit/i })).toBeDisabled()

    useChatStore.setState({ streaming: null })
    rerender(<PreviewToolbar />)
    expect(screen.getByRole('button', { name: /edit/i })).not.toBeDisabled()
  })
})

describe('PreviewToolbar — undo/redo', () => {
  beforeEach(() => reset())

  it('disables both buttons when there is no history', () => {
    render(<PreviewToolbar />)
    expect(screen.getByRole('button', { name: /undo/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /redo/i })).toBeDisabled()
  })

  it('undo reverts the last resume change; redo brings it back', async () => {
    const user = userEvent.setup()
    render(<PreviewToolbar />)

    act(() => {
      useResumeStore.getState().setResume(makeResume({ fullName: 'Ada Lovelace' }))
      useResumeStore.getState().setResume(makeResume({ fullName: 'Grace Hopper' }))
    })

    const undoButton = screen.getByRole('button', { name: /undo/i })
    expect(undoButton).not.toBeDisabled()
    await user.click(undoButton)
    expect(useResumeStore.getState().resume?.fullName).toBe('Ada Lovelace')

    const redoButton = screen.getByRole('button', { name: /redo/i })
    expect(redoButton).not.toBeDisabled()
    await user.click(redoButton)
    expect(useResumeStore.getState().resume?.fullName).toBe('Grace Hopper')
  })
})

describe('PreviewToolbar — non-blocking validation warning', () => {
  it('shows nothing when there are no validation issues', () => {
    reset({ fullName: 'Ada Lovelace' })
    render(<PreviewToolbar />)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('shows a discreet warning when the resume has validation issues, without hiding the resume', () => {
    reset(null)
    useResumeStore.getState().setResume(makeResume({ fullName: '' }))
    render(<PreviewToolbar />)

    expect(screen.getByRole('status')).toBeInTheDocument()
    // Non-blocking: the (invalid) resume is still there.
    expect(useResumeStore.getState().resume?.fullName).toBe('')
  })
})

describe('PreviewToolbar — language picker', () => {
  it('reflects the document\'s own language, not a request preference', () => {
    reset({ locale: 'en' })
    render(<PreviewToolbar />)
    expect(screen.getByRole('combobox', { name: /idioma/i })).toHaveValue('en')
  })

  it('shows Portuguese for a pt-BR document', () => {
    reset({ locale: 'pt-BR' })
    render(<PreviewToolbar />)
    expect(screen.getByRole('combobox', { name: /idioma/i })).toHaveValue('pt-BR')
  })

  it('switching the language queues a translation for that locale', async () => {
    const user = userEvent.setup()
    reset({ locale: 'pt-BR' })
    render(<PreviewToolbar />)

    await user.selectOptions(screen.getByRole('combobox', { name: /idioma/i }), 'en')

    expect(useChatStore.getState().pendingTranslation).toBe('en')
  })

  it('has no language picker before a resume exists (language is chosen at approval instead)', () => {
    reset(null)
    render(<PreviewToolbar />)
    expect(screen.queryByRole('combobox', { name: /idioma/i })).not.toBeInTheDocument()
  })
})
