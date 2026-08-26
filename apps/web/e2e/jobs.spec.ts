import { test, expect, type Page } from '@playwright/test'
import { mockBaseline } from './support/mocks'

/** v7 ticket 15 — the Job Monitor end to end: save a Search Profile, run an Immediate Scan,
 * read the ranked list (with a blocked board flagged), open a listing, download its One-click
 * Resume, and hand it over to the chat.
 *
 * Fixtures live in this file rather than in `support/`: they mirror `src/test/msw/
 * jobsScenarios.ts` (ticket 11) but they are not the same thing — the MSW world is a set of
 * static handlers, and this one is a small STATE MACHINE (a Scan that is idle, then running,
 * then done, with the listing table only existing after it). Nothing else in `e2e/` wants that.
 *
 * Route patterns are RegExps, not globs: `**` matches `/` and the query string too, so
 * `**\/api/jobs/listings` would also swallow `/listings/101` and `?board=indeed`.
 */

// Three columns (Search Profile · list · detail) need the room; Desktop Chrome's 1280 leaves
// the middle one ~285px wide, which is legal but pointlessly cramped for a click target.
test.use({ viewport: { width: 1600, height: 1000 } })

// --- Fixtures ---------------------------------------------------------------------------------

/** Relative to now, because `formatPostedAt` renders "publicada há 2h" from the wall clock —
 * a hard-coded date would change the card's copy every day the suite runs. */
function hoursAgo(hours: number): string {
  return new Date(Date.now() - hours * 3_600_000).toISOString()
}

const SEARCH_PROFILE = {
  roles: ['Backend Engineer'],
  locations: ['Brasil', 'Remote'],
  remote: 'any',
  languages: ['pt', 'en'],
  boards: ['linkedin', 'indeed', 'remotive'],
  maxApplicantBand: '<50',
  intervalHours: 6,
  updatedAt: '2026-08-24T22:10:00Z',
}

const BOARDS = [
  { id: 'linkedin', displayName: 'LinkedIn', minIntervalHours: 1 },
  { id: 'indeed', displayName: 'Indeed', minIntervalHours: 1 },
  { id: 'glassdoor', displayName: 'Glassdoor', minIntervalHours: 1 },
  { id: 'google', displayName: 'Google Jobs', minIntervalHours: 1 },
  { id: 'remotive', displayName: 'Remotive', minIntervalHours: 6 },
  { id: 'weworkremotely', displayName: 'We Work Remotely', minIntervalHours: 1 },
  { id: 'remoteok', displayName: 'Remote OK', minIntervalHours: 1 },
]

const ACME_DESCRIPTION =
  'Acme Cloud is hiring a Senior Backend Engineer to design and operate distributed services. ' +
  'Requisitos: Python, FastAPI, PostgreSQL, AWS e observabilidade em produção. ' +
  'Responsabilidades: ser dono dos serviços de ponta a ponta, mentorar pessoas engenheiras e ' +
  'conduzir o roadmap de APIs junto com o time de produto.'

/** Ranked by Visibility Score desc — the only order the list is ever served in. */
const LISTINGS = [
  {
    id: 101,
    title: 'Senior Backend Engineer',
    company: 'Acme Cloud',
    location: 'Remote',
    isRemote: true,
    description: ACME_DESCRIPTION,
    descriptionWordCount: 45,
    datePosted: hoursAgo(2),
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
        board: 'indeed',
        url: 'https://example.invalid/indeed/101',
        datePosted: hoursAgo(2),
        applicantBand: '<10',
      },
      {
        board: 'remotive',
        url: 'https://example.invalid/remotive/101',
        datePosted: hoursAgo(9),
        applicantBand: 'unknown',
      },
    ],
  },
  {
    id: 102,
    title: 'Engenheiro de Software Backend',
    company: 'Fintech BR',
    location: 'São Paulo, SP',
    isRemote: false,
    description: 'Vaga backend no time de pagamentos. Requisitos: Python, Django, PostgreSQL.',
    descriptionWordCount: 38,
    datePosted: hoursAgo(26),
    isRepost: true,
    applicantBand: '<50',
    fitScore: 76,
    fitEstimated: false,
    visibilityScore: 68,
    locale: 'pt',
    status: 'new',
    hasOneClickResume: false,
    sources: [
      {
        board: 'indeed',
        url: 'https://example.invalid/indeed/102',
        datePosted: hoursAgo(26),
        applicantBand: 'unknown',
      },
    ],
  },
  {
    id: 103,
    title: 'Full Stack Developer',
    company: 'Globex',
    location: 'Remote',
    isRemote: true,
    description: 'Full stack dev wanted. Apply on our site.',
    descriptionWordCount: 8,
    datePosted: hoursAgo(70),
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
        board: 'remoteok',
        url: 'https://example.invalid/remoteok/103',
        datePosted: hoursAgo(70),
        applicantBand: 'unknown',
      },
    ],
  },
]

