"""Integration tests for the v2 ticket 01 profile endpoints (docs/v2-living-profile.md item
5, "Perfil vivo como fonte de leitura"): GET /api/profile now reads the DB's active version
first, falling back to disk only when profile_versions is empty (compat with the v1 disk-only
behavior, characterized here since test_generate_endpoints_compat.py never covered
/api/profile at all). GET /api/profile/versions[/{n}] expose the version history, and
POST /api/profile/revert appends a new version instead of rewriting history.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlmodel import Session

from app.repositories import profile_repo
from app.services import profile_resolution as profile_resolution_module
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


class TestGithubReposProfileErrors:
    """Herdado da revisao do ticket 01 (ticket 04): GET /api/github/repos now goes through the
    same ``resolve_active_profile_or_error`` helper as GET /api/profile (both routes share the
    extracted try/except -- see routers/deps.py, moved there in ticket 04's router split since
    it is now shared across routers/profile.py and routers/github.py). The v1-era migration
    (ticket 01) already changed an invalid on-disk profile from an unhandled 500 to a handled
    400 here, but no test pinned it until now."""

    async def test_invalid_disk_profile_and_empty_db_is_400(self, client, isolated_data_env):
        (isolated_data_env / "resume.json").write_text("not valid json", encoding="utf-8")

        resp = await client.get("/api/github/repos")

        assert resp.status_code == 400

    async def test_missing_disk_profile_and_empty_db_is_404(self, client, isolated_data_env):
        resp = await client.get("/api/github/repos")

        assert resp.status_code == 404


class TestGetProfileWithCorruptedPdfAndActiveDbVersion:
    """Herdado da revisao do ticket 01 (ticket 04): a Profile.pdf present but unreadable is
    ALWAYS a hard error -- deliberately, even when the DB has an active version to serve (see
    profile_resolution.py's module docstring). This was only characterized at the module level
    (tests/unit/test_profile_resolution.py::TestResolveActiveProfilePdfErrors) -- this pins the
    same behavior through the real GET /api/profile endpoint."""

    async def test_broken_pdf_returns_400_even_with_an_active_db_version(
        self, client, test_db_engine, monkeypatch
    ):
        monkeypatch.setattr(
            profile_resolution_module,
            "load_profile_pdf_excerpt",
            lambda: ("", Path("/fake/Profile.pdf"), "could not decode PDF"),
        )
        with Session(test_db_engine) as session:
            profile_repo.insert_version(
                session, data=json.dumps(make_profile()), source_kind="seed_disk"
            )
            session.commit()

        resp = await client.get("/api/profile")

        assert resp.status_code == 400
        assert "could not decode PDF" in resp.json()["detail"]


class TestPatchProfileManualEdit:
    """v2 ticket 04: ``PATCH /api/profile {ops}`` is the manual/direct edit path -- same Patch
    Validator as upload/chat, ``source_kind="manual"`` (the one source_kind allowed to remove,
    per CONTEXT.md's Upload-never-removes)."""

    async def test_patch_creates_a_new_manual_version(self, client, test_db_engine):
        with Session(test_db_engine) as session:
            profile_repo.insert_version(session, data=json.dumps(make_profile()), source_kind="seed_disk")
            session.commit()

        resp = await client.patch(
            "/api/profile",
            json={
                "ops": [
                    {
                        "op": "replace",
                        "path": "/phone",
                        "value": "+55 11 90000-0000",
                        "reason": "user edited their phone number",
                        "confidence": 1.0,
                        "sourceExcerpt": "manual edit",
                    }
                ]
            },
        )

        assert resp.status_code == 200
        assert resp.json() == {"profileVersion": 2, "applied": 1, "skipped": 0}

        active = (await client.get("/api/profile")).json()
        assert active["phone"] == "+55 11 90000-0000"

        versions = (await client.get("/api/profile/versions")).json()["versions"]
        assert versions[0]["sourceKind"] == "manual"

    async def test_patch_allows_remove_unlike_upload(self, client, test_db_engine):
        with Session(test_db_engine) as session:
            profile_repo.insert_version(session, data=json.dumps(make_profile()), source_kind="seed_disk")
            session.commit()

        resp = await client.patch(
            "/api/profile",
            json={
                "ops": [
                    {
                        "op": "remove",
                        "path": "/experience/0",
                        "reason": "left the company",
                        "confidence": 1.0,
                        "sourceExcerpt": "manual edit",
                    }
                ]
            },
        )

        assert resp.status_code == 200
        assert resp.json()["applied"] == 1
        active = (await client.get("/api/profile")).json()
        assert active["experience"] == []

    async def test_patch_against_an_empty_profile_bootstraps_version_one(self, client, isolated_data_env):
        resp = await client.patch(
            "/api/profile",
            json={
                "ops": [
                    {
                        "op": "replace",
                        "path": "/fullName",
                        "value": "Someone New",
                        "reason": "first manual edit, no profile yet",
                        "confidence": 1.0,
                        "sourceExcerpt": "manual edit",
                    }
                ]
            },
        )

        assert resp.status_code == 200
        assert resp.json()["profileVersion"] == 1
        assert (await client.get("/api/profile")).json()["fullName"] == "Someone New"

    async def test_patch_applies_a_duplicate_looking_education_add_unlike_upload(
        self, client, test_db_engine
    ) -> None:
        """v4.1-04: the education dedup guard lives in ``merge_service.propose_merge`` (the
        upload/Adjudication pipeline) only -- ``PATCH /api/profile`` calls ``apply_patch``
        directly and never runs through it, so a manual add that looks like a duplicate
        (same institution + end year as the existing entry, just reworded) still applies. A
        manual edit is an explicit, already-reviewed user action, unlike an LLM adjudication."""
        with Session(test_db_engine) as session:
            profile_repo.insert_version(session, data=json.dumps(make_profile()), source_kind="seed_disk")
            session.commit()

        resp = await client.patch(
            "/api/profile",
            json={
                "ops": [
                    {
                        "op": "add",
                        "path": "/education/-",
                        "value": {
                            "institution": "Universidade de Sao Paulo",
                            "degree": "Bacharelado em Ciencia da Computacao",
                            "end": "2016",
                        },
                        "reason": "user manually re-added the same institution/year",
                        "confidence": 1.0,
                        "sourceExcerpt": "manual edit",
                    }
                ]
            },
        )

        assert resp.status_code == 200
        assert resp.json()["applied"] == 1

        active = (await client.get("/api/profile")).json()
        assert len(active["education"]) == 2

    async def test_patch_with_a_structurally_invalid_op_is_422(self, client, test_db_engine):
        with Session(test_db_engine) as session:
            profile_repo.insert_version(session, data=json.dumps(make_profile()), source_kind="seed_disk")
            session.commit()

        resp = await client.patch(
            "/api/profile",
            json={
                "ops": [
                    {
                        "op": "replace",
                        "path": "/summary",
                        "value": {"not": "a string"},
                        "reason": "bad value type",
                        "confidence": 1.0,
                        "sourceExcerpt": "n/a",
                    }
                ]
            },
        )

        assert resp.status_code == 422


class TestSetGithubUsername:
    """PUT /api/profile/github-username: the dedicated GitHub-linking write path --
    ``githubUsername`` is intentionally excluded from apply_patch's whitelist (see
    profile_patch.py's module docstring), so this bypasses it and inserts a new version
    directly, the same way ``revert_profile`` does."""

    async def test_sets_a_new_username_and_bumps_the_version(self, client, test_db_engine):
        with Session(test_db_engine) as session:
            profile_repo.insert_version(session, data=json.dumps(make_profile()), source_kind="seed_disk")
            session.commit()

        resp = await client.put("/api/profile/github-username", json={"githubUsername": "octocat"})

        assert resp.status_code == 200
        assert resp.json() == {"profileVersion": 2, "githubUsername": "octocat"}

        active = (await client.get("/api/profile")).json()
        assert active["githubUsername"] == "octocat"

    async def test_clearing_with_null_sets_it_to_none(self, client, test_db_engine):
        with Session(test_db_engine) as session:
            profile_repo.insert_version(
                session,
                data=json.dumps(make_profile(githubUsername="octocat")),
                source_kind="seed_disk",
            )
            session.commit()

        resp = await client.put("/api/profile/github-username", json={"githubUsername": None})

        assert resp.status_code == 200
        assert resp.json()["githubUsername"] is None

        active = (await client.get("/api/profile")).json()
        assert active["githubUsername"] is None

    async def test_clearing_with_empty_string_sets_it_to_none(self, client, test_db_engine):
        with Session(test_db_engine) as session:
            profile_repo.insert_version(
                session,
                data=json.dumps(make_profile(githubUsername="octocat")),
                source_kind="seed_disk",
            )
            session.commit()

        resp = await client.put("/api/profile/github-username", json={"githubUsername": "   "})

        assert resp.status_code == 200
        assert resp.json()["githubUsername"] is None

    async def test_strips_surrounding_whitespace(self, client, test_db_engine):
        with Session(test_db_engine) as session:
            profile_repo.insert_version(session, data=json.dumps(make_profile()), source_kind="seed_disk")
            session.commit()

        resp = await client.put("/api/profile/github-username", json={"githubUsername": "  octocat  "})

        assert resp.status_code == 200
        assert resp.json()["githubUsername"] == "octocat"

    async def test_with_no_active_profile_bootstraps_version_one(self, client, isolated_data_env):
        """Mirrors PATCH /api/profile's own behavior in this scenario
        (test_patch_against_an_empty_profile_bootstraps_version_one): resolve_profile_for_merge
        bootstraps a blank profile when nothing has ever been saved, it does not 400 --
        ProfileValidationError (-> 400) is reserved for a genuinely corrupted disk profile."""
        resp = await client.put("/api/profile/github-username", json={"githubUsername": "octocat"})

        assert resp.status_code == 200
        assert resp.json() == {"profileVersion": 1, "githubUsername": "octocat"}

    async def test_invalid_disk_profile_is_400(self, client, isolated_data_env):
        (isolated_data_env / "resume.json").write_text("not valid json", encoding="utf-8")

        resp = await client.put("/api/profile/github-username", json={"githubUsername": "octocat"})

        assert resp.status_code == 400
