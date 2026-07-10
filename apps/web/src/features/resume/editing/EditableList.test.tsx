import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { ListAddButton, ListRemoveButton } from './EditableList'
import { useResumeStore } from '../store/resumeStore'
import { makeResume } from '../../../test/factories'

function resetStore(overrides = {}) {
  useResumeStore.setState({ resume: makeResume(overrides), validationIssues: [] })
  useResumeStore.temporal.getState().clear()
}

describe('ListAddButton', () => {
  beforeEach(() => resetStore({ skills: ['TypeScript'] }))

  it('renders nothing when not editable', () => {
    render(<ListAddButton path="skills" label="Add skill" editable={false} />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('renders a labeled, no-print button when editable', () => {
    render(<ListAddButton path="skills" label="Add skill" editable />)
    const button = screen.getByRole('button', { name: 'Add skill' })
    expect(button).toHaveClass('no-print')
  })

  it('appends an item to the target list on click', async () => {
    const user = userEvent.setup()
    render(<ListAddButton path="skills" label="Add skill" editable />)

    await user.click(screen.getByRole('button', { name: 'Add skill' }))

    expect(useResumeStore.getState().resume?.skills).toEqual(['TypeScript', ''])
  })

  it('is a no-op if there is no active resume', async () => {
    useResumeStore.setState({ resume: null })
    const user = userEvent.setup()
    render(<ListAddButton path="skills" label="Add skill" editable />)

    await user.click(screen.getByRole('button', { name: 'Add skill' }))

    expect(useResumeStore.getState().resume).toBeNull()
  })
})

describe('ListRemoveButton', () => {
  beforeEach(() => resetStore({ skills: ['TypeScript', 'Python'] }))

  it('renders nothing when not editable', () => {
    render(<ListRemoveButton path="skills" index={0} label="Remove skill" editable={false} />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('renders a labeled, no-print button when editable', () => {
    render(<ListRemoveButton path="skills" index={0} label="Remove skill" editable />)
    const button = screen.getByRole('button', { name: 'Remove skill' })
    expect(button).toHaveClass('no-print')
  })

  it('removes the item at the given index on click', async () => {
    const user = userEvent.setup()
    render(<ListRemoveButton path="skills" index={0} label="Remove skill" editable />)

    await user.click(screen.getByRole('button', { name: 'Remove skill' }))

    expect(useResumeStore.getState().resume?.skills).toEqual(['Python'])
  })
})
