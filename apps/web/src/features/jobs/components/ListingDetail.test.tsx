import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { JobsShell } from './JobsShell'
import { ListingDetail } from './ListingDetail'
import { useAppModeStore } from '../../../app/appModeStore'
import { useChatStore } from '../../chat/store/chatStore'
import {
  makeListing,
  mockOneClickConflict,
  mockOneClickLlmError,
  mockOneClickTooShort,
} from '../../../test/msw/jobsScenarios'
import { renderApp } from '../../../test/render'
import { server } from '../../../test/setup'
import { TOO_SHORT_HINT } from '../hooks/useOneClickResume'

// Under full-suite parallel load these queries settle slowly (same call as JobsShell.test).
const T = { timeout: 15000 }

/** Every download this component triggers, as the browser would see it: jsdom has no
 * `URL.createObjectURL` and an <a download> click does nothing, so the anchor is captured
 * instead — `download` IS the filename the user gets. */
const downloads: { href: string; download: string }[] = []

beforeEach(() => {
  downloads.length = 0
  URL.createObjectURL = vi.fn(() => 'blob:fake-one-click')
  URL.revokeObjectURL = vi.fn()
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    downloads.push({ href: this.href, download: this.download })
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  useAppModeStore.setState({ mode: 'jobs' })
  useChatStore.getState().reset()
})

/** Serves `GET /listings/{id}` with exactly this listing, so each test states the world it
 * needs (word count, `hasOneClickResume`) instead of leaning on a fixture's id. */
function mockDetail(listing: ReturnType<typeof makeListing>) {
  server.use(http.get(`/api/jobs/listings/${listing.id}`, () => HttpResponse.json(listing)))
  return listing
}

const noop = () => {}

