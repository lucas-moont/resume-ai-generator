// --- Job Monitor (v7, ticket 11) — HTTP client for /api/jobs/* ---
//
// Wire shapes are frozen in `./dto.ts` (ticket 01); the endpoints are `docs/v7-job-monitor.md`
// §Backend-6. Same discipline as `endpoints.ts`: one thin function per endpoint, no caching and
// no state — TanStack Query owns both (tickets 12-14).
//
// Casing follows the frozen contract: bodies are camelCase, QUERY PARAMS are snake_case
// (`?max_band=`, `?include_dismissed=1`), which is why the filters object below is translated
// field by field instead of being spread into URLSearchParams.

import type {
  BoardId,
  BoardListResponse,
  JobListingDto,
  JobListingListResponse,
  ListingStatus,
  ListingStatusUpdateRequest,
  MaxApplicantBand,
  OpenInChatResponse,
  ScanDto,
  SearchProfileDto,
  SearchProfileUpdateRequest,
} from './dto'
import { ApiError, postInit, putInit, requestBlob, requestJson } from './client'

const BASE = '/api/jobs'

/** `GET /scans/current` and `GET /scans/latest` answer "no Scan at all" — a fresh install has
 * never scanned, and nothing is running most of the time. `requestJson` would blow up on a 204's
 * empty body, so this tolerates BOTH ways a backend can say "none": a 204, or a 200 whose body is
 * the JSON literal `null`. Any other non-2xx still raises `ApiError` unchanged. */
async function requestJsonOrNull<T>(path: string): Promise<T | null> {
  const response = await fetch(path)
  if (!response.ok) {
    const data = (await response.json().catch(() => ({}))) as { detail?: unknown }
    throw new ApiError(data.detail, response.status)
  }
  if (response.status === 204) return null
  const text = await response.text()
  if (!text.trim()) return null
  return JSON.parse(text) as T | null
}

// --- Search Profile ---

export function fetchSearchProfile(): Promise<SearchProfileDto> {
  return requestJson<SearchProfileDto>(`${BASE}/search-profile`)
}

/** The Search Profile is sent WHOLE on every save (`SearchProfileUpdateRequest`, not a patch):
 * the user owns it outright once suggested, so a PUT is the honest verb. */
export function updateSearchProfile(payload: SearchProfileUpdateRequest): Promise<SearchProfileDto> {
  return requestJson<SearchProfileDto>(`${BASE}/search-profile`, putInit(payload))
}

/** Deterministic seed from the Profile (headline + skills) — no LLM, and nothing is persisted:
 * the response comes back with `updatedAt: null` and the form saves it with a normal PUT. */
export function suggestSearchProfile(): Promise<SearchProfileDto> {
  return requestJson<SearchProfileDto>(`${BASE}/search-profile/suggest`, postInit({}))
}

// --- Boards ---

export function fetchBoards(): Promise<BoardListResponse> {
  return requestJson<BoardListResponse>(`${BASE}/boards`)
}

// --- Scans ---

/** Thrown by `startScan` when a Scan already holds the single-flight lock (409). `scan` is the
 * running Scan the backend reports back, so the UI can switch straight to polling it instead of
 * showing an error the user can do nothing about; `null` when the body did not carry one. */
export class ScanInProgressError extends ApiError {
  scan: ScanDto | null

  constructor(detail: unknown) {
    super(detail, 409)
    this.scan = looksLikeScan(detail) ? detail : null
  }
}

function looksLikeScan(detail: unknown): detail is ScanDto {
  if (typeof detail !== 'object' || detail === null) return false
  const candidate = detail as Partial<ScanDto>
  return typeof candidate.id === 'number' && typeof candidate.status === 'string'
}

/** Immediate Scan. Resolves with the Scan that just started (`status: 'running'`); rejects with
 * `ScanInProgressError` when one is already running. */
export async function startScan(): Promise<ScanDto> {
  try {
    return await requestJson<ScanDto>(`${BASE}/scans`, postInit({}))
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) throw new ScanInProgressError(e.detail)
    throw e
  }
}

