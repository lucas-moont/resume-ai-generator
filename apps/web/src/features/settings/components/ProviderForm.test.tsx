import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { ProviderForm } from './ProviderForm'
import { server } from '../../../test/setup'
import { renderApp } from '../../../test/render'
import { DEFAULT_KEYS_SETTINGS, DEFAULT_PROVIDERS_SETTINGS } from '../../../test/msw/handlers'

function mockProviders(overrides: Partial<typeof DEFAULT_PROVIDERS_SETTINGS> = {}) {
  server.use(
    http.get('/api/settings/providers', () =>
      HttpResponse.json({ ...DEFAULT_PROVIDERS_SETTINGS, ...overrides }),
    ),
  )
}

function mockKeys(keys: typeof DEFAULT_KEYS_SETTINGS.keys) {
  server.use(http.get('/api/settings/keys', () => HttpResponse.json({ keys })))
}

describe('ProviderForm', () => {
  describe('provider badges', () => {
    it('shows availability and auth mode per provider', async () => {
      mockProviders()
      renderApp(<ProviderForm />)

      const claudeRow = (await screen.findByText('Claude (Anthropic)')).closest('label') as HTMLElement
      expect(within(claudeRow).getByText(/unavailable/i)).toBeInTheDocument()

      const geminiRow = screen.getByText('Gemini (Google)').closest('label') as HTMLElement
      expect(within(geminiRow).getByText(/unavailable/i)).toBeInTheDocument()
    })

    it('shows a provider as available when the backend reports it so', async () => {
      mockProviders({
        providers: DEFAULT_PROVIDERS_SETTINGS.providers.map((p) =>
          p.name === 'claude' ? { ...p, available: true, auth: 'api_key' } : p,
        ),
      })
      renderApp(<ProviderForm />)

      const claudeRow = (await screen.findByText('Claude (Anthropic)')).closest('label') as HTMLElement
      expect(within(claudeRow).getByText(/^available/i)).toBeInTheDocument()
    })
  })

  describe('provider switch flow', () => {
    it('switching the active provider PUTs immediately and reflects the new active selection', async () => {
      mockProviders()
      let putBody: unknown
      server.use(
        http.put('/api/settings/providers', async ({ request }) => {
          putBody = await request.json()
          // Mimics the real backend: the write takes effect immediately, so the very next
          // GET (triggered by useUpdateProviderSettings's invalidation) reflects it.
          mockProviders({ active: 'claude' })
          return HttpResponse.json({ ...DEFAULT_PROVIDERS_SETTINGS, active: 'claude' })
        }),
      )
      const user = userEvent.setup()
      renderApp(<ProviderForm />)

      const autoRadio = await screen.findByRole('radio', { name: /auto/i })
      expect(autoRadio).toBeChecked()

      const claudeRadio = screen.getByRole('radio', { name: /^Claude \(Anthropic\)/ })
      await user.click(claudeRadio)

      await waitFor(() => expect(putBody).toEqual({ provider: 'claude' }))
      await waitFor(() => expect(claudeRadio).toBeChecked())
    })
  })

  describe('key set/remove flow', () => {
    it('a key configured via env is read-only (no input, no remove button)', async () => {
      mockProviders()
      mockKeys([
        { name: 'ANTHROPIC_API_KEY', configured: true, source: 'env' },
        { name: 'GEMINI_API_KEY', configured: false, source: null },
        { name: 'GITHUB_TOKEN', configured: false, source: null },
      ])
      renderApp(<ProviderForm />)

      expect(await screen.findByText(/configured via environment/i)).toBeInTheDocument()
      expect(screen.queryByLabelText(/anthropic api key/i)).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /remove anthropic/i })).not.toBeInTheDocument()
    })

    it('saving a new key PUTs it and clears the input afterward', async () => {
      mockProviders()
      mockKeys([
        { name: 'ANTHROPIC_API_KEY', configured: false, source: null },
        { name: 'GEMINI_API_KEY', configured: false, source: null },
        { name: 'GITHUB_TOKEN', configured: false, source: null },
      ])
      let putBody: unknown
      server.use(
        http.put('/api/settings/keys', async ({ request }) => {
          putBody = await request.json()
          return HttpResponse.json({ name: 'GEMINI_API_KEY', configured: true, source: 'keychain' })
        }),
      )
      const user = userEvent.setup()
      renderApp(<ProviderForm />)

      const input = await screen.findByLabelText('Gemini API key')
      await user.type(input, 'brand-new-secret-value')
      await user.click(screen.getByRole('button', { name: /save gemini api key/i }))

      await waitFor(() =>
        expect(putBody).toEqual({ name: 'GEMINI_API_KEY', value: 'brand-new-secret-value' }),
      )
      await waitFor(() => expect(input).toHaveValue(''))
      // Secret hygiene: the typed value must never linger anywhere in the rendered DOM.
      expect(screen.queryByText('brand-new-secret-value')).not.toBeInTheDocument()
    })

    it('removing a keychain-sourced key calls DELETE and the row reverts to unconfigured', async () => {
      mockProviders()
      mockKeys([
        { name: 'ANTHROPIC_API_KEY', configured: false, source: null },
        { name: 'GEMINI_API_KEY', configured: true, source: 'keychain' },
        { name: 'GITHUB_TOKEN', configured: false, source: null },
      ])
      let deleteCalled = false
      server.use(
        http.delete('/api/settings/keys/GEMINI_API_KEY', () => {
          deleteCalled = true
          mockKeys([
            { name: 'ANTHROPIC_API_KEY', configured: false, source: null },
            { name: 'GEMINI_API_KEY', configured: false, source: null },
            { name: 'GITHUB_TOKEN', configured: false, source: null },
          ])
          return new HttpResponse(null, { status: 204 })
        }),
      )
      const user = userEvent.setup()
      renderApp(<ProviderForm />)

      await user.click(await screen.findByRole('button', { name: /remove gemini api key/i }))

      await waitFor(() => expect(deleteCalled).toBe(true))
      await waitFor(() => expect(screen.getByLabelText('Gemini API key')).toBeInTheDocument())
    })

    it('never renders any key value, configured or not', async () => {
      mockProviders()
      mockKeys([
        { name: 'ANTHROPIC_API_KEY', configured: true, source: 'env' },
        { name: 'GEMINI_API_KEY', configured: true, source: 'keychain' },
        { name: 'GITHUB_TOKEN', configured: false, source: null },
      ])
      const { container } = renderApp(<ProviderForm />)

      await screen.findByText(/configured via environment/i)
      // No secret value ever appears — the server never sends one, and inputs stay write-only.
      const passwordInputs = container.querySelectorAll('input[type="password"]')
      passwordInputs.forEach((el) => expect(el).toHaveValue(''))
    })
  })
})
