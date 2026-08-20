"""Parses the v5 Analysis Turn LLM response -- either an Analysis
(``{type:"analysis", items, summary}``) or a Clarifying Question (``{type:"question", reply}``)
per docs/v5-profile-analysis.md -- into ``ParsedAnalysisResult``/``ParsedAnalysisQuestion``.

Mirrors ``proposal_json_parser``'s tolerance philosophy: NEVER raises on garbage; a malformed
individual item is dropped rather than failing the whole response; and only when nothing usable
survives (no items AND no reply) does the parse fail, returning ``None``. The caller (the b3
Analysis-Turn handler) treats ``None`` as "fall back to a canned, locale-aware reply" -- never a
crash, never an error frame.

The LLM's explicit ``type`` wins when present and valid. When it is missing or unrecognized we
infer: usable ``items`` -> analysis; else a non-blank ``reply`` -> question; else ``None``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.domain.schemas import AnalysisItem


@dataclass(frozen=True)
class ParsedAnalysisResult:
    """An Analysis outcome. ``items`` is always non-empty (a response with zero surviving items
    is a parse failure, not an empty analysis). ``summary`` is always non-blank -- the caller
    never has to invent prose: ``_fallback_summary`` already did if the LLM's own ``summary`` was
    missing/blank despite otherwise-valid items."""

    items: list[AnalysisItem]
    summary: str


@dataclass(frozen=True)
class ParsedAnalysisQuestion:
    """A Clarifying Question outcome (CONTEXT.md: Clarifying Question). ``reply`` is always
    non-blank -- a ``question`` with no reply is not a usable question."""

    reply: str


ParsedAnalysis = ParsedAnalysisResult | ParsedAnalysisQuestion


def _strip_code_fence(raw: str) -> str:
    raw = raw.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    return m.group(1).strip() if m else raw


def _parse_items(raw_items: list) -> list[AnalysisItem]:
    """Parses each candidate item independently -- an out-of-whitelist ``section``/``priority``
    or a missing required field drops just that item (via ``AnalysisItem``'s own pydantic
    validation), mirroring ``proposal_json_parser``'s per-item skip philosophy."""
    items: list[AnalysisItem] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        try:
            item = AnalysisItem.model_validate(raw_item)
        except Exception:
            continue
        items.append(item)
    return items


def _fallback_summary(items: list[AnalysisItem]) -> str:
    """Deterministic prose built FROM the items themselves -- used only when the LLM's own
    ``summary`` is missing/blank despite otherwise-valid items, so an analysis is never lost
    over a single empty string."""
    lines = [f"{i}. [{item.section}] {item.suggestion}" for i, item in enumerate(items, start=1)]
    return "Recommended changes:\n\n" + "\n".join(lines)


def parse_analysis_json(raw: str) -> ParsedAnalysis | None:
    try:
        data = json.loads(_strip_code_fence(raw))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    type_ = data.get("type")
    type_ = type_ if isinstance(type_, str) else None

    raw_items = data.get("items")
    items = _parse_items(raw_items) if isinstance(raw_items, list) else []

    reply = data.get("reply")
    reply = reply.strip() if isinstance(reply, str) else ""

    def _as_analysis() -> ParsedAnalysis | None:
        if not items:
            return None
        summary = data.get("summary")
        summary = summary.strip() if isinstance(summary, str) else ""
        return ParsedAnalysisResult(items=items, summary=summary or _fallback_summary(items))

    def _as_question() -> ParsedAnalysis | None:
        return ParsedAnalysisQuestion(reply=reply) if reply else None

    # Explicit, valid type wins -- even if the LLM contradicts itself (analysis with no items
    # -> None, so the caller falls back), so a stated intent is never silently reinterpreted.
    if type_ == "analysis":
        return _as_analysis()
    if type_ == "question":
        return _as_question()

    # Type missing/unrecognized: infer from what is usable.
    return _as_analysis() or _as_question()
