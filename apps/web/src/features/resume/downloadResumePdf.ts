import { exportPdf } from '../../lib/api/endpoints'
import type { ResumeDocument, TemplateId } from '../../types/resume'

/** Hands a Blob to the browser as a file download. Extracted from `downloadResumePdf` in v7
 * ticket 13 so the Job Monitor's One-click Resume (which gets its PDF from a different endpoint,
 * already rendered server-side) reuses the same object-URL dance instead of copying it. */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

/** Requests the PDF and triggers a browser download. Shared by the chat "export pdf" command and PreviewToolbar's Download button. */
export async function downloadResumePdf(resume: ResumeDocument, template: TemplateId): Promise<void> {
  const blob = await exportPdf({ resume, template })
  const safeName = (resume.fullName || 'resume').trim().replace(/\s+/g, '_')
  downloadBlob(blob, `${safeName}_CV.pdf`)
}
