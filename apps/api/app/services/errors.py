"""Centralized error-response construction so no error path can skip secret redaction.

Explicitly authorized fix (team-lead, B4): B3's report found that /api/generate/stream's
Profile.pdf-extraction error path never called ``redact_secrets``, unlike every other error
path in the app. Rather than remembering to call ``redact_secrets`` at each of the ~10 raise/
yield sites across the routers, ``http_error`` is the ONLY way routers construct an
``HTTPException`` with a message built from an underlying exception, and
``streaming.sse()`` redacts the ``message`` field of every ``"error"`` event on the way out
(see that module) -- so an un-redacted error is now a structural impossibility, not a
per-call-site discipline.
"""

from fastapi import HTTPException

from app.services.secret_redaction import redact_secrets


def http_error(status_code: int, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=redact_secrets(message))
