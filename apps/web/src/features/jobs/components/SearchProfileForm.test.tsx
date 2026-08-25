import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { SearchProfileForm } from './SearchProfileForm'
import { server } from '../../../test/setup'
import { renderApp } from '../../../test/render'
import {
  SAMPLE_SEARCH_PROFILE,
  SUGGESTED_SEARCH_PROFILE,
} from '../../../test/msw/jobsScenarios'
import type { SearchProfileDto, SearchProfileUpdateRequest } from '../../../lib/api/dto'

/** Captures the body of `PUT /api/jobs/search-profile` and echoes it back like the baseline
 * handler does, so the test can assert on the WHOLE payload — the profile is sent entire on
 * every save, never patched. */
function captureSave() {
  const calls: SearchProfileUpdateRequest[] = []
  server.use(
    http.put('/api/jobs/search-profile', async ({ request }) => {
      const body = (await request.json()) as SearchProfileUpdateRequest
      calls.push(body)
      return HttpResponse.json({ ...body, updatedAt: '2026-08-25T12:00:00Z' })
    }),
  )
  return calls
}

function mockProfile(profile: SearchProfileDto) {
  server.use(http.get('/api/jobs/search-profile', () => HttpResponse.json(profile)))
}

/** The chips of one group, read off their remove buttons — an accessible name is what the user
 * actually has to distinguish two chips by. */
function chipsOf(group: HTMLElement, kind: string): string[] {
  const prefix = `Remover ${kind} `
  return within(group)
    .queryAllByRole('button', { name: new RegExp(`^${prefix}`) })
    .map((button) => (button.getAttribute('aria-label') ?? '').slice(prefix.length))
}

async function renderForm() {
  const user = userEvent.setup()
  renderApp(<SearchProfileForm />)
  await screen.findByRole('form', { name: 'Perfil de busca' })
  return user
}

