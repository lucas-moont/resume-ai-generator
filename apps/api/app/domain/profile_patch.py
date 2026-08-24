"""PatchOp + Patch Validator (v2 ticket 02 -- "Kernel de dominio do patch").

``PatchOp`` is the restricted JSON-Patch subset this app accepts (CONTEXT.md: Patch Op).
``apply_patch`` is the Patch Validator: the deterministic gate every proposed change crosses
before it can become a new Profile Version -- nothing else is allowed to write
``profile_versions.data`` (CONTEXT.md: Patch Validator). It enforces, in this order:

1. Path whitelist (nothing outside the ``ProfileMaster`` schema) -- enforced at ``PatchOp``
   construction time via pydantic, so an out-of-whitelist ``PatchOp`` cannot even be built.
2. Upload-never-removes: a patch whose ``source_kind`` is ``"upload"`` may never carry a
   ``remove`` op (CONTEXT.md: Upload-never-removes). Such ops are skipped, not fatal -- the
   rest of the patch still applies.
3. Per-op target existence: ``replace``/``remove`` must address an element that already exists
   (an existing index); ``add`` only supports ``-`` (append). An op that fails this is skipped,
   not fatal -- this is the deterministic proxy for "replace only lands on a target the
   Deterministic Diff already pointed at" (the validator has no notion of the diff itself; a diff
   only ever flags *existing* profile entries as divergent, so "target must already exist" is
   what that rule cashes out to at this layer).
4. Sanitization: the fully-mutated document is run through ``sanitize_resume_for_display`` --
   the same choke point ``parse_resume_json`` uses -- before final validation, so there is no
   second, unsanitized path into a Profile Version.
5. Schema validity: ``ProfileMaster.model_validate`` on the final document is mandatory. Unlike
   3, a failure here is fatal for the *whole* patch (wrapped as ``PatchValidationFailed``) --
   by the time we reach it, per-op structural issues have already been filtered into
   ``skipped``, so a failure here means the resulting document itself is not a valid Profile,
   which no partial application can paper over.

Deliberately out of scope for this module (left to its callers, e.g. the merge_service ticket
03/04 builds and the chat ``profile_update`` intent handler): building the actual list of
``PatchOp`` from an LLM adjudication response, and anything about *where* a patch came from
beyond the three ``source_kind`` values this module needs to enforce Upload-never-removes.
``githubUsername`` is intentionally excluded from the path whitelist -- it is populated by the
separate GitHub-linking flow, never by upload/chat/manual patches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.schemas import ProfileMaster
from app.services.html_sanitize import sanitize_resume_for_display

PatchOpKind = Literal["add", "replace", "remove"]
PatchSourceKind = Literal["upload", "chat", "manual"]

_SCALAR_FIELDS = ("fullName", "headline", "location", "email", "phone", "summary", "locale")
_ENTITY_LIST_FIELDS: dict[str, tuple[str, ...]] = {
    "experience": ("company", "title", "location", "start", "end"),
    "education": ("institution", "degree", "end", "details"),
    "projects": ("name", "description"),
    "links": ("label", "url"),
}
# The per-experience string lists a patch may address element-wise (``/experience/2/
# highlights/1``). ``keyTechnologies`` joins ``highlights`` here (v7) so a chat request or a
# manual edit can fix one technology on one role -- an upload still cannot remove any of them
# (Upload-never-removes is enforced by source_kind, above this list).
_EXPERIENCE_NESTED_LIST_FIELDS = ("highlights", "keyTechnologies")
_INDEX = r"(?:-|\d+)"


def _build_whitelist() -> list[re.Pattern[str]]:
    patterns = [re.compile(rf"^/{field}$") for field in _SCALAR_FIELDS]
    patterns.append(re.compile(rf"^/skills/{_INDEX}$"))
    for entity, fields in _ENTITY_LIST_FIELDS.items():
        patterns.append(re.compile(rf"^/{entity}/{_INDEX}$"))
        field_alt = "|".join(re.escape(f) for f in fields)
        patterns.append(re.compile(rf"^/{entity}/{_INDEX}/(?:{field_alt})$"))
    for nested in _EXPERIENCE_NESTED_LIST_FIELDS:
        patterns.append(re.compile(rf"^/experience/{_INDEX}/{nested}/{_INDEX}$"))
    return patterns


_PATH_WHITELIST = _build_whitelist()


def is_whitelisted_path(path: str) -> bool:
    return any(p.match(path) for p in _PATH_WHITELIST)


class PatchOp(BaseModel):
    """One restricted JSON-Patch operation proposing a single Profile change (CONTEXT.md:
    Patch Op). ``reason`` and ``sourceExcerpt`` are Provenance -- both mandatory, non-blank."""

    op: PatchOpKind
    path: str
    value: Any = None
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    sourceExcerpt: str

    @field_validator("path")
    @classmethod
    def _path_must_be_whitelisted(cls, v: str) -> str:
        if not is_whitelisted_path(v):
            raise ValueError(f"path not in whitelist: {v!r}")
        return v

    @field_validator("reason", "sourceExcerpt")
    @classmethod
    def _must_be_non_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be blank")
        return v

    @model_validator(mode="after")
    def _value_required_for_add_or_replace(self) -> "PatchOp":
        if self.op in ("add", "replace") and self.value is None:
            raise ValueError(f"op={self.op!r} requires a non-null value")
        return self


class PatchTargetError(Exception):
    """A whitelisted-but-unreachable target: out-of-bounds index, wrong container shape, or an
    unsupported ``remove``/``add`` combination. Caught internally by ``apply_patch`` and
    surfaced per-op as a ``SkippedOp`` -- never raised across the ``apply_patch`` boundary."""


class PatchValidationFailed(Exception):
    """The fully-mutated document failed ``ProfileMaster.model_validate``. Unlike a
    ``PatchTargetError`` (per-op, skippable), this is fatal for the whole patch: no Profile
    Version can be produced from a document that isn't a valid Profile."""

    def __init__(self, cause: Exception) -> None:
        super().__init__(str(cause))
        self.cause = cause


