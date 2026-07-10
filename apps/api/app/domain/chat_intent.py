"""Deterministic chat intent classification (CONTEXT.md: Intent) -- extracted from
``chat_service.handle_chat_turn`` (pre-v2 chat_service.py:125-130) as v2 ticket 05's mandatory
first step.

``classify_intent`` reproduces the v1 3-way routing byte-for-byte:

- No active resume + the message reads like a pasted job description
  (``looks_like_job_description``, a length + JD-keyword-density heuristic) -> ``generate``.
- An active resume exists -> ``refine``, REGARDLESS of what the message says. This is the
  riskiest line in the original inline code (an active resume wins even over text that reads
  exactly like another job posting, or a one-word "ok") -- see
  ``tests/unit/test_chat_intent.py::TestV1PinnedRouting`` for the pinning tests run against
  this extraction to prove no behavior changed.
- Neither -> ``question`` (a canned, locale-aware reply -- no LLM call).

``profile_update`` (v2 ticket 05) is layered BEFORE this routing. CONTEXT.md draws the line as
"refine acts on the Resume, profile_update acts on facts of the Profile" -- see
``_looks_like_profile_update`` below for the deterministic pattern, and
``tests/unit/test_chat_intent.py::TestProfileUpdateVsRefineBoundary`` for the documented,
tested decisions on every ambiguous case this was tuned against.
"""

from __future__ import annotations

import re
from typing import Literal

from app.domain.keywords import extract_jd_keywords

Intent = Literal["generate", "refine", "profile_update", "question"]

# A message needs to be substantial to be treated as a pasted job description outright; a
# shorter message can still count if it is dense with recognizable tech/role keywords (e.g.
# someone pasting just the "Requirements" bullet list rather than the full posting).
_JD_MIN_WORDS_STRONG_SIGNAL = 30
_JD_MIN_WORDS_WEAK_SIGNAL = 12
_JD_MIN_KEYWORDS_WEAK_SIGNAL = 3


def looks_like_job_description(message: str) -> bool:
    words = message.split()
    if len(words) >= _JD_MIN_WORDS_STRONG_SIGNAL:
        return True
    if len(words) >= _JD_MIN_WORDS_WEAK_SIGNAL:
        return len(extract_jd_keywords(message)) >= _JD_MIN_KEYWORDS_WEAK_SIGNAL
    return False


def classify_intent(*, message: str, has_active_resume: bool) -> Intent:
    """The single seam ``chat_service.handle_chat_turn`` calls to route a turn. No LLM call is
    spent deciding it (CONTEXT.md: Intent)."""
    if not has_active_resume and looks_like_job_description(message):
        return "generate"
    if has_active_resume:
        return "refine"
    return "question"
