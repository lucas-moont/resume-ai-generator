"""GET /api/jobs/listings, GET /api/jobs/listings/{id} and PATCH .../status (v7 ticket 09).

Every test starts from a REAL Scan: three ``FakeJobBoard`` postings go through the actual engine
(dedup, Listing Sources, Visibility Score) and land in ``job_listings``, so what these endpoints
are asserted against is the data production writes rather than hand-built rows. No board is
real (the router's ``build_registry`` seam is replaced autouse) and no LLM is involved at all --
with no Profile saved, the Fit stage does not run and the ranking is recency plus crowding,
which is exactly what makes the expected order below deterministic.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session

from app.repositories import jobs_repo
from app.routers import jobs as jobs_router
from app.services.jobboards.provider_registry import BoardProviderRegistry
from app.services.jobs import scan_service
from app.services.jobs.scan_service import ScanRunner

NOW = datetime.now(timezone.utc)

# One posting per band/recency combination, chosen so the Visibility Score orders them
# unambiguously: fresh + uncrowded first, fresh + crowded second, stale + crowded last.
FRESH_UNCROWDED = {
    "title": "Senior Backend Engineer",
    "company": "Acme Cloud",
    "url": "https://linkedin.test/101",
    "description": "We are hiring a Senior Backend Engineer for Python, FastAPI and AWS work.",
    "date_posted": NOW - timedelta(hours=1),
    "applicant_band": "<10",
    "is_remote": True,
    "location": "Remote",
}
FRESH_CROWDED = {
    "title": "Engenheiro de Software Backend",
    "company": "Fintech BR",
    "url": "https://indeed.test/102",
    "description": "Vaga para pessoa engenheira de software backend com Python e Django.",
    "date_posted": NOW - timedelta(hours=12),
    "applicant_band": "<50",
    "location": "São Paulo, SP",
}
STALE_CROWDED = {
    "title": "PHP Developer",
    "company": "Legacy Systems",
    "url": "https://indeed.test/103",
    "description": "PHP developer wanted for a legacy platform: PHP 5.6, jQuery and MySQL.",
    "date_posted": NOW - timedelta(days=6),
    "applicant_band": "100+",
    "location": "Remote",
}


@pytest.fixture(autouse=True)
def isolated_runner(monkeypatch) -> ScanRunner:
    runner = ScanRunner()
    monkeypatch.setattr(scan_service, "default_runner", runner)
    return runner


@pytest.fixture(autouse=True)
def boards(monkeypatch) -> list:
    registered: list = []
    monkeypatch.setattr(jobs_router, "build_registry", lambda: BoardProviderRegistry(registered))
    return registered


@pytest.fixture(autouse=True)
async def _drain_scan_tasks():
    yield
    tasks = list(jobs_router._scan_tasks)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.fixture
async def scanned(client, test_db_engine, boards, make_fake_board):
    """A finished Scan with three listings, ranked. Returns the list endpoint's payload."""
    with Session(test_db_engine) as session:
        jobs_repo.put_search_profile(
            session,
            roles=["Backend Engineer"],
            locations=["Brasil"],
            remote="any",
            languages=["pt", "en"],
            boards=["linkedin", "indeed"],
            max_applicant_band=None,
            interval_hours=None,
        )
        session.commit()

    linkedin = make_fake_board("linkedin")
    linkedin.queue_ok(FRESH_UNCROWDED)
    indeed = make_fake_board("indeed")
    indeed.queue_ok(FRESH_CROWDED, STALE_CROWDED)
    boards.extend([linkedin, indeed])

    assert (await client.post("/api/jobs/scans")).status_code == 202
    tasks = list(jobs_router._scan_tasks)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    listings = (await client.get("/api/jobs/listings")).json()["listings"]
    assert len(listings) == 3, listings
    return listings


def by_title(listings: list[dict], title: str) -> dict:
    return next(item for item in listings if item["title"] == title)


class TestList:
    async def test_the_list_is_ranked_by_visibility_descending(self, scanned):
        """The ONE order this product has (CONTEXT.md: Visibility Score is the ranking key)."""
        assert [item["title"] for item in scanned] == [
            "Senior Backend Engineer",
            "Engenheiro de Software Backend",
            "PHP Developer",
        ]
        scores = [item["visibilityScore"] for item in scanned]
        assert scores == sorted(scores, reverse=True)

    async def test_the_list_omits_descriptions_and_keeps_the_word_count(self, scanned):
        for item in scanned:
            assert item["description"] is None
            assert item["descriptionWordCount"] > 0

    async def test_each_listing_carries_its_sources_and_wire_shape(self, scanned):
        top = scanned[0]
        assert top["company"] == "Acme Cloud"
        assert top["applicantBand"] == "<10"
        assert top["isRemote"] is True
        assert top["status"] == "new"
        assert top["hasOneClickResume"] is False
        assert top["fitEstimated"] is True  # no Profile saved, so nothing scored it
        assert [s["board"] for s in top["sources"]] == ["linkedin"]
        assert top["sources"][0]["url"] == "https://linkedin.test/101"

    async def test_before_the_first_scan_the_list_is_empty(self, client):
        resp = await client.get("/api/jobs/listings")

        assert resp.status_code == 200
        assert resp.json() == {"listings": []}


