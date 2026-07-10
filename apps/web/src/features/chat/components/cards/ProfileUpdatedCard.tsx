import { useState } from 'react'
import type { ProfileUpdatedCard as ProfileUpdatedCardData } from '../../store/chatStore'

const GENERIC_ACTION_ERROR = "Something went wrong — couldn't save that. Try again."

function statusPalette(status: ProfileUpdatedCardData['status']) {
  switch (status) {
    case 'applied':
      return 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300'
    case 'rejected':
      return 'border-stone-200 bg-stone-50 text-stone-600 dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-400'
    case 'failed':
      return 'border-red-200 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300'
    default:
      return 'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300'
  }
}

function statusHeadline(status: ProfileUpdatedCardData['status']) {
  switch (status) {
    case 'applied':
      return 'Applied to your profile'
    case 'rejected':
      return 'Discarded'
    case 'failed':
      return "Couldn't read this file"
    default:
      return 'Profile update proposed'
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

  const handleApprove = async () => {
    setPending('approve')
    setActionError(null)
    try {
      await onApprove(card.documentId)
    } catch {
      setActionError(GENERIC_ACTION_ERROR)
    } finally {
      setPending(null)
    }
  }

  const handleReject = async () => {
    setPending('reject')
    setActionError(null)
    try {
      await onReject(card.documentId)
    } catch {
      setActionError(GENERIC_ACTION_ERROR)
    } finally {
      setPending(null)
    }
  }

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

      {card.status !== 'failed' && (
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
            onClick={handleApprove}
            disabled={pending !== null}
            className="inline-flex items-center rounded-lg bg-amber-900 px-2.5 py-1 text-xs font-medium text-white shadow-sm hover:bg-amber-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 disabled:pointer-events-none disabled:opacity-50 dark:bg-amber-200 dark:text-amber-950 dark:hover:bg-amber-100"
          >
            Approve
          </button>
          <button
            type="button"
            onClick={handleReject}
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
