import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../../test/setup'
import {
  FAKE_ONE_CLICK_PDF,
  makeListing,
  makeRunningScan,
  mockNoScans,
  mockOneClickConflict,
  mockOneClickLlmError,
  mockOneClickTooShort,
  mockScanConflict,
  mockScanRunning,
  SAMPLE_SEARCH_PROFILE,
} from '../../test/msw/jobsScenarios'
import { ApiError } from './client'
import type { SearchProfileUpdateRequest } from './dto'
import {
  fetchBoards,
  fetchCurrentScan,
  fetchLatestScan,
  fetchListing,
  fetchListings,
  fetchSearchProfile,
  oneClickResume,
  openInChat,
  ScanInProgressError,
  startScan,
  suggestSearchProfile,
  updateListingStatus,
  updateSearchProfile,
} from './jobs'

/** Every test here runs against the baseline handlers in src/test/msw/jobsScenarios.ts. */

async function catchError(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise
    return null
  } catch (e) {
    return e
  }
}

describe('search profile', () => {
  it('fetches the saved Search Profile', async () => {
    await expect(fetchSearchProfile()).resolves.toEqual(SAMPLE_SEARCH_PROFILE)
  })

  it('PUTs the whole profile and resolves the saved version', async () => {
    let sent: unknown
    server.use(
      http.put('/api/jobs/search-profile', async ({ request }) => {
        sent = await request.json()
        return HttpResponse.json({ ...(sent as object), updatedAt: '2026-08-25T12:00:00Z' })
      }),
    )
    const payload: SearchProfileUpdateRequest = {
      roles: ['Backend Engineer'],
      locations: ['Remote'],
      remote: 'remote_only',
      languages: ['pt'],
      boards: ['remotive'],
      maxApplicantBand: '<25',
      intervalHours: 12,
    }

    const saved = await updateSearchProfile(payload)

    expect(sent).toEqual(payload)
    expect(saved.updatedAt).toBe('2026-08-25T12:00:00Z')
    expect(saved.maxApplicantBand).toBe('<25')
  })

  it('suggests a profile that was never saved (updatedAt null)', async () => {
    const suggestion = await suggestSearchProfile()

    expect(suggestion.updatedAt).toBeNull()
    expect(suggestion.roles.length).toBeGreaterThan(0)
  })
})

describe('fetchBoards', () => {
  it('resolves the board catalog with each board own minimum interval', async () => {
    const { boards } = await fetchBoards()

    expect(boards).toHaveLength(7)
    expect(boards.find((b) => b.id === 'remotive')).toMatchObject({
      displayName: 'Remotive',
      minIntervalHours: 6,
    })
  })
})

describe('fetchListings', () => {
  it('sends no query string when there are no filters', async () => {
    let search: string | undefined
    server.use(
      http.get('/api/jobs/listings', ({ request }) => {
        search = new URL(request.url).search
        return HttpResponse.json({ listings: [] })
      }),
    )

    await fetchListings()

    expect(search).toBe('')
  })

  it('hides dismissed listings, omits descriptions and keeps Visibility order', async () => {
    const { listings } = await fetchListings()

    expect(listings.map((l) => l.id)).toEqual([101, 102, 103])
    expect(listings.every((l) => l.description === null)).toBe(true)
    expect(listings.every((l) => l.descriptionWordCount > 0)).toBe(true)
    const scores = listings.map((l) => l.visibilityScore)
    expect([...scores].sort((a, b) => b - a)).toEqual(scores)
  })

  it('translates the filters into snake_case query params', async () => {
    let url: URL | undefined
    server.use(
      http.get('/api/jobs/listings', ({ request }) => {
        url = new URL(request.url)
        return HttpResponse.json({ listings: [] })
      }),
    )

    await fetchListings({
      status: 'seen',
      board: 'linkedin',
      maxBand: '<25',
      includeDismissed: true,
    })

    expect(url?.searchParams.get('status')).toBe('seen')
    expect(url?.searchParams.get('board')).toBe('linkedin')
    expect(url?.searchParams.get('max_band')).toBe('<25')
    expect(url?.searchParams.get('include_dismissed')).toBe('1')
  })

  it('omits include_dismissed entirely when it is false', async () => {
    let url: URL | undefined
    server.use(
      http.get('/api/jobs/listings', ({ request }) => {
        url = new URL(request.url)
        return HttpResponse.json({ listings: [] })
      }),
    )

    await fetchListings({ includeDismissed: false, status: 'new' })

    expect(url?.searchParams.has('include_dismissed')).toBe(false)
    expect(url?.searchParams.get('status')).toBe('new')
  })

  it('includes dismissed listings when asked', async () => {
    const { listings } = await fetchListings({ includeDismissed: true })

    expect(listings.map((l) => l.id)).toContain(104)
  })

  it('filters by board across every Listing Source', async () => {
    const { listings } = await fetchListings({ board: 'remotive' })

    expect(listings.map((l) => l.id)).toEqual([101])
  })

  it('caps by Applicant Band, but never excludes an unknown band', async () => {
    const { listings } = await fetchListings({ maxBand: '<25' })

    // 101 is `<10`; 103 is `unknown` and passes any cap; 102 (`<50`) is over the cap.
    expect(listings.map((l) => l.id)).toEqual([101, 103])
  })
})

