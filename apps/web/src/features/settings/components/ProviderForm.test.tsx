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

    it('shows an error alert when the provider switch fails, and does not treat it as applied', async () => {
      mockProviders()
      server.use(http.put('/api/settings/providers', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })))
      const user = userEvent.setup()
      renderApp(<ProviderForm />)

      const autoRadio = await screen.findByRole('radio', { name: /auto/i })
      await user.click(screen.getByRole('radio', { name: /^Claude \(Anthropic\)/ }))

      expect(await screen.findByRole('alert')).toHaveTextContent(/couldn't update/i)
      // Nothing was actually persisted -- the previously-active option is still selected.
      expect(autoRadio).toBeChecked()
    })
  })

  describe('env-lock indicator (v3 ticket 11)', () => {
    it('unlocked baseline: every provider radio and the model picker stay enabled', async () => {
      mockProviders()
      renderApp(<ProviderForm />)

      const autoRadio = await screen.findByRole('radio', { name: /auto/i })
      expect(autoRadio).toBeEnabled()
      expect(screen.getByRole('radio', { name: /^Claude \(Anthropic\)/ })).toBeEnabled()
      expect(screen.queryByText(/pinned by/i)).not.toBeInTheDocument()
    })

    it('disables every provider radio and shows which env var pins the active provider', async () => {
      mockProviders({ activeLockedByEnv: true, activeEnvVar: 'AI_PROVIDER' })
      renderApp(<ProviderForm />)

      const autoRadio = await screen.findByRole('radio', { name: /auto/i })
      expect(autoRadio).toBeDisabled()
      expect(screen.getByRole('radio', { name: /^Claude \(Anthropic\)/ })).toBeDisabled()
      expect(screen.getByText(/AI_PROVIDER/)).toBeInTheDocument()
      expect(screen.getByText(/pinned by/i)).toBeInTheDocument()

      // a11y fix round: a disabled radio drops out of the tab order, so the lock explanation
      // must reach assistive tech another way — the fieldset's accessible description, not just
      // sighted text next to it.
      expect(screen.getByRole('group', { name: /active provider/i })).toHaveAccessibleDescription(
        /AI_PROVIDER/,
      )
    })

    it('replaces the model picker with a read-only value when the active provider default is env-locked', async () => {
      mockProviders({
        active: 'claude',
        providers: DEFAULT_PROVIDERS_SETTINGS.providers.map((p) =>
          p.name === 'claude' ? { ...p, defaultModelLockedByEnv: true, defaultModelEnvVar: 'CLAUDE_MODEL' } : p,
        ),
      })
      renderApp(<ProviderForm />)

      await screen.findByText('Claude (Anthropic)')
      expect(screen.getByText('claude-sonnet-5')).toBeInTheDocument()
      expect(screen.getByText(/CLAUDE_MODEL/)).toBeInTheDocument()
      expect(screen.queryByLabelText('Default model')).not.toBeInTheDocument()
    })
  })

  describe('API keys section', () => {
    it('renders one KeyRow per managed key from the keys query — KeyRow itself owns the save/remove/badge mechanics (see KeyRow.test.tsx)', async () => {
      mockProviders()
      mockKeys([
        { name: 'ANTHROPIC_API_KEY', configured: true, source: 'env' },
        { name: 'GEMINI_API_KEY', configured: true, source: 'keychain' },
        { name: 'GITHUB_TOKEN', configured: false, source: null },
      ])
      renderApp(<ProviderForm />)

      expect(await screen.findByText(/configured via environment/i)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /remove gemini api key/i })).toBeInTheDocument()
      expect(screen.getByLabelText('GitHub token')).toBeInTheDocument()
    })
  })
})
