import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import App from './App'
import { server } from './test/setup'
import { renderApp } from './test/render'
import { sseResponse } from './test/msw/sse'
import { makeResume, makeStageEvents } from './test/factories'
import { STORAGE_KEY, useResumeStore } from './features/resume/store/resumeStore'

beforeEach(() => {
  localStorage.clear()
  useResumeStore.setState({ resume: null, template: 'modern', locale: 'auto' })
  useResumeStore.temporal.getState().clear()
})

describe('App', () => {
  it('renders the main heading and the core generation controls', () => {
    renderApp(<App />)

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
    renderApp(<App />)

    await user.type(
      screen.getByLabelText(/job description/i),
      'Senior Software Engineer, distributed systems team.',
    )
    await user.click(screen.getByRole('button', { name: /generate resume/i }))

    await waitFor(() => {
      expect(screen.getByText('Grace Hopper')).toBeInTheDocument()
    })
  })

  it('restores a previously generated resume from localStorage after a reload', async () => {
    const resume = makeResume({ fullName: 'Marie Curie' })
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ state: { resume, template: 'classic', locale: 'en' }, version: 1 }),
    )
    await useResumeStore.persist.rehydrate()

    renderApp(<App />)

    await waitFor(() => {
      expect(screen.getByText('Marie Curie')).toBeInTheDocument()
    })
    expect(screen.getByText(/preview — classic/i)).toBeInTheDocument()
  })
})