describe('fetchListing', () => {
  it('resolves the detail with the description and every source', async () => {
    const listing = await fetchListing(101)

    expect(listing.description).toContain('Senior Backend Engineer')
    expect(listing.sources.map((s) => s.board)).toEqual(['linkedin', 'remotive'])
  })

  it('rejects with an ApiError when the listing is gone (the list IS the last Scan)', async () => {
    const caught = await catchError(fetchListing(9999))

    expect(caught).toBeInstanceOf(ApiError)
    expect((caught as ApiError).status).toBe(404)
  })
})

describe('updateListingStatus', () => {
  it('PATCHes the status and resolves the updated listing', async () => {
    let sent: unknown
    server.use(
      http.patch('/api/jobs/listings/:id/status', async ({ request }) => {
        sent = await request.json()
        return HttpResponse.json(makeListing({ status: 'applied' }))
      }),
    )

    const updated = await updateListingStatus(101, 'applied')

    expect(sent).toEqual({ status: 'applied' })
    expect(updated.status).toBe('applied')
  })

  it('rejects with an ApiError on a refused transition', async () => {
    server.use(
      http.patch('/api/jobs/listings/:id/status', () =>
        HttpResponse.json({ detail: "status 'new' is not settable" }, { status: 422 }),
      ),
    )

    const caught = await catchError(updateListingStatus(101, 'dismissed'))

    expect(caught).toBeInstanceOf(ApiError)
    expect((caught as ApiError).status).toBe(422)
  })
})