/** The Scan holding the single-flight lock, or `null` when none is running. This is what the UI
 * polls while a Scan runs: `boards` fills in as each board answers. */
export function fetchCurrentScan(): Promise<ScanDto | null> {
  return requestJsonOrNull<ScanDto>(`${BASE}/scans/current`)
}

/** The most recent Scan (running or done), or `null` before the first one ever ran. Source of the
 * Board Status flags and of `nextScanAt`. */
export function fetchLatestScan(): Promise<ScanDto | null> {
  return requestJsonOrNull<ScanDto>(`${BASE}/scans/latest`)
}

// --- Listings ---

export interface ListingFilters {
  status?: ListingStatus
  board?: BoardId
  /** Listings above this band are dropped. A listing whose band is `'unknown'` always passes. */
  maxBand?: MaxApplicantBand
  /** `dismissed` listings are hidden by default — that is the point of dismissing one. */
  includeDismissed?: boolean
}

function listingsQuery(filters: ListingFilters): string {
  const params = new URLSearchParams()
  if (filters.status) params.set('status', filters.status)
  if (filters.board) params.set('board', filters.board)
  if (filters.maxBand) params.set('max_band', filters.maxBand)
  if (filters.includeDismissed) params.set('include_dismissed', '1')
  const qs = params.toString()
  return qs ? `?${qs}` : ''
}

/** The ranked list of the LAST Scan — always ordered by Visibility Score desc, server-side.
 * `description` is `null` on every item here; only `fetchListing` fills it in. */
export function fetchListings(filters: ListingFilters = {}): Promise<JobListingListResponse> {
  return requestJson<JobListingListResponse>(`${BASE}/listings${listingsQuery(filters)}`)
}

/** One listing WITH its description and every Listing Source. */
export function fetchListing(listingId: number): Promise<JobListingDto> {
  return requestJson<JobListingDto>(`${BASE}/listings/${listingId}`)
}

/** `'new'` is not settable (see `ListingStatusUpdateRequest`): a Scan writes it, the user cannot.
 * Resolves with the updated listing so a card can re-render from the response alone.
 *
 * PATCH is built inline for the same reason `renameChatSession` does it: `client.ts` only offers
 * POST/PUT init helpers, and one more call site does not justify a third. */
export function updateListingStatus(
  listingId: number,
  status: ListingStatusUpdateRequest['status'],
): Promise<JobListingDto> {
  const payload: ListingStatusUpdateRequest = { status }
  return requestJson<JobListingDto>(`${BASE}/listings/${listingId}/status`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export interface OneClickResumeOptions {
  /** Spend an LLM call even though the Listing Memory already holds a Resume for this listing.
   * Omitted/false replays the stored one, which is why the button reads "Baixar PDF" until the
   * user explicitly asks to regenerate. */
  regenerate?: boolean
  signal?: AbortSignal
}

/** One-click Resume: returns the PDF itself (`application/pdf`), not a job id — the whole
 * pipeline runs server-side inside this one request, so expect it to be slow.
 *
 * Known rejections, all `ApiError`: 422 when the description is too short to be a job description
 * (`description_too_short`), 409 when a One-click for this listing is already running, 502 when
 * the LLM call fails (the Listing Memory is left untouched, so a retry is safe). */
export function oneClickResume(
  listingId: number,
  { regenerate = false, signal }: OneClickResumeOptions = {},
): Promise<Blob> {
  const qs = `?regenerate=${regenerate ? '1' : '0'}`
  return requestBlob(`${BASE}/listings/${listingId}/one-click-resume${qs}`, {
    method: 'POST',
    signal,
  })
}

/** Creates a normal `kind: 'resume'` chat session seeded with the listing's description and
 * returns its id; the caller switches to the resume area and streams the turn as if the user had
 * pasted the posting. No new path through the chat. */
export function openInChat(listingId: number): Promise<OpenInChatResponse> {
  return requestJson<OpenInChatResponse>(`${BASE}/listings/${listingId}/open-in-chat`, postInit({}))
}
