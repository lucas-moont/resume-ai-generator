import type { ErrorCard as ErrorCardData } from '../../store/chatStore'

export function ErrorCard({ card, onRetry }: { card: ErrorCardData; onRetry: (message: string) => void }) {
  return (
    <div
      role="alert"
      className="mt-2 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300"
    >
      <span>{card.message}</span>
      <button
        type="button"
        onClick={() => onRetry(card.retryMessage)}
        className="inline-flex shrink-0 items-center rounded-lg border border-red-300 bg-white px-2.5 py-1 text-xs font-medium text-red-800 hover:bg-red-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400 dark:border-red-800 dark:bg-zinc-900 dark:text-red-300 dark:hover:bg-red-950/60"
      >
        Retry
      </button>
    </div>
  )
}
