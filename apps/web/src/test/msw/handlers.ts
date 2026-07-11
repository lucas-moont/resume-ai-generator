import { http, HttpResponse } from 'msw'

export const DEFAULT_MODEL_SUGGESTIONS = [
  { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
  { value: 'gemini-2.5-flash-lite', label: 'Gemini 2.5 Flash-Lite' },
]

export const DEFAULT_GITHUB_REPOS = [
  { name: 'resume-agent', url: 'https://github.com/example/resume-agent' },
]

// v3 ticket 06: mirrors the unconfigured/first-use-without-.env defaults GET
// /api/settings/providers reports (app/services/settings_service.py) — active
// 'auto', nothing available, static per-provider model suggestions.
export const DEFAULT_PROVIDERS_SETTINGS = {
  active: 'auto',
  providers: [
    {
      name: 'claude',
      available: false,
      auth: 'cli',
      defaultModel: 'claude-sonnet-5',
      models: [
        { value: 'claude-opus-4-8', label: 'Claude Opus 4.8' },
        { value: 'claude-sonnet-5', label: 'Claude Sonnet 5' },
        { value: 'claude-haiku-4-5', label: 'Claude Haiku 4.5' },
      ],
    },
    {
      name: 'gemini',
      available: false,
      auth: 'none',
      defaultModel: 'gemini-2.5-flash',
      models: [
        { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
        { value: 'gemini-2.5-flash-lite', label: 'Gemini 2.5 Flash-Lite' },
      ],
    },
    { name: 'ollama', available: false, auth: 'local', defaultModel: 'llama3.2', models: [] },
  ],
}

// v3 ticket 06: mirrors GET /api/settings/keys' unconfigured default — none of
// the three managed keys set via env or keychain.
export const DEFAULT_KEYS_SETTINGS = {
  keys: [
    { name: 'ANTHROPIC_API_KEY', configured: false, source: null }, // pragma: allowlist secret
    { name: 'GEMINI_API_KEY', configured: false, source: null }, // pragma: allowlist secret
    { name: 'GITHUB_TOKEN', configured: false, source: null }, // pragma: allowlist secret
  ],
}

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

  // Living Profile uploads (v2, F7): a happy-path proposed merge by default.
  // Tests override per scenario (invalid/oversize/failed extraction, a
  // specific documentId) with server.use(...). Handlers here never call
  // request.formData()/.arrayBuffer() on the multipart body — jsdom's File
  // doesn't survive @mswjs/interceptors' Node-side re-serialization in this
  // test environment (see client.test.ts's requestMultipart tests).
  http.post('/api/profile/documents', () =>
    HttpResponse.json(
      {
        documentId: 1,
        status: 'proposed',
        proposedPatch: [
          {
            op: 'add',
            path: '/skills/-',
            value: 'Rust',
            reason: 'New skill found in the uploaded document.',
            confidence: 0.92,
            sourceExcerpt: 'Proficient in Rust and systems programming.',
          },
        ],
        diffSummary: ['1 new skill: Rust'],
        extractedPreview: { skills: ['Rust'] },
      },
      { status: 202 },
    ),
  ),

  http.post('/api/profile/documents/:id/apply', () =>
    HttpResponse.json({ profileVersion: 2, applied: 1, skipped: 0 }),
  ),

  http.post('/api/profile/documents/:id/reject', () => new HttpResponse(null, { status: 204 })),

  // Settings (v3 ticket 06): unconfigured/first-use defaults. Tests override
  // per scenario (a key configured, a different active provider, a PUT/DELETE
  // capture) with server.use(...).
  http.get('/api/settings/providers', () => HttpResponse.json(DEFAULT_PROVIDERS_SETTINGS)),
  http.get('/api/settings/keys', () => HttpResponse.json(DEFAULT_KEYS_SETTINGS)),
]
