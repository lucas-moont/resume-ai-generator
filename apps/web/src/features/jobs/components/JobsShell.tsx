import { useMemo, useState } from 'react'
import { useTabUrl } from '../../../app/useMobileTabUrl'
import type { BoardId, ListingStatus, MaxApplicantBand } from '../../../lib/api/dto'
import type { ListingFilters } from '../../../lib/api/jobs'
import { useJobScanMonitor } from '../hooks/useJobScan'
import { BOARD_LABEL, formatScanMoment } from '../listingFormat'
import { BoardStatusBar } from './BoardStatusBar'
import { ListingList } from './ListingList'
import { SearchProfileForm } from './SearchProfileForm'

/** v7 ticket 12: the Job Monitor area's layout, rendered by AppShell when the app mode is
 * 'jobs'. Two columns — what you are looking for (Search Profile + Immediate Scan) on the left,
 * what was found (filters + the ranked list) on the right — the same two-column shape as
 * AnalysisShell, since there is no A4 preview here either.
 */

const JOBS_TABS = ['busca', 'vagas'] as const
type JobsTab = (typeof JOBS_TABS)[number]

const BAND_OPTIONS: MaxApplicantBand[] = ['<10', '<25', '<50', '<100']

const STATUS_OPTIONS: { value: ListingStatus; label: string }[] = [
  { value: 'new', label: 'Novas' },
  { value: 'seen', label: 'Vistas' },
  { value: 'applied', label: 'Candidatei-me' },
  { value: 'dismissed', label: 'Descartadas' },
]

const BOARD_OPTIONS = Object.entries(BOARD_LABEL) as [BoardId, string][]

function tabButtonClass(selected: boolean): string {
  return `rounded-lg px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:focus-visible:ring-zinc-500 ${
    selected
      ? 'bg-stone-900 text-white dark:bg-zinc-100 dark:text-zinc-950'
      : 'text-stone-600 hover:bg-stone-100 dark:text-zinc-400 dark:hover:bg-zinc-800'
  }`
}

const SELECT_CLASS =
  'min-h-[2rem] rounded-lg border border-stone-200 bg-white px-2 py-1 text-xs text-stone-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:focus-visible:ring-zinc-500'

/** What the left column says about scheduling. Only a finished Scan knows `nextScanAt`
 * (it is computed from the interval, and a running Scan has not set the clock yet). */
function nextScanLine(
  isRunning: boolean,
  isLoading: boolean,
  nextScanAt: string | null,
  hasEverScanned: boolean,
): string | null {
  if (isRunning || isLoading) return null
  if (!hasEverScanned) return 'Nenhuma varredura ainda.'
  if (nextScanAt === null) return 'Varredura automática desligada.'
  return `Próxima varredura: ${formatScanMoment(nextScanAt)}`
}

