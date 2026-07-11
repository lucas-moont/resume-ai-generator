import { SuccessBadge } from './SuccessBadge'
import type { ResumeUpdatedCard as ResumeUpdatedCardData } from '../../store/chatStore'
import { SECTION_LABELS } from '../../../resume/resumeDiff'

export function ResumeUpdatedCard({ card }: { card: ResumeUpdatedCardData }) {
  const diff = card.diff
  const sectionLabels = card.changedSections.map((s) => SECTION_LABELS[s] ?? s)
  return (
    <>
      <SuccessBadge>
        Resume updated · see the preview
        {/* Label-only fallback: what today's behavior degrades to when there's no
            "before" to diff against (history reload) or the diff is simply empty. */}
        {!diff && sectionLabels.length > 0 && (
          <span className="text-emerald-700/80 dark:text-emerald-400/80"> ({sectionLabels.join(', ')})</span>
        )}
      </SuccessBadge>
      {diff && diff.length > 0 && (
        <ul className="mt-1.5 space-y-1 rounded-xl border border-emerald-100 bg-emerald-50/60 px-3 py-2 text-xs dark:border-emerald-900/60 dark:bg-emerald-950/20">
          {diff.map((change) => (
            <li key={change.key} className="flex flex-wrap items-baseline gap-1.5">
              <span className="font-medium text-emerald-900 dark:text-emerald-200">{change.label}:</span>
              {change.before === null ? (
                <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[0.6875rem] font-medium uppercase tracking-wide text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-300">
                  added
                </span>
              ) : (
                <>
                  <span className="text-stone-500 line-through dark:text-zinc-500">{change.before}</span>
                  <span aria-hidden="true" className="text-emerald-700/80 dark:text-emerald-400/80">
                    →
                  </span>
                </>
              )}
              <span className="text-emerald-900 dark:text-emerald-200">{change.after}</span>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}
