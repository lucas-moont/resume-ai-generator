import { useEffect, useRef, useState, type DragEvent, type KeyboardEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchModels } from '../../../lib/api/endpoints'
import { useChatStore } from '../store/chatStore'
import type { UploadAttachment } from '../../upload/useFileUpload'
import { AttachmentChip } from '../../upload/components/AttachmentChip'
import { Combobox, type ComboboxOption } from '../../../ui/Combobox'
import { zIndex } from '../../../ui/zIndex'

const MAX_TEXTAREA_HEIGHT_PX = 220

export function Composer({
  draft,
  onDraftChange,
  focusSignal,
  onSend,
  onStop,
  attachments,
  validationError,
  onAddFiles,
  onRemoveAttachment,
  onRetryAttachment,
}: {
  draft: string
  onDraftChange: (value: string) => void
  /** Bump this to programmatically focus the textarea (e.g. from a suggestion click). */
  focusSignal: number
  onSend: (message: string, options: { model?: string }) => void
  onStop: () => void
  attachments: UploadAttachment[]
  validationError: string | null
  onAddFiles: (files: FileList | File[]) => void
  onRemoveAttachment: (id: string) => void
  onRetryAttachment: (id: string) => void
}) {
  const [model, setModel] = useState('')
  const [isDragging, setIsDragging] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const streaming = useChatStore((s) => s.streaming)

  const modelsQuery = useQuery({ queryKey: ['models'], queryFn: fetchModels })
  // ModelSuggestion (lib/api/dto.ts) and ComboboxOption (ui/Combobox.tsx) are
  // intentionally structurally identical ({ value, label }) but declared
  // independently — ui must not import from lib/api. `satisfies` makes that
  // alignment an explicit, compiler-checked fact here instead of an
  // incidental one discovered only if the shapes ever drift apart.
  const modelSuggestions = (modelsQuery.data?.models ?? []) satisfies ComboboxOption[]
  const modelEmptyState = modelsQuery.isLoading
    ? 'Loading models…'
    : modelsQuery.isError
      ? "Couldn't load models."
      : 'No models available.'

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, MAX_TEXTAREA_HEIGHT_PX)}px`
  }, [draft])

  useEffect(() => {
    if (focusSignal > 0) textareaRef.current?.focus()
  }, [focusSignal])

  const submit = () => {
    const text = draft.trim()
    if (!text || streaming) return
    onSend(text, { model: model || undefined })
    onDraftChange('')
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = () => setIsDragging(false)

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(false)
    if (e.dataTransfer.files.length > 0) onAddFiles(e.dataTransfer.files)
  }

  return (
    <div
      data-testid="composer-dropzone"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={`relative border-t bg-white/80 px-4 py-3 backdrop-blur-md dark:bg-zinc-950/80 sm:px-6 ${
        isDragging
          ? 'border-stone-400 dark:border-zinc-500'
          : 'border-stone-200/80 dark:border-zinc-800'
      }`}
    >
      {isDragging && (
        <div
          className={`pointer-events-none absolute inset-2 ${zIndex.dropzone} flex items-center justify-center rounded-xl border-2 border-dashed border-stone-400 bg-white/90 text-sm font-medium text-stone-600 dark:border-zinc-500 dark:bg-zinc-950/90 dark:text-zinc-300`}
        >
          Drop to attach — .json, .md, or .pdf
        </div>
      )}

      {attachments.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-2">
          {attachments.map((attachment) => (
            <AttachmentChip
              key={attachment.id}
              attachment={attachment}
              onRemove={() => onRemoveAttachment(attachment.id)}
              onRetry={() => onRetryAttachment(attachment.id)}
            />
          ))}
        </div>
      )}

      {validationError && (
        <p role="alert" className="mb-2 text-xs font-medium text-red-600 dark:text-red-400">
          {validationError}
        </p>
      )}

      <input
        ref={fileInputRef}
        data-testid="attachment-input"
        type="file"
        multiple
        accept=".json,.md,.pdf"
        tabIndex={-1}
        aria-hidden="true"
        className="hidden"
        onChange={(e) => {
          if (e.target.files && e.target.files.length > 0) onAddFiles(e.target.files)
          e.target.value = ''
        }}
      />

      <div className="flex items-end gap-2">
        <textarea
          ref={textareaRef}
          aria-label="Message"
          value={draft}
          onChange={(e) => onDraftChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Paste a job description, or ask for a change…"
          rows={1}
          className="min-h-10 flex-1 resize-none rounded-xl border border-stone-200 bg-white px-3 py-2.5 text-[0.9375rem] text-stone-900 shadow-sm placeholder:text-stone-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 focus-visible:ring-offset-2 focus-visible:ring-offset-stone-50 dark:border-zinc-700 dark:bg-zinc-900/80 dark:text-zinc-100 dark:placeholder:text-zinc-400 dark:focus-visible:ring-zinc-500 dark:focus-visible:ring-offset-zinc-950"
        />

        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          aria-label="Attach a profile document (.json, .md, or .pdf)"
          title="Attach a document"
          className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-stone-200 bg-white text-stone-500 shadow-sm hover:bg-stone-50 hover:text-stone-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:border-zinc-700 dark:bg-zinc-900/80 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
        >
          <svg aria-hidden="true" viewBox="0 0 20 20" className="h-4.5 w-4.5" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path
              d="M14.5 7.5 8.379 13.621a2 2 0 1 1-2.829-2.829L11.5 4.843a3.333 3.333 0 1 1 4.714 4.714L10.207 15.55a4.667 4.667 0 1 1-6.6-6.6L9.5 3.05"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>

        <Combobox
          id="composer-model"
          aria-label="AI model (optional)"
          value={model}
          onChange={setModel}
          options={modelSuggestions}
          emptyState={modelEmptyState}
          renderOption={(opt) => (
            <>
              <span className="font-medium text-stone-900 dark:text-zinc-100">{opt.value}</span>
              <span className="text-xs text-stone-500 dark:text-zinc-500">{opt.label}</span>
            </>
          )}
          placeholder="Model"
          wrapperClassName="shrink-0"
          className="w-24 rounded-xl border border-stone-200 bg-white px-2.5 py-2.5 text-xs text-stone-900 shadow-sm placeholder:text-stone-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:border-zinc-700 dark:bg-zinc-900/80 dark:text-zinc-100 dark:placeholder:text-zinc-400 dark:focus-visible:ring-zinc-500 sm:w-32"
          listClassName={`absolute bottom-full right-0 ${zIndex.dropdown} mb-1 max-h-60 w-56 overflow-auto rounded-xl border border-stone-200 bg-white py-1 shadow-lg dark:border-zinc-700 dark:bg-zinc-900`}
        />

        {streaming ? (
          <button
            type="button"
            onClick={onStop}
            className="inline-flex h-10 shrink-0 items-center justify-center gap-1.5 rounded-xl border border-red-300 bg-red-50 px-4 text-sm font-medium text-red-800 shadow-sm hover:bg-red-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300 dark:hover:bg-red-950/60"
          >
            Stop
          </button>
        ) : (
          <button
            type="button"
            onClick={submit}
            disabled={!draft.trim()}
            className="inline-flex h-10 shrink-0 items-center justify-center gap-1.5 rounded-xl bg-stone-900 px-4 text-sm font-medium text-white shadow-sm transition-opacity hover:bg-stone-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-500 focus-visible:ring-offset-2 focus-visible:ring-offset-stone-50 disabled:pointer-events-none disabled:opacity-45 dark:bg-zinc-100 dark:text-zinc-950 dark:hover:bg-white dark:focus-visible:ring-zinc-300 dark:focus-visible:ring-offset-zinc-950"
          >
            Send
          </button>
        )}
      </div>
      <p className="mt-1.5 text-xs text-stone-500 dark:text-zinc-500">
        Enter to send · Shift+Enter for a new line
      </p>
    </div>
  )
}
