import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchModels } from '../../../lib/api/endpoints'
import type { ModelSuggestion } from '../../../lib/api/dto'
import { useChatStore } from '../store/chatStore'

const FALLBACK_MODEL_SUGGESTIONS: ModelSuggestion[] = [
  { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
  { value: 'gemini-2.5-flash-lite', label: 'Gemini 2.5 Flash-Lite' },
  { value: 'gemini-3-flash-preview', label: 'Gemini 3 Flash Preview' },
  { value: 'qwen3:8b', label: 'qwen3:8b (Ollama, local)' },
  { value: 'phi4:latest', label: 'phi4:latest (Ollama, local)' },
  { value: 'gemma4', label: 'gemma4 (Ollama, local)' },
  { value: 'glm-5.2:cloud', label: 'glm-5.2:cloud (Ollama Cloud)' },
  { value: 'llama3.1:8b', label: 'llama3.1:8b (Ollama, local)' },
  { value: 'llama3.2', label: 'llama3.2 (Ollama, local)' },
]

const MAX_TEXTAREA_HEIGHT_PX = 220

export function Composer({
  draft,
  onDraftChange,
  focusSignal,
  onSend,
  onStop,
}: {
  draft: string
  onDraftChange: (value: string) => void
  /** Bump this to programmatically focus the textarea (e.g. from a suggestion click). */
  focusSignal: number
  onSend: (message: string, options: { model?: string }) => void
  onStop: () => void
}) {
  const [model, setModel] = useState('')
  const [modelSuggestOpen, setModelSuggestOpen] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const streaming = useChatStore((s) => s.streaming)

  const modelsQuery = useQuery({ queryKey: ['models'], queryFn: fetchModels })
  const modelSuggestions: ModelSuggestion[] =
    modelsQuery.data?.models && modelsQuery.data.models.length > 0
      ? modelsQuery.data.models
      : FALLBACK_MODEL_SUGGESTIONS

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

  return (
    <div className="border-t border-stone-200/80 bg-white/80 px-4 py-3 backdrop-blur-md dark:border-zinc-800 dark:bg-zinc-950/80 sm:px-6">
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

        <div className="relative shrink-0">
          <input
            aria-label="AI model (optional)"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            onFocus={() => setModelSuggestOpen(true)}
            onBlur={() => window.setTimeout(() => setModelSuggestOpen(false), 120)}
            placeholder="Model"
            autoComplete="off"
            spellCheck={false}
            role="combobox"
            aria-expanded={modelSuggestOpen}
            aria-controls="composer-model-suggestions"
            className="w-24 rounded-xl border border-stone-200 bg-white px-2.5 py-2.5 text-xs text-stone-900 shadow-sm placeholder:text-stone-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:border-zinc-700 dark:bg-zinc-900/80 dark:text-zinc-100 dark:placeholder:text-zinc-400 dark:focus-visible:ring-zinc-500 sm:w-32"
          />
          {modelSuggestOpen && (
            <ul
              id="composer-model-suggestions"
              className="absolute bottom-full right-0 z-20 mb-1 max-h-60 w-56 overflow-auto rounded-xl border border-stone-200 bg-white py-1 shadow-lg dark:border-zinc-700 dark:bg-zinc-900"
            >
              {modelSuggestions.map((opt) => (
                <li key={opt.value}>
                  <button
                    type="button"
                    onMouseDown={(e) => {
                      e.preventDefault()
                      setModel(opt.value)
                      setModelSuggestOpen(false)
                    }}
                    className="flex w-full flex-col items-start px-3 py-2 text-left text-sm hover:bg-stone-100 dark:hover:bg-zinc-800"
                  >
                    <span className="font-medium text-stone-900 dark:text-zinc-100">{opt.value}</span>
                    <span className="text-xs text-stone-500 dark:text-zinc-500">{opt.label}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

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
