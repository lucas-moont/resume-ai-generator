import { useCallback, useMemo, useState } from 'react'
import { ResumePreview } from './components/ResumePreview'
import type { ResumeDocument } from './types/resume'
import './App.css'

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

function App() {
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

  return (
    <div className="app-shell">
      <header className="app-top">
        <h1 className="app-title">Resume agent</h1>
        <p className="app-sub">Local Ollama · FastAPI · ATS-friendly layout</p>
      </header>
      <div className="split">
        <section className="panel panel-left">
          <label className="field-label">Job description</label>
          <textarea
            className="job-input"
            value={jobDescription}
            onChange={(e) => setJobDescription(e.target.value)}
            placeholder="Paste the full job posting here…"
            rows={14}
          />
          <div className="row">
            <label className="field-label inline">
              Ollama model
              <input
                className="text-input"
                value={model}
                onChange={(e) => setModel(e.target.value)}
              />
            </label>
            <label className="field-label inline">
              Locale
              <select
                className="text-input"
                value={locale}
                onChange={(e) => setLocale(e.target.value)}
              >
                <option value="pt-BR">pt-BR</option>
                <option value="en">en</option>
              </select>
            </label>
          </div>
          <div className="btn-row">
            <button
              type="button"
              className="btn primary"
              disabled={loading || !jobDescription.trim()}
              onClick={generate}
            >
              {loading && workType === 'generate' ? 'Generating…' : 'Generate resume'}
            </button>
            <button type="button" className="btn ghost" onClick={checkGithub}>
              Test GitHub
            </button>
          </div>
          {loading && (
            <div className="progress-card" role="status" aria-live="polite">
              <div className="progress-head">
                <span>{workType === 'refine' ? 'Refining resume' : 'Generating resume'}</span>
                <span>{progressPct}%</span>
              </div>
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${progressPct}%` }} />
              </div>
              <ol className="step-list">
                {WORK_STEPS.map((step, idx) => (
                  <li
                    key={step.id}
                    className={idx < workStep ? 'done' : idx === workStep ? 'active' : ''}
                  >
                    {step.label}
                  </li>
                ))}
              </ol>
              {workMessage && <p className="hint progress-hint">{workMessage}</p>}
            </div>
          )}
          {ghInfo && <p className="hint">{ghInfo}</p>}
          {error && <p className="error">{error}</p>}

          {resume && (
            <div className="refine-block">
              <label className="field-label">Refinements (after generate)</label>
              <textarea
                className="job-input small"
                value={refineText}
                onChange={(e) => setRefineText(e.target.value)}
                placeholder="e.g. Fix end date on Company X to 2024; add Docker to skills…"
                rows={4}
              />
              <div className="btn-row">
                <button
                  type="button"
                  className="btn secondary"
                  disabled={loading || !refineText.trim()}
                  onClick={refine}
                >
                  {loading && workType === 'refine' ? 'Refining…' : 'Apply refinement'}
                </button>
                <button
                  type="button"
                  className="btn primary"
                  onClick={downloadPdf}
                >
                  Download PDF
                </button>
                <button type="button" className="btn ghost" onClick={printFallback}>
                  Print
                </button>
              </div>
            </div>
          )}
        </section>
        <section className="panel panel-right">
          <div className="preview-wrap">
            {resume ? (
              <ResumePreview resume={resume} />
            ) : (
              <div className="preview-placeholder">
                Generate a resume to see the A4 preview here.
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}

export default App
