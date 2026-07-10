import { act, renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { server } from '../../test/setup'
import { makeUploadResponse } from '../../test/factories'
import { useFileUpload } from './useFileUpload'

function makeFile(name: string, content = 'content'): File {
  return new File([content], name)
}

describe('useFileUpload — validation (no network)', () => {
  it('rejects an unsupported file type without ever uploading it', () => {
    const onSettled = vi.fn()
    const { result } = renderHook(() => useFileUpload({ onSettled }))

    act(() => {
      result.current.addFiles([makeFile('resume.docx')])
    })

    expect(result.current.attachments).toEqual([])
    expect(result.current.validationError).toContain('resume.docx')
    expect(onSettled).not.toHaveBeenCalled()
  })

  it('rejects an oversize file without ever uploading it', () => {
    const onSettled = vi.fn()
    const { result } = renderHook(() => useFileUpload({ onSettled }))
    const huge = makeFile('huge.pdf')
    Object.defineProperty(huge, 'size', { value: 11 * 1024 * 1024 })

    act(() => {
      result.current.addFiles([huge])
    })

    expect(result.current.attachments).toEqual([])
    expect(result.current.validationError).toMatch(/large/i)
    expect(onSettled).not.toHaveBeenCalled()
  })
})

describe('useFileUpload — happy path', () => {
  it('uploads an accepted file, tracks it while uploading, then hands the settled result to onSettled and clears it', async () => {
    server.use(
      http.post('/api/profile/documents', () =>
        HttpResponse.json(makeUploadResponse({ documentId: 5, diffSummary: ['1 new skill'] }), { status: 202 }),
      ),
    )
    const onSettled = vi.fn()
    const { result } = renderHook(() => useFileUpload({ onSettled }))

    act(() => {
      result.current.addFiles([makeFile('profile.json', '{"fullName":"Ada"}')])
    })

    expect(result.current.attachments).toHaveLength(1)
    expect(result.current.attachments[0]).toMatchObject({ status: 'uploading', file: expect.any(File) })

    await waitFor(() => expect(result.current.attachments).toHaveLength(0))

    expect(onSettled).toHaveBeenCalledWith(
      expect.objectContaining({
        documentId: 5,
        filename: 'profile.json',
        status: 'proposed',
        diffSummary: ['1 new skill'],
        opsCount: 1,
      }),
    )
  })

  it('uploads multiple attached files independently', async () => {
    server.use(
      http.post('/api/profile/documents', () => HttpResponse.json(makeUploadResponse({ documentId: 7 }))),
    )
    const onSettled = vi.fn()
    const { result } = renderHook(() => useFileUpload({ onSettled }))

    act(() => {
      result.current.addFiles([makeFile('a.json'), makeFile('b.md')])
    })

    expect(result.current.attachments).toHaveLength(2)
    await waitFor(() => expect(onSettled).toHaveBeenCalledTimes(2))
  })
})

describe('useFileUpload — recoverable failure', () => {
  it('a request-level failure marks the attachment failed with a retry available, without calling onSettled', async () => {
    server.use(
      http.post('/api/profile/documents', () => HttpResponse.json({ detail: 'Server exploded' }, { status: 500 })),
    )
    const onSettled = vi.fn()
    const { result } = renderHook(() => useFileUpload({ onSettled }))

    act(() => {
      result.current.addFiles([makeFile('profile.json')])
    })

    await waitFor(() => {
      expect(result.current.attachments[0]).toMatchObject({ status: 'failed', error: 'Server exploded' })
    })
    expect(onSettled).not.toHaveBeenCalled()
  })

  it('retryAttachment re-uploads the same file and can succeed', async () => {
    let attempt = 0
    server.use(
      http.post('/api/profile/documents', () => {
        attempt += 1
        if (attempt === 1) return HttpResponse.json({ detail: 'Server exploded' }, { status: 500 })
        return HttpResponse.json(makeUploadResponse({ documentId: 11 }))
      }),
    )
    const onSettled = vi.fn()
    const { result } = renderHook(() => useFileUpload({ onSettled }))

    act(() => {
      result.current.addFiles([makeFile('profile.json')])
    })
    await waitFor(() => expect(result.current.attachments[0]?.status).toBe('failed'))

    act(() => {
      result.current.retryAttachment(result.current.attachments[0].id)
    })

    await waitFor(() => expect(result.current.attachments).toHaveLength(0))
    expect(onSettled).toHaveBeenCalledWith(expect.objectContaining({ documentId: 11 }))
    expect(attempt).toBe(2)
  })
})

describe('useFileUpload — remove', () => {
  it('removeAttachment drops it from the list immediately', async () => {
    server.use(
      http.post('/api/profile/documents', async () => {
        await new Promise((resolve) => setTimeout(resolve, 50))
        return HttpResponse.json(makeUploadResponse())
      }),
    )
    const onSettled = vi.fn()
    const { result } = renderHook(() => useFileUpload({ onSettled }))

    act(() => {
      result.current.addFiles([makeFile('profile.json')])
    })
    expect(result.current.attachments).toHaveLength(1)

    act(() => {
      result.current.removeAttachment(result.current.attachments[0].id)
    })

    expect(result.current.attachments).toHaveLength(0)
    // Give the in-flight (aborted) request a chance to settle; it must not
    // resurrect the attachment or call onSettled.
    await new Promise((resolve) => setTimeout(resolve, 100))
    expect(result.current.attachments).toHaveLength(0)
    expect(onSettled).not.toHaveBeenCalled()
  })
})
