"""Integration tests for linking a Source Document upload to its originating chat session
(v2 ticket 10 -- "Durabilidade do ProfileUpdatedCard"): POST /api/profile/documents accepts an
optional `sessionId` form field and, when it names a real chat session, persists a durable
assistant chat_message referencing the document (`meta: {"sourceDocumentId": ...}` -- the ONLY
thing persisted, never `status`, so there is no second, driftable source of truth). GET
/api/chat/sessions/{id} joins source_documents LIVE at read time to report each linked
message's CURRENT status/diffSummary/opsCount -- apply/reject never need to touch chat_messages.

Kept in its own file (same rationale as test_document_merge_endpoints.py's own docstring):
reduces collision risk in a working tree shared with parallel agents -- ticket 11 is
concurrently touching chat_service.py / domain/schemas.py / test_chat_endpoints.py.
"""

from __future__ import annotations

import io
import json

from pypdf import PdfWriter
from sqlmodel import Session

from app.repositories import chat_repo


def _blank_pdf_bytes() -> bytes:
    """A structurally valid PDF with a page but no text layer -- same helper as
    test_document_endpoints.py's, duplicated locally to keep this file collision-free."""
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


class TestUploadLinksToChatSession:
    async def test_upload_with_session_id_persists_a_linked_assistant_message(
        self, client, fake_llm, test_db_engine
    ):
        fake_llm.queue("[]")  # the merge step's Adjudication call (empty profile -> new data)
        created = (await client.post("/api/chat/sessions", json={})).json()

        resp = await client.post(
            "/api/profile/documents",
            data={"sessionId": str(created["id"])},
            files={"file": ("resume.json", VALID_JSON_BYTES, "application/json")},
        )

        assert resp.status_code == 202
        document_id = resp.json()["documentId"]

        with Session(test_db_engine) as session:
            _, messages = chat_repo.get_session_with_messages(session, created["id"])
            assistant_msgs = [m for m in messages if m.role == "assistant"]
            assert len(assistant_msgs) == 1
            meta = json.loads(assistant_msgs[0].meta)
            # Only the soft-ref id is persisted -- never a copy of status (single source of
            # truth lives in source_documents, joined live by GET /api/chat/sessions/{id}).
            assert meta == {"sourceDocumentId": document_id}
            assert assistant_msgs[0].intent == "profile_update"

    async def test_upload_without_session_id_persists_no_chat_message_and_still_succeeds(
        self, client, fake_llm
    ):
        fake_llm.queue("[]")
        created = (await client.post("/api/chat/sessions", json={})).json()

        resp = await client.post(
            "/api/profile/documents",
            files={"file": ("resume.json", VALID_JSON_BYTES, "application/json")},
        )

        assert resp.status_code == 202
        detail = (await client.get(f"/api/chat/sessions/{created['id']}")).json()
        assert detail["messages"] == []

    async def test_upload_with_an_unknown_session_id_still_succeeds(self, client, fake_llm):
        fake_llm.queue("[]")

        resp = await client.post(
            "/api/profile/documents",
            data={"sessionId": "999999"},
            files={"file": ("resume.json", VALID_JSON_BYTES, "application/json")},
        )

        # The upload itself never fails because of an unrelated/stale session id.
        assert resp.status_code == 202
        assert resp.json()["status"] == "proposed"

    async def test_upload_with_a_malformed_session_id_still_succeeds_with_no_linked_message(
        self, client, fake_llm
    ):
        """A malformed sessionId (not an int at all) must be treated the same as an
        unknown/missing one -- the upload is the primary flow, the session link is a
        best-effort side channel that must never veto it, let alone with FastAPI's own
        automatic 422 for a badly-typed Form field."""
        fake_llm.queue("[]")

        resp = await client.post(
            "/api/profile/documents",
            data={"sessionId": "not-a-number"},
            files={"file": ("resume.json", VALID_JSON_BYTES, "application/json")},
        )

        assert resp.status_code == 202
        assert resp.json()["status"] == "proposed"

    async def test_reuploading_the_same_bytes_from_a_new_session_still_links_a_message(
        self, client, fake_llm, test_db_engine
    ):
        """Dedup (same sha256) returns the EXISTING SourceDocument row without re-running
        ingestion/merge -- but a second session attaching the same file should still get its
        own durable link to that (shared) document."""
        fake_llm.queue("[]")
        first_session = (await client.post("/api/chat/sessions", json={})).json()
        await client.post(
            "/api/profile/documents",
            data={"sessionId": str(first_session["id"])},
            files={"file": ("resume.json", VALID_JSON_BYTES, "application/json")},
        )

        second_session = (await client.post("/api/chat/sessions", json={})).json()
        resp = await client.post(
            "/api/profile/documents",
            data={"sessionId": str(second_session["id"])},
            files={"file": ("resume-again.json", VALID_JSON_BYTES, "application/json")},
        )

        assert resp.status_code == 202
        with Session(test_db_engine) as session:
            _, messages = chat_repo.get_session_with_messages(session, second_session["id"])
            assistant_msgs = [m for m in messages if m.role == "assistant"]
            assert len(assistant_msgs) == 1
            assert json.loads(assistant_msgs[0].meta) == {"sourceDocumentId": resp.json()["documentId"]}