const RUNNING_SCAN = {
  id: 7,
  startedAt: hoursAgo(0),
  finishedAt: null,
  trigger: 'immediate',
  status: 'running',
  boards: [{ board: 'indeed', status: 'ok', message: null, count: 9 }],
  listingsFound: 9,
  listingsScored: 0,
  nextScanAt: null,
}

/** A PARTIAL Scan is the normal outcome, not the exception (CONTEXT.md: Scan): LinkedIn blocked
 * and Remotive skipped, the other two boards' results standing. */
const DONE_SCAN = {
  id: 7,
  startedAt: hoursAgo(0),
  finishedAt: new Date().toISOString(),
  trigger: 'immediate',
  status: 'done',
  boards: [
    {
      board: 'linkedin',
      status: 'blocked',
      message: 'LinkedIn recusou a busca (429).',
      count: 0,
    },
    { board: 'indeed', status: 'ok', message: null, count: 14 },
    {
      board: 'remotive',
      status: 'skipped',
      message: 'Intervalo mínimo de 6h ainda não passou.',
      count: 0,
    },
  ],
  listingsFound: 20,
  listingsScored: 20,
  nextScanAt: new Date(Date.now() + 6 * 3_600_000).toISOString(),
}

const FAKE_PDF = '%PDF-1.4 fake one-click resume'

// --- The mocked world -------------------------------------------------------------------------

interface JobsWorld {
  /** Every body the Search Profile form PUT, in order. */
  searchProfilePuts: Record<string, unknown>[]
  /** Every One-click Resume request URL, so a test can read back `?regenerate=`. */
  oneClickUrls: string[]
}

/**
 * A Job Monitor backend that starts out having never scanned. `POST /scans` flips it to
 * `running`; two polls later `/scans/current` goes quiet, which is the ONLY signal the frontend
 * has that a Scan finished — that transition is what makes the listing table appear.
 */
async function mockJobsApi(page: Page): Promise<JobsWorld> {
  const world: JobsWorld = { searchProfilePuts: [], oneClickUrls: [] }

  let phase: 'idle' | 'running' | 'done' = 'idle'
  let pollsWhileRunning = 0
  // `GET /listings/{id}` is what flips a listing to `seen` server-side, so the mock does it too:
  // the card in the list only catches up because `useListing` invalidates the list.
  const seen = new Set<number>()

  const listForWire = () =>
    LISTINGS.map((listing) => ({
      ...listing,
      // The list response never carries a description — only the detail does.
      description: null,
      status: seen.has(listing.id) && listing.status === 'new' ? 'seen' : listing.status,
    }))

  await page.route(/\/api\/jobs\/search-profile$/, async (route) => {
    if (route.request().method() === 'PUT') {
      const body = route.request().postDataJSON() as Record<string, unknown>
      world.searchProfilePuts.push(body)
      return route.fulfill({ json: { ...body, updatedAt: new Date().toISOString() } })
    }
    return route.fulfill({ json: SEARCH_PROFILE })
  })

  await page.route(/\/api\/jobs\/boards$/, (route) => route.fulfill({ json: { boards: BOARDS } }))

  await page.route(/\/api\/jobs\/scans$/, (route) => {
    phase = 'running'
    pollsWhileRunning = 0
    return route.fulfill({ status: 202, json: RUNNING_SCAN })
  })

  await page.route(/\/api\/jobs\/scans\/current$/, (route) => {
    if (phase !== 'running') return route.fulfill({ status: 204 })
    pollsWhileRunning += 1
    if (pollsWhileRunning >= 2) {
      phase = 'done'
      return route.fulfill({ status: 204 })
    }
    return route.fulfill({ json: RUNNING_SCAN })
  })

  await page.route(/\/api\/jobs\/scans\/latest$/, (route) =>
    phase === 'done' ? route.fulfill({ json: DONE_SCAN }) : route.fulfill({ status: 204 }),
  )

  await page.route(/\/api\/jobs\/listings(\?.*)?$/, (route) =>
    route.fulfill({ json: { listings: phase === 'done' ? listForWire() : [] } }),
  )

  await page.route(/\/api\/jobs\/listings\/(\d+)$/, (route) => {
    const id = Number(/\/listings\/(\d+)$/.exec(route.request().url())?.[1])
    const listing = LISTINGS.find((item) => item.id === id)
    if (!listing) return route.fulfill({ status: 404, json: { detail: 'listing not found' } })
    seen.add(id)
    return route.fulfill({ json: { ...listing, status: seen.has(id) ? 'seen' : listing.status } })
  })

  await page.route(/\/api\/jobs\/listings\/\d+\/one-click-resume/, (route) => {
    world.oneClickUrls.push(route.request().url())
    return route.fulfill({
      status: 200,
      headers: { 'Content-Type': 'application/pdf' },
      body: Buffer.from(FAKE_PDF),
    })
  })

  await page.route(/\/api\/jobs\/listings\/\d+\/open-in-chat$/, (route) =>
    route.fulfill({ status: 201, json: { sessionId: 7 } }),
  )

  // What `useOpenInChat` hydrates from: a normal `kind: 'resume'` session the backend seeded
  // with the posting. No resume yet — nothing has been generated in it.
  const createdAt = new Date().toISOString()
  await page.route(/\/api\/chat\/sessions\/7$/, (route) =>
    route.fulfill({
      json: {
        session: {
          id: 7,
          title: 'Senior Backend Engineer — Acme Cloud',
          updatedAt: createdAt,
          activeResumeVersionId: null,
        },
        messages: [
          {
            id: 1,
            role: 'user',
            content: ACME_DESCRIPTION,
            intent: null,
            resumeVersionId: null,
            createdAt,
          },
        ],
        activeResume: null,
      },
    }),
  )

  return world
}

