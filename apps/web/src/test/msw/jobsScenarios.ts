import { http, HttpResponse } from 'msw'
import type {
  ApplicantBand,
  BoardDto,
  BoardStatusDto,
  JobListingDto,
  MaxApplicantBand,
  ScanDto,
  SearchProfileDto,
} from '../../lib/api/dto'

/** v7 Job Monitor fixtures + MSW handlers (ticket 11).
 *
 * `jobsHandlers` is spread into the baseline handler list in `handlers.ts`, so every test starts
 * from one plausible world: a saved Search Profile, a finished Scan whose LinkedIn board was
 * blocked (a PARTIAL Scan is the normal case, not the exception), and a ranked list of three
 * listings. Per-scenario deviations — a Scan still running, the 409/422/502 rejections — are
 * `server.use(...)` overrides via the `mock*` helpers below, same shape as analysisScenarios.ts.
 */

// --- Fixtures ---

export function makeListing(overrides: Partial<JobListingDto> = {}): JobListingDto {
  return {
    id: 101,
    title: 'Senior Backend Engineer',
    company: 'Acme Cloud',
    location: 'Remote',
    isRemote: true,
    description:
      'We are hiring a Senior Backend Engineer to design and operate distributed services. ' +
      'Requisitos: Python, FastAPI, PostgreSQL, AWS, observability. Responsabilidades: own ' +
      'services end to end, mentor engineers, and drive the API roadmap with the product team.',
    descriptionWordCount: 42,
    datePosted: '2026-08-25T09:00:00Z',
    isRepost: false,
    applicantBand: '<10',
    fitScore: 88,
    fitEstimated: false,
    visibilityScore: 91,
    locale: 'en',
    status: 'new',
    hasOneClickResume: false,
    sources: [
      {
        board: 'linkedin',
        url: 'https://www.linkedin.com/jobs/view/101',
        datePosted: '2026-08-25T09:00:00Z',
        applicantBand: '<10',
      },
      {
        board: 'remotive',
        url: 'https://remotive.com/remote-jobs/101',
        datePosted: '2026-08-24T18:00:00Z',
        applicantBand: 'unknown',
      },
    ],
    ...overrides,
  }
}

/** Ranked by Visibility Score desc — the ONLY order the list is ever served in. Covers the badge
 * matrix the cards render: a Repost, an estimated (keyword-pass) Fit, an `'unknown'` band, a
 * listing whose memory already holds a One-click Resume, and one too short to generate from. */
export const SAMPLE_LISTINGS: JobListingDto[] = [
  makeListing(),
  makeListing({
    id: 102,
    title: 'Engenheiro de Software Backend',
    company: 'Fintech BR',
    location: 'São Paulo, SP',
    isRemote: false,
    description:
      'Vaga para pessoa engenheira de software backend. Requisitos: Python, Django, ' +
      'PostgreSQL e mensageria. Responsabilidades: evoluir os serviços de pagamento, ' +
      'participar do on-call e apoiar a evolução da arquitetura de dados do time.',
    descriptionWordCount: 38,
    datePosted: '2026-08-24T12:00:00Z',
    isRepost: true,
    applicantBand: '<50',
    fitScore: 76,
    fitEstimated: false,
    visibilityScore: 68,
    locale: 'pt',
    status: 'seen',
    hasOneClickResume: true,
    sources: [
      {
        board: 'indeed',
        url: 'https://br.indeed.com/viewjob?jk=102',
        datePosted: '2026-08-24T12:00:00Z',
        applicantBand: 'unknown',
      },
    ],
  }),
  makeListing({
    id: 103,
    title: 'Full Stack Developer',
    company: 'Globex',
    location: 'Remote',
    isRemote: true,
    // Too short to look like a job description: One-click must be disabled, not merely fail.
    description: 'Full stack dev wanted. Apply on our site.',
    descriptionWordCount: 8,
    datePosted: '2026-08-20T08:00:00Z',
    isRepost: false,
    applicantBand: 'unknown',
    fitScore: 54,
    fitEstimated: true,
    visibilityScore: 41,
    locale: 'en',
    status: 'new',
    hasOneClickResume: false,
    sources: [
      {
        board: 'weworkremotely',
        url: 'https://weworkremotely.com/remote-jobs/103',
        datePosted: '2026-08-20T08:00:00Z',
        applicantBand: 'unknown',
      },
    ],
  }),
  makeListing({
    id: 104,
    title: 'PHP Developer',
    company: 'Legacy Systems',
    location: 'Remote',
    isRemote: true,
    description:
      'PHP developer wanted for a legacy platform. Requirements: PHP 5.6, jQuery and MySQL. ' +
      'Responsibilities: keep the billing modules running and migrate reports to the new stack.',
    descriptionWordCount: 28,
    datePosted: '2026-08-22T08:00:00Z',
    applicantBand: '<100',
    fitScore: 22,
    fitEstimated: true,
    visibilityScore: 18,
    status: 'dismissed',
    sources: [
      {
        board: 'remoteok',
        url: 'https://remoteok.com/remote-jobs/104',
        datePosted: '2026-08-22T08:00:00Z',
        applicantBand: 'unknown',
      },
    ],
  }),
]