class TestFilters:
    async def test_board(self, client, scanned):
        resp = await client.get("/api/jobs/listings", params={"board": "linkedin"})

        assert [item["title"] for item in resp.json()["listings"]] == ["Senior Backend Engineer"]

    async def test_max_band_keeps_only_the_less_crowded(self, client, scanned):
        resp = await client.get("/api/jobs/listings", params={"max_band": "<25"})

        assert [item["applicantBand"] for item in resp.json()["listings"]] == ["<10"]

    async def test_status(self, client, scanned):
        target = by_title(scanned, "PHP Developer")["id"]
        await client.patch(f"/api/jobs/listings/{target}/status", json={"status": "applied"})

        applied = await client.get("/api/jobs/listings", params={"status": "applied"})
        assert [item["id"] for item in applied.json()["listings"]] == [target]

        still_new = await client.get("/api/jobs/listings", params={"status": "new"})
        assert target not in [item["id"] for item in still_new.json()["listings"]]

    async def test_dismissed_is_hidden_until_asked_for(self, client, scanned):
        target = by_title(scanned, "PHP Developer")["id"]
        await client.patch(f"/api/jobs/listings/{target}/status", json={"status": "dismissed"})

        default = await client.get("/api/jobs/listings")
        assert target not in [item["id"] for item in default.json()["listings"]]

        included = await client.get("/api/jobs/listings", params={"include_dismissed": "1"})
        assert target in [item["id"] for item in included.json()["listings"]]

    @pytest.mark.parametrize(
        "params",
        [
            {"board": "myspace"},
            {"status": "archived"},
            {"max_band": "100+"},
            {"max_band": "unknown"},
        ],
        ids=[
            "a board the catalog does not know",
            "a status outside the contract",
            "100+ is not offerable as a cap",
            "unknown is not offerable as a cap",
        ],
    )
    async def test_a_filter_outside_the_contract_is_422(self, client, scanned, params):
        """A confidently empty list would read as "no jobs match", which is a different and
        wrong answer -- the same 422 the Search Profile gives for the same mistake."""
        assert (await client.get("/api/jobs/listings", params=params)).status_code == 422


class TestDetail:
    async def test_the_detail_carries_the_description_and_every_source(self, client, scanned):
        target = scanned[0]["id"]

        resp = await client.get(f"/api/jobs/listings/{target}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == target
        assert body["description"].startswith("We are hiring a Senior Backend Engineer")
        assert body["sources"][0]["url"] == "https://linkedin.test/101"

    async def test_opening_a_listing_marks_it_seen(self, client, scanned):
        """CONTEXT.md: ``new -> seen``. Opening the detail IS the transition -- there is no
        separate "mark as read" the user has to remember."""
        target = scanned[0]["id"]
        assert scanned[0]["status"] == "new"

        assert (await client.get(f"/api/jobs/listings/{target}")).json()["status"] == "seen"

        listed = (await client.get("/api/jobs/listings")).json()["listings"]
        assert by_title(listed, "Senior Backend Engineer")["status"] == "seen"

    async def test_opening_an_applied_listing_does_not_undo_the_verdict(self, client, scanned):
        target = scanned[0]["id"]
        await client.patch(f"/api/jobs/listings/{target}/status", json={"status": "applied"})

        assert (await client.get(f"/api/jobs/listings/{target}")).json()["status"] == "applied"

    async def test_an_id_the_last_scan_does_not_have_is_404(self, client, scanned):
        """Listings are ephemeral -- an id from a previous Scan resolves to nothing rather than
        to a different job (see ``JobListing``'s AUTOINCREMENT note)."""
        resp = await client.get("/api/jobs/listings/999999")

        assert resp.status_code == 404
        assert "999999" in resp.json()["detail"]

    async def test_one_click_is_reported_from_the_listing_memory(
        self, client, scanned, test_db_engine
    ):
        target = by_title(scanned, "PHP Developer")
        with Session(test_db_engine) as session:
            key = jobs_repo.get_listing(session, target["id"]).identity_key
            jobs_repo.upsert_memory(session, key, resume_version_id=7)
            session.commit()

        body = (await client.get(f"/api/jobs/listings/{target['id']}")).json()
        assert body["hasOneClickResume"] is True


class TestPatchStatus:
    @pytest.mark.parametrize("status", ["seen", "applied", "dismissed"])
    async def test_it_returns_the_updated_listing(self, client, scanned, status):
        """Not 204: the card re-renders from the response alone."""
        target = scanned[0]["id"]

        resp = await client.patch(
            f"/api/jobs/listings/{target}/status", json={"status": status}
        )

        assert resp.status_code == 200
        assert resp.json()["id"] == target
        assert resp.json()["status"] == status

    async def test_new_is_not_settable(self, client, scanned):
        """A Scan writes ``new``; undoing a dismiss is ``seen``, not amnesia."""
        resp = await client.patch(
            f"/api/jobs/listings/{scanned[0]['id']}/status", json={"status": "new"}
        )

        assert resp.status_code == 422

    async def test_an_unknown_id_is_404(self, client, scanned):
        resp = await client.patch(
            "/api/jobs/listings/999999/status", json={"status": "applied"}
        )

        assert resp.status_code == 404

    async def test_the_verdict_is_written_to_the_listing_memory_by_identity(
        self, client, scanned, test_db_engine
    ):
        """The listing row is ephemeral, the verdict is not. Storing it by ``identity_key`` is
        what makes a dismissed job stay hidden when a LATER Scan finds it again -- that Scan
        then leaves it out of ``job_listings`` entirely (ticket 07), which is why
        ``include_dismissed=1`` only ever surfaces jobs dismissed AFTER the Scan that found
        them."""
        target = by_title(scanned, "Engenheiro de Software Backend")["id"]

        await client.patch(f"/api/jobs/listings/{target}/status", json={"status": "dismissed"})

        with Session(test_db_engine) as session:
            key = jobs_repo.get_listing(session, target).identity_key
            memory = jobs_repo.get_memory(session, key)
        assert memory is not None
        assert memory.status == "dismissed"
