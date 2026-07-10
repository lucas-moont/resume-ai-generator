"""Integration tests for the v2 ticket 01 profile endpoints (docs/v2-living-profile.md item
5, "Perfil vivo como fonte de leitura"): GET /api/profile now reads the DB's active version
first, falling back to disk only when profile_versions is empty (compat with the v1 disk-only
behavior, characterized here since test_generate_endpoints_compat.py never covered
/api/profile at all). GET /api/profile/versions[/{n}] expose the version history, and
POST /api/profile/revert appends a new version instead of rewriting history.
"""

from __future__ import annotations

import json

from sqlmodel import Session

from app.repositories import profile_repo
from tests.factories import make_profile


class TestGetProfileReadsDbFirst:
    async def test_empty_db_falls_back_to_disk(self, client, write_profile):
        write_profile(make_profile(fullName="Disk Person"))

        resp = await client.get("/api/profile")

        assert resp.status_code == 200
        assert resp.json()["fullName"] == "Disk Person"

    async def test_db_active_version_wins_over_disk(self, client, write_profile, test_db_engine):
        write_profile(make_profile(fullName="Disk Person"))
        with Session(test_db_engine) as session:
            profile_repo.insert_version(
                session, data=json.dumps(make_profile(fullName="DB Person")), source_kind="seed_disk"
            )
            session.commit()

        resp = await client.get("/api/profile")

        assert resp.status_code == 200
        assert resp.json()["fullName"] == "DB Person"

    async def test_missing_disk_profile_and_empty_db_is_404(self, client, isolated_data_env):
        resp = await client.get("/api/profile")
        assert resp.status_code == 404

    async def test_invalid_disk_profile_and_empty_db_is_400(self, client, isolated_data_env):
        (isolated_data_env / "resume.json").write_text("not valid json", encoding="utf-8")

        resp = await client.get("/api/profile")
        assert resp.status_code == 400


class TestProfileVersionsHistory:
    async def test_list_versions_is_empty_when_db_is_empty(self, client):
        resp = await client.get("/api/profile/versions")

        assert resp.status_code == 200
        assert resp.json()["versions"] == []

    async def test_list_versions_returns_the_expected_shape_newest_first(
        self, client, test_db_engine
    ):
        with Session(test_db_engine) as session:
            profile_repo.insert_version(
                session, data=json.dumps(make_profile()), source_kind="seed_disk", change_summary="seed from disk"
            )
            profile_repo.insert_version(
                session, data=json.dumps(make_profile()), source_kind="manual", change_summary="edited phone"
            )
            session.commit()

        resp = await client.get("/api/profile/versions")

        assert resp.status_code == 200
        versions = resp.json()["versions"]
        assert [v["version"] for v in versions] == [2, 1]
        assert versions[0]["sourceKind"] == "manual"
        assert versions[0]["changeSummary"] == "edited phone"
        assert "createdAt" in versions[0]
        assert set(versions[0].keys()) == {"version", "sourceKind", "changeSummary", "createdAt"}

    async def test_get_single_version_returns_its_data(self, client, test_db_engine):
        profile_v1 = make_profile(fullName="Version One")
        with Session(test_db_engine) as session:
            profile_repo.insert_version(session, data=json.dumps(profile_v1), source_kind="seed_disk")
            session.commit()

        resp = await client.get("/api/profile/versions/1")

        assert resp.status_code == 200
        body = resp.json()
        assert body["version"] == 1
        assert body["sourceKind"] == "seed_disk"
        assert body["data"]["fullName"] == "Version One"

    async def test_get_missing_version_is_404(self, client):
        resp = await client.get("/api/profile/versions/999")
        assert resp.status_code == 404


class TestRevertProfile:
    async def test_revert_appends_a_new_version_with_the_target_data(self, client, test_db_engine):
        with Session(test_db_engine) as session:
            profile_repo.insert_version(
                session, data=json.dumps(make_profile(fullName="Version One")), source_kind="seed_disk"
            )
            profile_repo.insert_version(
                session, data=json.dumps(make_profile(fullName="Version Two")), source_kind="manual"
            )
            session.commit()

        resp = await client.post("/api/profile/revert", json={"toVersion": 1})

        assert resp.status_code == 200
        body = resp.json()
        assert body["version"] == 3
        assert body["sourceKind"] == "revert"

        active = await client.get("/api/profile")
        assert active.json()["fullName"] == "Version One"

        history = (await client.get("/api/profile/versions")).json()["versions"]
        assert [v["version"] for v in history] == [3, 2, 1]  # history untouched, never rewritten

    async def test_revert_to_missing_version_is_404(self, client, test_db_engine):
        with Session(test_db_engine) as session:
            profile_repo.insert_version(session, data=json.dumps(make_profile()), source_kind="seed_disk")
            session.commit()

        resp = await client.post("/api/profile/revert", json={"toVersion": 999})

        assert resp.status_code == 404
