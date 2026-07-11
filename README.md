# Resume agent (local)

**Chat-based resume tailoring**: paste a job description into a conversation and watch an ATS-friendly resume come to life in the A4 preview beside it — then refine it by talking ("make the summary shorter", "translate to English"), **edit any field inline right on the preview** (with undo/redo), switch layouts instantly, and download a pixel-faithful PDF. Conversations are **persisted sessions** (local SQLite): close the app, come back, resume where you left off.

Your professional data is a **Living Profile**: drop a `.json`, `.md` or `.pdf` into the chat and an incremental merge pipeline (deterministic diff → LLM adjudicates only what's new or divergent → deterministic validator) proposes a reviewable patch — approve or reject it from the conversation. Every change is versioned with provenance (which upload or chat message caused it), history is append-only, and any version can be reverted. Quick fact changes work straight from chat: "I changed my phone number to X".

Powered by a **pluggable LLM backend**: **Anthropic Claude** (Opus / Sonnet / Haiku, authenticated by the Claude login already on your machine or an API key), **Ollama** (local HTTP API) and/or **Google Gemini**, selected via `.env` (`AI_PROVIDER` and related keys). Stack: **React + Vite** frontend (Zustand + TanStack Query), **FastAPI** backend (layered: `domain/` → `services/` → `routers/`), SQLite persistence, project sources as Markdown files under `data/projects/`.

## Features

- **Chat UI** (left) + always-visible **live A4 preview** (right): message bubbles, step-by-step progress card while the model runs, retry on errors, Stop button, mobile tabs.
- **Persisted chat sessions** (SQLite in `data/app.db`, created automatically): session sidebar to resume/delete conversations; the active session, resume, template and theme all survive a page reload.
- **Template picker** — **6 ATS-friendly designs** applied to both the live preview and the exported PDF: **Modern** (indigo sidebar), **Classic** (serif, single column), **Minimal** (airy, monochrome), **Compact** (dense), **ATS Plain** (single column, system fonts — maximum parser compatibility) and **Two-Column ATS** (visual grid, linear DOM order preserved). One semantic structure; switching is instant CSS — never a regeneration. The CSS is a **single shared source** (`packages/resume-templates/resume.css`) consumed by both the web preview and the PDF renderer.
- **Instant chat commands**: "switch to the classic layout" / "troca pro layout classic" and "export the pdf" are resolved locally — zero LLM/network round-trip.
- **Deterministic intent routing** in the chat backend: a job-description-looking message generates; a follow-up on an active resume refines (with recent conversation as context); small talk gets a canned localized reply without spending an LLM call.
- **Streaming** everywhere (SSE with heartbeat): generation and refinement show live progress.
- Download PDF without the browser print dialog (server-side Playwright, same CSS as the preview).
- Merge **GitHub public repos** (optional token) with **local project `.md` files** (including private work).
- Generation system prompt includes a **tailored-resume** skill block (job analysis, honest keyword mapping, ATS-oriented structure) composed with `generate.md` — see `apps/api/prompts/skills/tailored-resume-generator.md`.
- **Living Profile (v2)**: upload `.json`/`.md`/`.pdf` via drag & drop in the composer (progress, sha256 dedup, actionable errors for scanned PDFs); **incremental merge** that never rewrites what didn't change and never lets an upload delete data ("upload never removes"); approve/reject cards that survive page reloads; profile version history + revert (`GET /api/profile/versions`, `POST /api/profile/revert`); chat intent `profile_update` ("mudei meu telefone…") applies validated patches with provenance and offers — never forces — a resume regeneration.
- **Inline editing (v2)**: pencil toggle on the preview toolbar; edit any field via contenteditable (commit on blur/Enter, no caret jumps, same sanitization allowlist as rendering), add/remove list items, undo/redo via buttons or Ctrl-Z/Ctrl-Shift-Z (including undoing a bad refine that arrived over SSE); chat refines start from **exactly what you see**, edits included; non-blocking zod validation.
- **Light / dark theme** (persisted in `localStorage`).
- **Test suite + CI**: 359 pytest (unit + integration, LLM always faked; 3 e2e render a real PDF) · 375 Vitest/Testing-Library/MSW · 17 Playwright e2e tests (mocked by default, `@real` variants opt-in) · GitHub Actions workflows for web and api.

## Prerequisites

- **Node.js** 18+ and **npm**
- **Python** 3.11+
- **Ollama** installed and a model pulled (e.g. `ollama pull llama3.2`) when you use **`AI_PROVIDER=ollama`** or **`AI_PROVIDER=auto`** without `GEMINI_API_KEY` (see `.env.example`)
- After Python deps: **Playwright browsers** — `playwright install chromium` (see setup below)

## Personal data (not in this repository)

These files are **gitignored** and must be created on each machine:

| File / path | Purpose |
|-------------|---------|
| **`data/profile/resume.json`** | **Canonical profile (JSON)** for the agent. This is the single source of truth the API loads first. Copy from `data/examples/profile/resume.example.json`. |
| `data/profile/Profile.json` | Alternative filename (same schema) if you prefer that casing. |
| `data/profile/Profile.pdf` (optional) | **Plain text is extracted** ([pypdf](https://pypdf.readthedocs.io/)) and sent to the LLM together with your JSON; structured facts stay anchored in `resume.json`. Alternatives: `profile.pdf`, `resume.pdf`, or `PROFILE_PDF_PATH`. |
| `data/profile_master.json` | **Legacy** path — still supported if `resume.json` does not exist. |
| `data/projects/*.md` | One Markdown file per project (YAML frontmatter + narrative body). Copy samples from `data/examples/projects/` if helpful. |
| `data/app.db` (auto-created) | **Local SQLite database** for chat sessions, messages, resume versions, profile versions, source documents and the seeded profile. Created on first API boot (WAL mode); gitignored. Override the location/URL with `DATABASE_URL`. Delete it to start fresh — the profile re-seeds from `data/profile/` on next boot. |
| `data/uploads/` (auto-created) | **Uploaded source documents** (v2 Living Profile), stored as `<sha256>.<ext>`; gitignored — personal data never leaves your machine. |
| `.env` | Optional `GITHUB_TOKEN`; **`AI_PROVIDER`** (`auto` \| `claude` \| `gemini` \| `ollama`); **`AI_DEFAULT_MODEL`** (optional global model override for the active provider); `ANTHROPIC_API_KEY` / `CLAUDE_MODEL`; `OLLAMA_BASE_URL` / `OLLAMA_MODEL`; `GEMINI_API_KEY` / `GEMINI_MODEL`; `PROFILE_JSON_PATH`; `DATABASE_URL`, etc. Copy from `.env.example`. |

**LLM routing (summary):**

| `AI_PROVIDER` | Behavior |
|---------------|----------|
| `auto` | Claude if `ANTHROPIC_API_KEY` is set; else Gemini if `GEMINI_API_KEY` is set; otherwise Ollama. A local `ant auth login` sets no key, so use `claude` explicitly to select it that way. |
| `claude` | Always Claude. Auth resolves from `ant auth login` (the Claude session on your machine) or `ANTHROPIC_API_KEY`. Model from `CLAUDE_MODEL` (default `claude-sonnet-5`). |
| `gemini` | Always Gemini (requires `GEMINI_API_KEY`). |
| `ollama` | Always Ollama (uses `OLLAMA_MODEL` / `OLLAMA_BASE_URL`). |

**Claude "linked on your machine":** run `ant auth login` once (ships with the Claude / `ant` CLI) and the app uses that local session automatically — no key in the repo. Set `AI_PROVIDER=claude`, or simply pick **Claude Opus 4.8** / **Claude Sonnet 5** in the UI model selector: a `claude-*` (or `gemini-*`) model chosen in the UI routes to that backend regardless of `AI_PROVIDER`. Prefer not to keep a static key in `.env`? Store it in the **OS keychain** instead (see [Security](#security)).

Optional **`AI_DEFAULT_MODEL`** applies when the UI does not send a `model` field (empty override). Per-request `model` in the API body still wins when provided.

**Generation tuning (optional):** `LLM_TEMPERATURE` (default `0.4`, applies to Gemini/Ollama only — Claude Sonnet 5 / Opus reject sampling params, so it is not sent to Claude). Claude: `CLAUDE_MAX_OUTPUT_TOKENS` (default `8192`) and `CLAUDE_THINKING` (`off` default, or `adaptive`). Gemini: `GEMINI_MAX_OUTPUT_TOKENS` (default `8192`, avoids truncated/invalid JSON on longer resumes). Ollama: `OLLAMA_NUM_CTX` (default `8192`) and `OLLAMA_NUM_PREDICT` (default `4096`) — the stock context window on many local models is small enough to silently truncate the profile + PDF + projects prompt and lower quality, so this raises it. See `.env.example`.

**Resolution order:** `PROFILE_JSON_PATH` (if set) → `data/profile/resume.json` → `data/profile/Profile.json` → `data/profile_master.json`. After you use `resume.json`, you can delete the legacy `profile_master.json` to avoid two sources.

**Do not commit** real phone numbers, employer details, or tokens.

## Setup

### 1) Profile and projects

```bash
mkdir -p data/profile
# Windows: New-Item -ItemType Directory -Force data/profile
cp data/examples/profile/resume.example.json data/profile/resume.json
# Edit data/profile/resume.json (source of truth for the LLM).
# Optional: data/profile/Profile.pdf — text is extracted for the LLM (JSON remains canonical).
# Add data/projects/my-project.md (see data/examples/projects/).
```

### 2) Backend

```bash
cd apps/api
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
playwright install chromium
```

### 3) Optional env

```bash
cd ../..
copy .env.example .env          # Windows: edit .env
# cp .env.example .env && edit # Unix
```

### 4) Frontend

```bash
cd apps/web
npm install
```

## Run (two terminals)

**Terminal A — API**

```bash
cd apps/api
.venv\Scripts\activate
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**Terminal B — UI**

```bash
cd apps/web
npm run dev
```

Open `http://localhost:5173`. The UI proxies `/api/*` to the FastAPI server on port **8000** (override the proxy target with the `VITE_API_PROXY_TARGET` env var when the API runs elsewhere).

If the resolved backend is **Ollama** (`AI_PROVIDER=ollama`, or `auto` without `GEMINI_API_KEY`), ensure **Ollama** is running (`ollama serve` if needed).

## Project Markdown format

Each `data/projects/<slug>.md`:

```yaml
---
name: Display name
github_repo: owner/repo   # optional, for merge with GitHub
technologies: [React, Python]
visibility: private       # public | private | internal
highlight: true # optional hint for the LLM
url: https://...
---

Free-form markdown: problem, your role, stack, outcomes.
```

## API overview

**Chat (the primary flow used by the UI):**

- `POST /api/chat/sessions` — body: `{ "title?" }` → `201 { id, title, createdAt }`
- `GET /api/chat/sessions` — list sessions (most recently updated first)
- `GET /api/chat/sessions/{id}` — session detail: `{ session, messages, activeResume }`
- `DELETE /api/chat/sessions/{id}` — delete a session (messages cascade; resume versions are kept)
- `POST /api/chat/sessions/{id}/messages/stream` — body: `{ "message", "model?", "locale?", "jobDescription?", "resume?" }` → **SSE** stream with `stage` (progress), `resume` (`{ resume, resumeVersionId }` when the turn changes the resume), `profile_update` (`{ profileVersion, summary }` when the turn changes the Living Profile), `message` (assistant text for the chat bubble), `done` and `error` events. Intent (generate / refine / profile_update / plain reply) is decided deterministically server-side. The optional `resume` field lets the client supply the document as currently displayed (inline edits included) as the base for a refine.

**Living Profile (v2):**

- `POST /api/profile/documents` — multipart (`file`, optional `model` and `sessionId`) → synchronous `202 { documentId, status, proposedPatch?, diffSummary?, extractedPreview?, error? }`. Successful extractions always end `proposed` (empty proposal = "nothing new"); scanned PDFs with no text end `failed` with an actionable message. Re-uploading the same bytes (sha256) reuses the existing document. With `sessionId`, the proposal card is persisted into that chat session and survives reloads.
- `GET /api/profile/documents` — list uploads (newest first, live status)
- `POST /api/profile/documents/{id}/apply` — body `{ ops?: [indices] }` (subset or all) → `{ profileVersion, applied, skipped }`; `POST /api/profile/documents/{id}/reject` → 204. Non-`proposed` documents → 409.
- `GET /api/profile/versions` · `GET /api/profile/versions/{n}` — append-only version history with provenance (`sourceKind`: seed_disk | upload | chat | manual | revert)
- `PATCH /api/profile` — body `{ ops: [PatchOp] }` (direct manual edits, same deterministic validator)
- `POST /api/profile/revert` — body `{ "toVersion": n }` → creates a new version copying an older one (history is never rewritten)

**Legacy/direct endpoints (still supported — the UI falls back to them if the chat API is absent):**

- `GET /api/health` — health check
- `GET /api/models` — model suggestions for the UI picker (`{ default, models: [{value,label}] }`)
- `GET /api/profile` — loads the resolved profile JSON (same resolution order as [Personal data](#personal-data-not-in-this-repository); validates schema)
- `GET /api/github/repos` — lists repos for `githubUsername` in profile
- `POST /api/generate` — body: `{ "job_description", "model?", "locale?" }` → tailored `ResumeDocument`. `locale` accepts `"auto"` (default: detects the job description's language, pt-BR vs en), or `"pt-BR"`/`"en"` to force the output language.
- `POST /api/generate/stream` — same body as generate; **SSE** stream with `stage` events (progress, message) and a final `done` event with the resume JSON
- `POST /api/refine` — body: `{ "resume", "message", "model?" }`
- `POST /api/refine/stream` — same as refine over **SSE**
- `POST /api/export/pdf` — body: `{ "resume": { ... }, "template?": "modern" | "classic" | "minimal" | "compact" | "ats-plain" | "two-column-ats" }` → PDF download (defaults to `modern`)

## Prompts

- **System:** `apps/api/prompts/system/` — `generate.md`, `refine.md`, `extract_profile.md` (JSON-only resume output rules and PDF-profile extraction).
- **Skills:** `apps/api/prompts/skills/` — extra behavior merged into generation (e.g. `tailored-resume-generator.md`). The API loads `generate.md` plus that skill via `load_generate_system_prompt()` in `app/prompt_loader.py`. Edit these files to change LLM behavior without touching the UI.

## Tests

**Backend** (from `apps/api`, venv active): `python -m pytest` — 359 tests. Fast unit + integration suites use a fake LLM and an in-memory SQLite (never a real network call); the 3 tests marked `e2e` render a real PDF via Playwright (`-m "not e2e"` to skip them).

**Web** (from `apps/web`): `npm run test:run` (375 Vitest + Testing Library + MSW tests, including SSE stream mocks) · `npm run test:e2e` (17 Playwright tests against a mocked API — deterministic, CI-safe) · `npm run test:e2e:real` (opt-in variants against a live uvicorn on port 8000; see `e2e/README.md`).

**CI:** `.github/workflows/web.yml` and `api.yml` run lint/build/tests on every push touching each app.

## Security

Built to run **locally**, keeping credentials out of the repo and off disk in the clear.

- **Local only.** The API binds to `127.0.0.1:8000` and CORS is restricted to the Vite dev origin. Don't bind `0.0.0.0` or expose it publicly without adding authentication first.
- **Secrets never committed.** `.env` is gitignored, and a **pre-commit secret scanner** (below) blocks accidental key/token commits.
- **Claude auth — most secure first:** `ant auth login` (local OAuth session: short-lived, revocable, nothing stored in the repo) › **OS keychain** › `.env`.
- **Keys can live in the OS keychain** instead of `.env` (Windows Credential Locker / macOS Keychain / Linux SecretService). Per secret, resolution is **env var → keychain → unset** (`app/services/secret_store.py`).
- **Least privilege:** use a workspace-scoped Anthropic key and a **read-only** `GITHUB_TOKEN` (`public_repo`, or a fine-grained PAT with only `Contents: Read`).
- **Error redaction:** any configured secret value is stripped (`«redacted»`) from LLM error messages before they reach the UI or logs (`app/services/secret_redaction.py`). The Gemini key is sent as a header, never in the request URL.

### Store a key in the OS keychain (optional)

`keyring` is already in `requirements.txt`. Store secrets under the service name `resume-agent`, keyed by the env var name, then leave that variable **unset** in `.env` (an env var, if set, always wins):

```bash
keyring set resume-agent ANTHROPIC_API_KEY   # prompts for the value (hidden input)
keyring set resume-agent GEMINI_API_KEY
keyring set resume-agent GITHUB_TOKEN
```

### Pre-commit secret scanning (recommended)

```bash
pip install -r apps/api/requirements-dev.txt
pre-commit install              # from the repo root — wires the git hook
pre-commit run --all-files      # scan the whole repo on demand
```

Runs **detect-secrets** plus `detect-private-key` and a large-file guard (`.pre-commit-config.yaml`). The allowlist baseline is `.secrets.baseline`; after reviewing genuinely-new findings, regenerate it with `detect-secrets scan > .secrets.baseline`.

## Troubleshooting

**Ollama error on `/api/chat`:** If that endpoint returns any non-success status (404, 405, etc.), the API retries with `/api/generate`. If both fail, set `OLLAMA_BASE_URL` to `http://127.0.0.1:11434` (no `/v1` path), run `ollama serve`, and ensure `ollama list` includes your `OLLAMA_MODEL`.

**HTTP 404 on `/api/generate` with `model '…' not found`:** Ollama uses 404 for a missing local model. Run `ollama pull llama3.2` (or whatever tag you want), or set `OLLAMA_MODEL` in `.env` to an **exact** name from `ollama list`.

**Gemini errors:** Confirm the key from [Google AI Studio](https://aistudio.google.com/apikey), optional `GEMINI_MODEL` (default `gemini-2.5-flash`), and that the [Generative Language API](https://ai.google.dev/gemini-api/docs) is enabled for the project. To use Ollama instead, set **`AI_PROVIDER=ollama`** or use **`AI_PROVIDER=auto`** and remove/unset `GEMINI_API_KEY` (there is no automatic failover from Gemini to Ollama on HTTP errors).

**Claude authentication errors (HTTP 401/403):** With `AI_PROVIDER=claude` (or a `claude-*` model picked in the UI), the SDK needs a credential. Either run `ant auth login` once (uses the Claude session on your machine — no key in the repo), or set `ANTHROPIC_API_KEY` in `.env` from [the console](https://console.anthropic.com/settings/keys). A `403` usually means the authenticated account cannot access the chosen `CLAUDE_MODEL`. If you see "The 'anthropic' package is not installed", re-run `pip install -r apps/api/requirements.txt`.

**Wrong backend selected:** Set `AI_PROVIDER` explicitly (`claude`, `gemini`, or `ollama`) instead of `auto` for a fixed provider regardless of which keys exist in `.env`. Selecting a `claude-*`/`gemini-*` model in the UI overrides `AI_PROVIDER` for that request.

## License

MIT — see [LICENSE](LICENSE) if present; otherwise treat as MIT for the scaffold.