export function makeBoardStatus(overrides: Partial<BoardStatusDto> = {}): BoardStatusDto {
  return { board: 'indeed', status: 'ok', message: null, count: 14, ...overrides }
}

export function makeScan(overrides: Partial<ScanDto> = {}): ScanDto {
  return {
    id: 6,
    startedAt: '2026-08-25T09:00:00Z',
    finishedAt: '2026-08-25T09:02:31Z',
    trigger: 'scheduled',
    status: 'done',
    boards: [
      makeBoardStatus({ board: 'linkedin', status: 'blocked', message: 'LinkedIn recusou a busca (429).', count: 0 }),
      makeBoardStatus({ board: 'indeed', status: 'ok', count: 14 }),
      makeBoardStatus({ board: 'remotive', status: 'skipped', message: 'Intervalo mínimo de 6h ainda não passou.', count: 0 }),
      makeBoardStatus({ board: 'weworkremotely', status: 'ok', count: 6 }),
    ],
    listingsFound: 20,
    listingsScored: 20,
    nextScanAt: '2026-08-25T12:00:00Z',
    ...overrides,
  }
}

/** A Scan holding the single-flight lock: no `finishedAt`, boards still filling in, and
 * `nextScanAt` null because only a finished Scan knows when the next one is. */
export function makeRunningScan(overrides: Partial<ScanDto> = {}): ScanDto {
  return makeScan({
    id: 7,
    startedAt: '2026-08-25T11:00:00Z',
    finishedAt: null,
    trigger: 'immediate',
    status: 'running',
    boards: [makeBoardStatus({ board: 'indeed', status: 'ok', count: 9 })],
    listingsFound: 9,
    listingsScored: 0,
    nextScanAt: null,
    ...overrides,
  })
}

export const SAMPLE_BOARDS: BoardDto[] = [
  { id: 'linkedin', displayName: 'LinkedIn', minIntervalHours: 1 },
  { id: 'indeed', displayName: 'Indeed', minIntervalHours: 1 },
  { id: 'glassdoor', displayName: 'Glassdoor', minIntervalHours: 1 },
  { id: 'google', displayName: 'Google Jobs', minIntervalHours: 1 },
  // Remotive's terms cap us at 4 calls a day.
  { id: 'remotive', displayName: 'Remotive', minIntervalHours: 6 },
  { id: 'weworkremotely', displayName: 'We Work Remotely', minIntervalHours: 1 },
  { id: 'remoteok', displayName: 'Remote OK', minIntervalHours: 1 },
]

export const SAMPLE_SEARCH_PROFILE: SearchProfileDto = {
  roles: ['Backend Engineer', 'Engenheiro de Software'],
  locations: ['Brasil', 'Remote'],
  remote: 'any',
  languages: ['pt', 'en'],
  boards: ['linkedin', 'indeed', 'remotive'],
  maxApplicantBand: '<50',
  intervalHours: 6,
  updatedAt: '2026-08-24T22:10:00Z',
}

/** What `POST /search-profile/suggest` returns: the same shape, never saved — `updatedAt: null`
 * is the whole difference, and it is what tells the form "this is a suggestion". */
export const SUGGESTED_SEARCH_PROFILE: SearchProfileDto = {
  roles: ['Software Engineer'],
  locations: ['Brasil', 'Remote'],
  remote: 'any',
  languages: ['pt', 'en'],
  boards: ['linkedin', 'indeed', 'remotive', 'weworkremotely', 'remoteok'],
  maxApplicantBand: null,
  intervalHours: 6,
  updatedAt: null,
}

export const FAKE_ONE_CLICK_PDF = '%PDF-1.4 fake one-click resume'

// --- Filtering, mirroring what the router does server-side ---

const BAND_ORDER: ApplicantBand[] = ['<10', '<25', '<50', '<100', '100+']

/** `'unknown'` NEVER excludes a listing from the cap (CONTEXT.md: Applicant Band) — it only
 * scores neutrally. `'100+'` fails every cap, since no cap is offerable above `<100`. */
function passesBand(band: ApplicantBand, cap: MaxApplicantBand): boolean {
  if (band === 'unknown') return true
  return BAND_ORDER.indexOf(band) <= BAND_ORDER.indexOf(cap)
}

function filterListings(url: URL): JobListingDto[] {
  const status = url.searchParams.get('status')
  const board = url.searchParams.get('board')
  const maxBand = url.searchParams.get('max_band') as MaxApplicantBand | null
  const includeDismissed = url.searchParams.get('include_dismissed') === '1'

  return SAMPLE_LISTINGS.filter((listing) => {
    if (!includeDismissed && listing.status === 'dismissed') return false
    if (status && listing.status !== status) return false
    if (board && !listing.sources.some((source) => source.board === board)) return false
    if (maxBand && !passesBand(listing.applicantBand, maxBand)) return false
    return true
  })
}

