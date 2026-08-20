# Resume writing craft (skill)

Distilled from the ResumeSkills collection (`skills/_vendor/resume-skills/`, MIT) — specifically `resume-bullet-writer`, `resume-quantifier`, `resume-ats-optimizer`, `resume-section-builder`, and the tech / executive / creative / career-changer optimizers. Adapted to this product's hard contract: emit **only** the resume JSON, one target locale, first-person-singular voice where the language inflects person, and **never fabricate facts**. The base system prompt (schema, HTML subset, truthfulness, language, voice) always wins over anything here.

This block governs *how you write or revise the fields you touch* — it is not a mandate to rewrite fields the user did not ask about.

## Bullet shape

Every `highlights` bullet should read as an achievement, not a duty. Use whichever shape the real facts support:

- **X-Y-Z**: accomplished **X**, measured by **Y**, by doing **Z** (e.g. pt-BR: *"Reduzi o tempo de carga de 8s para 2s ao reescrever a renderização em Next.js"*).
- **Condensed STAR/CAR**: context/challenge → the action you took (tech/method) → the outcome.

Open every bullet with a strong action verb — never *"Responsible for"*, *"Helped with"*, *"Worked on"*, or a subject pronoun. Vary the verb across bullets; draw from: Led / Directed / Spearheaded · Built / Designed / Launched · Grew / Increased / Scaled · Streamlined / Optimized / Automated · Reduced / Eliminated / Resolved · Analyzed / Identified / Forecasted. One idea per bullet.

## Honest quantification (surface, never estimate)

Numbers make bullets credible — but here you may only surface magnitudes that are **already present in, or unambiguously derivable from, the inputs** (Profile JSON, PDF excerpt, project sources). Use these lenses to find real numbers buried in prose: money · time · percentage · volume/scale (team size, users, requests) · quality (uptime, accuracy, satisfaction) · frequency (per day/week).

- If a figure is stated (*"team of 8"*, *"30 deploys/dia"*), put it in the bullet.
- You MAY phrase a real figure conservatively (a range, or `X+`) to stay defensible — but the underlying number must come from the inputs.
- If no real number exists, write a strong **qualitative** bullet. NEVER invent, estimate, or infer a metric that is not grounded in the inputs. A fabricated number is a defect, not an improvement. **This deliberately overrides the upstream `resume-quantifier` skill's "estimate when data is unavailable" advice — that guidance does not apply to this product.**

## ATS keyword hygiene

The résumé is often filtered by software before a human reads it.

- Mirror the **exact phrasing** of the job's priority terms **when they are genuinely true** of the candidate (write `Next.js`, `CI/CD`, `PostgreSQL` the way the posting spells them and the profile confirms them).
- Place the most important true keywords where they carry weight: `summary`, `skills`, and the leading `highlights` — without stuffing (each term earns its place once or twice, never a keyword wall).
- Spell out an acronym with its plain meaning at most once, when both fit naturally.
- Layout and section headings are owned by the app's templates — never change structure for ATS; only the wording is yours.

## Emphasis by seniority (within the fixed schema)

You cannot reorder top-level sections (the template owns layout), but you control what leads:

- **Entry / recent grad**: let education and projects carry weight; bullets may quantify throughput, accuracy, or scope that is real.
- **Mid-level**: experience leads; each recent role opens with its most job-relevant, outcome-bearing bullet.
- **Senior / executive**: `summary` states scope and leadership brand (org size, budget/P&L, transformation) **only when the profile supports it**; bullets foreground strategic impact over task lists.

## Role archetypes (foreground, never fabricate)

| When the target role looks like… | Foreground — but only if it is in the profile |
|---|---|
| Software / technical | Real stack, scale (users, throughput, data size), and impact (latency, uptime, DAU); relevant projects with links |
| Executive / leadership | Strategy, organizational scope, team size, budget/P&L, transformation outcomes |
| Creative / design | Measurable outcomes plus a portfolio link, while keeping wording plain-text and ATS-parseable |
| Career change | Transferable outcomes and tools that appear in **both** the profile and the job; a `summary` that bridges past field → target role — never an invented title |
