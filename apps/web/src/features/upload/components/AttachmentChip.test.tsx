import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AttachmentChip } from './AttachmentChip'
import type { UploadAttachment } from '../useFileUpload'

function makeAttachment(overrides: Partial<UploadAttachment> = {}): UploadAttachment {
  return {
    id: 'att_1',
    file: new File(['{}'], 'profile.json', { type: 'application/json' }),
    status: 'uploading',
    progress: 40,
    ...overrides,
  }
}

describe('AttachmentChip — uploading', () => {
  it('shows the filename, type, size, and progress', () => {
    render(<AttachmentChip attachment={makeAttachment()} onRemove={vi.fn()} onRetry={vi.fn()} />)

    expect(screen.getByText('profile.json')).toBeInTheDocument()
    expect(screen.getByText('JSON')).toBeInTheDocument()
    expect(screen.getByText(/40%/)).toBeInTheDocument()
  })

  it('calls onRemove when the remove button is clicked', async () => {
    const onRemove = vi.fn()
    const user = userEvent.setup()
    render(<AttachmentChip attachment={makeAttachment()} onRemove={onRemove} onRetry={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: /remove/i }))

    expect(onRemove).toHaveBeenCalled()
  })

  it('does not show a retry button while uploading', () => {
    render(<AttachmentChip attachment={makeAttachment()} onRemove={vi.fn()} onRetry={vi.fn()} />)
    expect(screen.queryByRole('button', { name: /retry/i })).not.toBeInTheDocument()
  })
})

describe('AttachmentChip — failed', () => {
  it('shows the error message and a retry button', async () => {
    const onRetry = vi.fn()
    const user = userEvent.setup()
    render(
      <AttachmentChip
        attachment={makeAttachment({ status: 'failed', error: 'Upload failed — check your connection.' })}
        onRemove={vi.fn()}
        onRetry={onRetry}
      />,
    )

    expect(screen.getByText(/check your connection/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /retry/i }))
    expect(onRetry).toHaveBeenCalled()
  })
})

describe('AttachmentChip — file type labels', () => {
  it.each([
    ['profile.json', 'JSON'],
    ['profile.md', 'Markdown'],
    ['profile.pdf', 'PDF'],
  ])('labels %s as %s', (name, label) => {
    render(
      <AttachmentChip
        attachment={makeAttachment({ file: new File(['x'], name) })}
        onRemove={vi.fn()}
        onRetry={vi.fn()}
      />,
    )
    expect(screen.getByText(label)).toBeInTheDocument()
  })
})
