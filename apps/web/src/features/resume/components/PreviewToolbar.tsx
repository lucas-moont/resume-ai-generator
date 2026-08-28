import { useState } from 'react'
import { ApiError } from '../../../lib/api/endpoints'
import { downloadResumePdf } from '../downloadResumePdf'
import { useResume, useResumeStore, useResumeTemporal, useTemplate, useValidationIssues } from '../store/resumeStore'
import { useEditModeStore, useIsEditing } from '../store/editModeStore'
import { useUndoRedoShortcuts } from '../editing/undoRedoKeyboard'
import { useChatStore } from '../../chat/store/chatStore'
import { Tooltip } from '../../../ui/Tooltip'
import { TemplatePicker } from './TemplatePicker'

const btnBase =
  'inline-flex h-9 items-center justify-center gap-2 rounded-lg px-3.5 text-sm font-medium transition-[color,background-color,border-color,box-shadow,opacity] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-45'

const iconBtnBase =
  'inline-flex h-9 w-9 items-center justify-center rounded-lg border border-stone-200 bg-white text-stone-800 text-base transition-[color,background-color,border-color,box-shadow,opacity] hover:border-stone-300 hover:bg-stone-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 focus-visible:ring-offset-2 focus-visible:ring-offset-stone-50 disabled:pointer-events-none disabled:opacity-40 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:border-zinc-600 dark:hover:bg-zinc-800 dark:focus-visible:ring-zinc-500 dark:focus-visible:ring-offset-zinc-950'

export function PreviewToolbar() {
  const resume = useResume()
  const template = useTemplate()
  const setTemplate = useResumeStore((s) => s.setTemplate)
  const requestTranslation = useChatStore((s) => s.requestTranslation)
  // The picker shows the DOCUMENT's own language (the labels follow `resume.locale`), not the
  // request preference. Switching it asks ChatPanel for a translate turn.
  const currentLocale = (resume?.locale || '').toLowerCase().startsWith('pt') ? 'pt-BR' : 'en'
  const validationIssues = useValidationIssues()
  const [pdfLoading, setPdfLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isEditing = useIsEditing()
  const toggleEditing = useEditModeStore((s) => s.toggle)
  const isStreaming = useChatStore((s) => s.streaming !== null)
  const { pastStates, futureStates, undo, redo } = useResumeTemporal()

  useUndoRedoShortcuts()

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
        {resume && (
          <div>
            <label
              htmlFor="locale-picker"
              className="mb-1 block text-[0.6875rem] font-semibold uppercase tracking-wider text-stone-500 dark:text-zinc-500"
            >
              Idioma
            </label>
            <select
              id="locale-picker"
              aria-label="Idioma do currículo"
              value={currentLocale}
              disabled={isStreaming}
              onChange={(e) => {
                if (e.target.value !== currentLocale) requestTranslation(e.target.value)
              }}
              className="rounded-lg border border-stone-200 bg-white py-1.5 pl-2.5 pr-8 text-sm text-stone-900 shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 disabled:pointer-events-none disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:focus-visible:ring-zinc-500"
            >
              <option value="pt-BR">Português</option>
              <option value="en">English</option>
            </select>
          </div>
        )}
      </div>
      <div className="flex items-center gap-2">
        <Tooltip label="Undo (Ctrl+Z)" placement="bottom">
          <button
            type="button"
            // NOT onClick={undo}: zundo's undo(steps = 1) takes a step count, and
            // React invokes onClick handlers with the SyntheticEvent as the first
            // argument — passed straight through as `steps`, that event object
            // coerces to NaN/0 in splice()'s arithmetic, undo's `.shift()` comes
            // back `undefined`, and `userSet(undefined)` nulls out the ENTIRE
            // resumeStore (confirmed against zustand's vanilla setState: a
            // non-object partial with no explicit `replace` REPLACES state
            // wholesale instead of merging). Wrapping in a no-arg arrow avoids
            // ever leaking the event into zundo.
            onClick={() => undo()}
            disabled={pastStates.length === 0}
            aria-label="Undo"
            className={iconBtnBase}
          >
            ↶
          </button>
        </Tooltip>
        <Tooltip label="Redo (Ctrl+Shift+Z)" placement="bottom">
          <button
            type="button"
            onClick={() => redo()}
            disabled={futureStates.length === 0}
            aria-label="Redo"
            className={iconBtnBase}
          >
            ↷
          </button>
        </Tooltip>
        <Tooltip label={isEditing ? 'Stop editing' : 'Edit inline'} placement="bottom">
          <button
            type="button"
            onClick={toggleEditing}
            disabled={isStreaming}
            aria-pressed={isEditing}
            aria-label={isEditing ? 'Stop editing' : 'Edit inline'}
            // Kept as a native attribute (not the styled Tooltip): while
            // streaming the button is disabled + pointer-events-none, so it
            // fires no hover events for the custom tooltip — but the disabled
            // explanation is exactly what a user needs then.
            title={isStreaming ? 'Editing is disabled while a response is streaming' : undefined}
            className={`${iconBtnBase} ${isEditing ? 'border-indigo-400 bg-indigo-50 text-indigo-700 dark:border-indigo-500 dark:bg-indigo-950 dark:text-indigo-300' : ''}`}
          >
            ✎
          </button>
        </Tooltip>
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
      {validationIssues.length > 0 && (
        <p
          role="status"
          title={validationIssues.join('\n')}
          className="w-full text-xs font-medium text-amber-700 dark:text-amber-400"
        >
          {validationIssues.length === 1
            ? '1 field needs a closer look — nothing was lost.'
            : `${validationIssues.length} fields need a closer look — nothing was lost.`}
        </p>
      )}
    </div>
  )
}
