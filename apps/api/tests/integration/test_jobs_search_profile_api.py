"""GET/PUT /api/jobs/search-profile, POST /api/jobs/search-profile/suggest, GET /api/jobs/boards
(v7 ticket 06).

Uses the shared ``client`` fixture (a fresh app per test with ``deps.get_session`` overridden
onto in-memory SQLite) and ``write_profile`` for the Profile the suggestion reads. Nothing here
touches an LLM, a job board or the developer's real ``data/`` directory -- conftest's autouse
fixtures already sandbox all three.
"""

from __future__ import annotations

import pytest

from app.services.jobboards.provider_registry import BOARD_SPECS, known_board_ids


def _valid_body(**overrides) -> dict:
    body = {
        "roles": ["Backend Engineer"],
        "locations": ["São Paulo"],
        "remote": "remote_only",
        "languages": ["pt"],
        "boards": ["linkedin", "indeed"],
        "maxApplicantBand": "<25",
        "intervalHours": 6,
    }
    body.update(overrides)
    return body


def _profile(**overrides) -> dict:
    profile = {
        "fullName": "Ada Lovelace",
        "headline": "Backend Engineer | Data Engineer",
        "summary": "",
        "skills": ["Python"],
        "locale": "pt-BR",
    }
    profile.update(overrides)
    return profile


class TestGetSearchProfile:
    async def test_a_fresh_install_gets_defaults_and_a_null_updated_at(self, client) -> None:
        resp = await client.get("/api/jobs/search-profile")

        assert resp.status_code == 200
        body = resp.json()
        assert body["roles"] == []
        assert body["locations"] == ["Brasil", "Remote"]
        assert body["languages"] == ["pt", "en"]
        assert body["remote"] == "any"
        assert body["boards"] == list(known_board_ids())
        assert body["maxApplicantBand"] is None
        assert body["intervalHours"] is None
        assert body["updatedAt"] is None

    async def test_reading_twice_still_reports_never_saved(self, client) -> None:
        """A GET must not persist the defaults it serves -- otherwise the second read would
        claim the user configured something."""
        await client.get("/api/jobs/search-profile")

        assert (await client.get("/api/jobs/search-profile")).json()["updatedAt"] is None


class TestPutSearchProfile:
    async def test_a_saved_profile_survives_the_request(self, client) -> None:
        put = await client.put("/api/jobs/search-profile", json=_valid_body())

        assert put.status_code == 200
        assert put.json()["updatedAt"] is not None

        body = (await client.get("/api/jobs/search-profile")).json()
        assert body["roles"] == ["Backend Engineer"]
        assert body["locations"] == ["São Paulo"]
        assert body["remote"] == "remote_only"
        assert body["languages"] == ["pt"]
        assert body["boards"] == ["linkedin", "indeed"]
        assert body["maxApplicantBand"] == "<25"
        assert body["intervalHours"] == 6

    async def test_the_response_is_what_a_later_get_returns(self, client) -> None:
        put = await client.put("/api/jobs/search-profile", json=_valid_body())
        get = await client.get("/api/jobs/search-profile")

        assert put.json() == get.json()

    async def test_unchecking_every_board_is_saved_as_such(self, client) -> None:
        await client.put("/api/jobs/search-profile", json=_valid_body())
        await client.put("/api/jobs/search-profile", json=_valid_body(boards=[]))

        assert (await client.get("/api/jobs/search-profile")).json()["boards"] == []

    async def test_qualquer_and_off_are_sent_as_null(self, client) -> None:
        resp = await client.put(
            "/api/jobs/search-profile",
            json=_valid_body(maxApplicantBand=None, intervalHours=None),
        )

        assert resp.status_code == 200
        assert resp.json()["maxApplicantBand"] is None
        assert resp.json()["intervalHours"] is None

    @pytest.mark.parametrize(
        "overrides",
        [
            {"boards": ["myspace"]},
            {"remote": "hybrid"},
            {"maxApplicantBand": "100+"},
            {"maxApplicantBand": "unknown"},
            {"intervalHours": 2},
            {"intervalHours": 0},
        ],
        ids=[
            "unknown board",
            "unknown remote preference",
            "100+ is not offerable as a cap",
            "unknown is not offerable as a cap",
            "an interval the UI never offers",
            "zero is not off -- null is",
        ],
    )
    async def test_invalid_values_are_422(self, client, overrides) -> None:
        resp = await client.put("/api/jobs/search-profile", json=_valid_body(**overrides))

        assert resp.status_code == 422

    async def test_an_invalid_put_leaves_the_previous_profile_intact(self, client) -> None:
        await client.put("/api/jobs/search-profile", json=_valid_body())

        rejected = await client.put(
            "/api/jobs/search-profile", json=_valid_body(boards=["myspace"], roles=["Wrong"])
        )

        assert rejected.status_code == 422
        assert (await client.get("/api/jobs/search-profile")).json()["roles"] == [
            "Backend Engineer"
        ]

    async def test_board_order_is_the_catalogs_not_the_requests(self, client) -> None:
        resp = await client.put(
            "/api/jobs/search-profile", json=_valid_body(boards=["remoteok", "linkedin"])
        )

        assert resp.json()["boards"] == ["linkedin", "remoteok"]


