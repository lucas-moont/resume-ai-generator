import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { ListingList } from './ListingList'
import { makeListing, mockListings } from '../../../test/msw/jobsScenarios'
import { renderApp } from '../../../test/render'
import { server } from '../../../test/setup'

describe('ListingList', () => {
  it('renders the last Scan in the order the server sent (Visibility desc), dismissed hidden', async () => {
    renderApp(<ListingList filters={{}} selectedListingId={null} onSelect={vi.fn()} />)

    const list = await screen.findByRole('list', { name: 'Vagas encontradas' })
    const titles = within(list)
      .getAllByRole('heading')
      .map((h) => h.textContent)

    expect(titles).toEqual([
      'Senior Backend Engineer',
      'Engenheiro de Software Backend',
      'Full Stack Developer',
    ])
  })

  it('passes the filters through to the request instead of slicing client-side', async () => {
    const urls: string[] = []
    server.use(
      http.get('/api/jobs/listings', ({ request }) => {
        urls.push(new URL(request.url).search)
        return HttpResponse.json({ listings: [] })
      }),
    )

    renderApp(
      <ListingList
        filters={{ board: 'indeed', maxBand: '<50', status: 'seen' }}
        selectedListingId={null}
        onSelect={vi.fn()}
      />,
    )

    await waitFor(() => expect(urls).toHaveLength(1))
    expect(urls[0]).toContain('board=indeed')
    expect(urls[0]).toContain('max_band=%3C50')
    expect(urls[0]).toContain('status=seen')
  })

  it('says the list is empty rather than rendering nothing', async () => {
    server.use(mockListings([]))
    renderApp(<ListingList filters={{}} selectedListingId={null} onSelect={vi.fn()} />)

    expect(
      await screen.findByText('Nenhuma vaga na última varredura com esses filtros.'),
    ).toBeInTheDocument()
  })

  it('surfaces a failed load', async () => {
    server.use(
      http.get('/api/jobs/listings', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    )
    renderApp(<ListingList filters={{}} selectedListingId={null} onSelect={vi.fn()} />)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Não foi possível carregar as vagas.',
    )
  })

  it('reports the clicked listing id up to the shell', async () => {
    const onSelect = vi.fn()
    const user = userEvent.setup()
    server.use(mockListings([makeListing({ id: 777, title: 'Staff Engineer' })]))
    renderApp(<ListingList filters={{}} selectedListingId={null} onSelect={onSelect} />)

    await user.click(await screen.findByRole('button', { name: /Staff Engineer/ }))

    expect(onSelect).toHaveBeenCalledWith(777)
  })

  it('highlights the selected card', async () => {
    const { container } = renderApp(
      <ListingList filters={{}} selectedListingId={102} onSelect={vi.fn()} />,
    )

    await screen.findByRole('list', { name: 'Vagas encontradas' })
    const selected = container.querySelectorAll('li[aria-current="true"]')
    expect(selected).toHaveLength(1)
    expect(selected[0]).toHaveTextContent('Engenheiro de Software Backend')
  })
})
