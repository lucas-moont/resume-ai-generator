"""Merge service (v2 ticket 04 -- "Merge incremental + apply/reject + PATCH manual").

The Incremental Merge pipeline (CONTEXT.md: Incremental Merge), run synchronously within the
SAME request that produced an extracted Source Document (docs/v2-living-profile.md item 4),
in this exact order:

1. **Deterministic Diff** (``app.domain.profile_diff.deterministic_diff``) -- LLM-free,
   classifies the extracted candidate against the active profile into new/divergent/equal
   (equal discarded).
2. **Adjudication** -- an LLM call that turns ONLY the new+divergent items into ``PatchOp[]``
   (``prompts/system/merge_profile.md``). Skipped entirely when the diff is empty: an upload
   identical to the active profile costs zero LLM calls.
3. **Containment** (``app.domain.profile_diff.filter_ops_to_diff_scope``) -- drops any
   adjudicated op whose target the Diff never flagged. This closes a gap the Patch Validator's
   own whitelist/target-exists checks don't cover: those check "is this path shaped like a real
   Profile field" and "does this index exist", not "did THIS diff actually flag it".
4. **Education dedup guard** (``_drop_duplicate_education_credentials``, v4.1-04) -- drops any
   `add /education/-` op whose (institution, end) already matches an existing Profile entry:
   the SAME credential, even when Adjudication worded the degree as a translated/reworded
   variant of the existing one's. This is the deterministic net behind ``merge_profile.md``'s
   own instruction not to propose such an op in the first place. Only reachable from THIS
   pipeline (upload) -- the manual ``PATCH /api/profile`` path calls ``apply_patch`` directly
   and never runs through here.
5. **Patch Validator** (``app.domain.profile_patch.apply_patch``, ``source_kind="upload"``) --
   a DRY RUN against a copy of the profile. This is what ``proposedPatch`` in the upload
   response actually is: the already-vetted ``applied`` ops, never the raw LLM output. Nothing
   is persisted as a new Profile Version here -- that only happens when the user later calls
   ``POST .../apply`` (rejecting leaves the profile untouched).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from sqlmodel import Session

from app.config import PROMPTS_DIR
from app.domain.entity_identity import entity_key
from app.domain.profile_diff import DiffResult, deterministic_diff, filter_ops_to_diff_scope
from app.domain.profile_patch import PatchOp, apply_patch
from app.domain.schemas import ProfileMaster, ResumeDocument
from app.prompt_loader import load_merge_profile_system_prompt
from app.services import llm_client
from app.services.profile_resolution import resolve_active_profile

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MergeProposal:
    """What ``propose_merge`` hands its caller: ``ops`` is the Patch Validator's already-vetted
    ``applied`` list (never the raw LLM output -- see module docstring), and ``diff_summary``
    is the Deterministic Diff's own human-readable lines. Both are ``[]`` when the diff found
    nothing new or divergent."""

    ops: list[PatchOp]
    diff_summary: list[str]


def resolve_profile_for_merge(session: Session) -> ProfileMaster:
    """The base ``ProfileMaster`` a merge/patch operates against: the active DB/disk profile,
    or a blank one when neither exists yet (a user's very first upload, before any Profile
    Version has ever been created) -- the Deterministic Diff then classifies everything in the
    extracted candidate as new, with no special-casing needed downstream. A genuinely broken
    profile (invalid disk JSON, an unreadable Profile.pdf) is a real problem, not "nothing yet"
    -- ``ProfileValidationError`` propagates to the caller unchanged.
    """
    try:
        return resolve_active_profile(session).profile
    except FileNotFoundError:
        return ProfileMaster(fullName="", headline="", summary="", locale="pt-BR")


def _strip_code_fence(raw: str) -> str:
    raw = raw.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    return m.group(1).strip() if m else raw


def parse_patch_ops_from_llm_response(raw: str) -> list[PatchOp]:
    """Parses an LLM's raw response into ``PatchOp`` instances -- shared by every LLM call in
    this app that is asked to return ``PatchOp[]`` JSON (Adjudication here, and v2 ticket 05's
    chat ``profile_update`` turn in ``chat_service.py``, which reuses this function rather than
    duplicating the parsing). Each candidate op is validated independently --``PatchOp``'s own
    construction-time whitelist (path shape, non-blank reason/sourceExcerpt, required value)
    rejects a malformed or out-of-whitelist op WITHOUT losing the rest of an otherwise-good
    response, mirroring ``apply_patch``'s own per-op skip philosophy (see profile_patch.py's
    module docstring) rather than failing the whole response over one bad entry. Any response
    that isn't a JSON array (or ``{"ops": [...]}``) at all yields an empty list rather than
    raising -- callers treat "no usable ops" as a non-fatal, caller-specific outcome (the
    Source Document marked 'failed' here; a friendly chat reply with the profile left untouched
    in ticket 05), never a crash in this function."""
    try:
        data = json.loads(_strip_code_fence(raw))
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = data.get("ops", [])
    if not isinstance(data, list):
        return []
    ops: list[PatchOp] = []
    for raw_op in data:
        if not isinstance(raw_op, dict):
            continue
        try:
            ops.append(PatchOp.model_validate(raw_op))
        except Exception:
            continue
    return ops


def _render_entity(item: dict) -> dict:
    return {k: v for k, v in item.items() if v not in (None, "", [])}


def _build_adjudication_user_message(diff: DiffResult) -> str:
    payload = {
        "newExperience": [_render_entity(e) for e in diff.new_experience],
        "divergentExperience": [
            {"baseIndex": d.base_index, "current": _render_entity(d.base), "extracted": _render_entity(d.extracted)}
            for d in diff.divergent_experience
        ],
        "newEducation": [_render_entity(e) for e in diff.new_education],
        "divergentEducation": [
            {"baseIndex": d.base_index, "current": _render_entity(d.base), "extracted": _render_entity(d.extracted)}
            for d in diff.divergent_education
        ],
        "newProjects": [_render_entity(e) for e in diff.new_projects],
        "divergentProjects": [
            {"baseIndex": d.base_index, "current": _render_entity(d.base), "extracted": _render_entity(d.extracted)}
            for d in diff.divergent_projects
        ],
        "newLinks": [_render_entity(e) for e in diff.new_links],
        "divergentLinks": [
            {"baseIndex": d.base_index, "current": _render_entity(d.base), "extracted": _render_entity(d.extracted)}
            for d in diff.divergent_links
        ],
        "newSkills": diff.new_skills,
        "divergentScalars": [
            {"field": s.field, "current": s.current, "extracted": s.extracted} for s in diff.divergent_scalars
        ],
    }
    return (
        "Deterministic diff between the active profile and a newly extracted document "
        "(only new+divergent items are included -- everything else already matches and must "
        "not be touched):\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Return PatchOp[] JSON only."
    )


def _drop_duplicate_education_credentials(profile: ProfileMaster, ops: list[PatchOp]) -> list[PatchOp]:
    """The deterministic net for the real bug this guards against (v4.1-04): a Living Profile
    that ended up with the SAME credential twice because Adjudication proposed an `add` whose
    `degree` was merely a translated/reworded variant of an entry the profile already had (an
    EN "Associate Degree, Systems Analysis and Development" alongside a PT "Tecnologo em
    Analise e Desenvolvimento de Sistemas", same institution, same end year). ``degree`` is
    deliberately NOT part of the identity here -- it is exactly the field Adjudication may
    legitimately reword; ``institution`` (normalized via ``entity_key``, reused rather than
    reinvented) plus ``end`` is what makes two entries "the same credential" for this guard.
    Same institution with a DIFFERENT end year is kept: that is two legitimate credentials
    (e.g. a Bachelor's, then later a Master's). Runs only in this upload/Adjudication pipeline
    -- the manual ``PATCH /api/profile`` path calls ``apply_patch`` directly and never reaches
    this function, by design (a manual edit is an explicit, already-reviewed user action).
    """
    existing_index_by_key: dict[tuple[str, str], int] = {}
    for idx, entry in enumerate(profile.education):
        key = (entity_key(entry.institution), entity_key(entry.end))
        if key[0]:
            existing_index_by_key.setdefault(key, idx)

    kept: list[PatchOp] = []
    for op in ops:
        if op.op == "add" and op.path == "/education/-" and isinstance(op.value, dict):
            key = (entity_key(op.value.get("institution")), entity_key(op.value.get("end")))
            existing_idx = existing_index_by_key.get(key) if key[0] else None
            if existing_idx is not None:
                logger.warning(
                    "merge_service: dropped duplicate education add -- same institution and "
                    "end year as existing entry %d (value=%r)",
                    existing_idx,
                    op.value,
                )
                continue
        kept.append(op)
    return kept


async def adjudicate(diff: DiffResult, *, model: str | None = None) -> list[PatchOp]:
    system = load_merge_profile_system_prompt(PROMPTS_DIR)
    user = _build_adjudication_user_message(diff)
    raw = await llm_client.chat_json(system, user, model=model)
    return parse_patch_ops_from_llm_response(raw)


async def propose_merge(
    profile: ProfileMaster, extracted: ResumeDocument, *, model: str | None = None
) -> MergeProposal:
    """Runs the full Incremental Merge pipeline (module docstring) and returns the already-
    vetted proposal. ``source_kind`` is always ``"upload"`` here -- this pipeline only ever
    runs for a Source Document."""
    diff = deterministic_diff(profile, extracted)
    if diff.is_empty:
        return MergeProposal(ops=[], diff_summary=[])

    raw_ops = await adjudicate(diff, model=model)
    in_scope_ops = filter_ops_to_diff_scope(diff, raw_ops)
    deduped_ops = _drop_duplicate_education_credentials(profile, in_scope_ops)
    result = apply_patch(profile, deduped_ops, source_kind="upload")
    return MergeProposal(ops=result.applied, diff_summary=diff.summary())
