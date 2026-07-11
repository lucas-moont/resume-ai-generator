# CONTEXT — Domain Glossary

Canonical vocabulary for this project. Use these terms exactly — in code identifiers, test names, tickets, and conversation. Portuguese aliases (used in product docs) in parentheses.

## Core concepts

- **Profile** — the canonical professional profile of the single local user, validated by the `ProfileMaster` schema. The single source of truth every resume is generated from. _Avoid_: "master profile", "user data".
- **Living Profile** _(Perfil Vivo)_ — the Profile as a persistent, versioned entity that evolves through uploads, chat requests, and manual edits. It is never overwritten wholesale: changes arrive as Patch Ops, and only what is new or divergent ever changes.
- **Profile Version** — an immutable snapshot of the Profile produced by applying an approved patch. Every version records its **Provenance**. Reverting creates a new version; history is append-only.
- **Provenance** _(Proveniência)_ — the traceable origin of a profile change: which Source Document, chat message, or manual edit produced it, down to the source excerpt that justifies each op.
- **Resume** — a tailored `ResumeDocument` generated from the Profile for one job description. Derived data: refining or editing a Resume never mutates the Profile.
- **Template** — one of the ATS-friendly visual layouts. A global sticky user preference (like theme), applied instantly as CSS; presentation only, never tied to a specific Resume version.

## Ingestion & merge

- **Source Document** — an uploaded `.json`, `.md`, or `.pdf` file carrying professional information. Moves through a lifecycle: stored → extracted → proposed → applied | rejected | failed.
- **Ingestion** — turning a Source Document into candidate profile data. Structured JSON is validated directly (no LLM); markdown and PDF go through LLM extraction.
- **Deterministic Diff** _(diff determinístico)_ — the LLM-free comparison that classifies extracted data against the Profile as **new**, **divergent**, or **equal** (equal is discarded). Runs first, always.
- **Adjudication** _(adjudicação)_ — the LLM step that turns only new + divergent items into Patch Ops. Hard rule: the LLM never touches what the Deterministic Diff didn't flag.
- **Patch Op** — one restricted JSON-Patch operation (`add` / `replace` / `remove`) proposing a single profile change, carrying a reason, a confidence score, and a source excerpt for Provenance.
- **Patch Validator** — the deterministic gate that applies Patch Ops on a copy of the Profile, enforcing the path whitelist, schema validity, and the Upload-never-removes rule. Nothing reaches a Profile Version except through it.
- **Incremental Merge** _(merge incremental)_ — the full pipeline: Deterministic Diff → Adjudication → Patch Validator → new Profile Version. The user approves or rejects the proposed patch before it applies.
- **Upload-never-removes** — invariant: an upload can add or update profile data but never delete entities. Removal happens only via explicit chat request or manual edit.

## Chat & editing

- **Intent** — the deterministic server-side classification of a chat message: `generate` (job description), `refine` (change the active Resume), `profile_update` (change the Living Profile), `proposal_turn` (a session with a Pending Proposal), or a plain reply. No LLM call is spent deciding it — though a `proposal_turn`, once routed, uses an LLM to interpret the user's conversational reply.
- **Chat SSE contract** — the event stream (`stage`, `resume`, `message`, `proposal`, `profile_update`, `done`, `error`) between backend and frontend. It is the seam between the two workstreams: changes require agreement on both sides. Since v4, a turn may emit N `message` events (each a complete assistant bubble, appended immediately); card-bearing events (`resume`, `proposal`, `profile_update`) attach to the NEXT `message` in the stream.
- **Improvement Proposal** _(Proposta de Melhorias)_ — the detailed, job-anchored plan of what a generation will change, produced by an Analysis and negotiated in chat before any Resume is generated. Lifecycle: `proposed → approved | superseded | discarded`. No `generate` intent produces a Resume without an approved Improvement Proposal.
- **Proposal Item** — one improvement inside an Improvement Proposal: target section, current excerpt, proposed change, and a rationale anchored in the job description.
- **Pending Proposal** — the single `proposed` Improvement Proposal of a session (invariant: at most one). Its existence switches intent routing to the Proposal Turn.
- **Analysis** _(Análise)_ — the LLM call comparing Profile × job description that produces an Improvement Proposal (prose message + structured Proposal Items in one response).
- **Proposal Turn** — the conversational turn while a Pending Proposal exists: one combined LLM call classifies the user's reply as approve / adjust / question / new job description AND writes the assistant's answer. Approval chains straight into generation in the same SSE stream.
- **Inline Editing** _(edição inline)_ — direct manual edits on the A4 preview, committed on blur/Enter, undoable, synchronized with chat refinements.

## Settings & runtime config

- **Runtime Config** — the active AI provider, default model, and API keys as resolved by `get_runtime_config()` at CALL time (env var → App Settings/keychain → hardcoded default), never frozen at import; cache invalidável, invalidated on every settings write so a change takes effect on the next call, no process restart.
- **App Settings** _(Configurações)_ — the `app_settings` SQLite table holding only non-sensitive runtime preferences (active provider, default model). Never a home for an API key.
- **Key/secret rule** — an API key resolves env var → OS keychain and is written only through the keychain (`secret_store`); it never lands in App Settings/SQLite, a log, or an HTTP response (`secret_redaction`).
