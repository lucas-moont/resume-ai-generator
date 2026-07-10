import { useCallback, useRef, useState } from 'react'
import { ApiError } from '../../lib/api/client'
import { uploadSourceDocument } from '../../lib/api/endpoints'
import type { SourceDocumentStatus } from '../../lib/api/dto'
import { validateFile } from './fileMeta'

export interface UploadAttachment {
  id: string
  file: File
  status: 'uploading' | 'failed'
  progress: number
  error?: string
}

/** What a settled upload (proposed, failed extraction, or anything else the
 * server reports) hands back to the caller — enough to render a
 * ProfileUpdatedCard in the chat transcript. */
export interface SettledUpload {
  documentId: number
  filename: string
  status: SourceDocumentStatus
  diffSummary: string[]
  opsCount: number
  error?: string
}

export interface UseFileUploadOptions {
  onSettled?: (result: SettledUpload) => void
}

export interface UseFileUploadResult {
  attachments: UploadAttachment[]
  validationError: string | null
  addFiles: (files: FileList | File[]) => void
  removeAttachment: (id: string) => void
  retryAttachment: (id: string) => void
}

const GENERIC_UPLOAD_ERROR = 'Upload failed — check your connection and try again.'

function makeAttachmentId(): string {
  return `att_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

function isAbortError(e: unknown): boolean {
  return e instanceof DOMException && e.name === 'AbortError'
}

export function useFileUpload(options: UseFileUploadOptions = {}): UseFileUploadResult {
  const [attachments, setAttachments] = useState<UploadAttachment[]>([])
  const [validationError, setValidationError] = useState<string | null>(null)
  const controllers = useRef(new Map<string, AbortController>())
  const files = useRef(new Map<string, File>())
  const onSettledRef = useRef(options.onSettled)
  onSettledRef.current = options.onSettled

  const startUpload = useCallback((id: string, file: File) => {
    const controller = new AbortController()
    controllers.current.set(id, controller)

    uploadSourceDocument(file, {
      signal: controller.signal,
      onProgress: (pct) => {
        setAttachments((prev) => prev.map((a) => (a.id === id ? { ...a, progress: pct } : a)))
      },
    })
      .then((response) => {
        controllers.current.delete(id)
        files.current.delete(id)
        setAttachments((prev) => prev.filter((a) => a.id !== id))
        onSettledRef.current?.({
          documentId: response.documentId,
          filename: file.name,
          status: response.status,
          diffSummary: response.diffSummary ?? [],
          opsCount: response.proposedPatch?.length ?? 0,
          error: response.error,
        })
      })
      .catch((e: unknown) => {
        controllers.current.delete(id)
        // Removed locally mid-flight — not a failure worth surfacing.
        if (isAbortError(e)) return
        const message = e instanceof ApiError && typeof e.detail === 'string' ? e.detail : GENERIC_UPLOAD_ERROR
        setAttachments((prev) =>
          prev.map((a) => (a.id === id ? { ...a, status: 'failed', error: message } : a)),
        )
      })
  }, [])

  const addFiles = useCallback(
    (fileList: FileList | File[]) => {
      const list = Array.from(fileList)
      let firstError: string | null = null
      const accepted: Array<{ id: string; file: File }> = []

      for (const file of list) {
        const error = validateFile(file)
        if (error) {
          firstError = firstError ?? error
          continue
        }
        accepted.push({ id: makeAttachmentId(), file })
      }

      setValidationError(firstError)
      if (accepted.length === 0) return

      for (const { id, file } of accepted) files.current.set(id, file)
      setAttachments((prev) => [
        ...prev,
        ...accepted.map(({ id, file }) => ({ id, file, status: 'uploading' as const, progress: 0 })),
      ])
      for (const { id, file } of accepted) startUpload(id, file)
    },
    [startUpload],
  )

  const removeAttachment = useCallback((id: string) => {
    controllers.current.get(id)?.abort()
    controllers.current.delete(id)
    files.current.delete(id)
    setAttachments((prev) => prev.filter((a) => a.id !== id))
  }, [])

  const retryAttachment = useCallback(
    (id: string) => {
      const file = files.current.get(id)
      if (!file) return
      setAttachments((prev) =>
        prev.map((a) => (a.id === id ? { ...a, status: 'uploading', progress: 0, error: undefined } : a)),
      )
      startUpload(id, file)
    },
    [startUpload],
  )

  return { attachments, validationError, addFiles, removeAttachment, retryAttachment }
}
