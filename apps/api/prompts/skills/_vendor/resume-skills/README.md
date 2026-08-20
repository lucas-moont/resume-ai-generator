# Vendored: ResumeSkills (reference material)

Source: <https://github.com/Paramchoudhary/ResumeSkills> — MIT (see `LICENSE`).
Vendored on 2026-08-20 (upstream `skills/` layout, one `SKILL.md` per skill).

## Why these files are here

This is **reference material**, not a live prompt. Nothing in `_vendor/` is loaded or
composed into a system prompt automatically — `app/prompt_loader.py` names the files it
composes explicitly, and the leading `_` marks this tree as "keep out of composition".

The product only ever emits **one resume JSON** (the schema in `system/generate.md`). It
does not produce cover letters, LinkedIn profiles, interview prep, salary scripts, offer
comparisons, academic CVs, reference lists, portfolio case studies, cold emails, or filled
application forms. So most of the 22 upstream skills fall outside what the agent does.

The genuinely product-relevant craft was **distilled** — not copied verbatim — into the
product's own skill blocks, adapted to its hard constraints (JSON-only output, single
target locale, first-person voice for languages that inflect person, never fabricate):

| Distilled from (upstream) | Into (product prompt block) |
|---|---|
| `resume-tailor`, `job-description-analyzer` | `../tailored-resume-generator.md` |
| `resume-bullet-writer`, `resume-quantifier`, `resume-ats-optimizer`, `resume-section-builder`, `tech-resume-optimizer`, `executive-resume-writer`, `creative-portfolio-resume`, `career-changer-translator` | `../resume-craft.md` |

The remaining skills are kept here for provenance and possible future scope (e.g. if the
app ever grows a cover-letter or interview-prep feature).

## Do not

- Do not wire `_vendor/**` into `load_*_system_prompt()` verbatim: it would bloat every LLM
  call and push the model toward outputs the app does not emit, breaking the JSON contract.
- Do not edit these files to change agent behavior — edit the distilled blocks one level up.
