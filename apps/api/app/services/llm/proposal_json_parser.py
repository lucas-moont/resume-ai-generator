"""Parses the two v4 LLM response shapes -- the Analysis's ``{message, items}`` and the
Proposal Turn's ``{action, reply, items?}`` (docs/v4-improvement-proposal.md §4) -- into
``ParsedProposal``/``ParsedProposalTurn``. Both entry points, ``parse_proposal_json`` and
``parse_proposal_turn_json``, mirror ``merge_service.parse_patch_ops_from_llm_response``'s
tolerance philosophy: they NEVER raise on garbage, and a malformed individual item is dropped
rather than failing the whole response (only when EVERY item in a required list is unusable does
the whole parse fail, returning ``None``). Callers (the future B3/B4 chat handlers) treat
``None`` as "fall back to a canned, locale-aware reply" -- never a crash, never an error frame,
per spec §2/§6.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from app.domain.schemas import ProposalItem

ProposalTurnAction = Literal["approve", "adjust", "question", "new_jd"]

_VALID_TURN_ACTIONS = frozenset({"approve", "adjust", "question", "new_jd"})


@dataclass(frozen=True)
class ParsedProposal:
    """What ``parse_proposal_json`` hands its caller: ``message`` is always non-blank (the
    caller never has to fall back on prose itself -- ``_fallback_message`` already did if the
    LLM's own ``message`` was missing/blank), and ``items`` is always non-empty (a response with
    zero surviving items is a parse failure, not an empty proposal -- see module docstring).

    ``title`` (v4.1-02) is the job title the LLM proposes for the chat session itself -- totally
    optional and NEVER the reason a parse fails: missing, blank, or non-string all collapse to
    ``None`` (unlike ``message``, there is no deterministic fallback to build one from -- the
    caller just leaves the session's existing title alone), and an oversized value is silently
    truncated rather than rejected."""

    message: str
    items: list[ProposalItem]
    title: str | None = None


@dataclass(frozen=True)
class ParsedProposalTurn:
    """What ``parse_proposal_turn_json`` hands its caller. ``items`` is populated (non-empty)
    when ``action == "adjust"`` -- guaranteed, since an ``adjust`` with no usable items is itself
    a parse failure (``None``) rather than an ``adjust`` with an empty plan. For every other
    action ``items`` is ``None`` (the LLM may still have sent some; they are ignored -- only
    ``adjust`` carries a revised plan, per spec §4.2)."""

    action: ProposalTurnAction
    reply: str
    items: list[ProposalItem] | None


def _strip_code_fence(raw: str) -> str:
    raw = raw.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    return m.group(1).strip() if m else raw


_VALID_OPS = frozenset({"rewrite", "add", "drop", "compress"})

_DROP_SECTIONS = frozenset({"skills", "projects"})


def _coerce_op_and_targets(raw_item: dict) -> dict:
    """Normalize the v6 ``op``/``targets`` fields BEFORE pydantic sees them.

    Both are new and optional, so the tolerance here is deliberately softer than the module's
    "drop the malformed item" rule: that rule protects required fields, and applying it to a
    brand-new optional one would throw away an otherwise perfect item over a single invented
    word (a model writing ``"op": "remove"`` loses its whole recommendation, prose included).
    Unknown/garbage values collapse to the ``rewrite`` default instead -- the fail-SAFE
    direction, since a rewrite subtracts nothing.

    The section limits are enforced here too, not just asked for in the prompt: a ``drop`` on
    ``experience``/``education`` is downgraded to ``compress``/``rewrite`` rather than trusted.
    The anchor ignores such an item anyway (it only ever prunes skills/projects), but leaving a
    section-illegal ``drop`` in the item would put "DROP (remove from the resume entirely):
    Savvi" in the generation prompt and in the user's approved plan -- an instruction to open a
    timeline gap that the Relevance Filter never intends to give.
    """
    item = dict(raw_item)
    raw_op = item.get("op")
    op = raw_op if isinstance(raw_op, str) and raw_op in _VALID_OPS else "rewrite"
    section = item.get("section")
    if op == "drop" and section not in _DROP_SECTIONS:
        op = "compress" if section == "experience" else "rewrite"
    if op == "compress" and section != "experience":
        op = "rewrite"
    item["op"] = op
    raw_targets = item.get("targets")
    if isinstance(raw_targets, str):
        raw_targets = [raw_targets]
    if not isinstance(raw_targets, list):
        raw_targets = []
    item["targets"] = [t.strip() for t in raw_targets if isinstance(t, str) and t.strip()]
    return item


def _parse_items(raw_items: list) -> list[ProposalItem]:
    """Parses each candidate item independently -- an out-of-whitelist ``section`` or a missing
    required field drops just that item (via ``ProposalItem``'s own pydantic validation),
    mirroring ``merge_service``'s per-op skip philosophy. ``id`` is always assigned here as the
    surviving item's 1-based position, ignoring whatever ``id`` the LLM sent -- this is what
    keeps the "1-based, stable within the proposal" invariant (schemas.py's ``ProposalItem``
    docstring) true even when earlier items in the raw list were discarded.

    v6: ``op``/``targets`` are normalized first (``_coerce_op_and_targets``) rather than left to
    that per-item validation -- see there for why a new optional field gets softer treatment than
    a required one."""
    items: list[ProposalItem] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        try:
            item = ProposalItem.model_validate(
                {**_coerce_op_and_targets(raw_item), "id": len(items) + 1}
            )
        except Exception:
            continue
        items.append(item)
    return items


def _fallback_message(items: list[ProposalItem]) -> str:
    """Deterministic prose built FROM the items themselves (spec §4.1) -- used only when the
    LLM's own ``message`` is missing/blank despite otherwise-valid items, so a proposal is never
    lost over a single empty string."""
    lines = [f"{i}. [{item.section}] {item.proposed}" for i, item in enumerate(items, start=1)]
    return "Proposed improvements:\n\n" + "\n".join(lines)


_TITLE_MAX_LENGTH = 120


def _parse_title(raw: object) -> str | None:
    """Tolerant by construction (module docstring): absent/blank/non-string all become
    ``None``, never a parse failure; an oversized title is truncated, never rejected."""
    if not isinstance(raw, str):
        return None
    title = raw.strip()
    if not title:
        return None
    return title[:_TITLE_MAX_LENGTH]


def parse_proposal_json(raw: str) -> ParsedProposal | None:
    try:
        data = json.loads(_strip_code_fence(raw))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        return None
    items = _parse_items(raw_items)
    if not items:
        return None
    message = data.get("message")
    message = message.strip() if isinstance(message, str) else ""
    if not message:
        message = _fallback_message(items)
    title = _parse_title(data.get("title"))
    return ParsedProposal(message=message, items=items, title=title)


def parse_proposal_turn_json(raw: str) -> ParsedProposalTurn | None:
    try:
        data = json.loads(_strip_code_fence(raw))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    action = data.get("action")
    if not isinstance(action, str) or action not in _VALID_TURN_ACTIONS:
        return None
    reply = data.get("reply")
    reply = reply.strip() if isinstance(reply, str) else ""
    items: list[ProposalItem] | None = None
    raw_items = data.get("items")
    if isinstance(raw_items, list):
        parsed_items = _parse_items(raw_items)
        items = parsed_items or None
    if action == "adjust" and not items:
        return None
    return ParsedProposalTurn(action=action, reply=reply, items=items)
