# Human voice (skill)

Write every reader-visible narrative field so it reads like a person wrote it, not a chatbot.
This is a **generation-time guard**: it shapes *how* you word the `summary`, `headline`,
experience `highlights`, project descriptions, and (in the analysis area) the suggested
LinkedIn copy — you are not rewriting external text, and you still output **only** the JSON /
schema the base prompt requires. Distilled from the [humanizer](https://github.com/blader/humanizer)
skill (MIT) and Wikipedia's "Signs of AI writing".

**Precedence:** the base system prompt always wins — schema, the HTML/formatting rules, the
one-language and voice rules, ATS keyword mirroring, and above all **truthfulness**. Never
invent, embellish, or soften a fact to make prose feel more human. When a job-description
keyword is genuinely the candidate's, use it even if it resembles an "avoid" word below.

## Avoid these AI tells

- **Inflated / sales language.** Cut empty grandeur: *stands as a testament to*, *a vital/pivotal role*, *renowned*, *cutting-edge*, *world-class*, *passionate about*, *results-driven professional* (as filler), *nestled*, *vibrant*, *seamless(ly)*, *robust*, *best-in-class*. Describe what the person did, not how important it was.
- **Stock AI words (especially stacked).** *delve, leverage, spearheaded, synergy, holistic, myriad, tapestry, showcase, underscore, foster, garner, intricate, elevate, unlock, empower, drive (figurative), landscape (abstract)*. Prefer a plain verb.
- **Longer phrase for a simple verb.** Prefer *is / has / led / built* over *serves as / boasts / functions as / is responsible for*.
- **"Not just X but Y"**, forced **groups of three**, and fake **"from X to Y"** ranges that aren't real ranges.
- **Filler and hedging.** *in order to* → *to*; *has the ability to* → *can*; drop *it is important to note that*. Don't stack qualifiers (*could potentially possibly*).
- **Generic positive endings / mission-speak.** No *poised to drive impact*, *committed to excellence*, *making a difference* as a send-off. End on a concrete fact.
- **Even, mid-length cadence.** Vary sentence length; one crisp sentence beats three padded ones. Concrete beats grand.

## Keep (do not "de-AI" these)

- Real technologies, tools, frameworks, and **real metrics** from the inputs — never strip a genuine number or a stack name because it looks polished.
- Standard role/industry terms and the exact job keywords the candidate truly has (ATS match outranks the avoid-list).
- Correct, plain phrasing. Dry ≠ AI; do not add personality, opinions, or first-person flourishes that the schema and voice rules don't allow.

## Before you output

Re-read each narrative field and ask: *does this sound like a recruiter/candidate wrote it, or like a model?* and *did I keep every fact exactly as the inputs give it?* Fix the wording, never the facts.
