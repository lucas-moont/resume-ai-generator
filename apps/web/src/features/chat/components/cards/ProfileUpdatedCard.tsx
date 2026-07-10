import { useState } from 'react'
import type { ProfileUpdatedCard as ProfileUpdatedCardData } from '../../store/chatStore'

const GENERIC_ACTION_ERROR = "Something went wrong — couldn't save that. Try again."

const NEUTRAL_PALETTE =
  'border-stone-200 bg-stone-50 text-stone-600 dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-400'

/** Exhaustive by construction: adding a SourceDocumentStatus value without
 * handling it here is a compile error (`never`), not a silent fallback —
 * `stored`/`extracted` are pre-merge states that never carry a diffSummary
 * yet, so a default case would otherwise render a misleading "proposed" or
 * "nothing new" for them. */
function assertUnreachable(value: never): never {
  throw new Error(`Unhandled ProfileUpdatedCard status: ${String(value)}`)
}

function statusPalette(status: ProfileUpdatedCardData['status']): string {
  switch (status) {
    case 'stored':
    case 'extracted':
      return NEUTRAL_PALETTE
    case 'proposed':
      return 'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300'
    case 'applied':
      return 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300'
    case 'rejected':
      return NEUTRAL_PALETTE
    case 'failed':
      return 'border-red-200 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300'
    default:
      return assertUnreachable(status)
  }
}

function statusHeadline(status: ProfileUpdatedCardData['status']): string {
  switch (status) {
    case 'stored':
      return 'Uploading…'
    case 'extracted':
      return 'Reviewing this document…'
    case 'proposed':
      return 'Profile update proposed'
    case 'applied':
      return 'Applied to your profile'
    case 'rejected':
      return 'Discarded'
    case 'failed':
      return "Couldn't read this file"
    default:
      return assertUnreachable(status)
  }
}

export function ProfileUpdatedCard({
  card,
  onApprove,
  onReject,
}: {
  card: ProfileUpdatedCardData
  onApprove: (documentId: number) => Promise<void>
  onReject: (documentId: number) => Promise<void>
}) {
  const [pending, setPending] = useState<'approve' | 'reject' | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  /** Both actions are the same shape (set pending, run it, show a generic
   * error on failure, always clear pending) — approve/reject only differ in
   * which async call they run, so that's the one thing each button passes in. */
  const runAction = async (kind: 'approve' | 'reject', action: (documentId: number) => Promise<void>) => {
    setPending(kind)
    setActionError(null)
    try {
      await action(card.documentId)
    } catch {
      setActionError(GENERIC_ACTION_ERROR)
    } finally {
      setPending(null)
    }
  }

  const isPreMerge = card.status === 'stored' || card.status === 'extracted'
  const isProposed = card.status === 'proposed'
  const hasChanges = card.diffSummary.length > 0

  return (
    <div className={`mt-2 rounded-xl border px-3 py-2.5 text-sm ${statusPalette(card.status)}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">{statusHeadline(card.status)}</span>
        <span className="truncate text-xs opacity-80" title={card.filename}>
          {card.filename}
        </span>
      </div>

      {card.status === 'failed' && card.error && <p className="mt-1.5 text-xs">{card.error}</p>}

      {isPreMerge && (
        <p className="mt-1.5 text-xs opacity-80">This document hasn't been compared to your profile yet.</p>
      )}

      {!isPreMerge && card.status !== 'failed' && (
        <>
          {hasChanges ? (
            <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-xs opacity-90">
              {card.diffSummary.map((line, idx) => (
                <li key={idx}>{line}</li>
              ))}
            </ul>
          ) : (
            <p className="mt-1.5 text-xs opacity-80">Nothing new — this matches your current profile.</p>
          )}
          {hasChanges && (
            <p className="mt-1 text-xs font-medium opacity-80">
              {card.opsCount} {card.opsCount === 1 ? 'change' : 'changes'} proposed
            </p>
          )}
        </>
      )}

      {actionError && (
        <p role="alert" className="mt-1.5 text-xs font-medium text-red-700 dark:text-red-400">
          {actionError}
        </p>
      )}

      {isProposed && (
        <div className="mt-2 flex gap-2">
          <button
            type="button"
            onClick={() => runAction('approve', onApprove)}
            disabled={pending !== null}
            className="inline-flex items-center rounded-lg bg-amber-900 px-2.5 py-1 text-xs font-medium text-white shadow-sm hover:bg-amber-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 disabled:pointer-events-none disabled:opacity-50 dark:bg-amber-200 dark:text-amber-950 dark:hover:bg-amber-100"
          >
            Approve
          </button>
          <button
            type="button"
            onClick={() => runAction('reject', onReject)}
            disabled={pending !== null}
            className="inline-flex items-center rounded-lg border border-amber-300 bg-white px-2.5 py-1 text-xs font-medium text-amber-900 shadow-sm hover:bg-amber-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 disabled:pointer-events-none disabled:opacity-50 dark:border-amber-800 dark:bg-zinc-900 dark:text-amber-300 dark:hover:bg-amber-950/60"
          >
            Reject
          </button>
        </div>
      )}
    </div>
  )
}