describe('ListingDetail', () => {
  it('shows the posting, its badges and every Listing Source with the board that carries it', async () => {
    const listing = mockDetail(makeListing())
    renderApp(<ListingDetail listingId={listing.id} onClose={noop} />)

    expect(
      await screen.findByRole('heading', { name: 'Senior Backend Engineer' }, T),
    ).toBeInTheDocument()
    expect(screen.getByText(/Acme Cloud/)).toBeInTheDocument()
    expect(screen.getByText('Fit 88%')).toBeInTheDocument()
    expect(screen.getByText('Visibilidade 91')).toBeInTheDocument()

    const description = screen.getByRole('region', { name: 'Descrição da vaga' })
    expect(description).toHaveTextContent('Senior Backend Engineer to design and operate')

    const sources = screen.getByRole('list', { name: 'Fontes da vaga' })
    expect(within(sources).getByRole('link', { name: 'LinkedIn' })).toHaveAttribute(
      'href',
      'https://www.linkedin.com/jobs/view/101',
    )
    expect(within(sources).getByRole('link', { name: 'Remotive' })).toHaveAttribute(
      'href',
      'https://remotive.com/remote-jobs/101',
    )
  })

  // --- One-click Resume, the four states ---

  it('idle: offers to generate, and generating downloads a PDF named after company and role', async () => {
    const listing = mockDetail(makeListing())
    renderApp(<ListingDetail listingId={listing.id} onClose={noop} />)

    const button = await screen.findByRole('button', { name: 'Gerar currículo em um clique' }, T)
    expect(button).toBeEnabled()

    await userEvent.click(button)

    await waitFor(() => expect(downloads).toHaveLength(1), T)
    expect(downloads[0].download).toBe('curriculo-acme-cloud-senior-backend-engineer.pdf')
  })

  it('running: the button spins, is disabled, and asks for regenerate=0', async () => {
    const listing = mockDetail(makeListing())
    const requested: string[] = []
    server.use(
      http.post(`/api/jobs/listings/${listing.id}/one-click-resume`, async ({ request }) => {
        requested.push(new URL(request.url).searchParams.get('regenerate') ?? '')
        await delay('infinite')
      }),
    )
    renderApp(<ListingDetail listingId={listing.id} onClose={noop} />)

    await userEvent.click(
      await screen.findByRole('button', { name: 'Gerar currículo em um clique' }, T),
    )

    const spinning = await screen.findByRole('button', { name: 'Gerando…' }, T)
    expect(spinning).toBeDisabled()
    expect(requested).toEqual(['0'])
    expect(downloads).toHaveLength(0)
  })

  it('ready: a listing whose memory holds a Resume offers "Baixar PDF" (no LLM) and "Regerar" (regenerate=1)', async () => {
    const listing = mockDetail(makeListing({ hasOneClickResume: true }))
    const requested: string[] = []
    server.use(
      http.post(`/api/jobs/listings/${listing.id}/one-click-resume`, ({ request }) => {
        requested.push(new URL(request.url).searchParams.get('regenerate') ?? '')
        return new HttpResponse('%PDF-1.4 fake', {
          status: 200,
          headers: { 'Content-Type': 'application/pdf' },
        })
      }),
    )
    renderApp(<ListingDetail listingId={listing.id} onClose={noop} />)

    await userEvent.click(await screen.findByRole('button', { name: 'Baixar PDF' }, T))
    await waitFor(() => expect(downloads).toHaveLength(1), T)
    expect(requested).toEqual(['0'])

    await userEvent.click(screen.getByRole('button', { name: 'Regerar' }))
    await waitFor(() => expect(downloads).toHaveLength(2), T)
    expect(requested).toEqual(['0', '1'])
  })

  it('a fresh generation flips the panel to the ready state without a new LLM call', async () => {
    const listing = mockDetail(makeListing({ hasOneClickResume: false }))
    renderApp(<ListingDetail listingId={listing.id} onClose={noop} />)

    await userEvent.click(
      await screen.findByRole('button', { name: 'Gerar currículo em um clique' }, T),
    )

    expect(await screen.findByRole('button', { name: 'Baixar PDF' }, T)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Regerar' })).toBeInTheDocument()
  })

  // --- Refusals ---

  it('disables One-click before the click when the description is too short to be a posting', async () => {
    const listing = mockDetail(makeListing({ id: 103, descriptionWordCount: 8 }))
    renderApp(<ListingDetail listingId={listing.id} onClose={noop} />)

    const button = await screen.findByRole('button', { name: 'Gerar currículo em um clique' }, T)
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('title', TOO_SHORT_HINT)
    expect(screen.getByText(TOO_SHORT_HINT)).toBeInTheDocument()
  })

  it('a 422 from the backend disables the button too, and never shows the raw error code', async () => {
    // Word count says it is long enough; the backend's own predicate disagrees. The server wins.
    const listing = mockDetail(makeListing({ descriptionWordCount: 42 }))
    server.use(mockOneClickTooShort(listing.id))
    renderApp(<ListingDetail listingId={listing.id} onClose={noop} />)

    await userEvent.click(
      await screen.findByRole('button', { name: 'Gerar currículo em um clique' }, T),
    )

    expect(await screen.findByRole('alert', undefined, T)).toHaveTextContent(TOO_SHORT_HINT)
    expect(screen.getByRole('button', { name: 'Gerar currículo em um clique' })).toBeDisabled()
    expect(screen.queryByText(/description_too_short/)).not.toBeInTheDocument()
  })

  it('a 409 says a One-click for this listing is already running', async () => {
    const listing = mockDetail(makeListing())
    server.use(mockOneClickConflict(listing.id))
    renderApp(<ListingDetail listingId={listing.id} onClose={noop} />)

    await userEvent.click(
      await screen.findByRole('button', { name: 'Gerar currículo em um clique' }, T),
    )

    expect(await screen.findByRole('alert', undefined, T)).toHaveTextContent(
      'Já existe um currículo sendo gerado para esta vaga.',
    )
  })

  it("a 502 shows the backend's actionable message and leaves the button usable for a retry", async () => {
    const listing = mockDetail(makeListing())
    server.use(mockOneClickLlmError(listing.id, 'O provedor de IA não respondeu. Tente de novo.'))
    renderApp(<ListingDetail listingId={listing.id} onClose={noop} />)

    await userEvent.click(
      await screen.findByRole('button', { name: 'Gerar currículo em um clique' }, T),
    )

    expect(await screen.findByRole('alert', undefined, T)).toHaveTextContent(
      'O provedor de IA não respondeu. Tente de novo.',
    )
    expect(screen.getByRole('button', { name: 'Gerar currículo em um clique' })).toBeEnabled()
  })

  // --- Abrir no chat ---

  it('opens the listing in the chat: selects the created session and switches to the resume area', async () => {
    useAppModeStore.setState({ mode: 'jobs' })
    const listing = mockDetail(makeListing())
    server.use(
      http.post(`/api/jobs/listings/${listing.id}/open-in-chat`, () =>
        HttpResponse.json({ sessionId: 77 }),
      ),
      http.get('/api/chat/sessions/77', () =>
        HttpResponse.json({
          session: {
            id: 77,
            title: 'Acme Cloud · Senior Backend Engineer',
            updatedAt: '2026-08-25T12:00:00Z',
            activeResumeVersionId: null,
          },
          messages: [
            {
              id: 1,
              role: 'user',
              content: 'We are hiring a Senior Backend Engineer',
              intent: null,
              resumeVersionId: null,
              createdAt: '2026-08-25T12:00:00Z',
            },
          ],
          activeResume: null,
        }),
      ),
    )
    renderApp(<ListingDetail listingId={listing.id} onClose={noop} />)

    await userEvent.click(await screen.findByRole('button', { name: 'Abrir no chat' }, T))

    await waitFor(() => expect(useChatStore.getState().sessionId).toBe(77), T)
    expect(useAppModeStore.getState().mode).toBe('resume')
    expect(useChatStore.getState().messages).toHaveLength(1)
  })

  it('stays in the Job Monitor when the session cannot be opened', async () => {
    useAppModeStore.setState({ mode: 'jobs' })
    const listing = mockDetail(makeListing())
    server.use(
      http.post(`/api/jobs/listings/${listing.id}/open-in-chat`, () =>
        HttpResponse.json({ detail: 'listing not found' }, { status: 404 }),
      ),
    )
    renderApp(<ListingDetail listingId={listing.id} onClose={noop} />)

    await userEvent.click(await screen.findByRole('button', { name: 'Abrir no chat' }, T))

    expect(await screen.findByRole('alert', undefined, T)).toHaveTextContent(
      'Não foi possível abrir esta vaga no chat.',
    )
    expect(useAppModeStore.getState().mode).toBe('jobs')
  })

  // --- Loading / failure of the detail itself ---

  it('reports a detail that cannot be loaded instead of rendering an empty panel', async () => {
    server.use(
      http.get('/api/jobs/listings/999', () =>
        HttpResponse.json({ detail: 'listing not found' }, { status: 404 }),
      ),
    )
    renderApp(<ListingDetail listingId={999} onClose={noop} />)

    expect(await screen.findByRole('alert', undefined, T)).toHaveTextContent(
      'Não foi possível carregar esta vaga.',
    )
  })

  it('closes the panel through the header button', async () => {
    const listing = mockDetail(makeListing())
    const onClose = vi.fn()
    renderApp(<ListingDetail listingId={listing.id} onClose={onClose} />)

    await userEvent.click(await screen.findByRole('button', { name: 'Fechar detalhe da vaga' }, T))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})

describe('ListingDetail inside JobsShell', () => {
  afterEach(() => {
    window.history.pushState(null, '', '/')
  })

  it('appears when a card is selected and disappears when the panel is closed', async () => {
    renderApp(<JobsShell />)

    const list = await screen.findByRole('list', { name: 'Vagas encontradas' }, T)
    expect(screen.queryByRole('region', { name: 'Descrição da vaga' })).not.toBeInTheDocument()

    await userEvent.click(
      // The card's select button reads title + company + place + date, so match on the title.
      within(list).getByRole('button', { name: /Senior Backend Engineer/ }),
    )

    const panel = await screen.findByRole('region', { name: 'Detalhe da vaga' }, T)
    expect(
      await within(panel).findByRole('region', { name: 'Descrição da vaga' }, T),
    ).toHaveTextContent('design and operate distributed services')

    await userEvent.click(within(panel).getByRole('button', { name: 'Fechar detalhe da vaga' }))
    await waitFor(() =>
      expect(screen.queryByRole('region', { name: 'Descrição da vaga' })).not.toBeInTheDocument(),
    )
  })
})
