import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { ModelPicker } from './ModelPicker'
import { server } from '../../../test/setup'
import { renderApp } from '../../../test/render'

const ALL_MODELS = [
  { value: 'claude-sonnet-5', label: 'Claude Sonnet 5', provider: 'claude' },
  { value: 'claude-haiku-4-5', label: 'Claude Haiku 4.5', provider: 'claude' },
  { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash', provider: 'gemini' },
  { value: 'llama3.2', label: 'llama3.2 (Ollama, local)', provider: 'ollama' },
]

function mockModels() {
  server.use(http.get('/api/models', () => HttpResponse.json({ default: 'claude-sonnet-5', models: ALL_MODELS })))
}

describe('ModelPicker', () => {
  it('only offers the given provider models', async () => {
    mockModels()
    const user = userEvent.setup()
    renderApp(<ModelPicker id="model-picker" provider="claude" value="" onSelect={vi.fn()} />)

    await user.click(screen.getByRole('combobox', { name: /default model/i }))

    expect(await screen.findByRole('option', { name: /claude sonnet 5/i })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /claude haiku 4\.5/i })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /gemini/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /llama/i })).not.toBeInTheDocument()
  })

  it('offers every provider model when provider is auto', async () => {
    mockModels()
    const user = userEvent.setup()
    renderApp(<ModelPicker id="model-picker" provider="auto" value="" onSelect={vi.fn()} />)

    await user.click(screen.getByRole('combobox', { name: /default model/i }))

    expect(await screen.findByRole('option', { name: /claude sonnet 5/i })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /gemini 2\.5 flash/i })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /llama/i })).toBeInTheDocument()
  })

  it('calls onSelect with the chosen model value', async () => {
    mockModels()
    const onSelect = vi.fn()
    const user = userEvent.setup()
    renderApp(<ModelPicker id="model-picker" provider="claude" value="" onSelect={onSelect} />)

    await user.click(screen.getByRole('combobox', { name: /default model/i }))
    await user.click(await screen.findByRole('option', { name: /claude haiku 4\.5/i }))

    expect(onSelect).toHaveBeenCalledWith('claude-haiku-4-5')
  })

  it('shows a loading empty-state before the catalog resolves, and "no models" once resolved empty', async () => {
    server.use(http.get('/api/models', () => HttpResponse.json({ default: undefined, models: [] })))
    const user = userEvent.setup()
    renderApp(<ModelPicker id="model-picker" provider="claude" value="" onSelect={vi.fn()} />)

    await user.click(screen.getByRole('combobox', { name: /default model/i }))

    expect(await screen.findByText(/no models available/i)).toBeInTheDocument()
  })
})
