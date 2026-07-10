# CLAUDE.md

Chat-based resume tailoring app (React + Vite frontend, FastAPI backend, local SQLite). See `README.md` for setup and architecture.

## Agent skills

### Issue tracker

Issues live as local markdown files under `.scratch/<feature-slug>/issues/` (gitignored). See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: glossary at `CONTEXT.md` (repo root, committed), ADRs at `docs/adr/` (local-only — `docs/` is gitignored by convention). Consumer rules: `docs/agents/domain.md`. Use the glossary's vocabulary in code, tests, and tickets.

## Conventions that bind every agent session

- Execution playbook, roadmap state, and version specs live in `docs/` (local-only): `docs/EXECUTION.md`, `docs/VISION.md`, `docs/v*-*.md`.
- **Tests never call a real LLM by default**: backend uses `FakeLlmProvider` + in-memory SQLite; web uses MSW; Playwright e2e is mocked by default (`@real` variants opt-in).
- **Shared-worktree commit protocol** (mandatory with parallel agents): commit by pathspec — `git add -N <new-files>` then `git commit -m "..." -- <explicit paths>`. Never `git add -A`/`-a`; never leave anything staged between commits.
- Conventional commits, incremental per ticket/step. `docs/` is gitignored — never commit it. Secrets never in code, SQLite, or logs (`secret_store` / `secret_redaction`; detect-secrets runs on pre-commit).
- Ports: API `127.0.0.1:8000`, Vite `5173`.
