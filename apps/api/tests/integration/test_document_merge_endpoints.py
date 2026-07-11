"""Integration tests for the Incremental Merge pipeline's HTTP surface (v2 ticket 04 --
"Merge incremental + apply/reject + PATCH manual"): the extended ``POST /api/profile/documents``
response (``proposedPatch``/``diffSummary``), ``POST .../{id}/apply``, and
``POST .../{id}/reject``.

Uploads here land against a DB-seeded ACTIVE profile (``profile_repo.insert_version``) so the
Deterministic Diff has real data to compare against -- ``test_document_endpoints.py`` covers
uploads into an empty profile (bootstrapping). Kept in its own file (same rationale as ticket
03's ``test_source_document_repo.py``): reduces collision risk in a working tree shared with
parallel agents.
"""

from __future__ import annotations

import json

from sqlmodel import Session

from app.repositories import profile_repo
from tests.factories import make_profile, make_resume_payload


def _seed_active_profile(engine, **overrides) -> None:
    with Session(engine) as session:
        profile_repo.insert_version(
            session, data=json.dumps(make_profile(**overrides)), source_kind="seed_disk"
        )
        session.commit()


class TestUploadIdenticalToActiveProfile:
    async def test_empty_diff_produces_an_empty_proposal_with_no_llm_call(
        self, client, test_db_engine, fake_llm
    ):
        _seed_active_profile(test_db_engine)
        identical_bytes = json.dumps(make_resume_payload()).encode("utf-8")

        resp = await client.post(
            "/api/profile/documents",
            files={"file": ("resume.json", identical_bytes, "application/json")},
        )

        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "proposed"
        assert body["proposedPatch"] == []
        assert body["diffSummary"] == []
        assert fake_llm.call_count == 0

        # Nothing changed -- no new profile version was created either.
        versions = (await client.get("/api/profile/versions")).json()["versions"]
        assert len(versions) == 1


class TestUploadWithNewAndDivergentData:
    async def test_upload_proposes_only_the_new_skill(self, client, test_db_engine, fake_llm):
        _seed_active_profile(test_db_engine)
        upload_payload = make_resume_payload(skills=[*make_profile()["skills"], "Rust"])
        fake_llm.queue(
            json.dumps(
                [
                    {
                        "op": "add",
                        "path": "/skills/-",
                        "value": "Rust",
                        "reason": "New skill found in the uploaded document.",
                        "confidence": 0.9,
                        "sourceExcerpt": "Proficient in Rust.",
                    }
                ]
            )
        )

        resp = await client.post(
            "/api/profile/documents",
            files={"file": ("resume.json", json.dumps(upload_payload).encode(), "application/json")},
        )

        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "proposed"
        assert len(body["proposedPatch"]) == 1
        op = body["proposedPatch"][0]
        assert set(op.keys()) == {"op", "path", "value", "reason", "confidence", "sourceExcerpt"}
        assert op["path"] == "/skills/-"
        assert op["value"] == "Rust"
        assert body["diffSummary"] == ["1 new skill: Rust"]

        # The active profile is untouched until /apply is called.
        active = (await client.get("/api/profile")).json()
        assert "Rust" not in active["skills"]


