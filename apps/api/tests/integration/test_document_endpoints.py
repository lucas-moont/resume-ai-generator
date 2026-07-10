"""Integration tests for POST/GET /api/profile/documents (v2 ticket 03 -- "Ingestao e
Source Documents"). Multipart bodies are sent via httpx's ``files=`` kwarg against the
ASGITransport-backed ``client`` fixture (tests/conftest.py); the LLM boundary is never called
for `.json` uploads (deterministic ingestion, docs/v2-living-profile.md item 2).
"""

from __future__ import annotations

import json

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
