import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { ListingCard } from './ListingCard'
import { makeListing } from '../../../test/msw/jobsScenarios'
import { renderApp } from '../../../test/render'
import { server } from '../../../test/setup'
import type { JobListingDto } from '../../../lib/api/dto'

function renderCard(listing: JobListingDto, onSelect = vi.fn(), selected = false) {
  return renderApp(
    <ul>
      <ListingCard listing={listing} selected={selected} onSelect={onSelect} />
    </ul>,
  )
}

/** Captures the PATCH the quick actions send, and answers with the updated listing the way the
 * router does. */
function captureStatusPatch() {
  const calls: { id: string; status: string }[] = []
  server.use(
    http.patch('/api/jobs/listings/:id/status', async ({ params, request }) => {
      const body = (await request.json()) as { status: string }
      calls.push({ id: String(params.id), status: body.status })
      return HttpResponse.json({ ...makeListing(), status: body.status })
    }),
  )
  return calls
}

describe('ListingCard', () => {
  it('renders title, company, place and the ranking badges', () => {
    renderCard(makeListing())

    expect(screen.getByRole('heading', { name: 'Senior Backend Engineer' })).toBeInTheDocument()
    expect(screen.getByText('Acme Cloud · Remote')).toBeInTheDocument()
    expect(screen.getByText('Fit 88%')).toBeInTheDocument()
    expect(screen.getByText('Visibilidade 91')).toBeInTheDocument()
    expect(screen.getByText('<10 candidatos')).toBeInTheDocument()
    expect(screen.getByText('Nova')).toBeInTheDocument()
    expect(screen.queryByText('Repostada')).not.toBeInTheDocument()
  })

  it('marks a Repost and marks a Fit that came from the cheap keyword pass', () => {
    renderCard(
      makeListing({ isRepost: true, fitScore: 54, fitEstimated: true, applicantBand: 'unknown' }),
    )

    expect(screen.getByText('Repostada')).toBeInTheDocument()
    expect(screen.getByText('Fit ~54%')).toBeInTheDocument()
    expect(screen.getByText('candidatos: n/d')).toBeInTheDocument()
  })

  it('links every Listing Source by board name (dedup must not cost a board)', () => {
    renderCard(makeListing())

    const sources = within(screen.getByRole('list', { name: 'Fontes' }))
    expect(sources.getByRole('link', { name: 'LinkedIn' })).toHaveAttribute(
      'href',
      'https://www.linkedin.com/jobs/view/101',
    )
    expect(sources.getByRole('link', { name: 'Remotive' })).toHaveAttribute(
      'href',
      'https://remotive.com/remote-jobs/101',
    )
  })

  it('"Candidatei" PATCHes the status to applied', async () => {
    const calls = captureStatusPatch()
    const user = userEvent.setup()
    renderCard(makeListing())

    await user.click(screen.getByRole('button', { name: 'Candidatei' }))

    await waitFor(() => expect(calls).toEqual([{ id: '101', status: 'applied' }]))
  })

  it('"Descartar" PATCHes the status to dismissed', async () => {
    const calls = captureStatusPatch()
    const user = userEvent.setup()
    renderCard(makeListing())

    await user.click(screen.getByRole('button', { name: 'Descartar' }))

    await waitFor(() => expect(calls).toEqual([{ id: '101', status: 'dismissed' }]))
  })

  it("offers 'Restaurar' (to 'seen', never back to 'new') on a dismissed listing", async () => {
    const calls = captureStatusPatch()
    const user = userEvent.setup()
    renderCard(makeListing({ id: 104, status: 'dismissed' }))

    expect(screen.queryByRole('button', { name: 'Descartar' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Restaurar' }))

    await waitFor(() => expect(calls).toEqual([{ id: '104', status: 'seen' }]))
  })

  it('hides "Candidatei" once the listing is already applied', () => {
    renderCard(makeListing({ status: 'applied' }))

    expect(screen.queryByRole('button', { name: 'Candidatei' })).not.toBeInTheDocument()
    expect(screen.getByText('Candidatei-me')).toBeInTheDocument()
  })

  it('reports a failed status change instead of silently keeping the old one', async () => {
    server.use(
      http.patch('/api/jobs/listings/:id/status', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    )
    const user = userEvent.setup()
    renderCard(makeListing())

    await user.click(screen.getByRole('button', { name: 'Candidatei' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Não foi possível atualizar o status desta vaga.',
    )
  })

  it('selects the listing from the title button and shows the selection', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    renderCard(makeListing(), onSelect)

    await user.click(screen.getByRole('button', { name: /Senior Backend Engineer/ }))

    expect(onSelect).toHaveBeenCalledWith(101)
  })

  it('marks the selected card with aria-current', () => {
    const { container } = renderCard(makeListing(), vi.fn(), true)

    expect(container.querySelector('li[aria-current="true"]')).not.toBeNull()
  })
})
