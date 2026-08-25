import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import { JobsShell } from './JobsShell'
import {
  makeRunningScan,
  mockNoScans,
  mockScanRunning,
} from '../../../test/msw/jobsScenarios'
import { renderApp } from '../../../test/render'
import { server } from '../../../test/setup'

// Mounting the whole area runs the Search Profile form's queries too; under full-suite parallel
// load those settle slowly, so every findBy gets a generous timeout (same call as appMode.test).
const T = { timeout: 15000 }

afterEach(() => {
  window.history.pushState(null, '', '/')
})

describe('JobsShell', () => {
  it('shows the Search Profile on the left and the ranked list on the right', async () => {
    renderApp(<JobsShell />)

    expect(await screen.findByRole('form', { name: 'Perfil de busca' }, T)).toBeInTheDocument()
    const list = await screen.findByRole('list', { name: 'Vagas encontradas' }, T)
    expect(within(list).getByRole('heading', { name: 'Senior Backend Engineer' })).toBeInTheDocument()
  })

  it("flags the last Scan's blocked board and says when the next one runs", async () => {
    renderApp(<JobsShell />)

    expect(
      await screen.findByText('LinkedIn: bloqueado, tentamos na próxima varredura', undefined, T),
    ).toBeInTheDocument()
    expect(await screen.findByText(/^Próxima varredura: /, undefined, T)).toBeInTheDocument()
  })

  it('says nothing has ever run on a fresh install', async () => {
    server.use(...mockNoScans())
    renderApp(<JobsShell />)

    expect(await screen.findByText('Nenhuma varredura ainda.', undefined, T)).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'Status dos portais' })).not.toBeInTheDocument()
  })

  it('reports the interval being off rather than an empty next-scan line', async () => {
    server.use(
      http.get('/api/jobs/scans/latest', () =>
        HttpResponse.json({ ...makeRunningScan({ status: 'done' }), nextScanAt: null }),
      ),
    )
    renderApp(<JobsShell />)

    expect(
      await screen.findByText('Varredura automática desligada.', undefined, T),
    ).toBeInTheDocument()
  })

  it('"Buscar agora" starts an Immediate Scan and switches to the running state', async () => {
    let posted = 0
    server.use(
      // Nothing is running until the POST lands — otherwise the button would already be
      // disabled and the click under test would be a no-op.
      http.get('/api/jobs/scans/current', () =>
        HttpResponse.json(posted === 0 ? null : makeRunningScan()),
      ),
      http.post('/api/jobs/scans', () => {
        posted += 1
        return HttpResponse.json(makeRunningScan(), { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderApp(<JobsShell />)

    const button = await screen.findByRole('button', { name: 'Buscar agora' }, T)
    await user.click(button)

    await waitFor(() => expect(posted).toBe(1))
    expect(await screen.findByRole('button', { name: 'Buscando…' }, T)).toBeDisabled()
  })

  it('disables the button and shows progress while a Scan already holds the lock', async () => {
    server.use(mockScanRunning())
    renderApp(<JobsShell />)

    expect(await screen.findByRole('button', { name: 'Buscando…' }, T)).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Buscar agora' })).not.toBeInTheDocument()
    expect(
      await screen.findByText('Varredura em andamento · 9 vagas encontradas', undefined, T),
    ).toBeInTheDocument()
    // While running, the live board statuses replace the previous Scan's flags.
    expect(await screen.findByText('Indeed: 9 vagas', undefined, T)).toBeInTheDocument()
  })

  it('absorbs a 409 into the running state instead of showing an error', async () => {
    // A 409 means a Scan really is running, so `/scans/current` starts answering once the POST
    // has been refused — the polling the UI switches to has something to poll.
    let refused = false
    server.use(
      http.get('/api/jobs/scans/current', () =>
        HttpResponse.json(refused ? makeRunningScan() : null),
      ),
      http.post('/api/jobs/scans', () => {
        refused = true
        // The 409 body carries the Scan already holding the single-flight lock.
        return HttpResponse.json({ detail: makeRunningScan() }, { status: 409 })
      }),
    )
    const user = userEvent.setup()
    renderApp(<JobsShell />)

    await user.click(await screen.findByRole('button', { name: 'Buscar agora' }, T))

    expect(await screen.findByRole('button', { name: 'Buscando…' }, T)).toBeDisabled()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('surfaces a start failure that is not a 409', async () => {
    server.use(
      http.post('/api/jobs/scans', () =>
        HttpResponse.json({ detail: 'Nenhum portal habilitado.' }, { status: 400 }),
      ),
    )
    const user = userEvent.setup()
    renderApp(<JobsShell />)

    await user.click(await screen.findByRole('button', { name: 'Buscar agora' }, T))

    expect(await screen.findByRole('alert', undefined, T)).toHaveTextContent(
      'Nenhum portal habilitado.',
    )
  })

  it('filters the list by status, lifting the dismissed default when asked for them', async () => {
    const user = userEvent.setup()
    renderApp(<JobsShell />)

    const list = await screen.findByRole('list', { name: 'Vagas encontradas' }, T)
    expect(within(list).queryByRole('heading', { name: 'PHP Developer' })).not.toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Status'), 'dismissed')

    expect(await screen.findByRole('heading', { name: 'PHP Developer' }, T)).toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: 'Senior Backend Engineer' }),
    ).not.toBeInTheDocument()
  })

  it('filters the list by board', async () => {
    const user = userEvent.setup()
    renderApp(<JobsShell />)

    await screen.findByRole('list', { name: 'Vagas encontradas' }, T)
    await user.selectOptions(screen.getByLabelText('Portal'), 'weworkremotely')

    expect(await screen.findByRole('heading', { name: 'Full Stack Developer' }, T)).toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: 'Senior Backend Engineer' }),
    ).not.toBeInTheDocument()
  })

  it('mirrors the mobile tab in the URL', async () => {
    const user = userEvent.setup()
    renderApp(<JobsShell />)

    const vagas = await screen.findByRole('tab', { name: 'Vagas' }, T)
    expect(screen.getByRole('tab', { name: 'Busca' })).toHaveAttribute('aria-selected', 'true')

    await user.click(vagas)

    expect(vagas).toHaveAttribute('aria-selected', 'true')
    expect(new URLSearchParams(window.location.search).get('tab')).toBe('vagas')
  })
})
