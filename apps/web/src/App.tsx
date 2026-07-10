import { useCallback, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ResumePreview } from './components/ResumePreview'
import type { ResumeDocument } from './types/resume'
import { ApiError, exportPdf, fetchGithubRepos, fetchModels, generateStream, refineStream } from './lib/api/endpoints'
import type { SseEvent } from './lib/api/sse'
import type {
  ModelSuggestion,
  StreamDonePayload,
  StreamErrorPayload,
  StreamStagePayload,
} from './lib/api/dto'
import { ThemeToggle } from './app/theme/ThemeToggle'
import { useLocale, useResume, useResumeStore, useTemplate } from './features/resume/store/resumeStore'
import { TEMPLATE_REGISTRY } from './features/resume/templates/registry'

const DEFAULT_MODEL = ''
const TEMPLATE_OPTIONS = TEMPLATE_REGISTRY.map((t) => ({
  value: t.id,
  label: t.label,
  description: t.description,
}))

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
const WORK_STEPS = [
  { id: 'preparing_context', label: 'Preparing context' },
  { id: 'extracting_profile_pdf', label: 'Extracting profile from PDF' },
  { id: 'calling_ai', label: 'Calling AI model' },
  { id: 'validating_response', label: 'Validating response' },
  { id: 'finalizing', label: 'Finalizing' },
]
type WorkType = 'generate' | 'refine' | null

