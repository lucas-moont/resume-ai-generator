import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { KeyRow } from './KeyRow'
import { server } from '../../../test/setup'
import { renderApp } from '../../../test/render'

describe('KeyRow', () => {
  it('a key configured via env is read-only (no input, no remove button)', () => {
    renderApp(<KeyRow entry={{ name: 'ANTHROPIC_API_KEY', configured: true, source: 'env' }} />)

    expect(screen.getByText(/configured via environment/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/anthropic api key/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /remove anthropic/i })).not.toBeInTheDocument()
  })

  describe('save flow', () => {
    it('saving a new key PUTs it and clears the input afterward', async () => {
      let putBody: unknown
      server.use(
        http.put('/api/settings/keys', async ({ request }) => {
          putBody = await request.json()
          return HttpResponse.json({ name: 'GEMINI_API_KEY', configured: true, source: 'keychain' })
        }),
      )
      const user = userEvent.setup()
      renderApp(<KeyRow entry={{ name: 'GEMINI_API_KEY', configured: false, source: null }} />)

      const input = screen.getByLabelText('Gemini API key')
      await user.type(input, 'brand-new-secret-value')
      await user.click(screen.getByRole('button', { name: /save gemini api key/i }))

      await waitFor(() =>
        expect(putBody).toEqual({ name: 'GEMINI_API_KEY', value: 'brand-new-secret-value' }),
      )
      await waitFor(() => expect(input).toHaveValue(''))
      // Secret hygiene: the typed value must never linger anywhere in the rendered DOM.
      expect(screen.queryByText('brand-new-secret-value')).not.toBeInTheDocument()
    })

    it('shows an error alert and KEEPS the typed value when the save fails (422)', async () => {
      server.use(
        http.put('/api/settings/keys', () =>
          HttpResponse.json({ detail: 'value must not be empty' }, { status: 422 }),
        ),
      )
      const user = userEvent.setup()
      renderApp(<KeyRow entry={{ name: 'GEMINI_API_KEY', configured: false, source: null }} />)

      const input = screen.getByLabelText('Gemini API key')
      await user.type(input, 'brand-new-secret-value')
      await user.click(screen.getByRole('button', { name: /save gemini api key/i }))

      expect(await screen.findByRole('alert')).toHaveTextContent(/couldn't save/i)
      // Unlike the success path, a failed save must not silently discard what was typed —
      // clearing it here would look identical to success and hide the failure from the user.
      expect(input).toHaveValue('brand-new-secret-value')
      // The alert itself must never echo the typed secret value.
      expect(screen.getByRole('alert')).not.toHaveTextContent('brand-new-secret-value')
    })

    it('shows an error alert on a server error (500) too', async () => {
      server.use(http.put('/api/settings/keys', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })))
      const user = userEvent.setup()
      renderApp(<KeyRow entry={{ name: 'GITHUB_TOKEN', configured: false, source: null }} />)

      await user.type(screen.getByLabelText('GitHub token'), 'ghp_fake_token_value')
      await user.click(screen.getByRole('button', { name: /save github token/i }))

      expect(await screen.findByRole('alert')).toHaveTextContent(/couldn't save/i)
    })
  })

  describe('remove flow', () => {
    it('removing a keychain-sourced key calls DELETE', async () => {
      let deleteCalled = false
      server.use(
        http.delete('/api/settings/keys/GEMINI_API_KEY', () => {
          deleteCalled = true
          return new HttpResponse(null, { status: 204 })
        }),
      )
      const user = userEvent.setup()
      renderApp(<KeyRow entry={{ name: 'GEMINI_API_KEY', configured: true, source: 'keychain' }} />)

      await user.click(screen.getByRole('button', { name: /remove gemini api key/i }))

      await waitFor(() => expect(deleteCalled).toBe(true))
    })

    it('shows an error alert and keeps the keychain state when removal fails (500)', async () => {
      server.use(
        http.delete('/api/settings/keys/GEMINI_API_KEY', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })),
      )
      const user = userEvent.setup()
      renderApp(<KeyRow entry={{ name: 'GEMINI_API_KEY', configured: true, source: 'keychain' }} />)

      await user.click(screen.getByRole('button', { name: /remove gemini api key/i }))

      expect(await screen.findByRole('alert')).toHaveTextContent(/couldn't remove/i)
      // The row must not look like it silently succeeded — Remove is still there to retry.
      expect(screen.getByRole('button', { name: /remove gemini api key/i })).toBeInTheDocument()
    })
  })

  it('never renders any key value, configured or not', () => {
    const { container } = renderApp(
      <KeyRow entry={{ name: 'GITHUB_TOKEN', configured: false, source: null }} />,
    )

    const passwordInputs = container.querySelectorAll('input[type="password"]')
    passwordInputs.forEach((el) => expect(el).toHaveValue(''))
  })
})
