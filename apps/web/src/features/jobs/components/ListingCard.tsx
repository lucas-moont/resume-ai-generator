import type { JobListingDto } from '../../../lib/api/dto'
import { useUpdateListingStatus } from '../hooks/useListings'
import {
  applicantBandLabel,
  boardLabel,
  formatPlace,
  formatPostedAt,
  listingStatusLabel,
} from '../listingFormat'

/** v7 ticket 12 — one Job Listing in the ranked list.
 *
 * Selecting the card is the TITLE button, not the whole card: the card also holds one link per
 * Listing Source and two action buttons, and nesting those inside a clickable region is both an
 * a11y violation and a source of accidental clicks. The header button is the big hit target.
 *
 * The detail panel this selects is ticket 13; here it is only `onSelect`.
 */

interface ListingCardProps {
  listing: JobListingDto
  selected: boolean
  onSelect: (listingId: number) => void
}

function Badge({ children, tone, title }: { children: string; tone: string; title?: string }) {
  return (
    <li>
      <span
        title={title}
        className={`inline-block rounded-full px-2 py-0.5 text-[0.6875rem] font-medium ${tone}`}
      >
        {children}
      </span>
    </li>
  )
}

const NEUTRAL = 'bg-stone-100 text-stone-600 dark:bg-zinc-800 dark:text-zinc-300'
const STRONG = 'bg-stone-900 text-white dark:bg-zinc-100 dark:text-zinc-900'
const ACCENT = 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300'
const WARN = 'bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300'

export function ListingCard({ listing, selected, onSelect }: ListingCardProps) {
  const statusMutation = useUpdateListingStatus()
  const busy = statusMutation.isPending

  const setStatus = (status: 'seen' | 'applied' | 'dismissed') => {
    statusMutation.mutate({ listingId: listing.id, status })
  }

  return (
    <li
      aria-current={selected ? 'true' : undefined}
      className={`rounded-xl border bg-white p-3 shadow-sm transition-colors dark:bg-zinc-900 ${
        selected
          ? 'border-stone-900 dark:border-zinc-100'
          : 'border-stone-200 dark:border-zinc-800'
      }`}
    >
      <button
        type="button"
        onClick={() => onSelect(listing.id)}
        className="w-full rounded-lg text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:focus-visible:ring-zinc-500"
      >
        <h3 className="text-sm font-semibold text-stone-900 dark:text-zinc-50">{listing.title}</h3>
        <p className="mt-0.5 text-xs text-stone-600 dark:text-zinc-400">
          {listing.company} · {formatPlace(listing)}
        </p>
        <p className="mt-0.5 text-xs text-stone-400 dark:text-zinc-500">
          {formatPostedAt(listing.datePosted)}
        </p>
      </button>

      <ul className="mt-2 flex flex-wrap items-center gap-1.5">
        <Badge
          tone={STRONG}
          title={
            listing.fitEstimated
              ? 'Fit estimado pelo filtro de palavras-chave — a vaga ficou fora do top pontuado pelo modelo neste Scan.'
              : 'Fit calculado pelo modelo.'
          }
        >
          {`Fit ${listing.fitEstimated ? '~' : ''}${listing.fitScore}%`}
        </Badge>
        <Badge tone={ACCENT} title="Chance de o currículo ser visto: fit + recência + concorrência.">
          {`Visibilidade ${listing.visibilityScore}`}
        </Badge>
        <Badge tone={NEUTRAL}>{applicantBandLabel(listing.applicantBand)}</Badge>
        {listing.isRepost && (
          <Badge tone={WARN} title="Vaga já conhecida que reapareceu com data mais nova.">
            Repostada
          </Badge>
        )}
        <Badge tone={NEUTRAL}>{listingStatusLabel(listing.status)}</Badge>
      </ul>

      <ul aria-label="Fontes" className="mt-2 flex flex-wrap items-center gap-1.5">
        {listing.sources.map((source) => (
          <li key={`${source.board}-${source.url}`}>
            <a
              href={source.url}
              target="_blank"
              rel="noreferrer"
              title={`Abrir a vaga no ${boardLabel(source.board)}`}
              className="inline-block rounded-full border border-stone-200 px-2 py-0.5 text-[0.6875rem] font-medium text-stone-700 hover:bg-stone-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800 dark:focus-visible:ring-zinc-500"
            >
              {boardLabel(source.board)}
            </a>
          </li>
        ))}
      </ul>

      <div className="mt-2 flex flex-wrap gap-2">
        {listing.status !== 'applied' && (
          <button
            type="button"
            disabled={busy}
            onClick={() => setStatus('applied')}
            className="min-h-[1.75rem] rounded-lg border border-stone-200 px-2.5 py-1 text-xs font-medium text-stone-700 hover:bg-stone-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800 dark:focus-visible:ring-zinc-500"
          >
            Candidatei
          </button>
        )}
        {listing.status === 'dismissed' ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => setStatus('seen')}
            className="min-h-[1.75rem] rounded-lg border border-stone-200 px-2.5 py-1 text-xs font-medium text-stone-700 hover:bg-stone-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800 dark:focus-visible:ring-zinc-500"
          >
            Restaurar
          </button>
        ) : (
          <button
            type="button"
            disabled={busy}
            onClick={() => setStatus('dismissed')}
            className="min-h-[1.75rem] rounded-lg border border-stone-200 px-2.5 py-1 text-xs font-medium text-stone-500 hover:bg-stone-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:focus-visible:ring-zinc-500"
          >
            Descartar
          </button>
        )}
      </div>

      {statusMutation.isError && (
        <p role="alert" className="mt-1.5 text-xs text-red-600 dark:text-red-400">
          Não foi possível atualizar o status desta vaga.
        </p>
      )}
    </li>
  )
}
