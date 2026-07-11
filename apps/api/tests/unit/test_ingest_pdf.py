"""Unit tests for PDF Source Document ingestion (v2 ticket 03).

``extract_pdf_plain_text`` (the pypdf-backed reader) is monkeypatched at the point
``ingest_pdf`` imports it, so these tests exercise the ingestion logic (empty-text detection,
truncation, LLM hookup) without needing real PDF bytes;
tests/integration/test_document_endpoints.py covers the real pypdf path end-to-end via the
upload endpoint (a real pypdf-generated blank-page PDF for the no-text/'failed' case).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.schemas import ResumeDocument
from app.services import llm_client as llm_client_module
from app.services.ingestion import ingest_pdf as ingest_pdf_module
from app.services.ingestion.ingest_pdf import PdfIngestionError, ingest_pdf
from tests.fakes import FakeLlm


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> FakeLlm:
    fake = FakeLlm()
    monkeypatch.setattr(llm_client_module, "chat_json", fake)
    return fake


class TestIngestPdf:
    async def test_extracts_a_resume_document_when_text_is_present(
        self, fake_llm: FakeLlm, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(
            ingest_pdf_module, "extract_pdf_plain_text", lambda path: "Ana Costa\nSenior Engineer"
        )
        fake_llm.queue(
            json.dumps({"fullName": "Ana Costa", "headline": "Senior Engineer", "summary": "S."})
        )

        result = await ingest_pdf(Path("irrelevant.pdf"))

        assert isinstance(result, ResumeDocument)
        assert result.fullName == "Ana Costa"
        assert fake_llm.call_count == 1

    async def test_empty_text_raises_pdf_ingestion_error(
        self, monkeypatch: pytest.MonkeyPatch, fake_llm: FakeLlm
    ):
        monkeypatch.setattr(ingest_pdf_module, "extract_pdf_plain_text", lambda path: "   ")

        with pytest.raises(PdfIngestionError):
            await ingest_pdf(Path("scanned.pdf"))
        assert fake_llm.call_count == 0  # never calls the LLM with an empty prompt

    async def test_a_broken_pdf_raises_pdf_ingestion_error_not_the_raw_exception(
        self, monkeypatch: pytest.MonkeyPatch, fake_llm: FakeLlm
    ):
        def _boom(path):
            raise ValueError("corrupt xref table")

        monkeypatch.setattr(ingest_pdf_module, "extract_pdf_plain_text", _boom)

        with pytest.raises(PdfIngestionError):
            await ingest_pdf(Path("corrupt.pdf"))

    async def test_long_text_is_truncated_before_reaching_the_llm(
        self, monkeypatch: pytest.MonkeyPatch, fake_llm: FakeLlm
    ):
        monkeypatch.setenv("PROFILE_PDF_MAX_CHARS", "1000")
        monkeypatch.setattr(ingest_pdf_module, "extract_pdf_plain_text", lambda path: "x" * 5000)
        fake_llm.queue(json.dumps({"fullName": "A", "headline": "B", "summary": "C"}))

        await ingest_pdf(Path("long.pdf"))

        user_prompt = fake_llm.calls[0]["user"]
        assert len(user_prompt) < 5000 + 500  # far shorter than the raw 5000-char text