/** The list response omits descriptions (fifty full postings is a payload nobody reads); only
 * `GET /listings/{id}` carries one. Stripping it here keeps tests honest about that. */
function withoutDescription(listing: JobListingDto): JobListingDto {
  return { ...listing, description: null }
}

// --- Baseline handlers (registered for every test via handlers.ts) ---

export const jobsHandlers = [
  http.get('/api/jobs/search-profile', () => HttpResponse.json(SAMPLE_SEARCH_PROFILE)),

  http.put('/api/jobs/search-profile', async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>
    return HttpResponse.json({ ...body, updatedAt: '2026-08-25T12:00:00Z' })
  }),

  http.post('/api/jobs/search-profile/suggest', () => HttpResponse.json(SUGGESTED_SEARCH_PROFILE)),

  http.get('/api/jobs/boards', () => HttpResponse.json({ boards: SAMPLE_BOARDS })),

  http.post('/api/jobs/scans', () => HttpResponse.json(makeRunningScan(), { status: 201 })),

  // Nothing running by default; `mockScanRunning()` overrides it for the polling scenarios.
  http.get('/api/jobs/scans/current', () => HttpResponse.json(null)),

  http.get('/api/jobs/scans/latest', () => HttpResponse.json(makeScan())),

  http.get('/api/jobs/listings', ({ request }) =>
    HttpResponse.json({ listings: filterListings(new URL(request.url)).map(withoutDescription) }),
  ),

  http.get('/api/jobs/listings/:id', ({ params }) => {
    const listing = SAMPLE_LISTINGS.find((item) => item.id === Number(params.id))
    if (!listing) return HttpResponse.json({ detail: 'listing not found' }, { status: 404 })
    return HttpResponse.json(listing)
  }),

  http.patch('/api/jobs/listings/:id/status', async ({ params, request }) => {
    const { status } = (await request.json()) as { status: JobListingDto['status'] }
    const listing = SAMPLE_LISTINGS.find((item) => item.id === Number(params.id))
    if (!listing) return HttpResponse.json({ detail: 'listing not found' }, { status: 404 })
    if (status === 'new') {
      return HttpResponse.json({ detail: "status 'new' is not settable" }, { status: 422 })
    }
    return HttpResponse.json({ ...listing, status })
  }),

  http.post('/api/jobs/listings/:id/one-click-resume', () =>
    // A `Blob` body is serialized as the literal "[object Blob]" by MSW's node interceptor —
    // pass raw bytes as a string, same as the /api/export/pdf handler.
    new HttpResponse(FAKE_ONE_CLICK_PDF, {
      status: 200,
      headers: { 'Content-Type': 'application/pdf' },
    }),
  ),

  http.post('/api/jobs/listings/:id/open-in-chat', () => HttpResponse.json({ sessionId: 1 })),
]

// --- Scenario overrides (server.use(...)) ---

export function mockScanRunning(scan: ScanDto = makeRunningScan()) {
  return http.get('/api/jobs/scans/current', () => HttpResponse.json(scan))
}

/** The "nothing has ever run" world: a fresh install, before the first Scan. */
export function mockNoScans() {
  return [
    http.get('/api/jobs/scans/current', () => new HttpResponse(null, { status: 204 })),
    http.get('/api/jobs/scans/latest', () => new HttpResponse(null, { status: 204 })),
  ]
}

/** Immediate Scan refused because one already holds the lock. The 409 body carries the running
 * Scan so the UI can start polling it instead of reporting a dead end. */
export function mockScanConflict(scan: ScanDto = makeRunningScan()) {
  return http.post('/api/jobs/scans', () => HttpResponse.json({ detail: scan }, { status: 409 }))
}

export function mockListings(listings: JobListingDto[]) {
  return http.get('/api/jobs/listings', () =>
    HttpResponse.json({ listings: listings.map(withoutDescription) }),
  )
}

/** 422: the description is too short to look like a job description, so no LLM call is spent. */
export function mockOneClickTooShort(listingId: number) {
  return http.post(`/api/jobs/listings/${listingId}/one-click-resume`, () =>
    HttpResponse.json({ detail: 'description_too_short' }, { status: 422 }),
  )
}

/** 409: a One-click Resume for this listing is already running (one per listing at a time). */
export function mockOneClickConflict(listingId: number) {
  return http.post(`/api/jobs/listings/${listingId}/one-click-resume`, () =>
    HttpResponse.json({ detail: 'Já existe um currículo sendo gerado para esta vaga.' }, { status: 409 }),
  )
}

/** 502: the LLM call failed. The Listing Memory is left untouched, so retrying is safe. */
export function mockOneClickLlmError(listingId: number, detail = 'O provedor de IA não respondeu.') {
  return http.post(`/api/jobs/listings/${listingId}/one-click-resume`, () =>
    HttpResponse.json({ detail }, { status: 502 }),
  )
}
