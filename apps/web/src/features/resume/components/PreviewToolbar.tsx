import { useState } from 'react'
import { ApiError } from '../../../lib/api/endpoints'
import { downloadResumePdf } from '../downloadResumePdf'
import { useLocale, useResume, useResumeStore, useTemplate } from '../store/resumeStore'
import { TemplatePicker } from './TemplatePicker'

const btnBase =
  'inline-flex h-9 items-center justify-center gap-2 rounded-lg px-3.5 text-sm font-medium transition-[color,background-color,border-color,box-shadow,opacity] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-45'

export function PreviewToolbar() {
  const resume = useResume()
  const template = useTemplate()
  const locale = useLocale()
  const setTemplate = useResumeStore((s) => s.setTemplate)
  const setLocale = useResumeStore((s) => s.setLocale)
  const [pdfLoading, setPdfLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleDownload = async () => {
    if (!resume || pdfLoading) return
    setError(null)
    setPdfLoading(true)
    try {
      await downloadResumePdf(resume, template)
    } catch (e) {
      setError(e instanceof ApiError ? ((e.detail as string | undefined) ?? 'PDF export failed') : String(e))
    } finally {
      setPdfLoading(false)
    }
  }

  return (
    <div className="no-print flex flex-wrap items-end justify-between gap-3 border-b border-stone-200 bg-white/60 px-4 py-3 dark:border-zinc-800 dark:bg-zinc-950/40 sm:px-6">
      <div className="flex flex-wrap items-end gap-3">
        <TemplatePicker value={template} onChange={setTemplate} />
        <div>
          <label
            htmlFor="locale-picker"
            className="mb-1 block text-[0.6875rem] font-semibold uppercase tracking-wider text-stone-500 dark:text-zinc-500"
          >
            Locale
          </label>
          <select
            id="locale-picker"
            value={locale}
            onChange={(e) => setLocale(e.target.value)}
            className="rounded-lg border border-stone-200 bg-white py-1.5 pl-2.5 pr-8 text-sm text-stone-900 shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:focus-visible:ring-zinc-500"
          >
            <option value="auto">Auto</option>
            <option value="pt-BR">pt-BR</option>
            <option value="en">en</option>
          </select>
        </div>
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => window.print()}
          disabled={!resume}
          className={`${btnBase} border border-stone-200 bg-white text-stone-800 hover:border-stone-300 hover:bg-stone-50 focus-visible:ring-stone-400 focus-visible:ring-offset-stone-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:border-zinc-600 dark:hover:bg-zinc-800 dark:focus-visible:ring-zinc-500 dark:focus-visible:ring-offset-zinc-950`}
        >
          Print
        </button>
        <button
          type="button"
          onClick={handleDownload}
          disabled={!resume || pdfLoading}
          className={`${btnBase} bg-stone-900 text-white shadow-sm hover:bg-stone-800 focus-visible:ring-stone-500 focus-visible:ring-offset-stone-50 dark:bg-zinc-100 dark:text-zinc-950 dark:hover:bg-white dark:focus-visible:ring-zinc-300 dark:focus-visible:ring-offset-zinc-950`}
        >
          {pdfLoading ? 'Preparing PDF…' : 'Download PDF'}
        </button>
      </div>
      {error && (
        <p role="alert" className="w-full text-sm font-medium text-red-700 dark:text-red-400">
          {error}
        </p>
      )}
    </div>
  )
}
