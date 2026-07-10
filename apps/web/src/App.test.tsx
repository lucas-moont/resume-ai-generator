import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http } from 'msw'
import { describe, expect, it } from 'vitest'
import App from './App'
import { server } from './test/setup'
import { sseResponse } from './test/msw/sse'
import { makeResume, makeStageEvents } from './test/factories'

describe('App', () => {
  it('renders the main heading and the core generation controls', () => {
    render(<App />)

    expect(screen.getByRole('heading', { name: /resume agent/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/job description/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /generate resume/i })).toBeInTheDocument()
    expect(screen.getByRole('radiogroup', { name: /resume template/i })).toBeInTheDocument()
  })

  it('streams stage events from /api/generate/stream and renders the resulting resume in the preview', async () => {
    const resume = makeResume({ fullName: 'Grace Hopper' })
    server.use(
      http.post('/api/generate/stream', () => sseResponse(makeStageEvents(resume))),
    )

    const user = userEvent.setup()
    render(<App />)

    await user.type(
      screen.getByLabelText(/job description/i),
      'Senior Software Engineer, distributed systems team.',
    )
    await user.click(screen.getByRole('button', { name: /generate resume/i }))

    await waitFor(() => {
      expect(screen.getByText('Grace Hopper')).toBeInTheDocument()
    })
  })
})
