import type { BoardStatusDto } from '../../../lib/api/dto'
import { boardLabel } from '../listingFormat'

/** v7 ticket 12 — how each Job Board fared in the Scan being shown.
 *
 * A Scan is PARTIAL, never failed (CONTEXT.md: Scan): one board blocking does not invalidate the
 * others' results, so this is a flag strip, not an error banner. It says what happened and what
 * happens next ("tentamos na próxima varredura") because the user's only real question is
 * whether the missing board is coming back.
 */

const STATUS_CLASS: Record<BoardStatusDto['status'], string> = {
  ok: 'border-stone-200 bg-white text-stone-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300',
  blocked: 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300',
  error: 'border-red-200 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300',
  skipped: 'border-stone-200 bg-stone-50 text-stone-500 dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-400',
}

function summaryLine(entry: BoardStatusDto): string {
  const label = boardLabel(entry.board)
  switch (entry.status) {
    case 'ok':
      return `${label}: ${entry.count} ${entry.count === 1 ? 'vaga' : 'vagas'}`
    case 'blocked':
      return `${label}: bloqueado, tentamos na próxima varredura`
    case 'error':
      return `${label}: falhou, tentamos na próxima varredura`
    case 'skipped':
      // The backend's message carries the board's own minimum ("Intervalo mínimo de 6h ainda não
      // passou."); the fallback only has to say the shape of the reason.
      return `${label}: pulado, intervalo mínimo do portal ainda não passou`
  }
}

export function BoardStatusBar({ boards }: { boards: BoardStatusDto[] }) {
  if (boards.length === 0) return null

  return (
    <ul
      aria-label="Status dos portais"
      className="flex flex-col gap-1.5"
    >
      {boards.map((entry) => (
        <li
          key={entry.board}
          className={`rounded-lg border px-2.5 py-1.5 text-xs leading-relaxed ${STATUS_CLASS[entry.status]}`}
        >
          <span className="font-medium">{summaryLine(entry)}</span>
          {entry.status !== 'ok' && entry.message != null && entry.message !== '' && (
            <span className="mt-0.5 block opacity-80">{entry.message}</span>
          )}
        </li>
      ))}
    </ul>
  )
}
