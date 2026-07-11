import { describe, expect, it } from 'vitest'
import { fileTypeLabel, formatFileSize, MAX_UPLOAD_SIZE_BYTES, validateFile } from './fileMeta'

function makeFile(name: string, sizeBytes = 10): File {
  const file = new File(['x'.repeat(Math.min(sizeBytes, 10))], name)
  // Overrides the read-only `size` getter for oversize tests without
  // allocating megabytes of content in-memory.
  Object.defineProperty(file, 'size', { value: sizeBytes, configurable: true })
  return file
}

describe('validateFile', () => {
  it.each(['profile.json', 'profile.md', 'profile.pdf', 'PROFILE.PDF'])(
    'accepts %s (case-insensitive, one of the 3 supported formats)',
    (name) => {
      expect(validateFile(makeFile(name))).toBeNull()
    },
  )

  it('rejects an unsupported extension with a message naming the file', () => {
    const error = validateFile(makeFile('resume.docx'))
    expect(error).toContain('resume.docx')
    expect(error).toMatch(/json|md|pdf/i)
  })

  it('rejects a file over the ~10MB cap', () => {
    const error = validateFile(makeFile('big.pdf', MAX_UPLOAD_SIZE_BYTES + 1))
    expect(error).toContain('big.pdf')
    expect(error).toMatch(/large|10\s*MB/i)
  })

  it('accepts a file exactly at the cap', () => {
    expect(validateFile(makeFile('exact.pdf', MAX_UPLOAD_SIZE_BYTES))).toBeNull()
  })
})

describe('fileTypeLabel', () => {
  it('labels each supported extension', () => {
    expect(fileTypeLabel('profile.json')).toBe('JSON')
    expect(fileTypeLabel('profile.md')).toBe('Markdown')
    expect(fileTypeLabel('profile.pdf')).toBe('PDF')
  })

  it('falls back to a generic label for anything else', () => {
    expect(fileTypeLabel('profile.docx')).toBe('File')
  })
})

describe('formatFileSize', () => {
  it('formats bytes below 1KB as bytes', () => {
    expect(formatFileSize(512)).toBe('512 B')
  })

  it('formats kilobytes with no decimal once >= 10', () => {
    expect(formatFileSize(24 * 1024)).toBe('24 KB')
  })

  it('formats small kilobyte values with one decimal', () => {
    expect(formatFileSize(1.5 * 1024)).toBe('1.5 KB')
  })

  it('formats megabytes', () => {
    expect(formatFileSize(3.2 * 1024 * 1024)).toBe('3.2 MB')
  })
})
