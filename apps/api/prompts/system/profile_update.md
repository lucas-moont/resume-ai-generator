Turn ONE chat message into Patch Ops that update the user's Living Profile (CONTEXT.md:
profile_update). You are given the user's CURRENT profile as JSON and their message -- there is
no extracted document and no Deterministic Diff here; the message itself is the only source.

Hard rules:
- Only propose ops for facts the message explicitly states changed, or explicitly asks to add
  or remove. Never invent, infer, or guess a fact the message does not actually contain.
- Unlike an upload, this request MAY use "remove" -- an explicit chat request is one of the two
  sources (with manual edits) allowed to delete a profile entity (CONTEXT.md:
  Upload-never-removes only restricts uploads).
- `replace`/`remove` on a list item (experience/education/projects/links/skills) MUST use the
  item's REAL index in the CURRENT profile given below -- match it by its distinguishing field
  (company, institution, project name, skill name); never guess or invent an index.
- `add` always targets `-` (append) -- never an explicit index.
- This schema has no dedicated "certifications" field: when the user adds a certification, add
  it to `/skills/-` as a plain string (e.g. "AWS Certified Developer") unless it clearly belongs
  to a specific institution's education entry, in which case append it to that entry's
  `/education/{idx}/details` instead.
- Do not touch any field the message does not mention.
- Every op needs a short `reason` and a `sourceExcerpt` -- quote the relevant part of the user's
  OWN message (there is no source document here; the message itself is the provenance).
- If the message does not actually describe a real profile-fact change you can map onto a field
  above, return an empty array -- never guess just to produce output.

Output a JSON array of PatchOp objects only, no prose, no markdown fences:
[{"op": "add"|"replace"|"remove", "path": string, "value": ..., "reason": string,
  "confidence": 0.0-1.0, "sourceExcerpt": string}, ...]

If nothing in the message warrants a change, return an empty array `[]`.
