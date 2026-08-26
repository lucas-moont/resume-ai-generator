"""Parses stage 2 of the Fit Score -- the LLM's ``{"fit": 0-100}`` answer (v7 ticket 08).

The smallest parser in this package, and the same tolerance philosophy as
``proposal_json_parser`` / ``analysis_json_parser``: it NEVER raises, and unusable output is
``None`` rather than an exception. What differs is what the caller does with ``None``. The other
two fall back to a canned reply; here the fallback already exists and is a real number -- the
keyword pass's estimate (``fit_service``) -- so an unparseable answer costs the listing its
promotion from "estimated" to "scored" and nothing else. That is why this module is allowed to
be strict where they are lenient.

**Out of range is garbage, not something to clamp.** A model answering ``850`` did not scale its
answer differently, it misunderstood the question; clamping to 100 would silently promote that
misunderstanding into the top of the user's ranked list, which is the one place a wrong number
does real damage. ``None`` keeps the honest estimate instead.

**Booleans are not numbers**, even though ``bool`` is an ``int`` in Python: ``{"fit": true}``
reaching the ranking as a Fit Score of 1 would be a silent, absurd answer.
"""

from __future__ import annotations

import json
import re

# The key the prompt asks for, plus the two a model reaches for when it paraphrases the schema.
# Accepting them is free tolerance in the direction that cannot hurt: every one of them is
# unambiguously "the number I was asked for", and the range check below still guards the value.
_FIT_KEYS: tuple[str, ...] = ("fit", "fit_score", "fitScore", "score")

FIT_MIN = 0
FIT_MAX = 100


def _strip_code_fence(raw: str) -> str:
    raw = raw.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    return m.group(1).strip() if m else raw


def _as_fit(value: object) -> int | None:
    """One candidate value as a Fit Score, or ``None``.

    Accepts an int, a float (rounded -- ``82.4`` is a model being fussy, not a model failing),
    and a numeric string (``"82"``, ``"82%"``, ``" 82 "``), which is the single most common
    deviation from a JSON-only instruction. Rejects booleans, ``None``, and anything outside
    ``0..100``.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip().rstrip("%").strip()
        if not cleaned:
            return None
        try:
            value = float(cleaned)
        except ValueError:
            return None
    if not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):  # NaN / infinity
        return None
    fit = int(round(number))
    if fit < FIT_MIN or fit > FIT_MAX:
        return None
    return fit


def parse_fit_json(raw: str) -> int | None:
    """The LLM's Fit Score, or ``None`` when nothing usable came back.

    Tolerates a code fence and a bare number as the whole answer (a model that read "output only
    the number" more literally than the prompt intended still gave a usable answer). Anything
    else -- prose, a dict without a fit key, a value out of range -- is ``None``, and the caller
    keeps the keyword estimate.
    """
    if not isinstance(raw, str):
        return None
    text = _strip_code_fence(raw)
    if not text.strip():
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(data, dict):
        for key in _FIT_KEYS:
            if key in data:
                return _as_fit(data[key])
        return None
    # A bare ``82`` / ``"82"`` as the entire response.
    return _as_fit(data)