class TestApplyProposedDocument:
    async def test_apply_creates_a_new_profile_version_with_provenance(
        self, client, test_db_engine, fake_llm
    ):
        _seed_active_profile(test_db_engine)
        upload_payload = make_resume_payload(skills=[*make_profile()["skills"], "Rust"])
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
        upload_resp = await client.post(
            "/api/profile/documents",
            files={"file": ("resume.json", json.dumps(upload_payload).encode(), "application/json")},
        )
        document_id = upload_resp.json()["documentId"]

        apply_resp = await client.post(f"/api/profile/documents/{document_id}/apply", json={})

        assert apply_resp.status_code == 200
        body = apply_resp.json()
        assert set(body.keys()) == {"profileVersion", "applied", "skipped"}
        assert body["applied"] == 1
        assert body["skipped"] == 0
        assert body["profileVersion"] == 2  # 1 = seed, 2 = this upload

        active = (await client.get("/api/profile")).json()
        assert "Rust" in active["skills"]
        # Only the divergent field changed -- everything else survives untouched.
        assert active["fullName"] == make_profile()["fullName"]
        assert active["summary"] == make_profile()["summary"]

        versions = (await client.get("/api/profile/versions")).json()["versions"]
        assert versions[0]["sourceKind"] == "upload"

        listing = (await client.get("/api/profile/documents")).json()["documents"]
        assert listing[0]["status"] == "applied"

    async def test_apply_subset_by_index(self, client, test_db_engine, fake_llm):
        _seed_active_profile(test_db_engine)
        upload_payload = make_resume_payload(
            skills=[*make_profile()["skills"], "Rust"],
            headline="Staff Backend Engineer",
        )
        fake_llm.queue(
            json.dumps(
                [
                    {
                        "op": "add",
                        "path": "/skills/-",
                        "value": "Rust",
                        "reason": "r1",
                        "confidence": 0.9,
                        "sourceExcerpt": "Rust",
                    },
                    {
                        "op": "replace",
                        "path": "/headline",
                        "value": "Staff Backend Engineer",
                        "reason": "r2",
                        "confidence": 0.9,
                        "sourceExcerpt": "Staff Backend Engineer",
                    },
                ]
            )
        )
        upload_resp = await client.post(
            "/api/profile/documents",
            files={"file": ("resume.json", json.dumps(upload_payload).encode(), "application/json")},
        )
        document_id = upload_resp.json()["documentId"]
        assert len(upload_resp.json()["proposedPatch"]) == 2

        apply_resp = await client.post(
            f"/api/profile/documents/{document_id}/apply", json={"ops": [0]}
        )

        body = apply_resp.json()
        assert body["applied"] == 1
        # The unselected op (index 1) counts as skipped -- applied + skipped == len(proposedPatch),
        # it never just silently disappears.
        assert body["skipped"] == 1
        active = (await client.get("/api/profile")).json()
        assert "Rust" in active["skills"]
        assert active["headline"] == make_profile()["headline"]  # NOT applied (index 1 excluded)


class TestRejectProposedDocument:
    async def test_reject_marks_rejected_and_profile_stays_untouched(
        self, client, test_db_engine, fake_llm
    ):
        _seed_active_profile(test_db_engine)
        upload_payload = make_resume_payload(skills=[*make_profile()["skills"], "Rust"])
        fake_llm.queue(
            json.dumps(
                [
                    {
                        "op": "add",
                        "path": "/skills/-",
                        "value": "Rust",
                        "reason": "r",
                        "confidence": 0.9,
                        "sourceExcerpt": "Rust",
                    }
                ]
            )
        )
        upload_resp = await client.post(
            "/api/profile/documents",
            files={"file": ("resume.json", json.dumps(upload_payload).encode(), "application/json")},
        )
        document_id = upload_resp.json()["documentId"]

        reject_resp = await client.post(f"/api/profile/documents/{document_id}/reject")

        assert reject_resp.status_code == 204
        assert reject_resp.content == b""

        active = (await client.get("/api/profile")).json()
        assert "Rust" not in active["skills"]

        listing = (await client.get("/api/profile/documents")).json()["documents"]
        assert listing[0]["status"] == "rejected"

        versions = (await client.get("/api/profile/versions")).json()["versions"]
        assert len(versions) == 1  # only the seed -- reject never appends a version


