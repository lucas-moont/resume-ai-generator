"""Parses the conversation turn's LLM response shape -- ``{"reply": "<markdown>"}`` -- into the
reply string.

Mirrors ``proposal_json_parser``'s tolerance philosophy: it NEVER raises on garbage, and any
shape it cannot use (invalid JSON, a non-object top level, a missing/blank/non-string ``reply``)
collapses to ``None``. The caller treats ``None`` as "fall back to a canned, locale-aware reply"
-- never a crash, never an error frame.
"""

from __future__ import annotations

import json
import re


def _strip_code_fence(raw: str) -> str:
    raw = raw.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    return m.group(1).strip() if m else raw


def parse_converse_json(raw: str) -> str | None:
    try:
        data = json.loads(_strip_code_fence(raw))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    reply = data.get("reply")
    if not isinstance(reply, str):
        return None
    reply = reply.strip()
    return reply or None
