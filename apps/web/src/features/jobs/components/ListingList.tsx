import type { ListingFilters } from '../../../lib/api/jobs'
import { useListings } from '../hooks/useListings'
import { ListingCard } from './ListingCard'

/** v7 ticket 12 — the ranked list itself. The order is the server's (Visibility Score desc,
 * always) and so is the filtering: this component never re-sorts or re-slices what it gets. */

interface ListingListProps {
  filters: ListingFilters
  selectedListingId: number | null
  onSelect: (listingId: number) => void
}

const HINT_CLASS = 'px-1 py-6 text-sm text-stone-500 dark:text-zinc-400'

export function ListingList({ filters, selectedListingId, onSelect }: ListingListProps) {
  const { data, isLoading, isError } = useListings(filters)

  if (isLoading) {
    return (
      <p role="status" className={HINT_CLASS}>
        Carregando vagas…
      </p>
    )
  }

  if (isError) {
    return (
      <p role="alert" className={HINT_CLASS}>
        Não foi possível carregar as vagas.
      </p>
    )
  }

  const listings = data?.listings ?? []

  if (listings.length === 0) {
    return (
      <p role="status" className={HINT_CLASS}>
        Nenhuma vaga na última varredura com esses filtros.
      </p>
    )
  }

  return (
    <ul aria-label="Vagas encontradas" className="flex flex-col gap-2">
      {listings.map((listing) => (
        <ListingCard
          key={listing.id}
          listing={listing}
          selected={listing.id === selectedListingId}
          onSelect={onSelect}
        />
      ))}
    </ul>
  )
}
