import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { GithubUsernameRow } from './GithubUsernameRow'
import { server } from '../../../test/setup'
import { renderApp } from '../../../test/render'
import { DEFAULT_PROFILE } from '../../../test/msw/handlers'

describe('GithubUsernameRow', () => {
  it('shows the current value from GET /api/profile and no Remove button when unset', async () => {
    renderApp(<GithubUsernameRow />)

    expect(await screen.findByLabelText('Username')).toHaveValue('')
    expect(screen.queryByRole('button', { name: /remove github username/i })).not.toBeInTheDocument()
  })

  it('pre-fills the input and shows Remove when a username is already configured', async () => {
    server.use(
      http.get('/api/profile', () => HttpResponse.json({ ...DEFAULT_PROFILE, githubUsername: 'octocat' })),
    )
    renderApp(<GithubUsernameRow />)

    expect(await screen.findByLabelText('Username')).toHaveValue('octocat')
    expect(screen.getByRole('button', { name: /remove github username/i })).toBeInTheDocument()
  })

  it('saves a new username via PUT and reflects it after the refetch', async () => {
    let putBody: unknown
    let stored: string | null = null
    server.use(
      http.get('/api/profile', () => HttpResponse.json({ ...DEFAULT_PROFILE, githubUsername: stored })),
      http.put('/api/profile/github-username', async ({ request }) => {
        putBody = await request.json()
        stored = (putBody as { githubUsername: string | null }).githubUsername
        return HttpResponse.json({ profileVersion: 2, githubUsername: stored })
      }),
    )
    const user = userEvent.setup()
    renderApp(<GithubUsernameRow />)

    const input = await screen.findByLabelText('Username')
    await user.type(input, 'octocat')
    await user.click(screen.getByRole('button', { name: /save github username/i }))

    await waitFor(() => expect(putBody).toEqual({ githubUsername: 'octocat' }))
    await waitFor(() => expect(screen.getByRole('button', { name: /remove github username/i })).toBeInTheDocument())
    expect(screen.getByLabelText('Username')).toHaveValue('octocat')
  })

  it('clears the username via the Remove button, sending null', async () => {
    let putBody: unknown
    let stored: string | null = 'octocat'
    server.use(
      http.get('/api/profile', () => HttpResponse.json({ ...DEFAULT_PROFILE, githubUsername: stored })),
      http.put('/api/profile/github-username', async ({ request }) => {
        putBody = await request.json()
        stored = (putBody as { githubUsername: string | null }).githubUsername
        return HttpResponse.json({ profileVersion: 3, githubUsername: stored })
      }),
    )
    const user = userEvent.setup()
    renderApp(<GithubUsernameRow />)

    await screen.findByDisplayValue('octocat')
    await user.click(screen.getByRole('button', { name: /remove github username/i }))

    await waitFor(() => expect(putBody).toEqual({ githubUsername: null }))
    await waitFor(() => expect(screen.getByLabelText('Username')).toHaveValue(''))
    expect(screen.queryByRole('button', { name: /remove github username/i })).not.toBeInTheDocument()
  })

  it('shows an error alert when saving fails', async () => {
    server.use(http.put('/api/profile/github-username', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })))
    const user = userEvent.setup()
    renderApp(<GithubUsernameRow />)

    const input = await screen.findByLabelText('Username')
    await user.type(input, 'octocat')
    await user.click(screen.getByRole('button', { name: /save github username/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn't save/i)
  })
})
