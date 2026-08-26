"""POST /api/jobs/scans, GET /api/jobs/scans/current and GET /api/jobs/scans/latest (v7
ticket 09).

Real app, real SQLite, real Scan engine -- and never a real Job Board: ``build_registry`` (the
router's one seam onto the network-reaching adapters) is replaced for EVERY test here by an
autouse fixture, so a test that forgets to register a board gets an empty registry rather than
seven live boards. The single-flight lock is isolated the same way: each test gets its own
``ScanRunner``, since the production one is a module-level singleton by design and would
otherwise carry a held lock from one test into the next.

The 409 needs a Scan that stays running for the length of a second request, which no
``FakeJobBoard`` can do (it answers instantly) -- hence ``BlockingBoard`` below, a provider that
parks on an ``asyncio.Event`` the test releases when it is done asserting.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session

from app.domain.schemas import BoardQuery, BoardResult
from app.repositories import jobs_repo
from app.routers import jobs as jobs_router
from app.services.jobboards.provider_registry import BoardProviderRegistry, board_spec
from app.services.jobs import scan_service
from app.services.jobs.scan_service import ScanRunner


class BlockingBoard:
    """A Job Board that never answers until the test says so -- the only way to hold a Scan in
    its ``running`` state across another HTTP request."""

    def __init__(self, board_id: str = "indeed") -> None:
        spec = board_spec(board_id)
        self.id = spec.id
        self.display_name = spec.display_name
        self.min_interval_hours = spec.min_interval_hours
        self.release = asyncio.Event()
        self.calls = 0

    async def search(self, query: BoardQuery) -> BoardResult:
        self.calls += 1
        await self.release.wait()
        return BoardResult(items=[], status="ok")


@pytest.fixture(autouse=True)
def isolated_runner(monkeypatch) -> ScanRunner:
    """A fresh single-flight lock per test. ``scan_service.default_runner`` is process-wide on
    purpose (the HTTP handler and the scheduler must contend for the same lock), which makes it
    exactly the kind of state that must not leak between tests."""
    runner = ScanRunner()
    monkeypatch.setattr(scan_service, "default_runner", runner)
    return runner


@pytest.fixture(autouse=True)
def boards(monkeypatch) -> list:
    """The registry an Immediate Scan will use. Autouse and empty by default: no test in this
    file can reach a real board even by forgetting to configure one."""
    registered: list = []
    monkeypatch.setattr(jobs_router, "build_registry", lambda: BoardProviderRegistry(registered))
    return registered


@pytest.fixture(autouse=True)
async def _drain_scan_tasks():
    """Safety net: never leave a background Scan running into the next test."""
    yield
    tasks = list(jobs_router._scan_tasks)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def drain() -> None:
    """Wait for the background Scan the request under test started."""
    tasks = list(jobs_router._scan_tasks)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def save_profile(engine, **overrides) -> None:
    values = {
        "roles": ["Backend Engineer"],
        "locations": ["Brasil"],
        "remote": "any",
        "languages": ["pt", "en"],
        "boards": ["linkedin", "indeed"],
        "max_applicant_band": None,
        "interval_hours": None,
    }
    values.update(overrides)
    with Session(engine) as session:
        jobs_repo.put_search_profile(session, **values)
        session.commit()


def posting(url: str = "https://board.test/1", **overrides) -> dict:
    base = {
        "title": "Backend Engineer",
        "company": "Acme Tech",
        "url": url,
        "description": "We need Python and FastAPI experience for this backend role.",
        "date_posted": datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return base


class TestStartScan:
    async def test_it_answers_202_with_the_running_scan(
        self, client, test_db_engine, boards, make_fake_board
    ):
        """202, not 201: the boards have not been called yet. The body is the Scan itself so
        the UI can start polling it without a second round trip."""
        save_profile(test_db_engine, boards=["indeed"])
        board = make_fake_board("indeed")
        board.queue_ok(posting())
        boards.append(board)

        # ``{}`` because that is literally what the web client posts (``postInit({})``); the
        # endpoint declares no body and must not start caring about one.
        resp = await client.post("/api/jobs/scans", json={})

        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "running"
        assert body["trigger"] == "immediate"
        assert body["id"] > 0
        assert body["finishedAt"] is None
        assert body["nextScanAt"] is None

        await drain()

    async def test_the_scan_it_started_actually_runs(
        self, client, test_db_engine, boards, make_fake_board
    ):
        save_profile(test_db_engine, boards=["indeed"])
        board = make_fake_board("indeed")
        board.queue_ok(posting())
        boards.append(board)

        started = (await client.post("/api/jobs/scans")).json()
        await drain()

        latest = (await client.get("/api/jobs/scans/latest")).json()
        assert latest["id"] == started["id"]
        assert latest["status"] == "done"
        assert latest["finishedAt"] is not None
        assert latest["listingsFound"] == 1
        assert [b["board"] for b in latest["boards"]] == ["indeed"]
        assert board.call_count == 1

    async def test_a_blocked_board_is_reported_and_the_scan_still_finishes(
        self, client, test_db_engine, boards, make_fake_board
    ):
        """A Scan is partial, never failed (CONTEXT.md: Scan)."""
        save_profile(test_db_engine, boards=["linkedin", "indeed"])
        blocked = make_fake_board("linkedin")
        blocked.queue_blocked("LinkedIn recusou a busca (429).")
        ok = make_fake_board("indeed")
        ok.queue_ok(posting())
        boards.extend([blocked, ok])

        await client.post("/api/jobs/scans")
        await drain()

        latest = (await client.get("/api/jobs/scans/latest")).json()
        assert latest["status"] == "done"
        statuses = {b["board"]: b for b in latest["boards"]}
        assert statuses["linkedin"]["status"] == "blocked"
        assert statuses["linkedin"]["message"] == "LinkedIn recusou a busca (429)."
        assert statuses["indeed"]["status"] == "ok"
        assert statuses["indeed"]["count"] == 1

    async def test_with_no_search_profile_it_refuses_instead_of_scanning_on_defaults(
        self, client, boards, make_fake_board
    ):
        """Running seven boards on defaults the user never chose would be reaching the network
        on their behalf -- the same reason a GET does not persist those defaults."""
        board = make_fake_board("indeed")
        boards.append(board)

        resp = await client.post("/api/jobs/scans")

        assert resp.status_code == 422
        assert "Search Profile" in resp.json()["detail"]
        assert board.call_count == 0
        assert jobs_router._scan_tasks == set()

    async def test_a_scan_with_no_enabled_board_still_answers_with_its_scan(
        self, client, test_db_engine
    ):
        """Nothing in that Scan ever suspends, so it is already finished by the time the
        handler is resumed -- the response describes the Scan that ran, not a fiction."""
        save_profile(test_db_engine, boards=[])

        resp = await client.post("/api/jobs/scans")

        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "done"
        assert body["boards"] == []

    async def test_next_scan_at_is_the_interval_after_the_scan_finished(
        self, client, test_db_engine, boards, make_fake_board
    ):
        save_profile(test_db_engine, boards=["indeed"], interval_hours=6)
        board = make_fake_board("indeed")
        board.queue_ok(posting())
        boards.append(board)

        await client.post("/api/jobs/scans")
        await drain()

        latest = (await client.get("/api/jobs/scans/latest")).json()
        finished = datetime.fromisoformat(latest["finishedAt"])
        assert datetime.fromisoformat(latest["nextScanAt"]) - finished == timedelta(hours=6)

    async def test_scheduling_off_means_no_next_scan(
        self, client, test_db_engine, boards, make_fake_board
    ):
        save_profile(test_db_engine, boards=["indeed"], interval_hours=None)
        board = make_fake_board("indeed")
        board.queue_ok(posting())
        boards.append(board)

        await client.post("/api/jobs/scans")
        await drain()

        assert (await client.get("/api/jobs/scans/latest")).json()["nextScanAt"] is None


class TestSingleFlight:
    async def test_a_second_immediate_scan_is_refused_with_the_running_one(
        self, client, test_db_engine, boards
    ):
        """CONTEXT.md: at most one Scan runs at a time. The 409 carries the current Scan so the
        UI switches to polling it instead of showing an error nobody can act on."""
        save_profile(test_db_engine, boards=["indeed"])
        blocking = BlockingBoard("indeed")
        boards.append(blocking)

        first = await client.post("/api/jobs/scans")
        assert first.status_code == 202

        second = await client.post("/api/jobs/scans")

        assert second.status_code == 409
        detail = second.json()["detail"]
        assert detail["id"] == first.json()["id"]
        assert detail["status"] == "running"
        assert detail["trigger"] == "immediate"

        blocking.release.set()
        await drain()
        assert blocking.calls == 1

    async def test_the_lock_is_released_when_the_scan_ends(
        self, client, test_db_engine, boards, make_fake_board
    ):
        save_profile(test_db_engine, boards=["indeed"])
        first_board = make_fake_board("indeed")
        first_board.queue_ok(posting())
        boards.append(first_board)

        await client.post("/api/jobs/scans")
        await drain()

        # The board's own minimum interval has not elapsed, so the second Scan skips it -- what
        # matters here is that the request is accepted at all.
        second = await client.post("/api/jobs/scans")
        assert second.status_code == 202
        await drain()

    async def test_current_reports_the_running_scan_while_it_runs(
        self, client, test_db_engine, boards
    ):
        save_profile(test_db_engine, boards=["indeed"])
        blocking = BlockingBoard("indeed")
        boards.append(blocking)

        started = (await client.post("/api/jobs/scans")).json()
        current = await client.get("/api/jobs/scans/current")

        assert current.status_code == 200
        assert current.json()["id"] == started["id"]
        assert current.json()["status"] == "running"

        blocking.release.set()
        await drain()


class TestCurrentAndLatest:
    async def test_current_is_204_when_nothing_is_running(self, client):
        resp = await client.get("/api/jobs/scans/current")

        assert resp.status_code == 204
        assert resp.content == b""

    async def test_current_is_204_again_once_the_scan_finished(
        self, client, test_db_engine, boards, make_fake_board
    ):
        save_profile(test_db_engine, boards=["indeed"])
        board = make_fake_board("indeed")
        board.queue_ok(posting())
        boards.append(board)

        await client.post("/api/jobs/scans")
        await drain()

        assert (await client.get("/api/jobs/scans/current")).status_code == 204
        assert (await client.get("/api/jobs/scans/latest")).status_code == 200

    async def test_latest_is_204_on_a_fresh_install(self, client):
        """Nothing has ever scanned. 204 rather than 404: this is a normal state, not a
        missing resource."""
        resp = await client.get("/api/jobs/scans/latest")

        assert resp.status_code == 204
        assert resp.content == b""

    async def test_latest_is_the_running_scan_while_one_runs(
        self, client, test_db_engine, boards
    ):
        save_profile(test_db_engine, boards=["indeed"])
        blocking = BlockingBoard("indeed")
        boards.append(blocking)

        started = (await client.post("/api/jobs/scans")).json()

        latest = (await client.get("/api/jobs/scans/latest")).json()
        assert latest["id"] == started["id"]
        assert latest["status"] == "running"
        assert latest["nextScanAt"] is None

        blocking.release.set()
        await drain()