class TestGetChatSessionJoinsSourceDocumentLive:
    async def test_get_session_reports_the_documents_current_status(self, client, fake_llm):
        fake_llm.queue("[]")
        created = (await client.post("/api/chat/sessions", json={})).json()
        upload_resp = await client.post(
            "/api/profile/documents",
            data={"sessionId": str(created["id"])},
            files={"file": ("resume.json", VALID_JSON_BYTES, "application/json")},
        )
        document_id = upload_resp.json()["documentId"]

        detail = (await client.get(f"/api/chat/sessions/{created['id']}")).json()
        assistant_msg = next(m for m in detail["messages"] if m["role"] == "assistant")
        # Uploading into an empty profile means the Deterministic Diff finds everything "new"
        # (non-empty diffSummary), but the scripted "[]" Adjudication response produced no ops.
        assert assistant_msg["sourceDocument"] == {
            "documentId": document_id,
            "filename": "resume.json",
            "status": "proposed",
            "diffSummary": upload_resp.json()["diffSummary"],
            "opsCount": 0,
            "error": None,
        }
        assert assistant_msg["sourceDocument"]["diffSummary"]  # non-empty, sanity check

    async def test_get_session_reflects_apply_without_the_message_ever_being_touched(
        self, client, fake_llm, test_db_engine
    ):
        fake_llm.queue(
            json.dumps(
                [
                    {
                        "op": "add",
                        "path": "/skills/-",
                        "value": "Rust",
                        "reason": "new skill",
                        "confidence": 0.9,
                        "sourceExcerpt": "Rust",
                    }
                ]
            )
        )
        created = (await client.post("/api/chat/sessions", json={})).json()
        upload_resp = await client.post(
            "/api/profile/documents",
            data={"sessionId": str(created["id"])},
            files={"file": ("resume.json", VALID_JSON_BYTES, "application/json")},
        )
        document_id = upload_resp.json()["documentId"]

        apply_resp = await client.post(f"/api/profile/documents/{document_id}/apply", json={})
        assert apply_resp.status_code == 200

        detail = (await client.get(f"/api/chat/sessions/{created['id']}")).json()
        assistant_msg = next(m for m in detail["messages"] if m["role"] == "assistant")
        assert assistant_msg["sourceDocument"]["status"] == "applied"
        assert assistant_msg["sourceDocument"]["opsCount"] == 1

        # Single source of truth: the persisted meta never stored a status to begin with.
        with Session(test_db_engine) as session:
            _, messages = chat_repo.get_session_with_messages(session, created["id"])
            raw_meta = json.loads(next(m for m in messages if m.role == "assistant").meta)
            assert raw_meta == {"sourceDocumentId": document_id}

    async def test_get_session_reflects_reject(self, client, fake_llm):
        fake_llm.queue(
            json.dumps(
                [
                    {
                        "op": "add",
                        "path": "/skills/-",
                        "value": "Rust",
                        "reason": "new skill",
                        "confidence": 0.9,
                        "sourceExcerpt": "Rust",
                    }
                ]
            )
        )
        created = (await client.post("/api/chat/sessions", json={})).json()
        upload_resp = await client.post(
            "/api/profile/documents",
            data={"sessionId": str(created["id"])},
            files={"file": ("resume.json", VALID_JSON_BYTES, "application/json")},
        )
        document_id = upload_resp.json()["documentId"]

        await client.post(f"/api/profile/documents/{document_id}/reject")

        detail = (await client.get(f"/api/chat/sessions/{created['id']}")).json()
        assistant_msg = next(m for m in detail["messages"] if m["role"] == "assistant")
        assert assistant_msg["sourceDocument"]["status"] == "rejected"

    async def test_messages_unrelated_to_a_document_have_a_null_source_document(self, client):
        created = (await client.post("/api/chat/sessions", json={})).json()

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "hi there"},
        )
        assert resp.status_code == 200

        detail = (await client.get(f"/api/chat/sessions/{created['id']}")).json()
        assert len(detail["messages"]) == 2  # user + assistant
        assert all(m["sourceDocument"] is None for m in detail["messages"])

    async def test_a_failed_upload_from_a_session_reports_a_failed_source_document(
        self, client
    ):
        created = (await client.post("/api/chat/sessions", json={})).json()

        resp = await client.post(
            "/api/profile/documents",
            data={"sessionId": str(created["id"])},
            files={"file": ("scanned.pdf", _blank_pdf_bytes(), "application/pdf")},
        )
        assert resp.status_code == 202
        assert resp.json()["status"] == "failed"

        detail = (await client.get(f"/api/chat/sessions/{created['id']}")).json()
        assistant_msg = next(m for m in detail["messages"] if m["role"] == "assistant")
        assert assistant_msg["sourceDocument"]["status"] == "failed"
        assert assistant_msg["sourceDocument"]["error"]
