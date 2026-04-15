import { useCallback, useLayoutEffect, useMemo, useState } from 'react'
import { ResumePreview } from './components/ResumePreview'
import type { ResumeDocument } from './types/resume'

const DEFAULT_MODEL = 'llama3.2'
const WORK_STEPS = [
  { id: 'preparing_context', label: 'Preparing context' },
  { id: 'extracting_profile_pdf', label: 'Extracting profile from PDF' },
  { id: 'calling_ai', label: 'Calling AI model' },
  { id: 'validating_response', label: 'Validating response' },
  { id: 'finalizing', label: 'Finalizing' },
]
type WorkType = 'generate' | 'refine' | null
type StreamStage = { step: string; progress?: number; message?: string }
type StreamDone = { progress?: number; resume: ResumeDocument }
type StreamError = { message?: string }

type Theme = 'light' | 'dark'

function readStoredTheme(): Theme {
  try {
    const s = localStorage.getItem('theme')
    if (s === 'light' || s === 'dark') return s
  } catch {
    /* ignore */
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function ThemeToggle({ theme, onChange }: { theme: Theme; onChange: (t: Theme) => void }) {
  const isDark = theme === 'dark'
  return (
    <button
      type="button"
      onClick={() => onChange(isDark ? 'light' : 'dark')}
      className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-stone-200 bg-white text-stone-700 shadow-sm transition-[color,background-color,border-color,box-shadow] hover:border-stone-300 hover:bg-stone-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 focus-visible:ring-offset-2 focus-visible:ring-offset-stone-100 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:border-zinc-600 dark:hover:bg-zinc-800 dark:focus-visible:ring-zinc-500 dark:focus-visible:ring-offset-zinc-950"
      aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
    >
      {isDark ? (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path
            d="M12 18a6 6 0 1 0 0-12 6 6 0 0 0 0 12Z"
            stroke="currentColor"
            strokeWidth="1.75"
          />
          <path
            d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinecap="round"
          />
        </svg>
      ) : (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path
            d="M21 14.5A8.5 8.5 0 0 1 9.5 3a8.5 8.5 0 1 0 12 11.5Z"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinejoin="round"
          />
        </svg>
      )}
    </button>
  )
}

function App() {
  const [theme, setTheme] = useState<Theme>(() =>
    typeof window !== 'undefined' ? readStoredTheme() : 'light',
  )
  const [jobDescription, setJobDescription] = useState('')
  const [model, setModel] = useState(DEFAULT_MODEL)
  const [locale, setLocale] = useState('pt-BR')
  const [resume, setResume] = useState<ResumeDocument | null>(null)
  const [refineText, setRefineText] = useState('')
  const [loading, setLoading] = useState(false)
  const [workType, setWorkType] = useState<WorkType>(null)
  const [workStep, setWorkStep] = useState(0)
  const [workProgress, setWorkProgress] = useState(0)
  const [workMessage, setWorkMessage] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [ghInfo, setGhInfo] = useState<string | null>(null)

  useLayoutEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
  }, [theme])

  const applyTheme = useCallback((next: Theme) => {
    setTheme(next)
    try {
      localStorage.setItem('theme', next)
    } catch {
      /* ignore */
    }
  }, [])

  const progressPct = useMemo(() => (loading ? workProgress : 0), [loading, workProgress])

  const stepIndexFromId = useCallback((stepId: string) => {
    const idx = WORK_STEPS.findIndex((s) => s.id === stepId)
    return idx >= 0 ? idx : 0
  }, [])

  const runStreamRequest = useCallback(
    async (
      url: string,
      payload: unknown,
      onDone: (resume: ResumeDocument) => void,
    ) => {
      const r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!r.ok || !r.body) {
        const data = await r.json().catch(() => ({}))
        throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail))
      }
      const reader = r.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() ?? ''
        for (const chunk of parts) {
          const lines = chunk.split('\n')
          const eventLine = lines.find((l) => l.startsWith('event:'))
          const dataLine = lines.find((l) => l.startsWith('data:'))
          if (!eventLine || !dataLine) continue
          const event = eventLine.replace('event:', '').trim()
          const raw = dataLine.replace('data:', '').trim()
          if (!raw) continue
          const parsed = JSON.parse(raw) as StreamStage | StreamDone | StreamError
          if (event === 'stage') {
            const s = parsed as StreamStage
            setWorkStep(stepIndexFromId(s.step))
            setWorkProgress(Math.max(5, Math.min(99, Math.round(s.progress ?? 0))))
            setWorkMessage(s.message ?? '')
          } else if (event === 'done') {
            const d = parsed as StreamDone
            setWorkProgress(Math.round(d.progress ?? 100))
            setWorkStep(WORK_STEPS.length - 1)
            setWorkMessage('Done')
            onDone(d.resume)
          } else if (event === 'error') {
            const err = parsed as StreamError
            throw new Error(err.message || 'Stream failed')
          }
        }
      }
    },
    [stepIndexFromId],
  )

  const checkGithub = useCallback(async () => {
    setGhInfo(null)
    try {
      const r = await fetch('/api/github/repos')
      const data = await r.json()
      if (!r.ok) {
        setGhInfo(data.detail ?? 'GitHub check failed')
        return
      }
      if (data.warning) setGhInfo(data.warning)
      else if (!data.repos?.length) setGhInfo('No repositories in response.')
      else setGhInfo(`Loaded ${data.repos.length} repos from GitHub.`)
    } catch {
      setGhInfo('Could not reach API (is the backend running?)')
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
      await runStreamRequest(
        '/api/generate/stream',
        {
          job_description: jobDescription,
          model: model || undefined,
          locale: locale || undefined,
        },
        (nextResume) => setResume(nextResume),
      )
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
      await runStreamRequest(
        '/api/refine/stream',
        {
          resume,
          message: refineText,
          model: model || undefined,
        },
        (nextResume) => setResume(nextResume),
      )
      setRefineText('')
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  const downloadPdf = async () => {
    if (!resume) return
    setError(null)
    try {
      const r = await fetch('/api/export/pdf', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ resume }),
      })
      if (!r.ok) {
        const data = await r.json().catch(() => ({}))
        setError(data.detail ?? 'PDF export failed')
        return
      }
      const blob = await r.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'curriculo.pdf'
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(String(e))
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
              Local Ollama · FastAPI · ATS-friendly layout
            </p>
          </div>
          <ThemeToggle theme={theme} onChange={applyTheme} />
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
                  htmlFor="ollama-model"
                  className="mb-2 block text-xs font-semibold uppercase tracking-wider text-stone-500 dark:text-zinc-500"
                >
                  Ollama model
                </label>
                <input
                  id="ollama-model"
                  name="model"
                  type="text"
                  autoComplete="off"
                  spellCheck={false}
                  className={fieldClass}
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                />
              </div>
              <div>
                <label
                  htmlFor="locale"
                  className="mb-2 block text-xs font-semibold uppercase tracking-wider text-stone-500 dark:text-zinc-500"
                >
                  Locale
                </label>
                <select
                  id="locale"
                  name="locale"
                  className={fieldClass}
                  value={locale}
                  onChange={(e) => setLocale(e.target.value)}
                >
                  <option value="pt-BR">pt-BR</option>
                  <option value="en">en</option>
                </select>
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
                    className={`${btnBase} bg-stone-900 text-white shadow-sm hover:bg-stone-800 focus-visible:ring-stone-500 focus-visible:ring-offset-stone-50 dark:bg-zinc-100 dark:text-zinc-950 dark:hover:bg-white dark:focus-visible:ring-zinc-300 dark:focus-visible:ring-offset-zinc-950`}
                    onClick={downloadPdf}
                  >
                    Download PDF
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
          <div className="print-preview-wrap mx-auto flex justify-center lg:min-h-[320px]">
            {resume ? (
              <div className="print-scale origin-top scale-[0.92] rounded-sm shadow-[0_20px_50px_-12px_rgba(0,0,0,0.25)] ring-1 ring-black/5 dark:shadow-[0_24px_60px_-12px_rgba(0,0,0,0.55)] dark:ring-white/10">
                <ResumePreview resume={resume} />
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
