from __future__ import annotations

import os

from app.config import ANTHROPIC_API_KEY, GEMINI_API_KEY, GITHUB_TOKEN

# Credentials that must never surface in an error message, SSE event, or HTTP response body
# sent to the browser. Covered from two sources:
#   • live environment variables (picked up even if set after startup, and used by tests);
#   • values resolved by config at import time (which includes OS-keychain-sourced secrets).
_ENV_NAMES = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "GEMINI_API_KEY",
    "GITHUB_TOKEN",
)
_PLACEHOLDER = "«redacted»"
# Short values are skipped: a 3-4 char secret could match innocuous substrings and over-redact.
_MIN_SECRET_LEN = 8


def _secret_values() -> set[str]:
    values: set[str] = set()
    for name in _ENV_NAMES:
        raw = (os.getenv(name) or "").strip()
        if len(raw) >= _MIN_SECRET_LEN:
            values.add(raw)
    for resolved in (ANTHROPIC_API_KEY, GEMINI_API_KEY, GITHUB_TOKEN):
        cleaned = (resolved or "").strip()
        if len(cleaned) >= _MIN_SECRET_LEN:
            values.add(cleaned)
    return values


def redact_secrets(text: str) -> str:
    """Replace any configured secret value found in ``text`` with a placeholder.

    Value-based (not pattern-based): it scrubs the actual secrets in use, so it works for any
    provider and any exception shape without guessing key formats.
    """
    if not text:
        return text
    out = text
    for value in _secret_values():
        out = out.replace(value, _PLACEHOLDER)
    return out
