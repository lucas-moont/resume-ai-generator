import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import App from './App'
import { server } from './test/setup'
import { renderApp } from './test/render'
import { sseResponse } from './test/msw/sse'
import { makeChatTurnEvents, makeResume, makeStageEvents } from './test/factories'
import { STORAGE_KEY, useResumeStore } from './features/resume/store/resumeStore'
import { useChatStore } from './features/chat/store/chatStore'
import { __resetChatBackendAvailability } from './features/chat/hooks/useChatStream'

beforeEach(() => {
  localStorage.clear()
  useResumeStore.setState({ resume: null, template: 'modern', locale: 'auto' })
  useResumeStore.temporal.getState().clear()
  useChatStore.getState().reset()
  __resetChatBackendAvailability()
})

describe('App', () => {
  it('renders the main heading and the core chat controls', () => {
    renderApp(<App />)

    expect(screen.getByRole('heading', { name: /resume agent/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/^message$/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^send$/i })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: /template/i })).toBeInTheDocument()
    // Empty state before anything is generated.
    expect(screen.getByText(/let's build your resume/i)).toBeInTheDocument()
  })

  it('generates a resume via the composer and renders it in the preview', async () => {
    const resume = makeResume({ fullName: 'Grace Hopper' })
    server.use(
      http.post('/api/chat/sessions/1/messages/stream', () => sseResponse(makeChatTurnEvents(resume))),
    )

    const user = userEvent.setup()
    renderApp(<App />)

    await user.type(
      screen.getByLabelText(/^message$/i),
      'Senior Software Engineer, distributed systems team.',
    )
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    await waitFor(() => {
      expect(screen.getByText('Grace Hopper')).toBeInTheDocument()
    })
    // The chat records both the user's message and the assistant's reply.
    expect(screen.getByText('Senior Software Engineer, distributed systems team.')).toBeInTheDocument()
    expect(screen.getByText(/resume updated/i)).toBeInTheDocument()
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
    expect(screen.getByRole('combobox', { name: /template/i })).toHaveValue('classic')
  })

  it('offers all 6 templates and switches instantly, with no network request', async () => {
    const resume = makeResume({ fullName: 'Ada Lovelace' })
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ state: { resume, template: 'modern', locale: 'auto' }, version: 1 }),
    )
    await useResumeStore.persist.rehydrate()

    const user = userEvent.setup()
    renderApp(<App />)
    await waitFor(() => expect(screen.getByText('Ada Lovelace')).toBeInTheDocument())

    const picker = screen.getByRole('combobox', { name: /template/i })
    expect(within(picker).getAllByRole('option')).toHaveLength(6)

    // onUnhandledRequest: 'error' (src/test/setup.ts) means this would throw
    // if switching templates ever triggered a request.
    await user.selectOptions(picker, 'ats-plain')

    expect(picker).toHaveValue('ats-plain')
  })

  it('recognizes a template-switch command typed in the composer, without calling the LLM', async () => {
    const resume = makeResume({ fullName: 'Katherine Johnson' })
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ state: { resume, template: 'modern', locale: 'auto' }, version: 1 }),
    )
    await useResumeStore.persist.rehydrate()

    const user = userEvent.setup()
    renderApp(<App />)
    await waitFor(() => expect(screen.getByText('Katherine Johnson')).toBeInTheDocument())

    await user.type(screen.getByLabelText(/^message$/i), 'use the classic template')
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: /template/i })).toHaveValue('classic')
    })
    expect(screen.getByText(/switched to the classic template/i)).toBeInTheDocument()
  })

  it('graceful degradation: when the sessions list 404s, the sidebar hides but generating still works via the legacy endpoints', async () => {
    server.use(http.get('/api/chat/sessions', () => HttpResponse.json({ detail: 'not found' }, { status: 404 })))
    server.use(http.post('/api/chat/sessions', () => HttpResponse.json({ detail: 'not found' }, { status: 404 })))
    const resume = makeResume({ fullName: 'Legacy Fallback Person' })
    server.use(http.post('/api/generate/stream', () => sseResponse(makeStageEvents(resume))))

    const user = userEvent.setup()
    renderApp(<App />)

    await waitFor(() => {
      expect(screen.queryByRole('navigation', { name: /chat sessions/i })).not.toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/^message$/i), 'Senior backend engineer job posting')
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    await waitFor(() => {
      expect(screen.getByText('Legacy Fallback Person')).toBeInTheDocument()
    })
  })

  it('a plain conversational message with no JD/resume gets a reply without touching the preview (question intent)', async () => {
    server.use(
      http.post('/api/chat/sessions/1/messages/stream', () =>
        sseResponse([
          { event: 'message', data: { content: 'Paste a job description to generate a tailored resume.' } },
          { event: 'done', data: { progress: 100, messageId: 1, resumeVersionId: null } },
        ]),
      ),
    )

    const user = userEvent.setup()
    renderApp(<App />)

    await user.type(screen.getByLabelText(/^message$/i), 'hey there')
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    await waitFor(() => {
      expect(screen.getByText('Paste a job description to generate a tailored resume.')).toBeInTheDocument()
    })
    expect(useResumeStore.getState().resume).toBeNull()
    expect(screen.getByText(/generate a resume to see the a4 preview here/i)).toBeInTheDocument()
  })
})
