"""JSON Source Document ingestion (v2 ticket 03, docs/v2-living-profile.md item 2).

Deliberately the only ingestor with NO LLM in its path: a `.json` upload is parsed and
validated directly against `ResumeDocument`, deterministically. A failure here means the file
itself is not usable data (bad syntax, wrong encoding, or missing required fields) -- the
router treats it as a request-validation problem (HTTP 422), not a Source Document lifecycle
failure, so callers never persist a row for a JSON upload that fails this function.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from app.domain.schemas import ResumeDocument


class JsonIngestionError(Exception):
    """Raised for any problem parsing or validating an uploaded `.json` Source Document.

    ``fields`` lists the offending ``ResumeDocument`` field paths (dotted) when the failure
    came from schema validation; empty for a syntax/encoding failure.
    """

    def __init__(self, message: str, *, fields: list[str] | None = None) -> None:
        super().__init__(message)
        self.fields = fields or []


def ingest_json(raw: bytes) -> ResumeDocument:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise JsonIngestionError(f"file is not valid UTF-8 text: {e}") from e

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise JsonIngestionError(f"invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise JsonIngestionError("invalid resume JSON: root must be an object")

    try:
        return ResumeDocument.model_validate(data)
    except ValidationError as e:
        fields = [".".join(str(p) for p in err["loc"]) for err in e.errors()]
        raise JsonIngestionError(
            f"invalid resume JSON: {'; '.join(fields)}", fields=fields
        ) from e
