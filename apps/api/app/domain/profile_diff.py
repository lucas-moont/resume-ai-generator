"""Deterministic Diff (v2 ticket 04 -- "Merge incremental"), CONTEXT.md: Deterministic Diff.

Classifies a newly extracted document (``ResumeDocument``) against the active profile
(``ProfileMaster``) into **new** / **divergent** / **equal** (equal is discarded) -- LLM-free,
pure, no I/O. This is always the FIRST step of the Incremental Merge pipeline
(``app.services.ingestion.merge_service``); its output is exactly what the Adjudication LLM
step is allowed to see and act on (CONTEXT.md: Adjudication -- "the LLM never touches what the
Deterministic Diff didn't flag").

Identity/matching is delegated to ``app.domain.entity_identity`` throughout. Matchers there are
built ``matcher(base, candidates) -> list[dict | None]`` aligned with ``base``, claiming each
``candidates`` entry at most once -- the anchor (``resume_json_parser.py``) calls them as
``matcher(profile_entries, llm_patch_entries)`` (profile iterated, LLM patch claimed). This
module calls them the OTHER way around: ``matcher(extracted_entries, profile_entries)``
(extracted iterated, profile claimed) -- because here we ask "for each item in the newly
extracted document, is there a corresponding PROFILE entry" (so two extracted entries can never
both claim the same profile entry), not the anchor's "for each profile entry, is there patch
wording to adopt". Same functions, opposite direction, both valid uses of the same claim-once
algorithm.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from app.domain.entity_identity import (
    build_skill_lookup,
    entity_key,
    match_education_entries_for_diff,
    match_experience_entries,
    match_links_entries,
    match_projects_by_name,
    skill_token,
)
from app.domain.profile_patch import PatchOp
from app.domain.schemas import ProfileMaster, ResumeDocument

_SCALAR_FIELDS = ("fullName", "headline", "location", "email", "phone", "summary", "locale")
EntityCategory = Literal["experience", "education", "projects", "links"]


def _text(value: object) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class DivergentEntity:
    """A candidate (extracted) entity matched to an existing Profile entry that differs on at
    least one comparable field. ``base_index`` is the index into the ACTIVE profile's own list
    -- the only index Adjudication may target with a ``replace``/highlight-``add`` op."""

    category: EntityCategory
    base_index: int
    base: dict
    extracted: dict


@dataclass(frozen=True)
class DivergentScalar:
    field: str
    current: str
    extracted: str


@dataclass(frozen=True)
class DiffResult:
    new_experience: list[dict] = field(default_factory=list)
    divergent_experience: list[DivergentEntity] = field(default_factory=list)
    new_education: list[dict] = field(default_factory=list)
    divergent_education: list[DivergentEntity] = field(default_factory=list)
    new_projects: list[dict] = field(default_factory=list)
    divergent_projects: list[DivergentEntity] = field(default_factory=list)
    new_links: list[dict] = field(default_factory=list)
    divergent_links: list[DivergentEntity] = field(default_factory=list)
    new_skills: list[str] = field(default_factory=list)
    divergent_scalars: list[DivergentScalar] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """True when nothing new or divergent was found -- the Incremental Merge pipeline
        short-circuits here and never calls the Adjudication LLM (acceptance criterion: an
        upload identical to the active profile costs zero LLM calls)."""
        return not (
            self.new_experience
            or self.divergent_experience
            or self.new_education
            or self.divergent_education
            or self.new_projects
            or self.divergent_projects
            or self.new_links
            or self.divergent_links
            or self.new_skills
            or self.divergent_scalars
        )

    def summary(self) -> list[str]:
        """Human-readable ``diffSummary`` lines -- deterministic, never LLM-authored. Empty
        when the diff is empty (the frontend's ``ProfileUpdatedCard`` renders its own "nothing
        new" copy for an empty list; see apps/web's dto.ts/ProfileUpdatedCard.tsx)."""
        lines: list[str] = []
        for s in self.divergent_scalars:
            lines.append(f"Updated {s.field}")
        for e in self.new_experience:
            lines.append(f"New experience: {_text(e.get('company'))} — {_text(e.get('title'))}".strip(" —"))
        for d in self.divergent_experience:
            lines.append(f"Updated experience: {_text(d.base.get('company'))}")
        for e in self.new_education:
            lines.append(f"New education: {_text(e.get('institution'))} — {_text(e.get('degree'))}".strip(" —"))
        for d in self.divergent_education:
            lines.append(f"Updated education: {_text(d.base.get('institution'))}")
        for p in self.new_projects:
            lines.append(f"New project: {_text(p.get('name'))}")
        for d in self.divergent_projects:
            lines.append(f"Updated project: {_text(d.base.get('name'))}")
        for l in self.new_links:
            lines.append(f"New link: {_text(l.get('label')) or _text(l.get('url'))}")
        for d in self.divergent_links:
            lines.append(f"Updated link: {_text(d.base.get('label')) or _text(d.base.get('url'))}")
        if self.new_skills:
            n = len(self.new_skills)
            noun = "skill" if n == 1 else "skills"
            lines.append(f"{n} new {noun}: {', '.join(self.new_skills)}")
        return lines


def _entity_field_differs(base_value: object, cand_value: object) -> bool:
    """A field only counts as divergent when the CANDIDATE provides a non-blank value that
    differs from the base's -- a blank candidate field carries no signal (never treated as "the
    upload wants to clear this", which would violate Upload-never-removes in spirit even for a
    sub-field). Compared via ``entity_key`` (case/accent/punctuation-insensitive), not raw text:
    a cosmetic re-typing of the same value (e.g. "Sao Paulo" vs "São Paulo") must not generate a
    divergence -- and so a spurious Adjudication line item -- for an entry that is otherwise
    identical. A real content change (different words, a more complete date) still differs
    after normalization."""
    cand_key = entity_key(cand_value)
    if not cand_key:
        return False
    return cand_key != entity_key(base_value)


def _entity_differs(base: dict, cand: dict, fields: tuple[str, ...]) -> bool:
    return any(_entity_field_differs(base.get(f), cand.get(f)) for f in fields)


def _highlights_differ(base_highlights: object, cand_highlights: object) -> bool:
    cand_list = [h.strip() for h in (cand_highlights or []) if isinstance(h, str) and h.strip()]
    if not cand_list:
        return False
    base_set = {h.strip() for h in (base_highlights or []) if isinstance(h, str) and h.strip()}
    return set(cand_list) != base_set


def _match_projects(extracted_list: list[dict], profile_list: list[dict]) -> list[dict | None]:
    """Adapts ``match_projects_by_name`` (lookup-by-key, not claim-once -- see its own
    docstring) to the ``matcher(extracted, profile) -> aligned-with-extracted`` shape the other
    entity categories use here."""
    lookup = match_projects_by_name(profile_list)
    return [lookup.get(entity_key(c.get("name"))) if isinstance(c, dict) else None for c in extracted_list]


def _diff_entity_list(
    profile_list: list[dict],
    extracted_list: list[dict],
    *,
    category: EntityCategory,
    matcher: Callable[[list[dict], list[dict]], list[dict | None]],
    fields: tuple[str, ...],
    compare_highlights: bool = False,
) -> tuple[list[dict], list[DivergentEntity]]:
    matched = matcher(extracted_list, profile_list)
    id_to_index = {id(item): i for i, item in enumerate(profile_list)}

    new_items: list[dict] = []
    divergent: list[DivergentEntity] = []
    for i, cand in enumerate(extracted_list):
        if not isinstance(cand, dict):
            continue
        match = matched[i]
        if match is None:
            new_items.append(cand)
            continue
        base_index = id_to_index[id(match)]
        differs = _entity_differs(match, cand, fields)
        if compare_highlights:
            differs = differs or _highlights_differ(match.get("highlights"), cand.get("highlights"))
        if differs:
            divergent.append(DivergentEntity(category=category, base_index=base_index, base=match, extracted=cand))
    return new_items, divergent


def deterministic_diff(profile: ProfileMaster, extracted: ResumeDocument) -> DiffResult:
    """Classifies ``extracted`` against ``profile``: new / divergent / equal (equal discarded).
    Pure -- no LLM, no I/O; safe to call for every upload regardless of format."""
    profile_doc = profile.model_dump()
    extracted_doc = extracted.model_dump()

    divergent_scalars: list[DivergentScalar] = []
    for f in _SCALAR_FIELDS:
        current = _text(profile_doc.get(f))
        cand = _text(extracted_doc.get(f))
        if cand and cand != current:
            divergent_scalars.append(DivergentScalar(field=f, current=current, extracted=cand))

    base_skill_lookup = build_skill_lookup(profile_doc.get("skills") or [])
    new_skills: list[str] = []
    seen_tokens: set[str] = set()
    for s in extracted_doc.get("skills") or []:
        if not isinstance(s, str) or not s.strip():
            continue
        tok = skill_token(s)
        if tok and tok not in base_skill_lookup and tok not in seen_tokens:
            new_skills.append(s.strip())
            seen_tokens.add(tok)

    new_experience, divergent_experience = _diff_entity_list(
        profile_doc.get("experience") or [],
        extracted_doc.get("experience") or [],
        category="experience",
        matcher=match_experience_entries,
        fields=("company", "title", "location", "start", "end"),
        compare_highlights=True,
    )
    new_education, divergent_education = _diff_entity_list(
        profile_doc.get("education") or [],
        extracted_doc.get("education") or [],
        category="education",
        matcher=match_education_entries_for_diff,
        fields=("institution", "degree", "end", "details"),
    )
    new_projects, divergent_projects = _diff_entity_list(
        profile_doc.get("projects") or [],
        extracted_doc.get("projects") or [],
        category="projects",
        matcher=_match_projects,
        fields=("name", "description"),
    )
    new_links, divergent_links = _diff_entity_list(
        profile_doc.get("links") or [],
        extracted_doc.get("links") or [],
        category="links",
        matcher=match_links_entries,
        # "url" is deliberately excluded: it is already the identity/match key (via
        # ``link_key``, scheme/www/trailing-slash-insensitive), so a scheme or trailing-slash
        # difference alone is not meaningful enough to warrant its own Adjudication line item.
        fields=("label",),
    )

    return DiffResult(
        new_experience=new_experience,
        divergent_experience=divergent_experience,
        new_education=new_education,
        divergent_education=divergent_education,
        new_projects=new_projects,
        divergent_projects=divergent_projects,
        new_links=new_links,
        divergent_links=divergent_links,
        new_skills=new_skills,
        divergent_scalars=divergent_scalars,
    )


def _diff_scope(
    diff: DiffResult,
) -> tuple[frozenset[str], dict[str, frozenset[int]], frozenset[str]]:
    add_categories: set[str] = set()
    if diff.new_experience:
        add_categories.add("experience")
    if diff.new_education:
        add_categories.add("education")
    if diff.new_projects:
        add_categories.add("projects")
    if diff.new_links:
        add_categories.add("links")
    if diff.new_skills:
        add_categories.add("skills")

    divergent_indices: dict[str, set[int]] = {
        "experience": set(),
        "education": set(),
        "projects": set(),
        "links": set(),
    }
    for d in diff.divergent_experience:
        divergent_indices["experience"].add(d.base_index)
    for d in diff.divergent_education:
        divergent_indices["education"].add(d.base_index)
    for d in diff.divergent_projects:
        divergent_indices["projects"].add(d.base_index)
    for d in diff.divergent_links:
        divergent_indices["links"].add(d.base_index)

    divergent_scalars = frozenset(s.field for s in diff.divergent_scalars)
    return frozenset(add_categories), {k: frozenset(v) for k, v in divergent_indices.items()}, divergent_scalars


def is_op_in_diff_scope(diff: DiffResult, op: PatchOp) -> bool:
    """The Adjudication containment gate (CONTEXT.md: Adjudication -- "the LLM never touches
    what the Deterministic Diff didn't flag"). ``PatchOp``'s own construction-time whitelist
    (``app.domain.profile_patch``) only knows the ``ProfileMaster`` schema SHAPE -- it happily
    accepts e.g. ``replace /experience/0/title`` regardless of whether THIS diff ever flagged
    experience[0] as divergent. This function is the second, diff-aware gate: an op passes only
    when its target is something the Deterministic Diff actually flagged as new or divergent.
    """
    add_categories, divergent_indices, divergent_scalars = _diff_scope(diff)
    segments = op.path.strip("/").split("/")
    field_name = segments[0]

    if field_name in _SCALAR_FIELDS:
        return field_name in divergent_scalars
    if field_name == "skills":
        return op.op == "add" and "skills" in add_categories
    if field_name in ("experience", "education", "projects", "links"):
        if len(segments) >= 2 and segments[1] == "-":
            return op.op == "add" and field_name in add_categories
        if len(segments) >= 2 and segments[1].isdigit():
            return int(segments[1]) in divergent_indices.get(field_name, frozenset())
    return False


def filter_ops_to_diff_scope(diff: DiffResult, ops: list[PatchOp]) -> list[PatchOp]:
    """Drops any adjudicated op the Deterministic Diff never flagged (see
    ``is_op_in_diff_scope``). Runs BEFORE the Patch Validator (``apply_patch``) in
    ``merge_service.propose_merge`` -- containment happens here; ``apply_patch`` still runs
    afterward as the single, final gate (Upload-never-removes, target-exists, schema
    validity)."""
    return [op for op in ops if is_op_in_diff_scope(diff, op)]
