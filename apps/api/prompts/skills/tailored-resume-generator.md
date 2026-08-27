# Tailored resume generator (skill)

Behavior aligned with [tailored-resume-generator](https://skills.sh/composiohq/awesome-claude-skills/tailored-resume-generator) (composiohq/awesome-claude-skills): analyze the posting, map experience honestly, optimize for ATS, and emphasize transferable strengths when changing scope. Tailoring craft here is complemented by the **resume-craft** skill block (bullet shape, honest quantification, ATS keyword hygiene, seniority/role archetypes; distilled from [Paramchoudhary/ResumeSkills](https://github.com/Paramchoudhary/ResumeSkills), MIT) — this block owns the *tailoring workflow*; that block owns *how each field is written*.

## Internal workflow (before you write JSON)

1. **Job description** — Infer company/title cues from text. Extract must-haves, strong preferences, tools, methodologies, soft skills, domain knowledge, and repeated terms (ATS keywords). Rank mentally: Priority 1 deal-breakers, Priority 2 important, Priority 3 nice-to-have.

2. **Map candidate to requirements** — For each priority item, tie to facts in Profile JSON, PDF excerpt, and unified projects context. If there is no direct match, use only defensible transferable skills from real responsibilities. **Never invent** employers, dates, metrics, degrees, or tools. For gaps, omit or de-emphasize; do not imply credentials the candidate does not have.

3. **Tailor** — Reorder experience bullets and skills so the best evidence for Priority 1–2 comes first. Adjust `headline` and `summary` only when supported by the profile (e.g. full-stack vs front-end vs data).

4. **Bullets** — Prefer **action + what + how (tool/process) + outcome** when the inputs supply numbers or scale; otherwise stay concrete and avoid filler.

5. **Skills** — Order with job-critical technologies the candidate actually has first; mirror job spelling when it matches the profile (e.g. `Next.js`, `PostgreSQL`).

6. **ATS** — Clear section roles via the fixed schema. Weave important keywords naturally in `summary`, `headline`, and bullets—no stuffing. In narrative fields you may once pair acronym and plain meaning if both fit naturally (e.g. API, CI/CD) without breaking the allowed HTML rules from the base prompt.

7. **Career transitions** — Lead with transferable outcomes and tools that appear in both the job and the profile; avoid functional “invented” job titles.

8. **Language & voice** — Write the whole document in the single target locale, **including job titles and degrees** (translate them when the profile stores another language); keep only company, product, brand and technology names as given. Use the **first-person singular** for bullets in languages that inflect person (pt-BR: `Desenvolvi`, `Liderei`), and **person-neutral** action verbs in English — never explicit subject pronouns. See the base system prompt's *Language & consistency* and *Voice* sections.

## Output constraint

Emit **only** the single JSON object required by the base system instructions—no markdown fences, no separate sections for gap analysis, interview prep, or cover letter. Fold strategic choices into `summary`, `headline`, `highlights`, `skills`, and project descriptions.

## Final check before you output (do this every time)

Re-read your JSON and verify, in order:

1. **One language only.** EVERY reader-visible field is in the target locale — including each experience `title` and each education `degree`. If any `title` or `degree` is still in the profile's source language, **translate it now** (e.g. pt-BR: `Full Stack Developer` → `Desenvolvedor Full Stack`, `Associate Degree, Systems Analysis and Development` → `Tecnólogo em Análise e Desenvolvimento de Sistemas`). Only `company`, `institution`, product/brand and technology names keep their original form. A `title`/`degree` left in another language is a defect — fix it before returning.
2. **Correct person.** `highlights` use first-person singular in languages that inflect person (pt-BR: `Desenvolvi`, `Liderei`), person-neutral verbs in English; no explicit subject pronouns; no third person (`Liderou`).
3. **No split-gender titles.** No `(a)`, `/a`, `@`, `x`, or duplicated-gender variants in any `title`, `degree`, `headline`, or field — each reader-visible role is one natural grammatical form (pt-BR default: the unmarked market form, e.g. `Desenvolvedor Full Stack`). A `Desenvolvedor(a)`-style form is a defect — fix it before returning.
4. **No duplicated bullets** across different roles.
