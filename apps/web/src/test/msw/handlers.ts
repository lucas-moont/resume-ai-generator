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
    new HttpResponse(new Blob(['%PDF-1.4 fake pdf content'], { type: 'application/pdf' }), {
      status: 200,
      headers: { 'Content-Type': 'application/pdf' },
    }),
  ),
]
