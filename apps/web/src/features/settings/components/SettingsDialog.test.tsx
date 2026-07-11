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

  // Design fix round (P1): the ModelPicker's absolutely-positioned Combobox list must never
  // sit inside a scroll-clipping ancestor, or it gets visually cut off mid-scroll. jsdom can't
  // compute actual clipping, but it CAN tell us whether any ancestor between the open listbox
  // and the document opts into overflow-y-auto -- which is the structural precondition for that
  // clip to happen at all.
  it("keeps the model picker's dropdown list free of any overflow-y-auto ancestor", async () => {
    const user = userEvent.setup()
    renderApp(<SettingsDialog />)

    await user.click(screen.getByRole('button', { name: /^settings$/i }))
    await user.click(await screen.findByRole('combobox', { name: /default model/i }))

    const listbox = await screen.findByRole('listbox')
    for (let node = listbox.parentElement; node; node = node.parentElement) {
      expect(node.className).not.toMatch(/overflow-y-auto/)
    }
  })
})
