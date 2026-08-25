import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { AppShell } from './AppShell'
import { renderApp } from '../test/render'
import { useAppModeStore } from './appModeStore'

beforeEach(() => {
  useAppModeStore.setState({ mode: 'resume' })
})

describe('App mode toggle', () => {
  it('switches from the resume flow to the Profile Analysis area and back', async () => {
    // Rendering the full AppShell mounts both flows' panels + their queries, which is slow
    // under full-suite parallel load — generous findBy timeouts keep this from flaking.
    const T = { timeout: 15000 }
    const user = userEvent.setup()
    renderApp(<AppShell />)

    // Starts in resume mode: the resume sidebar's "New chat" is present.
    expect(await screen.findByRole('button', { name: /new chat/i }, T)).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Análise de Perfil' }))

    // Analysis area is shown: its empty-state heading + "Nova análise", resume "New chat" gone.
    expect(await screen.findByRole('heading', { name: /análise de perfil do linkedin/i }, T)).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /nova análise/i }, T)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /new chat/i })).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Currículo' }))
    expect(await screen.findByRole('button', { name: /new chat/i }, T)).toBeInTheDocument()
  })

  it('switches to the Job Monitor area and back (v7 ticket 12)', async () => {
    const T = { timeout: 15000 }
    const user = userEvent.setup()
    renderApp(<AppShell />)

    expect(await screen.findByRole('button', { name: /new chat/i }, T)).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Monitor de Vagas' }))

    // Both of the jobs area's columns are mounted: the Search Profile form and the ranked list.
    expect(await screen.findByRole('form', { name: 'Perfil de busca' }, T)).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Buscar agora' }, T)).toBeInTheDocument()
    expect(await screen.findByRole('list', { name: 'Vagas encontradas' }, T)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /new chat/i })).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Currículo' }))
    expect(await screen.findByRole('button', { name: /new chat/i }, T)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Buscar agora' })).not.toBeInTheDocument()
  })
})
