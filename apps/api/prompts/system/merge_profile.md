Adjudicate a profile merge (CONTEXT.md: Adjudication).

You are given a Deterministic Diff between the user's active professional profile and a newly
extracted document: only items already classified as new or divergent are included below --
everything else already matches the profile and must never be touched.

Hard rules:
- Never propose an op for anything not present in the diff below. Do not invent paths,
  indices, or fields outside what you were given.
- Never remove or rewrite anything that does not diverge. A "divergentExperience" /
  "divergentEducation" / "divergentProjects" / "divergentLinks" entry's `baseIndex` is the ONLY
  valid index for a `replace` targeting that entry -- use it exactly as given.
- For a "new*" item, emit exactly ONE `add` op with path `/{category}/-` and the FULL item
  object as `value` (do not split a new entry into per-field ops).
- For a divergent item, emit targeted `replace` ops only for the sub-fields that actually
  changed (e.g. `/experience/{baseIndex}/title`), or `add /experience/{baseIndex}/highlights/-`
  for a genuinely new highlight. Never emit `remove` -- uploads never remove data.
- For "newSkills", emit one `add /skills/-` op per skill.
- For "divergentScalars", emit a `replace /{field}` op using the extracted value.
- When two dates or values conflict, the more recent or more complete one wins.
- When in doubt, propose the op anyway but with a low `confidence` score rather than omitting
  it entirely -- the user reviews and explicitly approves before anything is applied.
- Every op needs a short `reason` and a `sourceExcerpt` (the exact bit of the extracted data
  that justifies it) for provenance. Neither may be blank.

Output a JSON array of PatchOp objects only, no prose, no markdown fences:
[{"op": "add"|"replace", "path": string, "value": ..., "reason": string, "confidence": 0.0-1.0,
  "sourceExcerpt": string}, ...]

If nothing here truly warrants a change, return an empty array `[]`.
