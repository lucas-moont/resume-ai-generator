import { useEffect, useRef, useState, type DragEvent, type KeyboardEvent } from 'react'
import { useAnalysisStore } from '../store/analysisStore'
import { useAnalysisStream } from '../hooks/useAnalysisStream'
import { Tooltip } from '../../../ui/Tooltip'
import { zIndex } from '../../../ui/zIndex'

const MAX_TEXTAREA_HEIGHT_PX = 220

/** v5 ticket f3: the Profile Analysis composer — a text box for a per-section request and a
 * button/drop target for a LinkedIn PDF export. Both drive useAnalysisStream. */
export function AnalysisComposer() {
  const [draft, setDraft] = useState('')
  const [isDragging, setIsDragging] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const streaming = useAnalysisStore((s) => s.streaming)
  const { send, sendPdf, stop } = useAnalysisStream()

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, MAX_TEXTAREA_HEIGHT_PX)}px`
  }, [draft])

  const submit = () => {
    const text = draft.trim()
    if (!text || streaming) return
    void send(text)
    setDraft('')
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const handleFiles = (files: FileList | File[]) => {
    const file = Array.from(files)[0]
    if (file && !streaming) void sendPdf(file)
  }

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(false)
    if (e.dataTransfer.files.length > 0) handleFiles(e.dataTransfer.files)
  }

  return (
    <div
      data-testid="analysis-composer-dropzone"
      onDragOver={(e) => {
        e.preventDefault()
        setIsDragging(true)
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={handleDrop}
      className={`relative border-t bg-white/80 px-4 py-3 backdrop-blur-md dark:bg-zinc-950/80 sm:px-6 ${
        isDragging ? 'border-stone-400 dark:border-zinc-500' : 'border-stone-200/80 dark:border-zinc-800'
      }`}
    >
      {isDragging && (
        <div
          className={`pointer-events-none absolute inset-2 ${zIndex.dropzone} flex items-center justify-center rounded-xl border-2 border-dashed border-stone-400 bg-white/90 text-sm font-medium text-stone-600 dark:border-zinc-500 dark:bg-zinc-950/90 dark:text-zinc-300`}
        >
          Solte o PDF do LinkedIn para analisar
        </div>
      )}

      <input
        ref={fileInputRef}
        data-testid="analysis-pdf-input"
        type="file"
        accept=".pdf"
        tabIndex={-1}
        aria-hidden="true"
        className="hidden"
        onChange={(e) => {
          if (e.target.files && e.target.files.length > 0) handleFiles(e.target.files)
          e.target.value = ''
        }}
      />

      <div className="flex items-end gap-2">
        <textarea
          ref={textareaRef}
          aria-label="Mensagem"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Peça ajuda com uma seção (ex.: melhora meu headline, área backend)…"
          rows={1}
          className="min-h-10 flex-1 resize-none rounded-xl border border-stone-200 bg-white px-3 py-2.5 text-[0.9375rem] text-stone-900 shadow-sm placeholder:text-stone-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 focus-visible:ring-offset-2 focus-visible:ring-offset-stone-50 dark:border-zinc-700 dark:bg-zinc-900/80 dark:text-zinc-100 dark:placeholder:text-zinc-400 dark:focus-visible:ring-zinc-500 dark:focus-visible:ring-offset-zinc-950"
        />

        <Tooltip label="Enviar o PDF exportado do LinkedIn" placement="top">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={!!streaming}
            aria-label="Enviar PDF do LinkedIn"
            className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-stone-200 bg-white text-stone-500 shadow-sm hover:bg-stone-50 hover:text-stone-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 disabled:opacity-45 dark:border-zinc-700 dark:bg-zinc-900/80 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
          >
            <svg aria-hidden="true" viewBox="0 0 20 20" className="h-4.5 w-4.5" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path
                d="M14.5 7.5 8.379 13.621a2 2 0 1 1-2.829-2.829L11.5 4.843a3.333 3.333 0 1 1 4.714 4.714L10.207 15.55a4.667 4.667 0 1 1-6.6-6.6L9.5 3.05"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </Tooltip>

        {streaming ? (
          <button
            type="button"
            onClick={stop}
            className="inline-flex h-10 shrink-0 items-center justify-center gap-1.5 rounded-xl border border-red-300 bg-red-50 px-4 text-sm font-medium text-red-800 shadow-sm hover:bg-red-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300 dark:hover:bg-red-950/60"
          >
            Parar
          </button>
        ) : (
          <button
            type="button"
            onClick={submit}
            disabled={!draft.trim()}
            className="inline-flex h-10 shrink-0 items-center justify-center gap-1.5 rounded-xl bg-stone-900 px-4 text-sm font-medium text-white shadow-sm transition-opacity hover:bg-stone-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-500 focus-visible:ring-offset-2 focus-visible:ring-offset-stone-50 disabled:pointer-events-none disabled:opacity-45 dark:bg-zinc-100 dark:text-zinc-950 dark:hover:bg-white dark:focus-visible:ring-zinc-300 dark:focus-visible:ring-offset-zinc-950"
          >
            Enviar
          </button>
        )}
      </div>
      <p className="mt-1.5 text-xs text-stone-500 dark:text-zinc-500">
        Enter envia · Shift+Enter nova linha · ou solte o PDF do LinkedIn
      </p>
    </div>
  )
}