class TestApplyRejectEdgeCases:
    async def test_apply_missing_document_is_404(self, client):
        resp = await client.post("/api/profile/documents/999/apply", json={})
        assert resp.status_code == 404

    async def test_reject_missing_document_is_404(self, client):
        resp = await client.post("/api/profile/documents/999/reject")
        assert resp.status_code == 404

    async def test_apply_a_document_that_is_not_proposed_is_409(self, client, test_db_engine, fake_llm):
        _seed_active_profile(test_db_engine)
        fake_llm.queue("[]")
        payload = json.dumps(make_resume_payload()).encode()
        upload_resp = await client.post(
            "/api/profile/documents", files={"file": ("r.json", payload, "application/json")}
        )
        document_id = upload_resp.json()["documentId"]
        await client.post(f"/api/profile/documents/{document_id}/reject")

        resp = await client.post(f"/api/profile/documents/{document_id}/apply", json={})
        assert resp.status_code == 409

    async def test_reject_a_document_twice_is_409(self, client, test_db_engine, fake_llm):
        _seed_active_profile(test_db_engine)
        fake_llm.queue("[]")
        payload = json.dumps(make_resume_payload()).encode()
        upload_resp = await client.post(
            "/api/profile/documents", files={"file": ("r.json", payload, "application/json")}
        )
        document_id = upload_resp.json()["documentId"]
        await client.post(f"/api/profile/documents/{document_id}/reject")

        resp = await client.post(f"/api/profile/documents/{document_id}/reject")
        assert resp.status_code == 409


class TestAdjudicationContainmentIntegration:
    """CONTEXT.md: Adjudication -- "the LLM never touches what the Deterministic Diff didn't
    flag". A FakeLlm scripted to smuggle in an op the diff never raised must never see that op
    survive into ``proposedPatch`` -- exercised here end-to-end through the real upload
    endpoint (unit-level coverage lives in tests/unit/test_merge_service.py and
    tests/unit/test_profile_diff.py)."""

    async def test_hallucinated_op_outside_diff_scope_never_reaches_the_response(
        self, client, test_db_engine, fake_llm
    ):
        _seed_active_profile(test_db_engine)
        upload_payload = make_resume_payload(skills=[*make_profile()["skills"], "Rust"])
        fake_llm.queue(
            json.dumps(
                [
                    {
                        "op": "add",
                        "path": "/skills/-",
                        "value": "Rust",
                        "reason": "legit",
                        "confidence": 0.9,
                        "sourceExcerpt": "Rust",
                    },
                    {
                        "op": "replace",
                        "path": "/experience/0/title",
                        "value": "Fabricated Title",
                        "reason": "not in diff",
                        "confidence": 0.9,
                        "sourceExcerpt": "n/a",
                    },
                ]
            )
        )

        resp = await client.post(
            "/api/profile/documents",
            files={"file": ("resume.json", json.dumps(upload_payload).encode(), "application/json")},
        )

        body = resp.json()
        paths = [op["path"] for op in body["proposedPatch"]]
        assert "/skills/-" in paths
        assert "/experience/0/title" not in paths

    async def test_remove_op_from_an_upload_is_never_proposed(self, client, test_db_engine, fake_llm):
        _seed_active_profile(test_db_engine)
        upload_payload = make_resume_payload(headline="Staff Backend Engineer")
        fake_llm.queue(
            json.dumps(
                [
                    {
                        "op": "remove",
                        "path": "/experience/0",
                        "reason": "upload thinks this is stale",
                        "confidence": 0.9,
                        "sourceExcerpt": "n/a",
                    },
                    {
                        "op": "replace",
                        "path": "/headline",
                        "value": "Staff Backend Engineer",
                        "reason": "legit",
                        "confidence": 0.9,
                        "sourceExcerpt": "Staff Backend Engineer",
                    },
                ]
            )
        )

        resp = await client.post(
            "/api/profile/documents",
            files={"file": ("resume.json", json.dumps(upload_payload).encode(), "application/json")},
        )

        body = resp.json()
        assert all(op["op"] != "remove" for op in body["proposedPatch"])
        assert any(op["path"] == "/headline" for op in body["proposedPatch"])
