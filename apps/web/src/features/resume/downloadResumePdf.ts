import { exportPdf } from '../../lib/api/endpoints'
import type { ResumeDocument, TemplateId } from '../../types/resume'

/** Requests the PDF and triggers a browser download. Shared by the chat "export pdf" command and PreviewToolbar's Download button. */
export async function downloadResumePdf(resume: ResumeDocument, template: TemplateId): Promise<void> {
  const blob = await exportPdf({ resume, template })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  const safeName = (resume.fullName || 'resume').trim().replace(/\s+/g, '_')
  a.download = `${safeName}_CV.pdf`
  a.click()
  URL.revokeObjectURL(url)
}
