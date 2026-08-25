import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ListingStatusUpdateRequest } from '../../../lib/api/dto'
import { fetchListings, updateListingStatus, type ListingFilters } from '../../../lib/api/jobs'

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
