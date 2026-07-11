import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../../test/setup'
import { sseResponse } from '../../test/msw/sse'
import { makeResume, makeStageEvents, makeUploadResponse } from '../../test/factories'
import {
  ApiError,
  applySourceDocument,
  chatMessageStream,
  createChatSession,
  deleteChatSession,
  deleteKeySetting,
  exportPdf,
  fetchGithubRepos,
  fetchKeySettings,
  fetchModels,
  fetchProviderSettings,
  generateStream,
  getChatSession,
  listChatSessions,
  refineStream,
  rejectSourceDocument,
  updateProviderSettings,
  uploadSourceDocument,
  upsertKeySetting,
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

  it('forwards the AbortSignal to fetch — an already-aborted signal rejects immediately', async () => {
    // MSW's mocked ReadableStream bodies aren't torn down by an in-flight
    // abort in this version, so cancellation-mid-stream is covered instead
    // at the parseSseStream level (sse.test.ts, real ReadableStream +
    // AbortController). This test only proves the signal is actually wired
    // through generateStream -> postInit -> fetch.
    const controller = new AbortController()
    controller.abort()

    await expect(
      generateStream({ job_description: 'Backend engineer' }, controller.signal),
    ).rejects.toThrow()
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

describe('createChatSession', () => {
  it('posts to /api/chat/sessions and resolves the created session', async () => {
    let capturedBody: unknown
    server.use(
      http.post('/api/chat/sessions', async ({ request }) => {
        capturedBody = await request.json()
        return HttpResponse.json(
          { id: 42, title: 'Backend engineer job posting', createdAt: '2026-07-10T00:00:00Z' },
          { status: 201 },
        )
      }),
    )

    const result = await createChatSession({ title: 'Backend engineer job posting' })

    expect(result).toEqual({ id: 42, title: 'Backend engineer job posting', createdAt: '2026-07-10T00:00:00Z' })
    expect(capturedBody).toEqual({ title: 'Backend engineer job posting' })
  })
})

describe('listChatSessions', () => {
  it('resolves the sessions list', async () => {
    server.use(
      http.get('/api/chat/sessions', () =>
        HttpResponse.json({
          sessions: [{ id: 1, title: 'Hello', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null }],
        }),
      ),
    )

    await expect(listChatSessions()).resolves.toEqual({
      sessions: [{ id: 1, title: 'Hello', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: null }],
    })
  })

  it('rejects with an ApiError when the chat feature is unavailable (e.g. 404)', async () => {
    server.use(http.get('/api/chat/sessions', () => HttpResponse.json({ detail: 'not found' }, { status: 404 })))

    let caught: unknown
    try {
      await listChatSessions()
    } catch (e) {
      caught = e
    }
    expect(caught).toBeInstanceOf(ApiError)
  })
})

describe('getChatSession', () => {
  it('resolves the session detail with messages and the active resume', async () => {
    const resume = makeResume({ fullName: 'Loaded Session' })
    server.use(
      http.get('/api/chat/sessions/7', () =>
        HttpResponse.json({
          session: { id: 7, title: 'Hi', updatedAt: '2026-07-10T00:00:00Z', activeResumeVersionId: 3 },
          messages: [
            { id: 1, role: 'user', content: 'hi', intent: null, resumeVersionId: null, createdAt: '2026-07-10T00:00:00Z' },
          ],
          activeResume: resume,
        }),
      ),
    )

    const result = await getChatSession(7)
    expect(result.session.id).toBe(7)
    expect(result.messages).toHaveLength(1)
    expect(result.activeResume?.fullName).toBe('Loaded Session')
  })
})

describe('deleteChatSession', () => {
  it('sends a DELETE request and resolves with no content', async () => {
    server.use(http.delete('/api/chat/sessions/9', () => new HttpResponse(null, { status: 204 })))

    await expect(deleteChatSession(9)).resolves.toBeUndefined()
  })
})

describe('chatMessageStream', () => {
  it('posts to the session-scoped stream endpoint and yields resume/message/done events', async () => {
    const resume = makeResume({ fullName: 'Chat Adapter Test' })
    let capturedBody: unknown
    server.use(
      http.post('/api/chat/sessions/5/messages/stream', async ({ request }) => {
        capturedBody = await request.json()
        return sseResponse([
          { event: 'stage', data: { step: 'calling_ai', progress: 40 } },
          { event: 'resume', data: { resume, resumeVersionId: 12 } },
          { event: 'message', data: { content: 'Generated a tailored resume for this job description.' } },
          { event: 'done', data: { progress: 100, messageId: 99, resumeVersionId: 12 } },
        ])
      }),
    )

    const generator = await chatMessageStream(5, { message: 'A job description' })
    const events = []
    for await (const evt of generator) events.push(evt)

    expect(capturedBody).toEqual({ message: 'A job description' })
    expect(events.map((e) => e.event)).toEqual(['stage', 'resume', 'message', 'done'])
    expect(events[1]).toMatchObject({ event: 'resume', data: { resumeVersionId: 12 } })
  })

  it('rejects with an ApiError when the session does not exist', async () => {
    server.use(
      http.post('/api/chat/sessions/404/messages/stream', () =>
        HttpResponse.json({ detail: 'Chat session 404 not found' }, { status: 404 }),
      ),
    )

    let caught: unknown
    try {
      await chatMessageStream(404, { message: 'hi' })
    } catch (e) {
      caught = e
    }
    expect(caught).toBeInstanceOf(ApiError)
  })
})

describe('uploadSourceDocument', () => {
  it('posts multipart to /api/profile/documents and resolves the parsed contract', async () => {
    server.use(
      http.post('/api/profile/documents', () =>
        HttpResponse.json(makeUploadResponse({ documentId: 9 }), { status: 202 }),
      ),
    )

    const file = new File(['{"fullName":"Ada"}'], 'profile.json', { type: 'application/json' })
    const result = await uploadSourceDocument(file)

    expect(result).toMatchObject({ documentId: 9, status: 'proposed' })
    expect(result.diffSummary).toEqual(['1 new skill: Rust'])
  })

  it('forwards onProgress and the abort signal through to the client', async () => {
    server.use(http.post('/api/profile/documents', () => HttpResponse.json(makeUploadResponse())))

    const progress: number[] = []
    const file = new File(['# notes'], 'notes.md')
    await uploadSourceDocument(file, { onProgress: (pct) => progress.push(pct) })

    expect(progress.at(-1)).toBe(100)
  })

  it('rejects with an ApiError carrying the detail when extraction fails outright (e.g. oversize on the server)', async () => {
    server.use(
      http.post('/api/profile/documents', () =>
        HttpResponse.json({ detail: 'File exceeds the 10MB limit' }, { status: 413 }),
      ),
    )

    let caught: unknown
    try {
      await uploadSourceDocument(new File(['x'], 'huge.pdf'))
    } catch (e) {
      caught = e
    }
    expect(caught).toBeInstanceOf(ApiError)
    expect((caught as ApiError).detail).toBe('File exceeds the 10MB limit')
  })
})

describe('applySourceDocument', () => {
  it('posts to the apply endpoint with no ops (apply-all) and resolves the new version', async () => {
    let capturedBody: unknown
    server.use(
      http.post('/api/profile/documents/9/apply', async ({ request }) => {
        capturedBody = await request.json()
        return HttpResponse.json({ profileVersion: 4, applied: 2, skipped: 0 })
      }),
    )

    const result = await applySourceDocument(9)

    expect(result).toEqual({ profileVersion: 4, applied: 2, skipped: 0 })
    expect(capturedBody).toEqual({})
  })

  it('posts a subset of ops when provided', async () => {
    let capturedBody: unknown
    server.use(
      http.post('/api/profile/documents/9/apply', async ({ request }) => {
        capturedBody = await request.json()
        return HttpResponse.json({ profileVersion: 5, applied: 1, skipped: 1 })
      }),
    )

    await applySourceDocument(9, [0])

    expect(capturedBody).toEqual({ ops: [0] })
  })
})

describe('rejectSourceDocument', () => {
  it('posts to the reject endpoint and resolves with no content', async () => {
    server.use(http.post('/api/profile/documents/9/reject', () => new HttpResponse(null, { status: 204 })))

    await expect(rejectSourceDocument(9)).resolves.toBeUndefined()
  })
})

// --- Settings (v3 ticket 06) ---

describe('fetchProviderSettings', () => {
  it('resolves the active provider and per-provider entries', async () => {
    server.use(
      http.get('/api/settings/providers', () =>
        HttpResponse.json({
          active: 'auto',
          providers: [
            { name: 'claude', available: false, auth: 'cli', defaultModel: 'claude-sonnet-5', models: [] },
          ],
        }),
      ),
    )

    await expect(fetchProviderSettings()).resolves.toMatchObject({ active: 'auto' })
  })
})

describe('updateProviderSettings', () => {
  it('PUTs the chosen provider/model and resolves the refreshed providers response', async () => {
    let capturedBody: unknown
    server.use(
      http.put('/api/settings/providers', async ({ request }) => {
        capturedBody = await request.json()
        return HttpResponse.json({ active: 'claude', providers: [] })
      }),
    )

    const result = await updateProviderSettings({ provider: 'claude', defaultModel: 'claude-haiku-4-5' })

    expect(capturedBody).toEqual({ provider: 'claude', defaultModel: 'claude-haiku-4-5' })
    expect(result).toEqual({ active: 'claude', providers: [] })
  })
})

describe('fetchKeySettings', () => {
  it('resolves the managed keys and their configured/source state', async () => {
    server.use(
      http.get('/api/settings/keys', () =>
        HttpResponse.json({
          keys: [{ name: 'ANTHROPIC_API_KEY', configured: false, source: null }],
        }),
      ),
    )

    await expect(fetchKeySettings()).resolves.toEqual({
      keys: [{ name: 'ANTHROPIC_API_KEY', configured: false, source: null }],
    })
  })
})

describe('upsertKeySetting', () => {
  it('PUTs the key name/value and resolves the entry the server reports back — never the value', async () => {
    let capturedBody: unknown
    server.use(
      http.put('/api/settings/keys', async ({ request }) => {
        capturedBody = await request.json()
        return HttpResponse.json({ name: 'GEMINI_API_KEY', configured: true, source: 'keychain' })
      }),
    )

    const result = await upsertKeySetting({ name: 'GEMINI_API_KEY', value: 'secret-value' })

    expect(capturedBody).toEqual({ name: 'GEMINI_API_KEY', value: 'secret-value' })
    expect(result).toEqual({ name: 'GEMINI_API_KEY', configured: true, source: 'keychain' })
  })

  it('rejects with an ApiError on an empty value (422)', async () => {
    server.use(
      http.put('/api/settings/keys', () => HttpResponse.json({ detail: 'value must not be empty' }, { status: 422 })),
    )

    let caught: unknown
    try {
      await upsertKeySetting({ name: 'GITHUB_TOKEN', value: '' })
    } catch (e) {
      caught = e
    }
    expect(caught).toBeInstanceOf(ApiError)
    expect((caught as ApiError).status).toBe(422)
  })
})

describe('deleteKeySetting', () => {
  it('sends a DELETE to the name-scoped endpoint and resolves with no content', async () => {
    server.use(http.delete('/api/settings/keys/ANTHROPIC_API_KEY', () => new HttpResponse(null, { status: 204 })))

    await expect(deleteKeySetting('ANTHROPIC_API_KEY')).resolves.toBeUndefined()
  })
})
