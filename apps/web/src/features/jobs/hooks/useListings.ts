import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ListingStatusUpdateRequest } from '../../../lib/api/dto'
import {
  fetchListing,
  fetchListings,
  updateListingStatus,
  type ListingFilters,
} from '../../../lib/api/jobs'

/** v7 ticket 12 — the ranked list of the last Scan, plus the two quick actions on a card.
 *
 * Query keys share the `['jobs', ...]` root with `useSearchProfile.ts` (ticket 14). The filters
 * object is part of the key: the backend does the filtering and the ordering (always Visibility
 * desc), so each filter combination is a distinct server answer, not a client-side slice.
 */

export const LISTINGS_QUERY_ROOT = ['jobs', 'listings'] as const

export const listingsQueryKey = (filters: ListingFilters) =>
  [...LISTINGS_QUERY_ROOT, filters] as const

export function useListings(filters: ListingFilters = {}) {
  return useQuery({
    queryKey: listingsQueryKey(filters),
    queryFn: () => fetchListings(filters),
    retry: false,
  })
}

/** v7 ticket 13 — ONE listing, with its description and every Listing Source.
 *
 * Deliberately a different query root from the list (`['jobs','listing',id]`, not a child of
 * `LISTINGS_QUERY_ROOT`): opening the detail marks the listing `seen` server-side, so this hook
 * invalidates the list to make the card catch up — and a key under the list root would make that
 * invalidation refetch the detail, which would mark it seen again, forever. */
export const listingQueryKey = (listingId: number) => ['jobs', 'listing', listingId] as const

export function useListing(listingId: number | null) {
  const queryClient = useQueryClient()

  const query = useQuery({
    queryKey: listingQueryKey(listingId ?? -1),
    queryFn: () => fetchListing(listingId as number),
    enabled: listingId !== null,
    retry: false,
  })

  // `GET /listings/{id}` is what flips `new` → `seen` (the backend does it, there is no separate
  // call), so the cards only learn about it if the list is refetched. Once per listing: a
  // refetch of the list must not loop back into another invalidation.
  const seenListingId = useRef<number | null>(null)
  useEffect(() => {
    if (listingId === null || !query.isSuccess) return
    if (seenListingId.current === listingId) return
    seenListingId.current = listingId
    void queryClient.invalidateQueries({ queryKey: LISTINGS_QUERY_ROOT })
  }, [listingId, query.isSuccess, queryClient])

  return query
}

export interface ListingStatusUpdate {
  listingId: number
  status: ListingStatusUpdateRequest['status']
}

/** "Candidatei" / "Descartar" / "Restaurar". The whole list root is invalidated rather than the
 * one row patched in place, because a status change can move a listing OUT of the current
 * filter (dismissing hides it, which is the point of dismissing) — patching would leave a card
 * on screen that the same request just excluded. */
export function useUpdateListingStatus() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ listingId, status }: ListingStatusUpdate) =>
      updateListingStatus(listingId, status),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: LISTINGS_QUERY_ROOT })
    },
  })
}
