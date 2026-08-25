import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ScanDto } from '../../../lib/api/dto'
import { ApiError } from '../../../lib/api/client'
import {
  fetchCurrentScan,
  fetchLatestScan,
  ScanInProgressError,
  startScan,
} from '../../../lib/api/jobs'
import { LISTINGS_QUERY_ROOT } from './useListings'

/** v7 ticket 12 — "Buscar agora" and the polling behind it.
 *
 * There is no push channel for a Scan (it is a background asyncio task, not an SSE turn), so the
 * UI polls `GET /scans/current` while one holds the single-flight lock and stops the moment it
 * answers "none". `GET /scans/latest` is a separate query because it survives the Scan: the
 * Board Status flags and `nextScanAt` are read off the last FINISHED Scan.
 */

export const CURRENT_SCAN_QUERY_KEY = ['jobs', 'scan', 'current'] as const
export const LATEST_SCAN_QUERY_KEY = ['jobs', 'scan', 'latest'] as const

/** Poll cadence while a Scan runs. A Scan takes tens of seconds (several boards, then the LLM
 * fit pass), so this is about the board statuses filling in, not about latency. */
export const SCAN_POLL_INTERVAL_MS = 2000

export interface JobScanMonitor {
  /** The Scan holding the lock right now, or `null`. Non-null is the whole "is it running?" test. */
  runningScan: ScanDto | null
  /** The most recent FINISHED Scan (`GET /scans/latest`) — source of `nextScanAt` and, once
   * nothing is running, of the Board Status flags. Callers show `runningScan ?? latestScan`:
   * a running Scan's `boards` fills in live, which is the more useful of the two. */
  latestScan: ScanDto | null
  /** True before the first `GET /scans/latest` answers, so the UI can hold off on "nunca varreu". */
  isLoadingLatest: boolean
  isStarting: boolean
  /** A message worth showing. A 409 is NOT one: it means a Scan is already running, which is
   * exactly what the user asked for, so it is absorbed into the polling state instead. */
  startError: string | null
  start: () => void
}

function startErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return typeof error.detail === 'string' && error.detail.trim() !== ''
      ? error.detail
      : 'Não foi possível iniciar a varredura.'
  }
  return 'Não foi possível falar com a API (o backend está rodando?).'
}

export function useJobScanMonitor(): JobScanMonitor {
  const queryClient = useQueryClient()

  const current = useQuery({
    queryKey: CURRENT_SCAN_QUERY_KEY,
    queryFn: fetchCurrentScan,
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.status === 'running' ? SCAN_POLL_INTERVAL_MS : false,
  })

  const latest = useQuery({
    queryKey: LATEST_SCAN_QUERY_KEY,
    queryFn: fetchLatestScan,
    retry: false,
  })

  const runningScan = current.data?.status === 'running' ? current.data : null
  const isRunning = runningScan !== null

  // A finished Scan REPLACES the listing table wholesale (the list IS the last Scan), and only
  // then does `nextScanAt` exist. Nothing tells us it finished except `/scans/current` going
  // quiet, so that transition is what refetches both.
  const wasRunning = useRef(false)
  useEffect(() => {
    if (isRunning) {
      wasRunning.current = true
      return
    }
    if (!wasRunning.current) return
    wasRunning.current = false
    void queryClient.invalidateQueries({ queryKey: LISTINGS_QUERY_ROOT })
    void queryClient.invalidateQueries({ queryKey: LATEST_SCAN_QUERY_KEY })
  }, [isRunning, queryClient])

  const startMutation = useMutation({
    mutationFn: startScan,
    // Seeding the cache instead of invalidating starts the polling on THIS render rather than a
    // round-trip later, so the button flips to "Buscando…" immediately.
    onSuccess: (scan) => {
      queryClient.setQueryData(CURRENT_SCAN_QUERY_KEY, scan)
    },
    onError: (error) => {
      if (error instanceof ScanInProgressError && error.scan !== null) {
        queryClient.setQueryData(CURRENT_SCAN_QUERY_KEY, error.scan)
      }
    },
  })

  const absorbedConflict =
    startMutation.error instanceof ScanInProgressError && startMutation.error.scan !== null

  return {
    runningScan,
    latestScan: latest.data ?? null,
    isLoadingLatest: latest.isLoading,
    isStarting: startMutation.isPending,
    startError:
      startMutation.error == null || absorbedConflict
        ? null
        : startErrorMessage(startMutation.error),
    start: () => startMutation.mutate(),
  }
}
