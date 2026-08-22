import type { ResumeDocument } from '../../../types/resume'
import { contactGapLabels, contactGaps } from '../contactGaps'

/**
 * Tells the user, above the A4 page, which contact details this resume is going out without.
 *
 * It sits between the toolbar and the document on purpose: that is where the eye lands before
 * Download PDF, which is the last moment a missing phone number is cheap to fix. It is a
 * statement, not an action — only the user has the value, so the fix is theirs to make in chat
 * ("meu telefone é ...") or by editing the field inline.
 *
 * Existence-of-a-value only. It never validates FORMAT: guessing what a valid phone or address
 * looks like across locales produces false alarms, and a false alarm on a correct resume teaches
 * the user to ignore the notice — which would cost more than the silence it replaced.
 *
 * `no-print` is load-bearing, not decoration. Browser Ctrl+P prints this pane (index.css's
 * `@media print` deliberately makes `.print-preview-wrap` and its children visible so a
 * multi-page resume prints in full), so without it an amber "this resume is missing a phone"
 * banner would land on the printed résumé itself. The backend PDF export is unaffected either
 * way — it renders `resume_print.html`, which knows nothing about this component.
 */
export function ContactGapsNotice({ resume }: { resume: ResumeDocument }) {
  const gaps = contactGaps(resume)
  if (gaps.length === 0) return null

  const isPt = (resume.locale || '').toLowerCase().startsWith('pt')
  const list = contactGapLabels(gaps, resume.locale).join(', ')
  const text = isPt
    ? `Este currículo vai sair sem: ${list}. Recrutadores esperam esses dados — dá pra preencher no chat ou editando direto no documento.`
    : `This resume is going out without: ${list}. Recruiters expect these — add them in chat or by editing the document directly.`

  return (
    <div
      role="status"
      className="no-print mx-auto mb-4 max-w-[794px] rounded-xl border border-amber-300 bg-amber-50 px-3.5 py-2.5 text-xs leading-relaxed text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
    >
      {text}
    </div>
  )
}