class TestSuggest:
    async def test_roles_come_from_the_headline_verbatim(self, client, write_profile) -> None:
        write_profile(_profile())

        resp = await client.post("/api/jobs/search-profile/suggest")

        assert resp.status_code == 200
        assert resp.json()["roles"] == ["Backend Engineer", "Data Engineer"]

    async def test_a_suggestion_is_marked_as_never_saved(self, client, write_profile) -> None:
        write_profile(_profile())

        resp = await client.post("/api/jobs/search-profile/suggest")

        assert resp.json()["updatedAt"] is None
        # and nothing was written: the GET still reports defaults
        assert (await client.get("/api/jobs/search-profile")).json()["roles"] == []

    async def test_a_profile_without_a_headline_suggests_no_roles(
        self, client, write_profile
    ) -> None:
        write_profile(_profile(headline=""))

        resp = await client.post("/api/jobs/search-profile/suggest")

        assert resp.status_code == 200
        assert resp.json()["roles"] == []
        assert resp.json()["locations"] == ["Brasil", "Remote"]

    async def test_no_profile_at_all_is_the_same_404_the_rest_of_the_app_gives(
        self, client
    ) -> None:
        resp = await client.post("/api/jobs/search-profile/suggest")

        assert resp.status_code == 404

    async def test_a_suggestion_can_be_saved_unchanged(self, client, write_profile) -> None:
        write_profile(_profile())
        suggested = (await client.post("/api/jobs/search-profile/suggest")).json()
        suggested.pop("updatedAt")

        resp = await client.put("/api/jobs/search-profile", json=suggested)

        assert resp.status_code == 200
        assert resp.json()["roles"] == ["Backend Engineer", "Data Engineer"]


class TestBoards:
    async def test_the_catalog_is_served_in_order_with_its_minimums(self, client) -> None:
        resp = await client.get("/api/jobs/boards")

        assert resp.status_code == 200
        boards = resp.json()["boards"]
        assert [b["id"] for b in boards] == list(known_board_ids())
        assert [b["displayName"] for b in boards] == [s.display_name for s in BOARD_SPECS]
        assert {b["id"]: b["minIntervalHours"] for b in boards}["remotive"] == 6

    async def test_the_boards_that_require_attribution_carry_the_note(self, client) -> None:
        by_id = {b["id"]: b for b in (await client.get("/api/jobs/boards")).json()["boards"]}

        assert by_id["remotive"]["attributionNote"]
        assert by_id["remoteok"]["attributionNote"]
        assert by_id["linkedin"]["attributionNote"] is None

    async def test_the_catalog_needs_no_saved_search_profile(self, client) -> None:
        """The form must be able to render its checkboxes before anything is configured."""
        assert (await client.get("/api/jobs/boards")).json()["boards"]
