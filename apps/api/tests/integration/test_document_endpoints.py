"""Integration tests for POST/GET /api/profile/documents (v2 ticket 03 -- "Ingestao e
Source Documents"). Multipart bodies are sent via httpx's ``files=`` kwarg against the
ASGITransport-backed ``client`` fixture (tests/conftest.py); the LLM boundary is never called
for `.json` uploads (deterministic ingestion, docs/v2-living-profile.md item 2).
"""

from __future__ import annotations

import io
import json

from pypdf import PdfWriter

from app.services.ingestion import ingest_pdf as ingest_pdf_module


def _blank_pdf_bytes() -> bytes:
    """A structurally valid PDF with a page but no text layer -- the "scanned document"
    shape ``ingest_pdf`` must reject as PdfIngestionError, never crash on."""
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


VALID_JSON_BYTES = json.dumps(
    {
        "fullName": "Ana Costa",
        "headline": "Senior Backend Engineer",
        "summary": "A strong summary of experience.",
        "skills": ["Python", "FastAPI"],
    }
).encode("utf-8")


class TestUploadJsonDocument:
    async def test_valid_json_upload_returns_202_with_extracted_preview(self, client):
        resp = await client.post(
            "/api/profile/documents",
            files={"file": ("resume.json", VALID_JSON_BYTES, "application/json")},
        )

        assert resp.status_code == 202
        body = resp.json()
        assert isinstance(body["documentId"], int)
        assert body["status"] == "extracted"
        assert body["extractedPreview"]["fullName"] == "Ana Costa"
        assert body["extractedPreview"]["skills"] == ["Python", "FastAPI"]

    async def test_invalid_json_upload_returns_422_naming_the_fields(self, client):
        resp = await client.post(
            "/api/profile/documents",
            files={"file": ("broken.json", b"{}", "application/json")},
        )

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "fullName" in detail
        assert "headline" in detail
        assert "summary" in detail

    async def test_malformed_json_syntax_returns_422(self, client):
        resp = await client.post(
            "/api/profile/documents",
            files={"file": ("broken.json", b"{not json", "application/json")},
        )

        assert resp.status_code == 422

    async def test_unsupported_file_extension_is_rejected(self, client):
        resp = await client.post(
            "/api/profile/documents",
            files={"file": ("resume.txt", b"hello", "text/plain")},
        )

        assert resp.status_code == 415


class TestUploadMarkdownDocument:
    async def test_valid_markdown_upload_is_extracted_via_the_llm(self, client, fake_llm):
        fake_llm.queue(
            json.dumps(
                {
                    "fullName": "Bruno Reis",
                    "headline": "Data Engineer",
                    "summary": "Extracted from markdown.",
                }
            )
        )
        raw = b"""---
name: Bruno Reis
title: Data Engineer
---
## Experience
Some markdown body about data engineering.
"""

        resp = await client.post(
            "/api/profile/documents",
            files={"file": ("notes.md", raw, "text/markdown")},
        )

        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "extracted"
        assert body["extractedPreview"]["fullName"] == "Bruno Reis"
        assert fake_llm.call_count == 1

    async def test_llm_extraction_failure_is_a_failed_status_not_a_500(self, client, fake_llm):
        fake_llm.queue(ValueError("LLM backend unreachable"))

        resp = await client.post(
            "/api/profile/documents",
            files={"file": ("notes.md", b"# Just a body, no frontmatter", "text/markdown")},
        )

        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "failed"
        assert body["extractedPreview"] is None
        assert body["error"]  # actionable message, not empty

        listing = (await client.get("/api/profile/documents")).json()["documents"]
        assert listing[0]["status"] == "failed"


class TestUploadPdfDocument:
    async def test_pdf_with_no_extractable_text_is_a_failed_status_not_a_500(self, client):
        resp = await client.post(
            "/api/profile/documents",
            files={"file": ("scanned.pdf", _blank_pdf_bytes(), "application/pdf")},
        )

        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "failed"
        assert body["extractedPreview"] is None
        assert body["error"]  # actionable, per the acceptance criteria

    async def test_pdf_with_text_is_extracted_via_the_llm(self, client, fake_llm, monkeypatch):
        monkeypatch.setattr(
            ingest_pdf_module, "extract_pdf_plain_text", lambda path: "Diana Melo\nPrincipal Engineer"
        )
        fake_llm.queue(
            json.dumps({"fullName": "Diana Melo", "headline": "Principal Engineer", "summary": "S."})
        )

        resp = await client.post(
            "/api/profile/documents",
            files={"file": ("resume.pdf", _blank_pdf_bytes(), "application/pdf")},
        )

        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "extracted"
        assert body["extractedPreview"]["fullName"] == "Diana Melo"
        assert fake_llm.call_count == 1


class TestUploadSizeAndDedup:
    async def test_oversize_upload_is_rejected_with_413(self, client, monkeypatch):
        monkeypatch.setenv("MAX_UPLOAD_BYTES", "1024")  # clamped minimum -- see config.max_upload_bytes
        big_content = b"x" * 2000

        resp = await client.post(
            "/api/profile/documents",
            files={"file": ("big.json", big_content, "application/json")},
        )

        assert resp.status_code == 413

    async def test_oversize_upload_is_not_persisted(self, client, monkeypatch):
        monkeypatch.setenv("MAX_UPLOAD_BYTES", "1024")

        await client.post(
            "/api/profile/documents",
            files={"file": ("big.json", b"x" * 2000, "application/json")},
        )

        listing = (await client.get("/api/profile/documents")).json()["documents"]
        assert listing == []

    async def test_reuploading_the_same_bytes_does_not_duplicate(self, client):
        first = await client.post(
            "/api/profile/documents",
            files={"file": ("resume.json", VALID_JSON_BYTES, "application/json")},
        )
        second = await client.post(
            "/api/profile/documents",
            files={"file": ("resume-again.json", VALID_JSON_BYTES, "application/json")},
        )

        assert first.status_code == 202
        assert second.status_code == 202
        assert first.json()["documentId"] == second.json()["documentId"]
        assert second.json()["status"] == "extracted"

        listing = (await client.get("/api/profile/documents")).json()["documents"]
        assert len(listing) == 1  # the resend is a no-op, not a second row

    async def test_dedup_also_applies_across_md_and_pdf(self, client, fake_llm):
        fake_llm.queue(json.dumps({"fullName": "Once", "headline": "Only", "summary": "S."}))
        raw = b"# Body with no frontmatter, unique to this test"

        first = await client.post(
            "/api/profile/documents", files={"file": ("a.md", raw, "text/markdown")}
        )
        second = await client.post(
            "/api/profile/documents", files={"file": ("b.md", raw, "text/markdown")}
        )

        assert first.json()["documentId"] == second.json()["documentId"]
        assert fake_llm.call_count == 1  # the second upload never re-ran extraction


class TestListDocuments:
    async def test_list_is_empty_when_no_uploads_yet(self, client):
        resp = await client.get("/api/profile/documents")

        assert resp.status_code == 200
        assert resp.json()["documents"] == []

    async def test_list_returns_the_uploaded_document(self, client):
        await client.post(
            "/api/profile/documents",
            files={"file": ("resume.json", VALID_JSON_BYTES, "application/json")},
        )

        resp = await client.get("/api/profile/documents")

        assert resp.status_code == 200
        docs = resp.json()["documents"]
        assert len(docs) == 1
        assert docs[0]["filename"] == "resume.json"
        assert docs[0]["mediaType"] == "json"
        assert docs[0]["status"] == "extracted"
        assert "documentId" in docs[0]
        assert "createdAt" in docs[0]
