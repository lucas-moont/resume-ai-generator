import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../../test/setup'
import { sseResponse } from '../../test/msw/sse'
import { makeResume, makeStageEvents } from '../../test/factories'
import {
  ApiError,
  exportPdf,
  fetchGithubRepos,
  fetchModels,
  generateStream,
  refineStream,
} from './endpoints'

describe('fetchModels', () => {
  it('resolves the parsed models response (default handler from src/test/msw/handlers.ts)', async () => {
    const data = await fetchModels()

    expect(data.default).toBe('gemini-2.5-flash')
    expect(data.models?.[0]).toEqual({ value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' })
  })
})

describe('fetchGithubRepos', () => {
  it('resolves the parsed repos response (default handler)', async () => {
    await expect(fetchGithubRepos()).resolves.toMatchObject({
      repos: [{ name: 'resume-agent' }],
    })
  })

  it('rejects with an ApiError carrying the raw detail on failure', async () => {
    server.use(
      http.get('/api/github/repos', () =>
        HttpResponse.json({ detail: 'no token configured' }, { status: 401 }),
      ),
    )

    let caught: unknown
    try {
      await fetchGithubRepos()
    } catch (e) {
      caught = e
    }
    expect(caught).toBeInstanceOf(ApiError)
    expect((caught as ApiError).detail).toBe('no token configured')
  })
})

describe('exportPdf', () => {
  it('resolves a Blob on success (default handler returns a fake PDF)', async () => {
    const blob = await exportPdf({ resume: makeResume(), template: 'modern' })
    expect(await blob.text()).toContain('%PDF-1.4')
  })

  it('rejects with an ApiError carrying the raw detail on failure', async () => {
    server.use(
      http.post('/api/export/pdf', () =>
        HttpResponse.json({ detail: 'render failed' }, { status: 500 }),
      ),
    )

    let caught: unknown
    try {
      await exportPdf({ resume: makeResume(), template: 'modern' })
    } catch (e) {
      caught = e
    }
    expect(caught).toBeInstanceOf(ApiError)
    expect((caught as ApiError).detail).toBe('render failed')
  })
})

describe('generateStream', () => {
  it('yields the stage/done events from the mocked SSE response', async () => {
    const resume = makeResume({ fullName: 'Ada Lovelace' })
    server.use(
      http.post('/api/generate/stream', () => sseResponse(makeStageEvents(resume))),
    )

    const generator = await generateStream({ job_description: 'Backend engineer' })
    const events = []
    for await (const evt of generator) events.push(evt)

    expect(events[0]).toMatchObject({ event: 'stage', data: { step: 'preparing_context' } })
    expect(events.at(-1)).toMatchObject({ event: 'done', data: { resume } })
  })

  it('rejects with an ApiError when the stream endpoint responds with an error', async () => {
    server.use(
      http.post('/api/generate/stream', () =>
        HttpResponse.json({ detail: 'model unavailable' }, { status: 502 }),
      ),
    )

    let caught: unknown
    try {
      await generateStream({ job_description: 'Backend engineer' })
    } catch (e) {
      caught = e
    }
    expect(caught).toBeInstanceOf(ApiError)
    expect((caught as ApiError).detail).toBe('model unavailable')
  })
})

describe('refineStream', () => {
  it('yields the stage/done events from the mocked SSE response', async () => {
    const resume = makeResume({ fullName: 'Grace Hopper' })
    server.use(http.post('/api/refine/stream', () => sseResponse(makeStageEvents(resume))))

    const generator = await refineStream({ resume: makeResume(), message: 'Fix dates' })
    const events = []
    for await (const evt of generator) events.push(evt)

    expect(events.at(-1)).toMatchObject({ event: 'done', data: { resume } })
  })
})
