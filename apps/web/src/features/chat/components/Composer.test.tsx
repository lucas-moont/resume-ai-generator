import { fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Composer } from './Composer'
import { renderApp } from '../../../test/render'
import type { UploadAttachment } from '../../upload/useFileUpload'

function makeAttachment(overrides: Partial<UploadAttachment> = {}): UploadAttachment {
  return {
    id: 'att_1',
    file: new File(['{}'], 'profile.json'),
    status: 'uploading',
    progress: 10,
    ...overrides,
  }
}

function renderComposer(overrides: Partial<Parameters<typeof Composer>[0]> = {}) {
  return renderApp(
    <Composer
      draft=""
      onDraftChange={vi.fn()}
      focusSignal={0}
      onSend={vi.fn()}
      onStop={vi.fn()}
      attachments={[]}
      validationError={null}
      onAddFiles={vi.fn()}
      onRemoveAttachment={vi.fn()}
      onRetryAttachment={vi.fn()}
      {...overrides}
    />,
  )
}

describe('Composer — file picker', () => {
  it('has an accessible attach button that opens the hidden file input', async () => {
    const clickSpy = vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => {})
    const user = userEvent.setup()
    renderComposer()

    await user.click(screen.getByRole('button', { name: /attach/i }))

    expect(clickSpy).toHaveBeenCalled()
    clickSpy.mockRestore()
  })

  it('calls onAddFiles when a file is selected via the input', () => {
    const onAddFiles = vi.fn()
    renderComposer({ onAddFiles })
    const input = screen.getByTestId('attachment-input') as HTMLInputElement
    const file = new File(['{}'], 'profile.json')

    fireEvent.change(input, { target: { files: [file] } })

    expect(onAddFiles).toHaveBeenCalledTimes(1)
    const passedFiles = Array.from(onAddFiles.mock.calls[0][0] as FileList | File[])
    expect(passedFiles).toHaveLength(1)
    expect(passedFiles[0].name).toBe('profile.json')
  })
})

describe('Composer — drag & drop', () => {
  it('calls onAddFiles with the dropped files', () => {
    const onAddFiles = vi.fn()
    renderComposer({ onAddFiles })
    const dropzone = screen.getByTestId('composer-dropzone')
    const file = new File(['# notes'], 'notes.md')

    fireEvent.drop(dropzone, { dataTransfer: { files: [file] } })

    expect(onAddFiles).toHaveBeenCalledTimes(1)
  })

  it('shows a drop hint while a file is dragged over, and clears it on drop', () => {
    renderComposer()
    const dropzone = screen.getByTestId('composer-dropzone')

    fireEvent.dragOver(dropzone, { dataTransfer: { types: ['Files'] } })
    expect(screen.getByText(/drop to attach/i)).toBeInTheDocument()

    fireEvent.drop(dropzone, { dataTransfer: { files: [new File(['x'], 'a.json')] } })
    expect(screen.queryByText(/drop to attach/i)).not.toBeInTheDocument()
  })
})

describe('Composer — attachments and validation', () => {
  it('renders an attachment chip for each pending upload', () => {
    renderComposer({ attachments: [makeAttachment(), makeAttachment({ id: 'att_2', file: new File(['x'], 'b.md') })] })

    expect(screen.getByText('profile.json')).toBeInTheDocument()
    expect(screen.getByText('b.md')).toBeInTheDocument()
  })

  it('wires the chip remove button to onRemoveAttachment', async () => {
    const onRemoveAttachment = vi.fn()
    const user = userEvent.setup()
    renderComposer({ attachments: [makeAttachment()], onRemoveAttachment })

    await user.click(screen.getByRole('button', { name: /remove/i }))

    expect(onRemoveAttachment).toHaveBeenCalledWith('att_1')
  })

  it('shows a validation error message when present', () => {
    renderComposer({ validationError: '"resume.docx" isn\'t a supported file type.' })
    expect(screen.getByText(/resume\.docx/)).toBeInTheDocument()
  })
})