export function JobsShell() {
  const [tab, setTab] = useTabUrl(JOBS_TABS, 'busca')
  const [board, setBoard] = useState<BoardId | ''>('')
  const [maxBand, setMaxBand] = useState<MaxApplicantBand | ''>('')
  const [status, setStatus] = useState<ListingStatus | ''>('')
  // Ticket 13 mounts <ListingDetail listingId={selectedListingId} /> in the slot below; this
  // shell only owns which listing is selected and highlights that card.
  const [selectedListingId, setSelectedListingId] = useState<number | null>(null)

  const { runningScan, latestScan, isLoadingLatest, isStarting, startError, start } =
    useJobScanMonitor()

  const filters: ListingFilters = useMemo(
    () => ({
      ...(board !== '' ? { board } : {}),
      ...(maxBand !== '' ? { maxBand } : {}),
      ...(status !== '' ? { status } : {}),
      // Dismissing hides a listing, so asking for the dismissed ones has to lift that default.
      ...(status === 'dismissed' ? { includeDismissed: true } : {}),
    }),
    [board, maxBand, status],
  )

  const isRunning = runningScan !== null
  const shownScan = runningScan ?? latestScan
  const scheduleLine = nextScanLine(
    isRunning,
    isLoadingLatest,
    latestScan?.nextScanAt ?? null,
    latestScan !== null,
  )

  return (
    <main
      id="main-content"
      className="mx-auto flex w-full min-h-0 max-w-[1920px] flex-1 flex-col lg:flex-row"
    >
      <div
        role="tablist"
        aria-label="Monitor de Vagas"
        className="flex gap-1 border-b border-stone-200 bg-white px-4 py-2 dark:border-zinc-800 dark:bg-zinc-950 lg:hidden"
      >
        {(
          [
            ['busca', 'Busca'],
            ['vagas', 'Vagas'],
          ] as [JobsTab, string][]
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={tab === value}
            onClick={() => setTab(value)}
            className={tabButtonClass(tab === value)}
          >
            {label}
          </button>
        ))}
      </div>

      <section
        aria-label="Busca"
        className={`min-h-0 flex-col overflow-y-auto border-stone-200 bg-white/60 p-4 dark:border-zinc-800 dark:bg-zinc-950/40 lg:flex lg:w-[34%] lg:max-w-[480px] lg:border-r ${
          tab === 'busca' ? 'flex' : 'hidden'
        }`}
      >
        <SearchProfileForm />

        <div className="mt-4 border-t border-stone-200 pt-4 dark:border-zinc-800">
          <button
            type="button"
            onClick={start}
            disabled={isRunning || isStarting}
            className="w-full rounded-lg bg-stone-900 px-3 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-stone-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-950 dark:hover:bg-zinc-200 dark:focus-visible:ring-zinc-500"
          >
            {isRunning || isStarting ? 'Buscando…' : 'Buscar agora'}
          </button>

          {isRunning && (
            <p role="status" className="mt-2 text-xs text-stone-500 dark:text-zinc-400">
              {`Varredura em andamento · ${runningScan.listingsFound} ${
                runningScan.listingsFound === 1 ? 'vaga encontrada' : 'vagas encontradas'
              }`}
            </p>
          )}

          {startError !== null && (
            <p role="alert" className="mt-2 text-xs text-red-600 dark:text-red-400">
              {startError}
            </p>
          )}

          {scheduleLine !== null && (
            <p className="mt-2 text-xs text-stone-500 dark:text-zinc-400">{scheduleLine}</p>
          )}

          <div className="mt-3">
            <BoardStatusBar boards={shownScan?.boards ?? []} />
          </div>
        </div>
      </section>

      <section
        aria-label="Vagas"
        className={`min-h-0 flex-1 flex-col overflow-y-auto p-4 lg:flex ${
          tab === 'vagas' ? 'flex' : 'hidden'
        }`}
      >
        <div className="mb-3 flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-xs font-medium text-stone-600 dark:text-zinc-400">
            Portal
            <select
              value={board}
              onChange={(e) => setBoard(e.target.value as BoardId | '')}
              className={SELECT_CLASS}
            >
              <option value="">Todos</option>
              {BOARD_OPTIONS.map(([id, label]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-xs font-medium text-stone-600 dark:text-zinc-400">
            Máximo de candidatos
            <select
              value={maxBand}
              onChange={(e) => setMaxBand(e.target.value as MaxApplicantBand | '')}
              className={SELECT_CLASS}
            >
              <option value="">Qualquer</option>
              {BAND_OPTIONS.map((band) => (
                <option key={band} value={band}>
                  {band}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-xs font-medium text-stone-600 dark:text-zinc-400">
            Status
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value as ListingStatus | '')}
              className={SELECT_CLASS}
            >
              <option value="">Todos</option>
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <ListingList
          filters={filters}
          selectedListingId={selectedListingId}
          onSelect={setSelectedListingId}
        />
      </section>
    </main>
  )
}
