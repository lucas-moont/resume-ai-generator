import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { AppHeader } from './AppHeader'
import { renderApp } from '../test/render'

describe('AppHeader', () => {
  it('opens the SettingsDialog from its gear button (v3 ticket 06)', async () => {
    const user = userEvent.setup()
    renderApp(<AppHeader />)

    await user.click(screen.getByRole('button', { name: /^settings$/i }))

    expect(screen.getByRole('dialog', { name: /settings/i })).toBeInTheDocument()
  })
})