// --- The flow ---------------------------------------------------------------------------------

test.describe('Job Monitor', () => {
  test('save a Search Profile, scan, rank, download a One-click Resume, hand it to the chat', async ({
    page,
  }) => {
    await mockBaseline(page)
    const world = await mockJobsApi(page)

    await page.goto('/')

    // --- The third app area ---
    await page.getByRole('tab', { name: 'Monitor de Vagas' }).click()
    const search = page.getByRole('form', { name: 'Perfil de busca' })
    await expect(search).toBeVisible()
    // Nothing has ever scanned: no board flags, no listings, no next-scan clock.
    await expect(page.getByText('Nenhuma varredura ainda.')).toBeVisible()
    await expect(
      page.getByText('Nenhuma vaga na última varredura com esses filtros.'),
    ).toBeVisible()

    // --- Search Profile ---
    // Enter adds the chip and must NOT submit the form (which would save a profile without the
    // role the user was in the middle of typing).
    await page.getByLabel('Adicionar cargo').fill('Staff Backend Engineer')
    await page.getByLabel('Adicionar cargo').press('Enter')
    await expect(search.getByText('Staff Backend Engineer')).toBeVisible()
    expect(world.searchProfilePuts).toHaveLength(0)

    await page.getByLabel('Intervalo de varredura').selectOption('3')
    await page.getByRole('button', { name: 'Salvar', exact: true }).click()

    await expect(page.getByText('Perfil de busca salvo.')).toBeVisible()
    expect(world.searchProfilePuts).toHaveLength(1)
    expect(world.searchProfilePuts[0]).toMatchObject({
      roles: ['Backend Engineer', 'Staff Backend Engineer'],
      intervalHours: 3,
      boards: ['linkedin', 'indeed', 'remotive'],
    })

    // --- Immediate Scan ---
    await page.getByRole('button', { name: 'Buscar agora' }).click()
    await expect(page.getByRole('button', { name: 'Buscando…' })).toBeDisabled()
    await expect(page.getByText('Varredura em andamento · 9 vagas encontradas')).toBeVisible()

    // The Scan going quiet is what replaces the listing table; polling is on a 2s cadence.
    const listings = page.getByRole('list', { name: 'Vagas encontradas' })
    await expect(listings).toBeVisible({ timeout: 20_000 })
    await expect(page.getByRole('button', { name: 'Buscar agora' })).toBeEnabled()

    // Ranked by Visibility Score desc, server-side — the list never re-sorts.
    await expect(listings.getByRole('heading', { level: 3 })).toHaveText([
      'Senior Backend Engineer',
      'Engenheiro de Software Backend',
      'Full Stack Developer',
    ])

    // --- Board Status: partial, not failed ---
    const boardStatus = page.getByRole('list', { name: 'Status dos portais' })
    await expect(
      boardStatus.getByText('LinkedIn: bloqueado, tentamos na próxima varredura'),
    ).toBeVisible()
    await expect(boardStatus.getByText('LinkedIn recusou a busca (429).')).toBeVisible()
    await expect(boardStatus.getByText('Indeed: 14 vagas')).toBeVisible()
    await expect(
      boardStatus.getByText('Remotive: pulado, intervalo mínimo do portal ainda não passou'),
    ).toBeVisible()

    // --- Detail ---
    await page.getByRole('button', { name: /Senior Backend Engineer/ }).click()
    const detail = page.getByRole('region', { name: 'Detalhe da vaga' })
    await expect(detail.getByRole('region', { name: 'Descrição da vaga' })).toContainText(
      'Requisitos: Python, FastAPI, PostgreSQL',
    )
    // Every Listing Source is kept and named — dedup must not cost the user a board.
    await expect(detail.getByRole('list', { name: 'Fontes da vaga' }).getByRole('link')).toHaveText(
      ['Indeed', 'Remotive'],
    )
    // Opening the detail is what marks the listing `seen`; the card catches up on the refetch.
    await expect(listings.getByRole('listitem').first()).toContainText('Vista')

    // --- One-click Resume ---
    const downloadPromise = page.waitForEvent('download')
    await detail.getByRole('button', { name: 'Gerar currículo em um clique' }).click()
    const download = await downloadPromise

    expect(download.suggestedFilename()).toBe(
      'curriculo-acme-cloud-senior-backend-engineer.pdf',
    )
    expect(world.oneClickUrls).toHaveLength(1)
    expect(world.oneClickUrls[0]).toContain('regenerate=0')
    // The Listing Memory now holds a Resume, so the two-button state takes over.
    await expect(detail.getByRole('button', { name: 'Baixar PDF' })).toBeVisible()
    await expect(detail.getByRole('button', { name: 'Regerar' })).toBeVisible()

    // --- Hand it to the chat ---
    await detail.getByRole('button', { name: 'Abrir no chat' }).click()

    await expect(page.getByRole('tab', { name: 'Currículo' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    await expect(page.getByRole('list', { name: 'Vagas encontradas' })).toBeHidden()
    // The session the backend seeded with the posting is the one now open.
    await expect(page.getByText(/Requisitos: Python, FastAPI, PostgreSQL/)).toBeVisible()
  })

  /**
   * The same flow against the real FastAPI app and the real LLM — and never a real Job Board.
   *
   * Requires the backend on 127.0.0.1:8000 started with `JOB_BOARDS_FAKE=1`, which swaps the
   * seven network adapters for three deterministic `StaticJobBoard`s (one of them `blocked`);
   * see `apps/api/app/services/jobboards/fake_providers.py` and this folder's README. Without
   * that variable an Immediate Scan would call LinkedIn, Indeed and Glassdoor for real, which
   * CLAUDE.md and the v7 spec both forbid — so the run is gated on the fake registry being
   * visible in `GET /api/jobs/boards` before anything is clicked.
   *
   * Slow by nature: the Scan runs three boards plus the LLM Fit pass, and One-click runs an
   * Analysis, a generation and a Playwright PDF render inside one request.
   */
  test('the whole flow against the real backend and fake boards @real', async ({ page }) => {
    test.setTimeout(300_000)

    await page.goto('/')
    await page.getByRole('tab', { name: 'Monitor de Vagas' }).click()
    await expect(page.getByRole('form', { name: 'Perfil de busca' })).toBeVisible()

    // A reachability probe, so a missing backend fails here instead of as a mystified timeout
    // twenty seconds into the Scan. Whether the FAKE registry is loaded cannot be read off any
    // endpoint (`GET /boards` serves the static catalog, which is identical either way) — the
    // Board Status assertion after the Scan is what proves it.
    const health = await page.request.get('http://127.0.0.1:8000/api/jobs/scans/latest')
    expect(
      health.ok(),
      'the API on 127.0.0.1:8000 must be reachable (see e2e/README.md)',
    ).toBeTruthy()

    // A Search Profile the fake boards can answer: the three they register, and roles that
    // give the Fit pass something to match.
    await page.getByLabel('Adicionar cargo').fill('Backend Engineer')
    await page.getByLabel('Adicionar cargo').press('Enter')
    for (const board of ['LinkedIn', 'Indeed', 'Remote OK']) {
      await page.getByRole('checkbox', { name: board, exact: true }).check()
    }
    await page.getByRole('button', { name: 'Salvar', exact: true }).click()
    await expect(page.getByText('Perfil de busca salvo.')).toBeVisible()

    await page.getByRole('button', { name: 'Buscar agora' }).click()

    const listings = page.getByRole('list', { name: 'Vagas encontradas' })
    await expect(listings).toBeVisible({ timeout: 180_000 })
    // The blocked fake board proves no real board answered: the real LinkedIn adapter would
    // have reported `ok` or `error`, not this fixture's message.
    await expect(
      page.getByRole('list', { name: 'Status dos portais' }),
    ).toContainText('JOB_BOARDS_FAKE=1')

    await page.getByRole('button', { name: /Senior Backend Engineer/ }).first().click()
    const detail = page.getByRole('region', { name: 'Detalhe da vaga' })
    await expect(detail).toContainText('Acme Cloud')

    const downloadPromise = page.waitForEvent('download', { timeout: 240_000 })
    await detail.getByRole('button', { name: 'Gerar currículo em um clique' }).click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toMatch(/^curriculo-.+\.pdf$/)

    await detail.getByRole('button', { name: 'Abrir no chat' }).click()
    await expect(page.getByRole('tab', { name: 'Currículo' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
  })
})
