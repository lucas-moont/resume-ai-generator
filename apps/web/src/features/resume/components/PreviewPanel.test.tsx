import { act, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { PreviewPanel } from './PreviewPanel'
import { useResumeStore } from '../store/resumeStore'
import { useEditModeStore } from '../store/editModeStore'
import { useChatStore } from '../../chat/store/chatStore'
import { makeResume } from '../../../test/factories'

describe('PreviewPanel — threads editModeStore into ResumePreview', () => {
  beforeEach(() => {
    useResumeStore.setState({ resume: makeResume(), validationIssues: [] })
    useResumeStore.temporal.getState().clear()
    useEditModeStore.setState({ isEditing: false })
    useChatStore.setState({ streaming: null })
  })

  it('renders read-only when edit mode is off', () => {
    render(<PreviewPanel />)
    expect(screen.getByText('Ada Lovelace')).not.toHaveAttribute('contenteditable')
  })

  it('renders contenteditable fields once edit mode is toggled on', () => {
    render(<PreviewPanel />)

    act(() => {
      useEditModeStore.getState().toggle()
    })

    expect(screen.getByText('Ada Lovelace')).toHaveAttribute('contenteditable', 'true')
  })
})
