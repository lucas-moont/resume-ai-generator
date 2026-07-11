import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { SettingsDialog } from './SettingsDialog'
import { renderApp } from '../../../test/render'

describe('SettingsDialog', () => {
  it('renders a gear trigger button, closed by default', () => {
    renderApp(<SettingsDialog />)

    expect(screen.getByRole('button', { name: /settings/i })).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('opens the dialog (with the ProviderForm content) when the gear button is clicked', async () => {
    const user = userEvent.setup()
    renderApp(<SettingsDialog />)

    await user.click(screen.getByRole('button', { name: /settings/i }))

    expect(screen.getByRole('dialog', { name: /settings/i })).toBeInTheDocument()
    expect(await screen.findByRole('group', { name: /active provider/i })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: /^api keys$/i })).toBeInTheDocument()
  })

  it('closes via the dialog\'s own close control', async () => {
    const user = userEvent.setup()
    renderApp(<SettingsDialog />)

    await user.click(screen.getByRole('button', { name: /^settings$/i }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /close settings/i }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
})
