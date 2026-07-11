import { WORK_STEPS } from '../../workSteps'
import type { StreamingState } from '../../store/chatStore'

// v4, F4: `analyzing_job` (WORK_STEPS[0], added by F3 per spec §3.5) is the Analysis/Proposal
// Turn heartbeat — MessageList swaps in a typing indicator for that step instead of mounting
// this card at all, so `streaming.step` is never `analyzing_job` while ProgressCard is on
// screen. Keeping it in the checklist below would render "Analyzing job description" as
// already-completed on every ordinary generation turn (approve-chain, refine, ...), which
// never went through that step in the first place — excluded from the rendered list here,
// not from WORK_STEPS itself (other consumers still need that entry for its label).
const CHECKLIST_STEPS = WORK_STEPS.filter((step) => step.id !== 'analyzing_job')

export function ProgressCard({ streaming }: { streaming: StreamingState }) {
  const stepIndex = Math.max(
    0,
    CHECKLIST_STEPS.findIndex((s) => s.id === streaming.step),
  )
  const progress = Math.max(0, Math.min(100, Math.round(streaming.progress)))

  return (
    <div
      className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900/60"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <div className="mb-3 flex items-center justify-between gap-3 text-sm font-medium text-stone-800 dark:text-zinc-200">
        <span>Working…</span>
        <span className="tabular-nums text-stone-500 dark:text-zinc-400">{progress}%</span>
      </div>
      <div
        className="mb-4 h-2 overflow-hidden rounded-full bg-stone-100 dark:bg-zinc-800"
        role="progressbar"
        aria-label="Progress"
        aria-valuenow={progress}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className="h-full rounded-full bg-stone-800 transition-[width] duration-300 ease-out motion-reduce:transition-none dark:bg-zinc-200"
          style={{ width: `${progress}%` }}
        />
      </div>
      <ol className="grid gap-1.5 text-xs text-stone-500 dark:text-zinc-500">
        {CHECKLIST_STEPS.map((step, idx) => (
          <li
            key={step.id}
            className={
              idx < stepIndex
                ? 'text-emerald-700 dark:text-emerald-400'
                : idx === stepIndex
                  ? 'font-medium text-stone-900 dark:text-zinc-100'
                  : ''
            }
          >
            {step.label}
          </li>
        ))}
      </ol>
      {streaming.message && (
        <p className="mt-3 text-xs text-stone-600 dark:text-zinc-400">{streaming.message}</p>
      )}
    </div>
  )
}
