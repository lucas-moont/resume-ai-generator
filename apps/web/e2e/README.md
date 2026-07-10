# apps/web/e2e — Playwright suite

Five core flows, each with a **default (mocked)** test and, where practical, an
opt-in **`@real`**-tagged counterpart that exercises the actual FastAPI backend.
Plus a couple of regression specs for bugs found in the v1 QA live pass.

| Spec | Flow |
|---|---|
| `generate.spec.ts` | Paste a job description in a fresh chat → session created lazily → resume rendered |
| `refine.spec.ts` | Follow-up message on an active resume → preview updates, "resume updated" card |
| `template-switch.spec.ts` | Toolbar select **and** a chat command switch templates instantly, zero network calls |
| `export-pdf.spec.ts` | Toolbar "Download PDF" → correct request payload → browser download fires |
| `persistence.spec.ts` | Resume/template/theme survive a reload; the active session auto-restores the conversation |
| `responsive-preview.spec.ts` | The A4 preview scales to fit a narrow (~400px) viewport instead of overflowing (B3 regression) |

## Running the mocked suite (default, required to pass)

No backend needed — every `/api/**` call is intercepted with `page.route(...)`,
built from the real request/response shapes in `apps/api`'s router/service code
and integration tests (see `e2e/support/{sse,mocks,fixtures}.ts`).

```bash
npm run test:e2e        # headless
npm run test:e2e:ui     # Playwright's UI mode, for debugging
```

## Running the `@real` suite (opt-in, not required to pass in CI)

These hit `http://127.0.0.1:8000` for real — no `page.route` mocks. Start the
API first:

```bash
# in apps/api, with the venv active
uvicorn app.main:app --reload --port 8000
```

Then, in `apps/web`:

```bash
npm run test:e2e:real
```

This is a tool for the v1 gate's live QA pass, not a CI gate — it depends on a
real LLM/Ollama backend being configured and reachable, which CI doesn't have.

## Tagging convention

`@real` in the test title is the tag. `test:e2e` runs `--grep-invert @real`
(mocked only); `test:e2e:real` runs `--grep @real` (real backend only). A spec
file can hold both variants of the same flow side by side.