function App() {
  const [jobDescription, setJobDescription] = useState('')
  const [model, setModel] = useState(DEFAULT_MODEL)
  const locale = useLocale()
  const template = useTemplate()
  const resume = useResume()
  const setLocale = useResumeStore((s) => s.setLocale)
  const setTemplate = useResumeStore((s) => s.setTemplate)
  const setResume = useResumeStore((s) => s.setResume)
  const [refineText, setRefineText] = useState('')
  const [loading, setLoading] = useState(false)
  const [pdfLoading, setPdfLoading] = useState(false)
  const [modelSuggestOpen, setModelSuggestOpen] = useState(false)
  const [workType, setWorkType] = useState<WorkType>(null)
  const [workStep, setWorkStep] = useState(0)
  const [workProgress, setWorkProgress] = useState(0)
  const [workMessage, setWorkMessage] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [ghInfo, setGhInfo] = useState<string | null>(null)

  const modelsQuery = useQuery({ queryKey: ['models'], queryFn: fetchModels })
  const modelSuggestions: ModelSuggestion[] =
    modelsQuery.data?.models && modelsQuery.data.models.length > 0
      ? modelsQuery.data.models
      : FALLBACK_MODEL_SUGGESTIONS

  const progressPct = useMemo(() => (loading ? workProgress : 0), [loading, workProgress])

  const stepIndexFromId = useCallback((stepId: string) => {
    const idx = WORK_STEPS.findIndex((s) => s.id === stepId)
    return idx >= 0 ? idx : 0
  }, [])

  const runStreamEvents = useCallback(
    async (
      events: AsyncGenerator<SseEvent>,
      onDone: (resume: ResumeDocument) => void,
    ) => {
      for await (const { event, data } of events) {
        if (event === 'stage') {
          const s = data as StreamStagePayload
          setWorkStep(stepIndexFromId(s.step))
          setWorkProgress(Math.max(5, Math.min(99, Math.round(s.progress ?? 0))))
          setWorkMessage(s.message ?? '')
        } else if (event === 'done') {
          const d = data as StreamDonePayload
          setWorkProgress(Math.round(d.progress ?? 100))
          setWorkStep(WORK_STEPS.length - 1)
          setWorkMessage('Done')
          onDone(d.resume)
        } else if (event === 'error') {
          const err = data as StreamErrorPayload
          throw new Error(err.message || 'Stream failed')
        }
      }
    },
    [stepIndexFromId],
  )

  const checkGithub = useCallback(async () => {
    setGhInfo(null)
    try {
      const data = await fetchGithubRepos()
      if (data.warning) setGhInfo(data.warning)
      else if (!data.repos?.length) setGhInfo('No repositories in response.')
      else setGhInfo(`Loaded ${data.repos.length} repos from GitHub.`)
    } catch (e) {
      if (e instanceof ApiError) setGhInfo((e.detail as string | undefined) ?? 'GitHub check failed')
      else setGhInfo('Could not reach API (is the backend running?)')
    }
  }, [])

  const generate = async () => {
    setError(null)
    setWorkType('generate')
    setWorkStep(0)
    setWorkProgress(5)
    setWorkMessage('Starting generation')
    setLoading(true)
    try {
      const events = await generateStream({
        job_description: jobDescription,
        model: model || undefined,
        locale: locale || undefined,
      })
      await runStreamEvents(events, (nextResume) => setResume(nextResume))
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  const refine = async () => {
    if (!resume || !refineText.trim()) return
    setError(null)
    setWorkType('refine')
    setWorkStep(0)
    setWorkProgress(5)
    setWorkMessage('Starting refinement')
    setLoading(true)
    try {
      const events = await refineStream({
        resume,
        message: refineText,
        model: model || undefined,
      })
      await runStreamEvents(events, (nextResume) => setResume(nextResume))
      setRefineText('')
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  const downloadPdf = async () => {
    if (!resume || pdfLoading) return
    setError(null)
    setPdfLoading(true)
    try {
      const blob = await exportPdf({ resume, template })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const safeName = (resume.fullName || 'resume').trim().replace(/\s+/g, '_')
      a.download = `${safeName}_CV.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      if (e instanceof ApiError) setError((e.detail as string | undefined) ?? 'PDF export failed')
      else setError(String(e))
    } finally {
      setPdfLoading(false)
    }
  }

  const printFallback = () => window.print()

  const fieldClass =
    'w-full rounded-xl border border-stone-200 bg-white px-3 py-2.5 text-[0.9375rem] text-stone-900 shadow-sm placeholder:text-stone-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 focus-visible:ring-offset-2 focus-visible:ring-offset-stone-50 dark:border-zinc-700 dark:bg-zinc-900/80 dark:text-zinc-100 dark:placeholder:text-zinc-500 dark:focus-visible:ring-zinc-500 dark:focus-visible:ring-offset-zinc-950'

  const btnBase =
    'inline-flex min-h-10 items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-[color,background-color,border-color,box-shadow,opacity] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-45'

  return (
    <div className="print-shell min-h-screen bg-stone-50 text-stone-900 transition-colors duration-200 dark:bg-zinc-950 dark:text-zinc-100">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[100] focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-stone-900 focus:shadow-lg dark:focus:bg-zinc-900 dark:focus:text-zinc-100"
      >
        Skip to main content
      </a>
      <header className="no-print border-b border-stone-200/80 bg-white/80 backdrop-blur-md dark:border-zinc-800 dark:bg-zinc-950/80">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-end justify-between gap-4 px-4 py-5 sm:px-6 lg:px-8">
          <div className="min-w-0">
            <h1 className="font-display text-pretty text-2xl font-semibold tracking-tight text-stone-900 sm:text-3xl dark:text-zinc-50">
              Resume agent
            </h1>
            <p className="mt-1 max-w-xl text-sm leading-relaxed text-stone-600 dark:text-zinc-400">
              Local AI API · FastAPI · ATS-friendly layout
            </p>
          </div>
          <ThemeToggle />
        </div>
      </header>

      <main
        id="main-content"
        className="print-grid mx-auto grid min-h-[calc(100vh-5.5rem)] max-w-[1600px] grid-cols-1 lg:grid-cols-[minmax(280px,38%)_1fr]"
      >
        <section className="no-print border-stone-200 bg-white/60 px-4 py-6 sm:px-6 lg:border-r lg:px-8 dark:border-zinc-800 dark:bg-zinc-950/40">
          <div className="mx-auto max-w-xl space-y-6 lg:mx-0">
            <div>
              <label
                htmlFor="job-description"
                className="mb-2 block text-xs font-semibold uppercase tracking-wider text-stone-500 dark:text-zinc-500"
              >
                Job description
              </label>
              <textarea
                id="job-description"
                name="job_description"
                className={`${fieldClass} min-h-[220px] resize-y`}
                value={jobDescription}
                onChange={(e) => setJobDescription(e.target.value)}
                placeholder="Paste the full job posting here…"
                rows={14}
                spellCheck
              />
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label
                  htmlFor="ai-model"
                  className="mb-2 block text-xs font-semibold uppercase tracking-wider text-stone-500 dark:text-zinc-500"
                >
                  AI model (optional)
                </label>
                <div className="relative">
                  <input
                    id="ai-model"
                    name="model"
                    className={fieldClass}
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    onFocus={() => setModelSuggestOpen(true)}
                    onBlur={() => window.setTimeout(() => setModelSuggestOpen(false), 120)}
                    placeholder="Blank = server default · or an exact Ollama tag"
                    autoComplete="off"
                    spellCheck={false}
                    role="combobox"
                    aria-expanded={modelSuggestOpen}
                    aria-controls="model-suggestions"
                  />
                  {modelSuggestOpen && (
                    <ul
                      id="model-suggestions"
                      className="absolute left-0 right-0 top-full z-20 mt-1 max-h-60 overflow-auto rounded-xl border border-stone-200 bg-white py-1 shadow-lg dark:border-zinc-700 dark:bg-zinc-900"
                    >
                      {modelSuggestions.map((opt) => (
                        <li key={opt.value}>
                          <button
                            type="button"
                            className="flex w-full flex-col items-start px-3 py-2 text-left text-sm hover:bg-stone-100 dark:hover:bg-zinc-800"
                            onMouseDown={(e) => {
                              e.preventDefault()
                              setModel(opt.value)
                              setModelSuggestOpen(false)
                            }}
                          >
                            <span className="font-medium text-stone-900 dark:text-zinc-100">{opt.value}</span>
                            <span className="text-xs text-stone-500 dark:text-zinc-500">{opt.label}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <p className="mt-1.5 text-xs leading-relaxed text-stone-500 dark:text-zinc-500">
                  Ollama models must match a name from <code>ollama list</code> (pull first).
                </p>
              </div>
              <div>
                <label
                  htmlFor="locale"
                  className="mb-2 block text-xs font-semibold uppercase tracking-wider text-stone-500 dark:text-zinc-500"
                >
                  Locale
                </label>
                <div className="relative">
                  <select
                    id="locale"
                    name="locale"
                    className={`${fieldClass} appearance-none pr-10`}
                    value={locale}
                    onChange={(e) => setLocale(e.target.value)}
                  >
                    <option value="auto">Auto (match job language)</option>
                    <option value="pt-BR">pt-BR</option>
                    <option value="en">en</option>
                  </select>
                  <svg
                    aria-hidden="true"
                    viewBox="0 0 20 20"
                    className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-stone-500 dark:text-zinc-500"
                  >
                    <path d="m5 7 5 6 5-6" fill="none" stroke="currentColor" strokeWidth="1.8" />
                  </svg>
                </div>
              </div>
            </div>

            <div>
              <span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-stone-500 dark:text-zinc-500">
                Resume template
              </span>
              <div
                role="radiogroup"
                aria-label="Resume template"
                className="grid grid-cols-2 gap-2 sm:grid-cols-4"
              >
                {TEMPLATE_OPTIONS.map((opt) => {
                  const selected = template === opt.value
                  return (
                    <button
                      key={opt.value}
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      onClick={() => setTemplate(opt.value)}
                      className={`rounded-xl border px-3 py-2.5 text-left transition-[color,background-color,border-color,box-shadow] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-stone-50 dark:focus-visible:ring-offset-zinc-950 ${
                        selected
                          ? 'border-stone-900 bg-stone-900 text-white shadow-sm focus-visible:ring-stone-500 dark:border-zinc-100 dark:bg-zinc-100 dark:text-zinc-950 dark:focus-visible:ring-zinc-300'
                          : 'border-stone-200 bg-white text-stone-800 hover:border-stone-300 hover:bg-stone-50 focus-visible:ring-stone-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:border-zinc-600 dark:hover:bg-zinc-800 dark:focus-visible:ring-zinc-500'
                      }`}
                    >
                      <span className="block text-sm font-semibold">{opt.label}</span>
                      <span
                        className={`mt-0.5 block text-xs ${
                          selected
                            ? 'text-white/70 dark:text-zinc-950/60'
                            : 'text-stone-500 dark:text-zinc-500'
                        }`}
                      >
                        {opt.description}
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className={`${btnBase} bg-stone-900 text-white shadow-sm hover:bg-stone-800 focus-visible:ring-stone-500 focus-visible:ring-offset-stone-50 dark:bg-zinc-100 dark:text-zinc-950 dark:hover:bg-white dark:focus-visible:ring-zinc-300 dark:focus-visible:ring-offset-zinc-950`}
                disabled={loading || !jobDescription.trim()}
                onClick={generate}
              >
                {loading && workType === 'generate' ? 'Generating…' : 'Generate resume'}
              </button>
              <button
                type="button"
                className={`${btnBase} border border-stone-200 bg-white text-stone-800 hover:border-stone-300 hover:bg-stone-50 focus-visible:ring-stone-400 focus-visible:ring-offset-stone-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:border-zinc-600 dark:hover:bg-zinc-800 dark:focus-visible:ring-zinc-500 dark:focus-visible:ring-offset-zinc-950`}
                onClick={checkGithub}
              >
                Test GitHub
              </button>
            </div>

            {loading && (
              <div
                className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900/60"
                role="status"
                aria-live="polite"
                aria-busy="true"
              >
                <div className="mb-3 flex items-center justify-between gap-3 text-sm font-medium text-stone-800 dark:text-zinc-200">
                  <span>
                    {workType === 'refine' ? 'Refining resume' : 'Generating resume'}
                  </span>
                  <span className="tabular-nums text-stone-500 dark:text-zinc-400">{progressPct}%</span>
                </div>
                <div
                  className="mb-4 h-2 overflow-hidden rounded-full bg-stone-100 dark:bg-zinc-800"
                  aria-hidden="true"
                >
                  <div
                    className="h-full rounded-full bg-stone-800 transition-[width] duration-300 ease-out motion-reduce:transition-none dark:bg-zinc-200"
                    style={{ width: `${progressPct}%` }}
                  />
                </div>
                <ol className="grid gap-1.5 text-xs text-stone-500 dark:text-zinc-500">
                  {WORK_STEPS.map((step, idx) => (
                    <li
                      key={step.id}
                      className={
                        idx < workStep
                          ? 'text-emerald-700 dark:text-emerald-400'
                          : idx === workStep
                            ? 'font-medium text-stone-900 dark:text-zinc-100'
                            : ''
                      }
                    >
                      {step.label}
                    </li>
                  ))}
                </ol>
                {workMessage && (
                  <p className="mt-3 text-xs text-stone-600 dark:text-zinc-400">{workMessage}</p>
                )}
              </div>
            )}

            {ghInfo && (
              <p className="text-sm text-stone-600 dark:text-zinc-400" role="status">
                {ghInfo}
              </p>
            )}
            {error && (
              <p className="text-sm font-medium text-red-700 dark:text-red-400" role="alert">
                {error}
              </p>
            )}

            {resume && (
              <div className="border-t border-dashed border-stone-200 pt-6 dark:border-zinc-800">
                <label
                  htmlFor="refine-text"
                  className="mb-2 block text-xs font-semibold uppercase tracking-wider text-stone-500 dark:text-zinc-500"
                >
                  Refinements (after generate)
                </label>
                <textarea
                  id="refine-text"
                  name="refinement"
                  className={`${fieldClass} min-h-[100px] resize-y`}
                  value={refineText}
                  onChange={(e) => setRefineText(e.target.value)}
                  placeholder="e.g. Fix end date on Company X to 2024; add Docker to skills…"
                  rows={4}
                  spellCheck
                />
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    className={`${btnBase} border border-stone-300 bg-stone-100 text-stone-900 hover:bg-stone-200 focus-visible:ring-stone-400 focus-visible:ring-offset-stone-50 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-100 dark:hover:bg-zinc-700 dark:focus-visible:ring-zinc-500 dark:focus-visible:ring-offset-zinc-950`}
                    disabled={loading || !refineText.trim()}
                    onClick={refine}
                  >
                    {loading && workType === 'refine' ? 'Refining…' : 'Apply refinement'}
                  </button>
                  <button
                    type="button"
                    className={`${btnBase} bg-stone-900 text-white shadow-sm hover:bg-stone-800 focus-visible:ring-stone-500 focus-visible:ring-offset-stone-50 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-950 dark:hover:bg-white dark:focus-visible:ring-zinc-300 dark:focus-visible:ring-offset-zinc-950`}
                    disabled={pdfLoading}
                    onClick={downloadPdf}
                  >
                    {pdfLoading ? 'Preparing PDF…' : 'Download PDF'}
                  </button>
                  <button
                    type="button"
                    className={`${btnBase} border border-stone-200 bg-white text-stone-800 hover:border-stone-300 hover:bg-stone-50 focus-visible:ring-stone-400 focus-visible:ring-offset-stone-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:border-zinc-600 dark:hover:bg-zinc-800 dark:focus-visible:ring-zinc-500 dark:focus-visible:ring-offset-zinc-950`}
                    onClick={printFallback}
                  >
                    Print
                  </button>
                </div>
              </div>
            )}
          </div>
        </section>

        <section className="print-preview border-stone-200 bg-stone-200/80 px-4 py-6 sm:px-6 lg:overflow-auto dark:border-zinc-800 dark:bg-zinc-900/50">
          {resume && (
            <div className="no-print mx-auto mb-5 flex max-w-[820px] items-center justify-between gap-3">
              <span className="text-xs font-semibold uppercase tracking-wider text-stone-500 dark:text-zinc-500">
                Preview — {template}
              </span>
              <button
                type="button"
                className={`${btnBase} bg-stone-900 text-white shadow-sm hover:bg-stone-800 focus-visible:ring-stone-500 focus-visible:ring-offset-stone-200 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-950 dark:hover:bg-white dark:focus-visible:ring-zinc-300 dark:focus-visible:ring-offset-zinc-900`}
                disabled={pdfLoading}
                onClick={downloadPdf}
              >
                <svg aria-hidden="true" viewBox="0 0 20 20" className="mr-2 h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <path d="M10 3v9m0 0 3.5-3.5M10 12 6.5 8.5M4 15h12" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                {pdfLoading ? 'Preparing PDF…' : 'Download PDF'}
              </button>
            </div>
          )}
          <div className="print-preview-wrap mx-auto flex justify-center lg:min-h-[320px]">
            {resume ? (
              <div className="print-scale origin-top scale-[0.92] rounded-sm shadow-[0_20px_50px_-12px_rgba(0,0,0,0.25)] ring-1 ring-black/5 dark:shadow-[0_24px_60px_-12px_rgba(0,0,0,0.55)] dark:ring-white/10">
                <ResumePreview resume={resume} template={template} />
              </div>
            ) : (
              <div className="mt-12 max-w-sm rounded-2xl border border-dashed border-stone-300 bg-white/90 px-6 py-10 text-center text-sm leading-relaxed text-stone-600 dark:border-zinc-700 dark:bg-zinc-900/80 dark:text-zinc-400">
                Generate a resume to see the A4 preview here.
              </div>
            )}
          </div>
        </section>
      </main>
    </div>
  )
}

export default App
