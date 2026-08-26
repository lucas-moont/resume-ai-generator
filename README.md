# Resume agent (local)

**Chat-based resume tailoring**: paste a job description into a conversation and watch an ATS-friendly resume come to life in the A4 preview beside it — then refine it by talking ("make the summary shorter", "translate to English"), **edit any field inline right on the preview** (with undo/redo), switch layouts instantly, and download a pixel-faithful PDF. Conversations are **persisted sessions** (local SQLite): close the app, come back, resume where you left off. Since v7 you don't even have to bring the posting: the **Job Monitor** scans seven job boards on your schedule, ranks what it finds by how likely your resume is to be read, and turns any listing into a tailored PDF in one click.

Your professional data is a **Living Profile**: drop a `.json`, `.md` or `.pdf` into the chat and an incremental merge pipeline (deterministic diff → LLM adjudicates only what's new or divergent → deterministic validator) proposes a reviewable patch — approve or reject it from the conversation. Every change is versioned with provenance (which upload or chat message caused it), history is append-only, and any version can be reverted. Quick fact changes work straight from chat: "I changed my phone number to X".

Powered by a **pluggable LLM backend**: **Anthropic Claude** (Opus / Sonnet / Haiku, authenticated by the Claude login already on your machine or an API key), **Ollama** (local HTTP API) and/or **Google Gemini** — all configurable **from the UI at runtime** (v3): a Settings dialog switches the active provider and default model with immediate effect (no restart), stores API keys in the **OS keychain** (never in SQLite, never echoed back), and lists each provider's models from a live catalog. `.env` still works and, when set, takes precedence — the UI shows a lock indicator naming the variable instead of silently losing your change. Stack: **React + Vite** frontend (Zustand + TanStack Query), **FastAPI** backend (layered: `domain/` → `services/` → `routers/`), SQLite persistence, project sources as Markdown files under `data/projects/`.

## Features

- **Chat UI** (left) + always-visible **live A4 preview** (right): message bubbles, step-by-step progress card while the model runs, retry on errors, Stop button, mobile tabs.
- **Persisted chat sessions** (SQLite in `data/app.db`, created automatically): session sidebar to resume/delete conversations; the active session, resume, template and theme all survive a page reload.
- **Template picker** — **9 ATS-friendly designs** with visual thumbnails, applied to both the live preview and the exported PDF: **Modern** (indigo sidebar), **Classic** (serif, single column), **Minimal** (airy, monochrome), **Compact** (dense), **ATS Plain** (single column, system fonts — maximum parser compatibility), **Two-Column ATS** (visual grid, linear DOM order preserved), **Executive** (spacious serif, centered header), **Tech** (monospace accents, skills first) and **LaTeX ATS** (single column, navy rules, per-role key-technologies line — ported from [danielteles/ats-friendly-latex-cv](https://github.com/danielteles/ats-friendly-latex-cv), MIT). One semantic structure; switching is instant CSS — never a regeneration. Template identity + CSS live in a **single shared package** (`packages/resume-templates`: `templates.json` manifest + `resume.css`) consumed by both the web preview and the PDF renderer, with a guard test binding the two sides.
- **Instant chat commands**: "switch to the classic layout" / "troca pro layout classic" and "export the pdf" are resolved locally — zero LLM/network round-trip.
- **Deterministic intent routing** in the chat backend: a job-description-looking message generates; a follow-up on an active resume refines (with recent conversation as context); small talk gets a canned localized reply without spending an LLM call.
- **Streaming** everywhere (SSE with heartbeat): generation and refinement show live progress.
- Download PDF without the browser print dialog (server-side Playwright, same CSS as the preview).
- Merge **GitHub public repos** (optional token) with **local project `.md` files** (including private work). Chat refines tap the same sources: when a request mentions GitHub or a project, the refine only names projects that actually exist (local `data/projects/*.md`, or real repos for the configured `githubUsername`) — and asks a clarifying question instead of guessing when the request is ambiguous.
- Generation, refine and Profile-Analysis system prompts include composable **skill blocks** (`apps/api/prompts/skills/`): a **tailored-resume** block (job analysis, honest keyword mapping, ATS-oriented structure), a **resume-craft** block (bullet shape, honest quantification, ATS keyword hygiene, seniority/role archetypes — distilled from the [ResumeSkills](https://github.com/Paramchoudhary/ResumeSkills) collection, MIT), and a **humanizer** block (strip AI-writing tells while keeping every fact — distilled from [blader/humanizer](https://github.com/blader/humanizer), MIT). See the *Prompts* section below for how they compose.
- **Living Profile (v2)**: upload `.json`/`.md`/`.pdf` via drag & drop in the composer (progress, sha256 dedup, actionable errors for scanned PDFs); **incremental merge** that never rewrites what didn't change and never lets an upload delete data ("upload never removes"); approve/reject cards that survive page reloads; profile version history + revert (`GET /api/profile/versions`, `POST /api/profile/revert`); chat intent `profile_update` ("mudei meu telefone…") applies validated patches with provenance and offers — never forces — a resume regeneration.
- **Inline editing (v2)**: pencil toggle on the preview toolbar; edit any field via contenteditable (commit on blur/Enter, no caret jumps, same sanitization allowlist as rendering), add/remove list items, undo/redo via buttons or Ctrl-Z/Ctrl-Shift-Z (including undoing a bad refine that arrived over SSE); chat refines start from **exactly what you see**, edits included; non-blocking zod validation.
- **Settings UI (v3)**: gear icon in the header → runtime provider/model/key management. Availability + auth-mode badge per provider (`api_key` / `cli` / `local`), write-only key inputs showing only the configured state (`env` / `keychain`), dynamic per-provider model picker, env-lock indicators when a `.env` variable pins a setting. Everything takes effect on the next LLM call — no restart, no `.env` edits. A **GitHub** section lets you view, set or clear the `githubUsername` used for repo merging directly from the UI — no more hand-editing `data/profile/resume.json`.
- **Visual resume diff (v3)**: after a refine, the chat card shows what actually changed — before → after per section, with honest fallbacks when only deeper details changed.
- **Accessible primitives (v3)**: a single Dialog (focus trap, Escape, focus return) and an ARIA-complete Combobox power the settings, confirmations and model pickers; mobile tab state lives in the URL (`?tab=`), so reload and deep links work.
- **Job Monitor (v7)**: a third app area that scans **7 job boards** on your schedule (or on demand), deduplicates across them, scores **Fit** against your Profile and ranks by **Visibility Score** — how likely your resume is to actually be read. Each listing offers a **One-click Resume** (tailored PDF, no approval turn) and **Open in chat** (the full proposal-review flow). See [Job Monitor](#job-monitor-v7) below.
- **Light / dark theme** (persisted in `localStorage`).
- **Keyboard shortcuts**: `Enter` sends a chat message (`Shift+Enter` for a newline), `Esc` closes any open dialog, `Ctrl`/`Cmd`-`Z` and `Ctrl`/`Cmd`-`Shift`-`Z` undo/redo resume edits — all left alone while typing in a text field or contenteditable region, so they never fight native per-field editing.
- **Test suite + CI**: 1575 pytest (unit + integration, LLM and job boards always faked and network-isolated; 6 e2e render a real PDF) · 754 Vitest/Testing-Library/MSW · 31 Playwright e2e tests (mocked by default, `@real` variants opt-in) · GitHub Actions workflows for web and api (PDF e2e as a separate opt-in job).

## Prerequisites

- **Node.js** 18+ and **npm**
- **Python** 3.11+
- **Ollama** installed and a model pulled (e.g. `ollama pull llama3.2`) when you want the free/local provider — selected in the Settings UI, via `AI_PROVIDER=ollama`, or as the `auto` fallback when no Claude/Gemini key is configured
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
| `.env` | **Optional since v3** — provider, default model and API keys are all manageable from the Settings UI (persisted in `app_settings`/OS keychain). When a variable IS set here it wins over the UI and the Settings dialog shows a lock naming it. Variables: `GITHUB_TOKEN`; **`AI_PROVIDER`** (`auto` \| `claude` \| `gemini` \| `ollama`); **`AI_DEFAULT_MODEL`**; `ANTHROPIC_API_KEY` / `CLAUDE_MODEL`; `OLLAMA_BASE_URL` / `OLLAMA_MODEL`; `GEMINI_API_KEY` / `GEMINI_MODEL`; `PROFILE_JSON_PATH`; `DATABASE_URL`, etc. Copy from `.env.example`. |

**LLM routing (summary):** since v3 the active provider is a **runtime setting** — change it in the Settings UI (gear icon) with immediate effect, persisted in `app_settings`. The `AI_PROVIDER` env var is optional; when set it **overrides** the UI choice and the Settings dialog shows a lock naming it. The values mean the same in both places:

| Provider | Behavior |
|---------------|----------|
| `auto` | Claude if `ANTHROPIC_API_KEY` is set; else Gemini if `GEMINI_API_KEY` is set; otherwise Ollama. A local `ant auth login` sets no key, so use `claude` explicitly to select it that way. |
| `claude` | Always Claude. Auth resolves from `ant auth login` (the Claude session on your machine) or `ANTHROPIC_API_KEY`. Model from `CLAUDE_MODEL` (default `claude-sonnet-5`). |
| `gemini` | Always Gemini (requires `GEMINI_API_KEY`). |
| `ollama` | Always Ollama (uses `OLLAMA_MODEL` / `OLLAMA_BASE_URL`). |

**Claude "linked on your machine":** run `ant auth login` once (ships with the Claude / `ant` CLI) and the app uses that local session automatically — no key anywhere (the Settings UI shows Claude with auth mode `cli`). Select Claude in Settings, or simply pick **Claude Opus 4.8** / **Claude Sonnet 5** in the model selector: a `claude-*` (or `gemini-*`) model chosen in the UI routes to that backend regardless of the active provider. Have an API key? Paste it in **Settings → API keys** and it goes straight to the **OS keychain** (see [Security](#security)) — never to a file.

Optional **`AI_DEFAULT_MODEL`** applies when the UI does not send a `model` field (empty override). Per-request `model` in the API body still wins when provided.

**Generation tuning (optional):** `LLM_TEMPERATURE` (default `0.4`, applies to Gemini/Ollama only — Claude Sonnet 5 / Opus reject sampling params, so it is not sent to Claude). Claude: `CLAUDE_MAX_OUTPUT_TOKENS` (default `8192`) and `CLAUDE_THINKING` (`off` default, or `adaptive`). Gemini: `GEMINI_MAX_OUTPUT_TOKENS` (default `8192`, avoids truncated/invalid JSON on longer resumes). Ollama: `OLLAMA_NUM_CTX` (default `8192`) and `OLLAMA_NUM_PREDICT` (default `4096`) — the stock context window on many local models is small enough to silently truncate the profile + PDF + projects prompt and lower quality, so this raises it. See `.env.example`.

**Resolution order:** `PROFILE_JSON_PATH` (if set) → `data/profile/resume.json` → `data/profile/Profile.json` → `data/profile_master.json`. After you use `resume.json`, you can delete the legacy `profile_master.json` to avoid two sources.

**Do not commit** real phone numbers, employer details, or tokens.

## Setup

**Single command:** `npm run setup` creates the backend venv, installs Python deps, installs the Playwright Chromium browser, installs frontend deps, and seeds `.env` / `data/profile/resume.json` from their examples when missing. Edit `data/profile/resume.json` afterwards with your real data — it's just seeded from the example. Safe to re-run any time (skips what's already done). See the manual steps below if you'd rather run them one by one or something in `setup` fails. It does **not** install `python-jobspy` — that one is a deliberate opt-in, see [Job Monitor](#job-monitor-v7).

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

## Run

**Single command (after the one-time setup above):**

```bash
npm run dev
```

Runs the API (`uvicorn`, reloading) and the UI (`vite`) together from the root, using the venv at `apps/api/.venv`. `Ctrl+C` stops both. Cross-platform (Windows/macOS/Linux). Other root scripts: `npm run dev:api` (backend only), `npm run dev:web` (frontend only).

**Or two terminals (manual, if you want them separate):**

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

If the active provider resolves to **Ollama** (chosen in Settings, `AI_PROVIDER=ollama`, or the `auto` fallback with no keys), ensure **Ollama** is running (`ollama serve` if needed) — the Settings dialog shows its live reachability.

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

## Job Monitor (v7)

The third area of the app (next to the resume chat and Profile Analysis), reachable from the header toggle. On a schedule you choose — or when you press **Buscar agora** — it searches job boards for the roles in your **Search Profile**, merges duplicates across boards, scores each listing against your Profile and ranks the result by how likely your resume is to actually be read.

Three things it deliberately does **not** do:

- **It never touches the Living Profile.** The Monitor only reads your Profile; writes still come from chat, uploads and inline edits alone.
- **It is the only part of the product that reaches a job board.** The chat still accepts pasted text only — pressing *Open in chat* hands over the description the scan already fetched, it does not open a new fetching path.
- **Tests never call a real board or a real LLM** — fake boards, fake LLM, in-memory SQLite, like everywhere else in this repo.

**How the ranking works.** Every listing gets a **Fit Score** (0–100, how well your Profile matches it) in two stages: a cheap deterministic keyword pass scores everything and discards the clear misses, then the LLM scores only the top 25 of what survived — one small JSON-only call each, capped by `FIT_LLM_CONCURRENCY`. A listing already scored is not re-scored on the next scan unless it was reposted with a different description. The list is then ordered by **Visibility Score** = `0.55·fit + 0.25·recency + 0.20·competition` (recency decays from 1.0 at ≤24h to 0 at 7 days; competition comes from the applicant band). A perfect fit with 300 applicants ranks below a good fit posted an hour ago. The weights live in `apps/api/app/config.py` (`VISIBILITY_WEIGHTS`, `APPLICANT_BAND_SCORE`) and are not editable from the UI in v7.

**The list is the last scan.** Job listings are ephemeral — a listing that the newest scan did not find disappears from it. What survives is the **Listing Memory**, keyed by normalized company + title: the status you gave the listing (`new → seen → applied | dismissed`), the Fit Score already paid for, and the One-click Resume already generated. A dismissed job stays hidden when a later scan finds it again.

### The seven boards

Each board is toggled on or off in the Search Profile, and each has its own minimum interval — the scan uses `max(your interval, the board's minimum)` and reports `skipped` for a board whose own floor has not elapsed yet.

| Board | How it is reached | Min. interval |
|---|---|---|
| **LinkedIn** | `python-jobspy` scraper (optional install, see below) | 1h |
| **Indeed** | `python-jobspy` scraper | 1h |
| **Glassdoor** | `python-jobspy` scraper | 1h |
| **Google Jobs** | `python-jobspy` scraper | 1h |
| **Remotive** | Public JSON API — `GET https://remotive.com/api/remote-jobs?category=software-dev` | **6h** (terms) |
| **We Work Remotely** | Public RSS feeds (`remote-programming-jobs.rss` plus back-end / front-end / full-stack), parsed with the stdlib `xml.etree` | 1h |
| **Remote OK** | Public JSON API — `GET https://remoteok.com/api`, explicit `User-Agent` | 1h |

**A scan is partial, not failed.** Each board reports its own status — `ok`, `blocked`, `error` or `skipped` — and the other boards' results stand. The `BoardStatusBar` above the list shows what happened ("LinkedIn: bloqueado, tentamos na próxima varredura"). The previous list is only replaced when a scan actually learned something about the market: if every board was blocked, your listings stay where they were instead of being wiped by a rate limit.

### Optional: install the JobSpy-backed boards

`python-jobspy` is **not** installed by `requirements.txt`. Its published metadata hard-pins `NUMPY==1.26.3` and `regex<2025`, neither of which has a wheel for CPython 3.13+/3.14 (and numpy 1.26.3 does not build against it), so listing it there would make `pip install -r requirements.txt` fail outright. Those pins are stale rather than real — the library runs fine on the modern versions this project installs — but pip cannot override a dependency's pin from a requirements file, so the resolver is skipped for this one package:

```bash
cd apps/api
pip install -r requirements.txt              # includes jobspy's REAL deps: pandas, beautifulsoup4, markdownify, regex, tls-client
pip install --no-deps -r requirements-jobspy.txt
```

**Without it the app still runs, and so does the Monitor.** The import is lazy, all seven boards stay registered, and the four JobSpy-backed ones report Board Status `error` with an actionable message while Remotive, We Work Remotely and Remote OK work normally. Removing them from the registry instead would leave a Search Profile with LinkedIn enabled scanning nothing, silently — the opposite of what the status bar exists for.

### Terms of use and attribution

- **Remotive** allows at most **4 API calls a day**. That is where the 6h minimum interval comes from, and the Monitor makes exactly **one** request per scan (with several target roles it asks for a wider page and filters locally, rather than one call per role). Their terms also require attribution: the app serves the note *"Vagas fornecidas por Remotive (remotive.com)."* with the board catalog and shows the board name next to every source link.
- **Remote OK** requires attribution as well — *"Vagas fornecidas por Remote OK (remoteok.com)."*, same mechanism.
- Every Listing Source always keeps and displays its board's name plus the original link, on every board. If you add a board, put its attribution note next to its id in `apps/api/app/services/jobs/search_profile_service.py` rather than in the web app — it is a legal obligation, not copy.

### LinkedIn: what it can and cannot do

- **It is the only board that reports applicant counts**, and only as an **Applicant Band** (`<10`, `<25`, `<50`, `<100`, `100+`, `unknown`) — never an exact number, because LinkedIn itself only shows the exact figure up to 100 and "over 100" past that. Getting it costs one extra request to the listing's public page (concurrency 4, 6s timeout); a failure yields `unknown` and never brings the board down. Every other board reports nothing, and `unknown` never excludes a listing from your maximum-applicants filter — it just scores neutrally.
- **429 blocks are common and are detected from the log, not from an exception.** The scraper swallows LinkedIn's 429 and returns an empty result, which would be indistinguishable from "nothing found today"; the adapter watches the library's logger during the call and reports `blocked` instead.
- **There are no proxies and no IP rotation in v7.** A blocked board is reported and retried on the next scan; that is the whole mitigation. If `blocked` shows up constantly, that is the signal to revisit.
- Searches are sequential, not parallel (roles × locations, capped at 6 queries per board per scan, with `SCAN_RESULTS_WANTED` split across them) — a burst is the fastest way to get rate-limited.

### The scheduler

An `asyncio` task started in the API's lifespan, next to the upload reaper — no new scheduling dependency. It wakes every `SCAN_CHECK_INTERVAL_SECONDS`, re-reads your interval from the Search Profile each time (so changing it, or switching it off, takes effect without a restart) and decides whether the next scan is due by looking at the **last scan in the database** — so a 24h interval survives a restart, and an on-demand scan resets the clock. **At most one scan runs at a time**: a second request while one is running gets `409` carrying the running scan.

The product's off switch is `intervalHours: off` in the Search Profile, not an env var.

### One-click Resume vs. Open in chat

| | **One-click Resume** | **Open in chat** |
|---|---|---|
| What happens | The full pipeline runs — Analysis → Improvement Proposal → generation → PDF — with the proposal **auto-approved exactly as produced**. The only place in the app where a Resume is generated without a human approving the plan. | Creates a chat session titled "Company · Role" seeded with the listing's description as your first message, hydrates it and takes you to the resume area. From there it is an ordinary session: the normal Analysis → proposal → review flow. |
| Guard rails | Unchanged: Patch Validator, Relevance Filter, `MIN_SKILLS_AFTER_DROPS`, employer/role/degree never dropped. | Unchanged. |
| Language | The locale the scan resolved for that posting. | Resolved normally from the description. |
| Refused when | The description is too short to look like a job description (the button is disabled, with a tooltip). | — |
| Repeat click | Returns the saved PDF without spending an LLM call; **Regerar** is the explicit button that pays for a new one. | A new session each time. |
| Where it lands | `resume_versions` with `session_id = NULL` — it does **not** appear in the session sidebar. | A normal session in the sidebar. |

> **Known gap (v7):** the One-click PDF is rendered on the server, which reads the global template preference from `app_settings['resume_template']` — and nothing writes that key yet (the web app keeps your choice in `localStorage`). In practice every One-click PDF currently comes out in **Modern**. The chat/preview export is unaffected.

### `/api/jobs/*` endpoints

- `GET /api/jobs/search-profile` · `PUT /api/jobs/search-profile` — what you are looking for: target roles, locations, remote preference, accepted languages, enabled boards, maximum applicant band, scan interval. A profile is only stored once you save it; the `GET` on a fresh install returns a suggestion-shaped default with `updatedAt: null`.
- `POST /api/jobs/search-profile/suggest` — a Search Profile derived deterministically from your Profile's `headline` (no LLM call, at most 5 roles, your own words kept verbatim). It is **not** persisted — review it and save.
- `GET /api/jobs/boards` — the catalog: board id, display name, minimum interval, attribution note.
- `POST /api/jobs/scans` — start an immediate scan → `202` with the running scan; `409` (carrying the current scan) if one is already running; `422` if no Search Profile has been saved.
- `GET /api/jobs/scans/current` · `GET /api/jobs/scans/latest` — the running scan and the last finished one, with per-board statuses and `nextScanAt`. `204` when there is none.
- `GET /api/jobs/listings?status=&board=&max_band=&include_dismissed=1` — the ranked list (Visibility descending); dismissed listings are hidden unless asked for.
- `GET /api/jobs/listings/{id}` — full description and every source link (also advances `new → seen`) · `PATCH /api/jobs/listings/{id}/status` → the updated listing.
- `POST /api/jobs/listings/{id}/one-click-resume?regenerate=0|1` → `application/pdf`. `422 description_too_short`, `409` while one is already generating for that listing, `502` when the LLM call fails.
- `POST /api/jobs/listings/{id}/open-in-chat` → `{ sessionId }`.

### Environment variables

All optional; the defaults are what the app runs on.

| Variable | Default | What it does |
|---|---|---|
| `SCAN_CHECK_INTERVAL_SECONDS` | `60` (1–3600) | How often the scheduler wakes to re-read your interval and check whether a scan is due. **Not** the scan interval — that one lives in the Search Profile. |
| `SCAN_RESULTS_WANTED` | `50` (1–200) | Cap on postings **one board** returns for one scan. The JobSpy adapter divides it across its role × location grid, so it is that board's whole budget for the query. |
| `FIT_LLM_CONCURRENCY` | `4` (1–25) | Parallel LLM calls in the Fit stage. Lower it if a hosted provider rate-limits you; raise it against a fast local Ollama. |
| `SCAN_SCHEDULER_ENABLED` | on | Whether the lifespan starts the background scheduler at all. Exists for the test suite (`0` in `tests/conftest.py`); to stop scheduled scans as a user, set the interval to **off** in the Search Profile instead. |
| `JOB_BOARDS_FAKE` | off | Swaps the real board adapters for deterministic fakes. For the opt-in `@real` Playwright run, which drives the real app and a real LLM but must never reach a real board. Not for normal use. |

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
- `PUT /api/profile/github-username` — body `{ "githubUsername": string | null }` (an empty string also clears it) → `{ profileVersion, githubUsername }`; creates a new profile version with `sourceKind: "manual"`, same as any direct manual edit

**Legacy/direct endpoints (still supported — the UI falls back to them if the chat API is absent):**

- `GET /api/health` — health check
- `GET /api/models` — model suggestions for the UI picker (`{ default, models: [{value,label,provider}] }`) — since v3, a live per-provider catalog (Anthropic `/v1/models`, Gemini `models.list`, Ollama `/api/tags`, ~5 min cache) with static fallback when offline/keyless
- `GET /api/profile` — loads the resolved profile JSON (same resolution order as [Personal data](#personal-data-not-in-this-repository); validates schema)
- `GET /api/github/repos` — lists repos for `githubUsername` in profile
- `POST /api/generate` — body: `{ "job_description", "model?", "locale?" }` → tailored `ResumeDocument`. `locale` accepts `"auto"` (default: detects the job description's language, pt-BR vs en), or `"pt-BR"`/`"en"` to force the output language.
- `POST /api/generate/stream` — same body as generate; **SSE** stream with `stage` events (progress, message) and a final `done` event with the resume JSON
- `POST /api/refine` — body: `{ "resume", "message", "model?" }`
- `POST /api/refine/stream` — same as refine over **SSE**
- `POST /api/export/pdf` — body: `{ "resume": { ... }, "template?": "modern" | "classic" | "minimal" | "compact" | "ats-plain" | "two-column-ats" | "executive" | "tech" | "latex-ats" }` → PDF download (defaults to `modern`)

**Settings (v3 — runtime provider/model/key management):**

- `GET /api/settings/providers` — `{ active, activeLockedByEnv, activeEnvVar, providers: [{ name, available, auth, defaultModel, defaultModelLockedByEnv, defaultModelEnvVar, models }] }`
- `PUT /api/settings/providers` — body `{ provider: "auto" | "claude" | "gemini" | "ollama", defaultModel? }` — immediate effect (no restart), persisted in `app_settings`; env-pinned settings are reported as locked instead of silently ignored
- `GET /api/settings/keys` — `{ keys: [{ name, configured, source: "env" | "keychain" | null }] }` — values are never returned
- `PUT /api/settings/keys` — body `{ name: "ANTHROPIC_API_KEY" | "GEMINI_API_KEY" | "GITHUB_TOKEN", value }` — writes to the OS keychain only (never SQLite, never logged/echoed)
- `DELETE /api/settings/keys/{name}` — removes the keychain entry

**Job Monitor (v7):** `/api/jobs/*` — search profile, scans, ranked listings, one-click resume. Listed in [Job Monitor](#job-monitor-v7) above.

## Prompts

- **System:** `apps/api/prompts/system/` — `generate.md`, `refine.md`, `extract_profile.md` (JSON-only resume output rules and PDF-profile extraction).
- **Skills:** `apps/api/prompts/skills/` — extra behavior merged into the system prompts. Generation loads `generate.md` + `resume-craft.md` + `tailored-resume-generator.md` + `humanizer.md` via `load_generate_system_prompt()`; refine (and the post-generation auto-improve pass) loads `refine.md` + `resume-craft.md` + `humanizer.md` via `load_refine_system_prompt()`; the Profile Analysis area loads `linkedin-analysis.md` + `humanizer.md` via `load_linkedin_analysis_system_prompt()` — all in `app/prompt_loader.py`. `resume-craft.md` (bullet shape, honest quantification, ATS keyword hygiene, seniority/role archetypes) is **distilled** from the [Paramchoudhary/ResumeSkills](https://github.com/Paramchoudhary/ResumeSkills) collection (MIT); `humanizer.md` (avoid AI-writing tells while keeping every fact) is **distilled** from [blader/humanizer](https://github.com/blader/humanizer) (MIT, based on Wikipedia's "Signs of AI writing"). Both are adapted to this app's JSON-only / advice-only, single-locale, never-fabricate contract. The raw upstream skills are vendored under `skills/_vendor/` as **reference only** — not composed into any prompt (see each folder's `README.md`). Edit the composed blocks to change LLM behavior without touching the UI.

## Tests

**Backend** (from `apps/api`, venv active): `python -m pytest` — 1575 tests. Fast unit + integration suites use a fake LLM, fake Job Boards, an in-memory SQLite and a black-holed HTTP transport (never a real network call, even if real keys exist on the machine); the 6 tests marked `e2e` render a real PDF via Playwright (`-m "not e2e"` to skip them).

**Web** (from `apps/web`): `npm run test:run` (754 Vitest + Testing Library + MSW tests, including SSE stream mocks) · `npm run test:e2e` (31 Playwright tests against a mocked API — deterministic, CI-safe) · `npm run test:e2e:real` (opt-in variants against a live uvicorn on port 8000; see `e2e/README.md`). Under a loaded machine the full Vitest run can trip the default 5s per-test timeout on a handful of unrelated heavy tests — `--testTimeout=30000` is the known workaround, not a regression.

**CI:** `.github/workflows/web.yml` (npm ci → lint → tsc → vitest coverage → mocked Playwright) and `api.yml` (pytest, plus a separate opt-in `workflow_dispatch` job for the PDF e2e) run on every push touching each app.

## Security

Built to run **locally**, keeping credentials out of the repo and off disk in the clear.

- **Local only.** The API binds to `127.0.0.1:8000` and CORS is restricted to the Vite dev origin. Don't bind `0.0.0.0` or expose it publicly without adding authentication first.
- **Secrets never committed.** `.env` is gitignored, and a **pre-commit secret scanner** (below) blocks accidental key/token commits.
- **Claude auth — most secure first:** `ant auth login` (local OAuth session: short-lived, revocable, nothing stored in the repo) › **OS keychain** › `.env`.
- **Keys can live in the OS keychain** instead of `.env` (Windows Credential Locker / macOS Keychain / Linux SecretService). Per secret, resolution is **env var → keychain → unset** (`app/services/secret_store.py`).
- **Least privilege:** use a workspace-scoped Anthropic key and a **read-only** `GITHUB_TOKEN` (`public_repo`, or a fine-grained PAT with only `Contents: Read`).
- **Error redaction:** any configured secret value is stripped (`«redacted»`) from LLM error messages before they reach the UI or logs (`app/services/secret_redaction.py`). The Gemini key is sent as a header, never in the request URL.

### Store a key in the OS keychain (optional)

Since v3 the easiest way is the **Settings UI** (gear icon → API keys): it writes to the keychain under the hood, shows only the configured state, and removal is one click. The CLI route still works too — `keyring` is already in `requirements.txt`. Store secrets under the service name `resume-agent`, keyed by the env var name, then leave that variable **unset** in `.env` (an env var, if set, always wins and shows as locked in the UI):

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

**Gemini errors:** Confirm the key from [Google AI Studio](https://aistudio.google.com/apikey), optional `GEMINI_MODEL` (default `gemini-2.5-flash`), and that the [Generative Language API](https://ai.google.dev/gemini-api/docs) is enabled for the project. To use Ollama instead, switch the provider in **Settings** (or set `AI_PROVIDER=ollama`); there is no automatic failover from Gemini to Ollama on HTTP errors.

**Claude authentication errors (HTTP 401/403):** With Claude active (or a `claude-*` model picked in the UI), the SDK needs a credential. Either run `ant auth login` once (uses the Claude session on your machine — no key anywhere), or add `ANTHROPIC_API_KEY` via **Settings → API keys** (keychain) or `.env`, from [the console](https://console.anthropic.com/settings/keys). A `403` usually means the authenticated account cannot access the chosen model. If you see "The 'anthropic' package is not installed", re-run `pip install -r apps/api/requirements.txt`.

**Wrong backend selected:** Pick the provider explicitly in **Settings** (`claude`, `gemini`, or `ollama`) instead of `auto` for a fixed choice. If the Settings dialog shows a lock, an `AI_PROVIDER` env var is pinning the value — unset it in `.env` to manage it from the UI. Selecting a `claude-*`/`gemini-*` model in the composer overrides the active provider for that request.

## License

MIT — see [LICENSE](LICENSE) if present; otherwise treat as MIT for the scaffold.
