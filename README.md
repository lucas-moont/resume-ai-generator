# Resume agent (local)

Web app to tailor your resume to a job description using **Ollama** (local LLM) or, optionally, **Google Gemini** when `GEMINI_API_KEY` is set in `.env`, with a live A4 preview and **one-click PDF** export (Playwright). Stack: **React + Vite** frontend, **FastAPI** backend, project sources as Markdown files under `data/projects/`.

## Features

- Paste a job description → generate an ATS-friendly, tech-styled resume JSON rendered in the preview.
- Refine with short natural-language instructions.
- Download PDF without using the browser print dialog (server-side Playwright).
- Merge **GitHub public repos** (optional token) with **local project `.md` files** (including private work).

## Prerequisites

- **Node.js** 18+ and **npm**
- **Python** 3.11+
- **Ollama** installed and a model pulled (e.g. `ollama pull llama3.2`) **unless** you only use **Gemini** via `GEMINI_API_KEY` (see `.env.example`)
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
| `.env` | Optional `GITHUB_TOKEN`, `OLLAMA_*`, `GEMINI_API_KEY` / `GEMINI_MODEL` (Gemini overrides Ollama for all resume JSON LLM calls when the key is set), `PROFILE_JSON_PATH`. Copy from `.env.example`. |

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

Open `http://localhost:5173`. The UI proxies `/api/*` to the FastAPI server on port **8000**.

If you are not using **Gemini** (`GEMINI_API_KEY`), ensure **Ollama** is running (`ollama serve` if needed).

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

- `GET /api/health` — health check
- `GET /api/profile` — loads `data/profile_master.json` (validation)
- `GET /api/github/repos` — lists repos for `githubUsername` in profile
- `POST /api/generate` — body: `{ "job_description", "model?", "locale?" }` → tailored `ResumeDocument`
- `POST /api/refine` — body: `{ "resume", "message", "model?" }`
- `POST /api/export/pdf` — body: `{ "resume": { ... } }` → PDF download

## Prompts

System prompts live in `apps/api/prompts/system/` (`generate.md`, `refine.md`). Edit them to change LLM behavior without touching the UI.

## Troubleshooting

**Ollama error on `/api/chat`:** If that endpoint returns any non-success status (404, 405, etc.), the API retries with `/api/generate`. If both fail, set `OLLAMA_BASE_URL` to `http://127.0.0.1:11434` (no `/v1` path), run `ollama serve`, and ensure `ollama list` includes your `OLLAMA_MODEL`.

**HTTP 404 on `/api/generate` with `model '…' not found`:** Ollama uses 404 for a missing local model. Run `ollama pull llama3.2` (or whatever tag you want), or set `OLLAMA_MODEL` in `.env` to an **exact** name from `ollama list`.

**Gemini errors:** Confirm the key from [Google AI Studio](https://aistudio.google.com/apikey), optional `GEMINI_MODEL` (default `gemini-2.5-flash`), and that the [Generative Language API](https://ai.google.dev/gemini-api/docs) is enabled for the project. Remove or unset `GEMINI_API_KEY` to fall back to Ollama.

## License

MIT — see [LICENSE](LICENSE) if present; otherwise treat as MIT for the scaffold.