describe('SearchProfileForm', () => {
  it('renders the saved Search Profile: chips, remote, languages, boards and both selects', async () => {
    await renderForm()

    for (const role of SAMPLE_SEARCH_PROFILE.roles) {
      expect(screen.getByText(role)).toBeInTheDocument()
    }
    for (const location of SAMPLE_SEARCH_PROFILE.locations) {
      expect(screen.getByText(location)).toBeInTheDocument()
    }
    expect(screen.getByRole('radio', { name: 'Tanto faz' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Português' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Inglês' })).toBeChecked()
    // SAMPLE_SEARCH_PROFILE.boards = linkedin + indeed + remotive
    expect(screen.getByRole('checkbox', { name: 'LinkedIn' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Remotive' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Glassdoor' })).not.toBeChecked()
    expect(screen.getByLabelText('Máximo de candidatos')).toHaveValue('<50')
    expect(screen.getByLabelText('Intervalo de varredura')).toHaveValue('6')
  })

  it('shows the loading state and then an alert when the profile cannot be loaded', async () => {
    server.use(
      http.get('/api/jobs/search-profile', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })),
    )
    renderApp(<SearchProfileForm />)

    expect(screen.getByText('Carregando perfil de busca…')).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Não foi possível carregar o perfil de busca.',
    )
  })

  it('adds a role chip with Enter without submitting the form', async () => {
    const calls = captureSave()
    const user = await renderForm()

    await user.type(screen.getByLabelText('Adicionar cargo'), 'Staff Engineer{Enter}')

    expect(screen.getByText('Staff Engineer')).toBeInTheDocument()
    expect(screen.getByLabelText('Adicionar cargo')).toHaveValue('')
    expect(calls).toHaveLength(0)
  })

  it('adds a location chip with the Adicionar button and removes one with its × button', async () => {
    const user = await renderForm()

    const locations = screen.getByRole('group', { name: 'Localizações' })
    await user.type(within(locations).getByLabelText('Adicionar localização'), 'Portugal')
    await user.click(within(locations).getByRole('button', { name: 'Adicionar' }))
    expect(screen.getByText('Portugal')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Remover localização Brasil' }))
    expect(screen.queryByText('Brasil')).not.toBeInTheDocument()
    expect(screen.getByText('Portugal')).toBeInTheDocument()
  })

  it('rejects a duplicate chip case-insensitively and keeps the list unchanged', async () => {
    const user = await renderForm()

    const roles = screen.getByRole('group', { name: 'Cargos-alvo' })
    await user.type(within(roles).getByLabelText('Adicionar cargo'), '  backend engineer  ')
    await user.click(within(roles).getByRole('button', { name: 'Adicionar' }))

    expect(within(roles).getByRole('alert')).toHaveTextContent('Já está na lista.')
    expect(chipsOf(roles, 'cargo')).toEqual(['Backend Engineer', 'Engenheiro de Software'])
  })

  it('the Adicionar button is disabled for blank input', async () => {
    const user = await renderForm()

    const roles = screen.getByRole('group', { name: 'Cargos-alvo' })
    expect(within(roles).getByRole('button', { name: 'Adicionar' })).toBeDisabled()
    await user.type(within(roles).getByLabelText('Adicionar cargo'), '   ')
    expect(within(roles).getByRole('button', { name: 'Adicionar' })).toBeDisabled()
  })

  it('saves the whole profile, sending every edited field', async () => {
    const calls = captureSave()
    const user = await renderForm()

    await user.type(screen.getByLabelText('Adicionar cargo'), 'Staff Engineer{Enter}')
    await user.click(screen.getByRole('button', { name: 'Remover cargo Backend Engineer' }))
    await user.click(screen.getByRole('radio', { name: 'Só remoto' }))
    await user.click(screen.getByRole('checkbox', { name: 'Português' }))
    await user.click(screen.getByRole('checkbox', { name: 'Glassdoor' }))
    await user.selectOptions(screen.getByLabelText('Máximo de candidatos'), '<10')
    await user.selectOptions(screen.getByLabelText('Intervalo de varredura'), '3')
    await user.click(screen.getByRole('button', { name: 'Salvar' }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toEqual({
      roles: ['Engenheiro de Software', 'Staff Engineer'],
      locations: ['Brasil', 'Remote'],
      remote: 'remote_only',
      languages: ['en'],
      boards: ['linkedin', 'indeed', 'remotive', 'glassdoor'],
      maxApplicantBand: '<10',
      intervalHours: 3,
    })
    expect(await screen.findByText('Perfil de busca salvo.')).toBeInTheDocument()
  })

  it('sends null for "qualquer" and for the "off" interval', async () => {
    const calls = captureSave()
    const user = await renderForm()

    const bandSelect = screen.getByLabelText('Máximo de candidatos')
    const intervalSelect = screen.getByLabelText('Intervalo de varredura')
    await user.selectOptions(bandSelect, within(bandSelect).getByRole('option', { name: 'qualquer' }))
    await user.selectOptions(intervalSelect, within(intervalSelect).getByRole('option', { name: 'off' }))
    await user.click(screen.getByRole('button', { name: 'Salvar' }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].maxApplicantBand).toBeNull()
    expect(calls[0].intervalHours).toBeNull()
    expect(
      screen.getByText('Sem varredura automática — "Buscar agora" continua valendo.'),
    ).toBeInTheDocument()
  })

  it('reports a failed save without losing the draft', async () => {
    server.use(
      http.put('/api/jobs/search-profile', () => HttpResponse.json({ detail: 'nope' }, { status: 500 })),
    )
    const user = await renderForm()

    await user.type(screen.getByLabelText('Adicionar cargo'), 'Staff Engineer{Enter}')
    await user.click(screen.getByRole('button', { name: 'Salvar' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Não foi possível salvar o perfil de busca. Tente de novo.',
    )
    expect(screen.getByText('Staff Engineer')).toBeInTheDocument()
  })

  it('"Sugerir do meu perfil" fills the form and saves nothing', async () => {
    const calls = captureSave()
    const user = await renderForm()

    await user.click(screen.getByRole('button', { name: 'Sugerir do meu perfil' }))

    expect(await screen.findByText(SUGGESTED_SEARCH_PROFILE.roles[0])).toBeInTheDocument()
    expect(screen.queryByText('Backend Engineer')).not.toBeInTheDocument()
    // SUGGESTED_SEARCH_PROFILE: maxApplicantBand null, and two more boards enabled.
    expect(screen.getByLabelText('Máximo de candidatos')).toHaveValue('')
    expect(screen.getByRole('checkbox', { name: 'Remote OK' })).toBeChecked()
    expect(
      screen.getByText('Sugestão preenchida a partir do seu perfil. Revise e clique em Salvar.'),
    ).toBeInTheDocument()
    expect(calls).toHaveLength(0)
  })

  it('reports a failed suggestion', async () => {
    server.use(
      http.post('/api/jobs/search-profile/suggest', () =>
        HttpResponse.json({ detail: 'nope' }, { status: 500 }),
      ),
    )
    const user = await renderForm()

    await user.click(screen.getByRole('button', { name: 'Sugerir do meu perfil' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Não foi possível sugerir a partir do seu perfil. Tente de novo.',
    )
  })

  it('shows each board minimum above 1h and the attribution note for Remotive and Remote OK', async () => {
    await renderForm()

    // Remotive's terms cap us at 4 calls a day.
    expect(screen.getByText('mín. 6h')).toBeInTheDocument()
    const notes = screen.getAllByText('Os termos deste portal exigem citar a fonte em cada vaga.')
    expect(notes).toHaveLength(2)
    expect(screen.getByRole('checkbox', { name: 'Remotive' })).toHaveAccessibleDescription(
      'Os termos deste portal exigem citar a fonte em cada vaga.',
    )
    expect(screen.getByRole('checkbox', { name: 'Remote OK' })).toHaveAccessibleDescription(
      'Os termos deste portal exigem citar a fonte em cada vaga.',
    )
    expect(screen.getByRole('checkbox', { name: 'LinkedIn' })).not.toHaveAccessibleDescription()
  })

  it('warns that a board keeps its own pace when the chosen interval is below its minimum', async () => {
    const user = await renderForm()

    expect(screen.queryByText(/Ritmo próprio destes portais/)).not.toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Intervalo de varredura'), '1')
    expect(screen.getByText(/Ritmo próprio destes portais: Remotive \(6h\)\./)).toBeInTheDocument()

    // Turning that board off removes the warning: it only applies to boards actually enabled.
    await user.click(screen.getByRole('checkbox', { name: 'Remotive' }))
    expect(screen.queryByText(/Ritmo próprio destes portais/)).not.toBeInTheDocument()
  })

  it('warns when there is nothing to search for or nowhere to search', async () => {
    mockProfile({ ...SAMPLE_SEARCH_PROFILE, roles: [], boards: [] })
    await renderForm()

    expect(screen.getByText('Sem cargos-alvo, uma varredura não tem o que buscar.')).toBeInTheDocument()
    expect(
      screen.getByText('Sem nenhum portal ligado, uma varredura não consulta nada.'),
    ).toBeInTheDocument()
  })

  it('saving an empty profile is allowed — the form mirrors the contract, which permits it', async () => {
    mockProfile({ ...SAMPLE_SEARCH_PROFILE, roles: [], boards: [] })
    const calls = captureSave()
    const user = await renderForm()

    await user.click(screen.getByRole('button', { name: 'Salvar' }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].roles).toEqual([])
    expect(calls[0].boards).toEqual([])
  })

  it('preserves a language it has no toggle for instead of dropping it on save', async () => {
    mockProfile({ ...SAMPLE_SEARCH_PROFILE, languages: ['pt', 'es'] })
    const calls = captureSave()
    const user = await renderForm()

    expect(screen.getByRole('checkbox', { name: 'Português' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Inglês' })).not.toBeChecked()
    expect(screen.getByText('es')).toBeInTheDocument()

    await user.click(screen.getByRole('checkbox', { name: 'Inglês' }))
    await user.click(screen.getByRole('button', { name: 'Salvar' }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].languages).toEqual(['pt', 'es', 'en'])
  })

  it('drops an extra language through its chip', async () => {
    mockProfile({ ...SAMPLE_SEARCH_PROFILE, languages: ['pt', 'es'] })
    const calls = captureSave()
    const user = await renderForm()

    await user.click(screen.getByRole('button', { name: 'Remover idioma es' }))
    await user.click(screen.getByRole('button', { name: 'Salvar' }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].languages).toEqual(['pt'])
  })

  it('shows when the profile was last saved, and says so when it never was', async () => {
    mockProfile({ ...SAMPLE_SEARCH_PROFILE, updatedAt: null })
    await renderForm()

    expect(screen.getByText('Ainda não salvo.')).toBeInTheDocument()
  })

  it('gives every chip remove button a 24px hit target', async () => {
    await renderForm()

    const remove = screen.getByRole('button', { name: 'Remover cargo Backend Engineer' })
    expect(remove).toHaveClass('h-6', 'w-6')
  })
})
