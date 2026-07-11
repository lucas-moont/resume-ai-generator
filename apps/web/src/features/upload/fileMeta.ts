const ACCEPTED_EXTENSIONS = ['.json', '.md', '.pdf'] as const

/** ~10MB, matching the backend cap (docs/v2-living-profile.md item 3). Client-side
 * validation is a fast-feedback courtesy — the server enforces this authoritatively. */
export const MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024

/** Returns a user-facing error message, or `null` if the file is acceptable. */
export function validateFile(file: File): string | null {
  const name = file.name.toLowerCase()
  if (!ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext))) {
    return `"${file.name}" isn't a supported file type — attach a .json, .md, or .pdf file.`
  }
  if (file.size > MAX_UPLOAD_SIZE_BYTES) {
    return `"${file.name}" is too large — the max upload size is 10MB.`
  }
  return null
}

export function fileTypeLabel(filename: string): string {
  const name = filename.toLowerCase()
  if (name.endsWith('.json')) return 'JSON'
  if (name.endsWith('.md')) return 'Markdown'
  if (name.endsWith('.pdf')) return 'PDF'
  return 'File'
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const kb = bytes / 1024
  if (kb < 1024) return `${kb < 10 ? kb.toFixed(1) : Math.round(kb)} KB`
  const mb = kb / 1024
  return `${mb < 10 ? mb.toFixed(1) : Math.round(mb)} MB`
}
