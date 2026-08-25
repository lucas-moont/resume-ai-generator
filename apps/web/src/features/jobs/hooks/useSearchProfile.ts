import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { SearchProfileDto, SearchProfileUpdateRequest } from '../../../lib/api/dto'
import {
  fetchBoards,
  fetchSearchProfile,
  suggestSearchProfile,
  updateSearchProfile,
} from '../../../lib/api/jobs'

/** v7 ticket 14 — TanStack Query wiring for the Search Profile form.
 *
 * Same idiom as `features/settings/hooks/useSettings.ts`: one thin hook per endpoint, the query
 * keys exported so a sibling feature can invalidate them without re-deriving the tuple.
 */

export const SEARCH_PROFILE_QUERY_KEY = ['jobs', 'search-profile'] as const
export const BOARDS_QUERY_KEY = ['jobs', 'boards'] as const

export function useSearchProfile() {
  return useQuery({ queryKey: SEARCH_PROFILE_QUERY_KEY, queryFn: fetchSearchProfile })
}

/** The board catalog is a server-side registry, not user data: it only changes when the backend
 * ships a new provider, so it never needs a background refetch inside one session. */
export function useBoards() {
  return useQuery({ queryKey: BOARDS_QUERY_KEY, queryFn: fetchBoards, staleTime: Infinity })
}

/** The PUT answers with the saved profile (`updatedAt` refreshed), so the cache is SET from the
 * response rather than invalidated — a refetch would only ask the server to repeat itself. */
export function useUpdateSearchProfile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: SearchProfileUpdateRequest) => updateSearchProfile(payload),
    onSuccess: (saved: SearchProfileDto) => {
      queryClient.setQueryData(SEARCH_PROFILE_QUERY_KEY, saved)
    },
  })
}

/** Deterministic seed from the Profile — nothing is persisted (the response carries
 * `updatedAt: null`), so this deliberately does NOT touch the cache: the suggestion lives in the
 * form's local draft until the user saves it with a normal PUT. */
export function useSuggestSearchProfile() {
  return useMutation({ mutationFn: suggestSearchProfile })
}
