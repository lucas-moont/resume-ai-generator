import type { ApplicantBand, BoardId, JobListingDto, ListingStatus } from '../../lib/api/dto'

/** v7 ticket 12 — the pure copy/formatting rules the Job Monitor's cards and status bar share.
 * Kept out of the .tsx files so they can be exported and unit-tested without tripping
 * `react-refresh/only-export-components`. */

/** Display name per Job Board.
 *
 * `GET /api/jobs/boards` is the backend's catalog and carries the same names, but a Listing
 * Source chip has to render WITH its card — waiting on a second request to name a link the user
 * can already click is the worse trade. `BoardId` is a closed union (dto.ts), so widening it
 * fails to compile until a name is added here; the `??` is for the runtime case only (a backend
 * that ships a board before the frontend's union knows it), where the raw id still beats blank. */
export const BOARD_LABEL: Record<BoardId, string> = {
  linkedin: 'LinkedIn',
  indeed: 'Indeed',
  glassdoor: 'Glassdoor',
  google: 'Google Jobs',
  remotive: 'Remotive',
  weworkremotely: 'We Work Remotely',
  remoteok: 'Remote OK',
}

export function boardLabel(board: BoardId): string {
  return BOARD_LABEL[board] ?? board
}

/** Bands are shown as the band, never as a count (CONTEXT.md: Applicant Band). `'unknown'` is
 * "not reported", NOT "zero" — every board but LinkedIn is silent about this. */
const APPLICANT_BAND_LABEL: Record<ApplicantBand, string> = {
  '<10': '<10 candidatos',
  '<25': '<25 candidatos',
  '<50': '<50 candidatos',
  '<100': '<100 candidatos',
  '100+': '100+ candidatos',
  unknown: 'candidatos: n/d',
}

export function applicantBandLabel(band: ApplicantBand): string {
  return APPLICANT_BAND_LABEL[band] ?? APPLICANT_BAND_LABEL.unknown
}

const LISTING_STATUS_LABEL: Record<ListingStatus, string> = {
  new: 'Nova',
  seen: 'Vista',
  applied: 'Candidatei-me',
  dismissed: 'Descartada',
}

export function listingStatusLabel(status: ListingStatus): string {
  return LISTING_STATUS_LABEL[status] ?? status
}

/** Where the job is, as one line. `isRemote` is a flag, `location` is free text from the board,
 * and the two overlap constantly ("Remote" + remote flag) — appending "Remoto" to a location
 * that already says so would read as a stutter, so it is only added when it tells the user
 * something the location text did not. */
export function formatPlace(listing: Pick<JobListingDto, 'location' | 'isRemote'>): string {
  const location = listing.location?.trim() ?? ''
  const alreadySaysRemote = /remot/i.test(location)
  if (listing.isRemote && (location === '' || alreadySaysRemote)) return location || 'Remoto'
  if (listing.isRemote) return `${location} · Remoto`
  return location || 'Local não informado'
}

const MINUTE_MS = 60_000
const HOUR_MS = 60 * MINUTE_MS
const DAY_MS = 24 * HOUR_MS

/** Coarse "how fresh is this queue" line. Recency is a third of the Visibility Score, so the
 * card states it in words rather than making the user decode a rank. A Repost is labelled by
 * its own badge, not here: `datePosted` already carries the newer date. */
export function formatPostedAt(iso: string | null, now: number = Date.now()): string {
  if (iso === null) return 'data não informada'
  const posted = new Date(iso).getTime()
  if (Number.isNaN(posted)) return 'data não informada'
  const diffMs = now - posted
  if (diffMs < HOUR_MS) return 'publicada há menos de 1h'
  if (diffMs < DAY_MS) return `publicada há ${Math.floor(diffMs / HOUR_MS)}h`
  const days = Math.floor(diffMs / DAY_MS)
  return days === 1 ? 'publicada há 1 dia' : `publicada há ${days} dias`
}

const DATE_TIME_FORMAT = new Intl.DateTimeFormat('pt-BR', {
  dateStyle: 'short',
  timeStyle: 'short',
})

export function formatScanMoment(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : DATE_TIME_FORMAT.format(date)
}