@dataclass(frozen=True)
class SkippedOp:
    op: PatchOp
    reason: str


@dataclass(frozen=True)
class PatchResult:
    profile: ProfileMaster
    applied: list[PatchOp]
    skipped: list[SkippedOp]


def _resolve_list(doc: dict, field: str) -> list:
    lst = doc.setdefault(field, [])
    if not isinstance(lst, list):
        raise PatchTargetError(f"{field} is not a list")
    return lst


def _apply_to_list(lst: list, idx_token: str, op: PatchOp, *, context: str) -> None:
    if idx_token == "-":
        if op.op != "add":
            raise PatchTargetError(f"'-' (append) is only valid for add, got {op.op!r}")
        lst.append(op.value)
        return
    idx = int(idx_token)
    if idx >= len(lst):
        raise PatchTargetError(
            f"{context}[{idx}] does not exist ({len(lst)} item(s)) -- "
            "replace/remove must target an existing entry"
        )
    if op.op == "remove":
        lst.pop(idx)
    elif op.op == "add":
        raise PatchTargetError("add only supports '-' (append), not an explicit index")
    else:
        lst[idx] = op.value


def _apply_one(doc: dict, op: PatchOp) -> None:
    segments = op.path.strip("/").split("/")
    field = segments[0]

    if len(segments) == 1 and field in _SCALAR_FIELDS:
        if op.op == "remove":
            doc[field] = None if field in ("location", "email", "phone") else ""
        else:
            doc[field] = op.value
        return

    if field == "skills":
        _apply_to_list(_resolve_list(doc, "skills"), segments[1], op, context="skills")
        return

    if field in _ENTITY_LIST_FIELDS:
        lst = _resolve_list(doc, field)
        rest = segments[1:]
        if len(rest) == 1:
            _apply_to_list(lst, rest[0], op, context=field)
            return
        idx_token = rest[0]
        if not idx_token.isdigit():
            raise PatchTargetError(f"invalid index: {idx_token!r}")
        idx = int(idx_token)
        if idx >= len(lst):
            raise PatchTargetError(f"{field}[{idx}] does not exist ({len(lst)} item(s))")
        if len(rest) == 3 and field == "experience" and rest[1] in _EXPERIENCE_NESTED_LIST_FIELDS:
            entry = lst[idx]
            nested_field = rest[1]
            nested = entry.setdefault(nested_field, [])
            _apply_to_list(nested, rest[2], op, context=f"experience[{idx}].{nested_field}")
            return
        if len(rest) == 2:
            subfield = rest[1]
            if op.op == "remove":
                raise PatchTargetError(
                    "remove is not supported on an entity sub-field; remove the whole entity by index"
                )
            lst[idx][subfield] = op.value
            return

    raise PatchTargetError(f"unsupported path shape: {op.path!r}")


def apply_patch(
    profile: ProfileMaster, ops: list[PatchOp], *, source_kind: PatchSourceKind
) -> PatchResult:
    """Apply ``ops`` on a COPY of ``profile``. See module docstring for the full gate order.
    Never mutates ``profile`` itself.
    """
    doc = profile.model_dump()
    applied: list[PatchOp] = []
    skipped: list[SkippedOp] = []

    for op in ops:
        if op.op == "remove" and source_kind == "upload":
            skipped.append(
                SkippedOp(op, "upload source cannot remove (Upload-never-removes)")
            )
            continue
        try:
            _apply_one(doc, op)
        except PatchTargetError as e:
            skipped.append(SkippedOp(op, str(e)))
            continue
        applied.append(op)

    sanitize_resume_for_display(doc)
    try:
        validated = ProfileMaster.model_validate(doc)
    except Exception as e:  # pydantic.ValidationError, not imported to keep this a thin wrap
        raise PatchValidationFailed(e) from e

    return PatchResult(profile=validated, applied=applied, skipped=skipped)
