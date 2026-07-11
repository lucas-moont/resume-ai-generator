"""Unit tests for JSON Source Document ingestion (v2 ticket 03).

Per docs/v2-living-profile.md item 2 and the ticket's acceptance criteria: JSON ingestion is
parse + ``ResumeDocument.model_validate`` directly, with NO LLM call involved -- pure,
deterministic, no I/O.
"""

from __future__ import annotations

import pytest

from app.domain.schemas import ResumeDocument
from app.services.ingestion.ingest_json import JsonIngestionError, ingest_json


class TestIngestJson:
    def test_valid_json_becomes_a_resume_document(self):
        raw = b'{"fullName": "Ana Costa", "headline": "Engineer", "summary": "A summary."}'

        result = ingest_json(raw)

        assert isinstance(result, ResumeDocument)
        assert result.fullName == "Ana Costa"
        assert result.headline == "Engineer"
        assert result.summary == "A summary."

    def test_malformed_json_syntax_raises_ingestion_error(self):
        raw = b"{not valid json"

        with pytest.raises(JsonIngestionError):
            ingest_json(raw)

    def test_non_utf8_bytes_raises_ingestion_error(self):
        raw = b"\xff\xfe\x00invalid"

        with pytest.raises(JsonIngestionError):
            ingest_json(raw)

    def test_json_root_must_be_an_object(self):
        raw = b"[1, 2, 3]"

        with pytest.raises(JsonIngestionError, match="object"):
            ingest_json(raw)

    def test_schema_validation_failure_names_the_offending_fields(self):
        # Missing every required field (fullName, headline, summary).
        raw = b"{}"

        with pytest.raises(JsonIngestionError) as exc_info:
            ingest_json(raw)

        error = exc_info.value
        assert "fullName" in str(error)
        assert "headline" in str(error)
        assert "summary" in str(error)
        assert set(error.fields) == {"fullName", "headline", "summary"}