describe('scans', () => {
  it('startScan resolves the Scan that just took the lock', async () => {
    const scan = await startScan()

    expect(scan.status).toBe('running')
    expect(scan.trigger).toBe('immediate')
    expect(scan.finishedAt).toBeNull()
  })

  it('startScan rejects with ScanInProgressError carrying the running Scan on 409', async () => {
    const running = makeRunningScan({ id: 42 })
    server.use(mockScanConflict(running))

    const caught = await catchError(startScan())

    expect(caught).toBeInstanceOf(ScanInProgressError)
    expect(caught).toBeInstanceOf(ApiError)
    expect((caught as ScanInProgressError).status).toBe(409)
    expect((caught as ScanInProgressError).scan?.id).toBe(42)
  })

  it('startScan leaves scan null when the 409 body carries no Scan', async () => {
    server.use(
      http.post('/api/jobs/scans', () =>
        HttpResponse.json({ detail: 'a scan is already running' }, { status: 409 }),
      ),
    )

    const caught = await catchError(startScan())

    expect(caught).toBeInstanceOf(ScanInProgressError)
    expect((caught as ScanInProgressError).scan).toBeNull()
  })

  it('startScan rethrows any other failure as a plain ApiError', async () => {
    server.use(
      http.post('/api/jobs/scans', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })),
    )

    const caught = await catchError(startScan())

    expect(caught).toBeInstanceOf(ApiError)
    expect(caught).not.toBeInstanceOf(ScanInProgressError)
  })

  it('fetchCurrentScan resolves null when nothing is running', async () => {
    await expect(fetchCurrentScan()).resolves.toBeNull()
  })

  it('fetchCurrentScan resolves the running Scan with the boards reported so far', async () => {
    server.use(mockScanRunning())

    const scan = await fetchCurrentScan()

    expect(scan?.status).toBe('running')
    expect(scan?.boards.map((b) => b.board)).toEqual(['indeed'])
    expect(scan?.nextScanAt).toBeNull()
  })

  it('fetchLatestScan reports a partial Scan board by board', async () => {
    const scan = await fetchLatestScan()

    expect(scan?.status).toBe('done')
    expect(scan?.boards.find((b) => b.board === 'linkedin')).toMatchObject({
      status: 'blocked',
      message: expect.stringContaining('LinkedIn'),
    })
    expect(scan?.boards.find((b) => b.board === 'remotive')?.status).toBe('skipped')
    expect(scan?.nextScanAt).toBe('2026-08-25T12:00:00Z')
  })

  it('treats a 204 as "no Scan at all" on both scan endpoints', async () => {
    server.use(...mockNoScans())

    await expect(fetchCurrentScan()).resolves.toBeNull()
    await expect(fetchLatestScan()).resolves.toBeNull()
  })

  it('propagates a real failure instead of swallowing it as null', async () => {
    server.use(
      http.get('/api/jobs/scans/latest', () =>
        HttpResponse.json({ detail: 'db locked' }, { status: 500 }),
      ),
    )

    const caught = await catchError(fetchLatestScan())

    expect(caught).toBeInstanceOf(ApiError)
    expect((caught as ApiError).detail).toBe('db locked')
  })
})

describe('oneClickResume', () => {
  it('resolves the PDF blob and asks for the stored Resume by default', async () => {
    let url: URL | undefined
    server.use(
      http.post('/api/jobs/listings/:id/one-click-resume', ({ request }) => {
        url = new URL(request.url)
        return new HttpResponse(FAKE_ONE_CLICK_PDF, {
          status: 200,
          headers: { 'Content-Type': 'application/pdf' },
        })
      }),
    )

    const blob = await oneClickResume(102)

    expect(await blob.text()).toContain('%PDF-1.4')
    expect(url?.searchParams.get('regenerate')).toBe('0')
  })

  it('asks for a regeneration explicitly', async () => {
    let url: URL | undefined
    server.use(
      http.post('/api/jobs/listings/:id/one-click-resume', ({ request }) => {
        url = new URL(request.url)
        return new HttpResponse(FAKE_ONE_CLICK_PDF, {
          status: 200,
          headers: { 'Content-Type': 'application/pdf' },
        })
      }),
    )

    await oneClickResume(102, { regenerate: true })

    expect(url?.searchParams.get('regenerate')).toBe('1')
  })

  it('rejects with 422 description_too_short for a listing that is not a job description', async () => {
    server.use(mockOneClickTooShort(103))

    const caught = await catchError(oneClickResume(103))

    expect(caught).toBeInstanceOf(ApiError)
    expect((caught as ApiError).status).toBe(422)
    expect((caught as ApiError).detail).toBe('description_too_short')
  })

  it('rejects with 409 when a One-click for this listing is already running', async () => {
    server.use(mockOneClickConflict(101))

    const caught = await catchError(oneClickResume(101))

    expect((caught as ApiError).status).toBe(409)
  })

  it('rejects with 502 and an actionable message when the LLM fails', async () => {
    server.use(mockOneClickLlmError(101))

    const caught = await catchError(oneClickResume(101))

    expect((caught as ApiError).status).toBe(502)
    expect((caught as ApiError).detail).toContain('provedor de IA')
  })
})

describe('openInChat', () => {
  it('resolves the id of the seeded chat session', async () => {
    await expect(openInChat(101)).resolves.toEqual({ sessionId: 1 })
  })

  it('rejects with an ApiError when the listing is gone', async () => {
    server.use(
      http.post('/api/jobs/listings/:id/open-in-chat', () =>
        HttpResponse.json({ detail: 'listing not found' }, { status: 404 }),
      ),
    )

    const caught = await catchError(openInChat(9999))

    expect((caught as ApiError).status).toBe(404)
  })
})
