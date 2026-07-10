import type { ReactNode } from 'react'

/** Shared visual shell for chat cards confirming a change already applied —
 * emerald badge + check icon. Used by ResumeUpdatedCard and
 * ProfileUpdateAppliedCard; purely presentational, callers own all text. */
export function SuccessBadge({ children }: { children: ReactNode }) {
  return (
    <div className="mt-2 flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300">
      <svg aria-hidden="true" viewBox="0 0 20 20" className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="m4 10 4 4 8-8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span>{children}</span>
    </div>
  )
}
