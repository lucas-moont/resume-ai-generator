import { http, HttpResponse } from 'msw'

export const DEFAULT_MODEL_SUGGESTIONS = [
  { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
  { value: 'gemini-2.5-flash-lite', label: 'Gemini 2.5 Flash-Lite' },
]

export const DEFAULT_GITHUB_REPOS = [
  { name: 'resume-agent', url: 'https://github.com/example/resume-agent' },
]

/**
 * Baseline handlers registered for every test via src/test/setup.ts.
 * Individual tests override endpoints (e.g. the SSE streams) with
 * `server.use(...)` rather than editing this file.
 */
export const handlers = [
  http.get('/api/models', () =>
    HttpResponse.json({
      default: DEFAULT_MODEL_SUGGESTIONS[0].value,
      models: DEFAULT_MODEL_SUGGESTIONS,
    }),
  ),

  http.get('/api/github/repos', () => HttpResponse.json({ repos: DEFAULT_GITHUB_REPOS })),

  http.post('/api/export/pdf', () =>
    // A `Blob` body here gets serialized as the literal string "[object Blob]"
    // by MSW's node interceptor — pass the raw bytes as a string instead.
    new HttpResponse('%PDF-1.4 fake pdf content', {
      status: 200,
      headers: { 'Content-Type': 'application/pdf' },
    }),
  ),

  // Chat (F5): default = an empty session list, and creation always mints
  // session id 1. Individual tests override the message-stream endpoint
  // (`/api/chat/sessions/1/messages/stream`) with `server.use(...)`.
  http.get('/api/chat/sessions', () => HttpResponse.json({ sessions: [] })),

  http.post('/api/chat/sessions', () =>
    HttpResponse.json({ id: 1, title: 'New chat', createdAt: '2026-07-10T00:00:00Z' }, { status: 201 }),
  ),
]
