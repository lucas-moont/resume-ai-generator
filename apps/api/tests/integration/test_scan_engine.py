"""Integration tests for the Scan engine and its scheduler (v7 ticket 07).

Real SQLite (in memory), real repository, real transaction -- and never a real Job Board: every
provider here is a ``FakeJobBoard`` (or a purpose-built stub) handed to the engine through a
``BoardProviderRegistry``, which is exactly how production wires it too. No LLM is involved at
all; the Fit Score arrives in ticket 08.

The four acceptance criteria of the ticket are the four class groups below: partial Scan with a
blocked board, ``skipped`` by a board's own minimum interval, a second Scan that replaces the
list and reattaches the Listing Memory (including Repost), and the single-flight lock plus the
scheduler's lifecycle.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session

from app.db.tables import JobListing, JobScan, ListingMemory, ListingSource
from app.domain.listing_identity import identity_key
from app.domain.schemas import BoardQuery, BoardResult, RawPosting
from app.repositories import jobs_repo
from app.services.jobboards.provider_registry import BoardProviderRegistry
from app.services.jobs import scheduler as scheduler_module
from app.services.jobs.scan_service import ScanAlreadyRunning, ScanRunner, run_scan
from app.services.jobs.scheduler import ScanScheduler

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


def ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


def save_profile(engine, **overrides) -> None:
    """The Search Profile a Scan needs to have anything to search for."""
    values = {
        "roles": ["Backend Engineer"],
        "locations": ["Brasil", "Remote"],
        "remote": "any",
        "languages": ["pt", "en"],
        "boards": ["linkedin", "indeed", "remotive"],
        "max_applicant_band": None,
        "interval_hours": None,
    }
    values.update(overrides)
    with Session(engine) as session:
        jobs_repo.put_search_profile(session, **values)
        session.commit()


def job(title="Backend Engineer", company="Acme Tech", url="https://board.test/1", **kwargs):
    base = {
        "title": title,
        "company": company,
        "url": url,
        "description": "We need Python and FastAPI experience for this backend role.",
    }
    base.update(kwargs)
    return RawPosting(**base)


def read_listings(engine) -> list[JobListing]:
    with Session(engine) as session:
        return jobs_repo.list_listings(session)


def read_memory(engine, key: str) -> ListingMemory | None:
    with Session(engine) as session:
        row = jobs_repo.get_memory(session, key)
        if row is not None:
            session.expunge(row)
        return row


def read_sources(engine, listing_id: int) -> list[ListingSource]:
    with Session(engine) as session:
        return jobs_repo.get_listing_sources(session, listing_id)


async def scan(engine, registry, *, trigger="immediate", now=NOW, runner=None):
    """Always with a private ``ScanRunner``: the module-level one is process-wide, and two
    tests sharing a lock would couple them. ``clock`` is pinned to the same instant as ``now``
    so a Scan is fully deterministic -- ``finished_at`` included, which is what the next Scan's
    ``skipped`` decision reads."""
    return await run_scan(
        engine, registry, trigger, now=now, clock=lambda: now, runner=runner or ScanRunner()
    )


# --- Criterion 1: a partial Scan ---------------------------------------------------------------


class TestPartialScan:
    async def test_a_blocked_board_is_reported_and_the_others_results_stand(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine)
        registry = BoardProviderRegistry(
            [
                make_fake_board("linkedin").queue_ok(
                    job(title="Backend Engineer", url="https://linkedin.test/1")
                ),
                make_fake_board("indeed").queue_blocked("429 — tentamos no próximo Scan."),
                make_fake_board("remotive").queue_ok(
                    job(title="Platform Engineer", url="https://remotive.test/2")
                ),
            ]
        )

        outcome = await scan(test_db_engine, registry)

        assert outcome is not None
        assert outcome.board_statuses["linkedin"]["status"] == "ok"
        assert outcome.board_statuses["indeed"]["status"] == "blocked"
        assert outcome.board_statuses["indeed"]["message"] == "429 — tentamos no próximo Scan."
        assert outcome.board_statuses["remotive"]["status"] == "ok"
        titles = {listing.title for listing in read_listings(test_db_engine)}
        assert titles == {"Backend Engineer", "Platform Engineer"}
        assert outcome.listings_found == 2

    async def test_an_adapter_that_raises_only_fails_its_own_board(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine)
        registry = BoardProviderRegistry(
            [
                make_fake_board("linkedin").queue(RuntimeError("adapter bug")),
                make_fake_board("indeed").queue_ok(job(url="https://indeed.test/1")),
            ]
        )

        outcome = await scan(test_db_engine, registry)

        assert outcome.board_statuses["linkedin"]["status"] == "error"
        assert "RuntimeError" in outcome.board_statuses["linkedin"]["message"]
        assert outcome.board_statuses["indeed"]["status"] == "ok"
        assert len(read_listings(test_db_engine)) == 1

    async def test_the_scan_row_is_done_not_failed_even_when_every_board_broke(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine, boards=["linkedin", "indeed"])
        registry = BoardProviderRegistry(
            [
                make_fake_board("linkedin").queue_blocked("429"),
                make_fake_board("indeed").queue_error("timeout"),
            ]
        )

        outcome = await scan(test_db_engine, registry)

        with Session(test_db_engine) as session:
            row = jobs_repo.get_scan(session, outcome.scan_id)
            assert row.status == "done" and row.finished_at is not None

    async def test_a_total_refusal_does_not_wipe_the_previous_list(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine, boards=["linkedin"])
        good = BoardProviderRegistry([make_fake_board("linkedin").queue_ok(job())])
        await scan(test_db_engine, good, now=ago(5))
        assert len(read_listings(test_db_engine)) == 1

        blocked = BoardProviderRegistry([make_fake_board("linkedin").queue_blocked("429")])
        outcome = await scan(test_db_engine, blocked, now=NOW)

        # A rate limiter is evidence about LinkedIn, not about the job market -- truncating
        # the whole Job Monitor on it would delete the user's list because of a 429.
        assert outcome.listings_replaced is False
        assert len(read_listings(test_db_engine)) == 1

    async def test_a_blocked_board_that_still_returned_items_does_replace_the_list(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine, boards=["linkedin"])
        board = make_fake_board("linkedin")
        board.queue(
            BoardResult(items=[job(url="https://linkedin.test/9")], status="blocked", message="429")
        )
        outcome = await scan(test_db_engine, BoardProviderRegistry([board]))

        assert outcome.listings_replaced is True
        assert len(read_listings(test_db_engine)) == 1

    async def test_an_ok_board_with_nothing_new_does_empty_the_list(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine, boards=["linkedin"])
        await scan(
            test_db_engine,
            BoardProviderRegistry([make_fake_board("linkedin").queue_ok(job())]),
            now=ago(5),
        )
        outcome = await scan(
            test_db_engine,
            BoardProviderRegistry([make_fake_board("linkedin").queue_ok()]),
            now=NOW,
        )

        # "We looked and there is nothing" IS an answer about the market: the list is the last
        # Scan (CONTEXT.md), so the job that did not come back leaves on the spot.
        assert outcome.listings_replaced is True
        assert read_listings(test_db_engine) == []


# --- Criterion 2: skipped by the board's own minimum interval -----------------------------------


class TestBoardMinimumInterval:
    async def test_a_board_whose_minimum_has_not_elapsed_is_skipped_not_called(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine, boards=["linkedin", "remotive"])
        first = BoardProviderRegistry(
            [
                make_fake_board("linkedin").queue_ok(job(url="https://linkedin.test/1")),
                make_fake_board("remotive").queue_ok(job(url="https://remotive.test/1")),
            ]
        )
        await scan(test_db_engine, first, now=ago(2))

        linkedin = make_fake_board("linkedin").queue_ok(job(url="https://linkedin.test/1"))
        # Nothing queued: an unscripted call is an AssertionError, so this board being called
        # at all would fail the test loudly.
        remotive = make_fake_board("remotive")
        outcome = await scan(test_db_engine, BoardProviderRegistry([linkedin, remotive]), now=NOW)

        assert outcome.board_statuses["remotive"]["status"] == "skipped"
        assert outcome.board_statuses["linkedin"]["status"] == "ok"
        assert remotive.call_count == 0
        assert linkedin.call_count == 1
        assert "6h" in outcome.board_statuses["remotive"]["message"]

    async def test_the_board_is_called_again_once_its_minimum_has_elapsed(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine, boards=["remotive"])
        await scan(
            test_db_engine,
            BoardProviderRegistry([make_fake_board("remotive").queue_ok(job())]),
            now=ago(7),
        )

        remotive = make_fake_board("remotive").queue_ok(job())
        outcome = await scan(test_db_engine, BoardProviderRegistry([remotive]), now=NOW)

        assert outcome.board_statuses["remotive"]["status"] == "ok"
        assert remotive.call_count == 1

    async def test_a_board_that_only_ever_blocked_is_retried_on_the_next_scan(
        self, test_db_engine, make_fake_board
    ):
        # "X bloqueou; tentamos no próximo Scan" is the promise the BoardStatusBar makes: only
        # a SUCCESSFUL call arms the minimum interval.
        save_profile(test_db_engine, boards=["remotive"])
        await scan(
            test_db_engine,
            BoardProviderRegistry([make_fake_board("remotive").queue_blocked("429")]),
            now=ago(1),
        )

        remotive = make_fake_board("remotive").queue_ok(job())
        outcome = await scan(test_db_engine, BoardProviderRegistry([remotive]), now=NOW)

        assert outcome.board_statuses["remotive"]["status"] == "ok"
        assert remotive.call_count == 1

    async def test_a_board_with_no_adapter_is_silently_left_out(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine, boards=["linkedin", "glassdoor"])
        registry = BoardProviderRegistry([make_fake_board("linkedin").queue_ok(job())])

        outcome = await scan(test_db_engine, registry)

        assert "glassdoor" not in outcome.board_statuses
        assert outcome.board_statuses["linkedin"]["status"] == "ok"

    async def test_a_board_the_user_switched_off_is_never_called(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine, boards=["linkedin"])
        indeed = make_fake_board("indeed")  # unscripted: any call is an AssertionError
        registry = BoardProviderRegistry([make_fake_board("linkedin").queue_ok(job()), indeed])

        outcome = await scan(test_db_engine, registry)

        assert indeed.call_count == 0
        assert set(outcome.board_statuses) == {"linkedin"}


# --- Criterion 3: the second Scan, the Listing Memory and Reposts --------------------------------


class TestSecondScan:
    async def test_the_second_scan_replaces_the_list_entirely(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine, boards=["linkedin"])
        await scan(
            test_db_engine,
            BoardProviderRegistry(
                [make_fake_board("linkedin").queue_ok(job(title="Old Role", url="https://a.test"))]
            ),
            now=ago(5),
        )
        await scan(
            test_db_engine,
            BoardProviderRegistry(
                [make_fake_board("linkedin").queue_ok(job(title="New Role", url="https://b.test"))]
            ),
            now=NOW,
        )

        assert [listing.title for listing in read_listings(test_db_engine)] == ["New Role"]

    async def test_a_dismissed_job_stays_hidden_when_it_comes_back(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine, boards=["linkedin"])
        await scan(
            test_db_engine,
            BoardProviderRegistry([make_fake_board("linkedin").queue_ok(job())]),
            now=ago(5),
        )
        key = identity_key("Acme Tech", "Backend Engineer")
        with Session(test_db_engine) as session:
            jobs_repo.upsert_memory(session, key, status="dismissed")
            session.commit()

        outcome = await scan(
            test_db_engine,
            BoardProviderRegistry([make_fake_board("linkedin").queue_ok(job())]),
            now=NOW,
        )

        assert read_listings(test_db_engine) == []
        assert outcome.listings_found == 0
        # The memory still tracks it: the Monitor saw the job, the user just does not.
        memory = read_memory(test_db_engine, key)
        assert memory.status == "dismissed"

    async def test_an_applied_job_keeps_its_status_across_scans(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine, boards=["linkedin"])
        await scan(
            test_db_engine,
            BoardProviderRegistry([make_fake_board("linkedin").queue_ok(job())]),
            now=ago(5),
        )
        key = identity_key("Acme Tech", "Backend Engineer")
        with Session(test_db_engine) as session:
            jobs_repo.upsert_memory(session, key, status="applied")
            session.commit()

        await scan(
            test_db_engine,
            BoardProviderRegistry([make_fake_board("linkedin").queue_ok(job())]),
            now=NOW,
        )

        memory = read_memory(test_db_engine, key)
        assert memory.status == "applied"
        # ...and it is still on the list: only 'dismissed' hides a job.
        assert len(read_listings(test_db_engine)) == 1

    async def test_a_first_sighting_creates_the_memory_as_new(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine, boards=["linkedin"])
        await scan(
            test_db_engine,
            BoardProviderRegistry([make_fake_board("linkedin").queue_ok(job())]),
            now=NOW,
        )
        memory = read_memory(test_db_engine, identity_key("Acme Tech", "Backend Engineer"))
        assert memory.status == "new"
        assert memory.first_seen_at.replace(tzinfo=timezone.utc) == NOW

    async def test_first_seen_at_survives_a_rescan_while_last_seen_at_moves(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine, boards=["linkedin"])
        await scan(
            test_db_engine,
            BoardProviderRegistry([make_fake_board("linkedin").queue_ok(job())]),
            now=ago(10),
        )
        await scan(
            test_db_engine,
            BoardProviderRegistry([make_fake_board("linkedin").queue_ok(job())]),
            now=NOW,
        )

        memory = read_memory(test_db_engine, identity_key("Acme Tech", "Backend Engineer"))
        assert memory.first_seen_at.replace(tzinfo=timezone.utc) == ago(10)
        assert memory.last_seen_at.replace(tzinfo=timezone.utc) == NOW

    async def test_a_job_republished_since_the_last_scan_is_flagged_as_a_repost(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine, boards=["linkedin"])
        await scan(
            test_db_engine,
            BoardProviderRegistry(
                [make_fake_board("linkedin").queue_ok(job(date_posted=ago(80)))]
            ),
            now=ago(48),
        )
        await scan(
            test_db_engine,
            BoardProviderRegistry(
                [make_fake_board("linkedin").queue_ok(job(date_posted=ago(2)))]
            ),
            now=NOW,
        )

        listing = read_listings(test_db_engine)[0]
        assert listing.is_repost is True
        # A Repost counts as new for ranking, and the fresh date is what makes that true.
        assert listing.visibility_score == 100.0

    async def test_the_same_old_posting_coming_back_is_not_a_repost(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine, boards=["linkedin"])
        for when in (ago(48), NOW):
            await scan(
                test_db_engine,
                BoardProviderRegistry(
                    [make_fake_board("linkedin").queue_ok(job(date_posted=ago(80)))]
                ),
                now=when,
            )

        assert read_listings(test_db_engine)[0].is_repost is False

    async def test_a_repost_with_a_rewritten_description_clears_the_stale_fit(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine, boards=["linkedin"])
        key = identity_key("Acme Tech", "Backend Engineer")
        await scan(
            test_db_engine,
            BoardProviderRegistry(
                [make_fake_board("linkedin").queue_ok(job(date_posted=ago(80)))]
            ),
            now=ago(48),
        )
        with Session(test_db_engine) as session:
            jobs_repo.upsert_memory(
                session,
                key,
                fit_score=91,
                fit_description_hash="hash-of-the-old-text",
                # Pinned: the Repost comparison is `date_posted > last_seen_at`, so a memory
                # stamped with the real wall clock would make the test's dates meaningless.
                seen_at=ago(48),
            )
            session.commit()

        await scan(
            test_db_engine,
            BoardProviderRegistry(
                [
                    make_fake_board("linkedin").queue_ok(
                        job(date_posted=ago(2), description="A completely rewritten posting.")
                    )
                ]
            ),
            now=NOW,
        )

        memory = read_memory(test_db_engine, key)
        assert memory.fit_score is None
        assert memory.fit_description_hash is None

    async def test_a_repost_with_the_same_description_keeps_the_fit_already_paid_for(
        self, test_db_engine, make_fake_board
    ):
        from app.services.jobs.scan_service import description_hash

        save_profile(test_db_engine, boards=["linkedin"])
        key = identity_key("Acme Tech", "Backend Engineer")
        await scan(
            test_db_engine,
            BoardProviderRegistry(
                [make_fake_board("linkedin").queue_ok(job(date_posted=ago(80)))]
            ),
            now=ago(48),
        )
        with Session(test_db_engine) as session:
            jobs_repo.upsert_memory(
                session,
                key,
                fit_score=91,
                fit_description_hash=description_hash(job().description),
                seen_at=ago(48),
            )
            session.commit()

        await scan(
            test_db_engine,
            BoardProviderRegistry(
                [make_fake_board("linkedin").queue_ok(job(date_posted=ago(2)))]
            ),
            now=NOW,
        )

        memory = read_memory(test_db_engine, key)
        assert memory.fit_score == 91
        assert read_listings(test_db_engine)[0].fit_score == 91

    async def test_a_scan_never_downgrades_a_status_it_did_not_change(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine, boards=["linkedin"])
        key = identity_key("Acme Tech", "Backend Engineer")
        await scan(
            test_db_engine,
            BoardProviderRegistry([make_fake_board("linkedin").queue_ok(job())]),
            now=ago(10),
        )
        with Session(test_db_engine) as session:
            jobs_repo.upsert_memory(session, key, status="seen")
            session.commit()
        changed_at = read_memory(test_db_engine, key).status_changed_at

        await scan(
            test_db_engine,
            BoardProviderRegistry([make_fake_board("linkedin").queue_ok(job())]),
            now=NOW,
        )

        memory = read_memory(test_db_engine, key)
        assert memory.status == "seen"
        assert memory.status_changed_at == changed_at


# --- Dedup, sources and ranking, end to end ------------------------------------------------------


class TestDedupAndRanking:
    async def test_one_job_on_two_boards_is_one_listing_with_both_links(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine, boards=["linkedin", "indeed"])
        registry = BoardProviderRegistry(
            [
                make_fake_board("linkedin").queue_ok(
                    job(company="Acme Tech", url="https://linkedin.test/1", applicant_band="100+")
                ),
                make_fake_board("indeed").queue_ok(
                    job(company="AcmeTech Ltda.", url="https://indeed.test/1")
                ),
            ]
        )

        outcome = await scan(test_db_engine, registry)

        listings = read_listings(test_db_engine)
        assert len(listings) == 1
        assert outcome.listings_found == 1
        sources = read_sources(test_db_engine, listings[0].id)
        assert {s.board for s in sources} == {"linkedin", "indeed"}
        assert {s.url for s in sources} == {"https://linkedin.test/1", "https://indeed.test/1"}
        # The listing takes the smallest known band; each source keeps what its board said.
        assert listings[0].applicant_band == "100+"
        assert {s.applicant_band for s in sources} == {"100+", "unknown"}
        # The per-board count is raw postings, BEFORE dedup -- that is what explains the Scan.
        assert outcome.board_statuses["linkedin"]["count"] == 1
        assert outcome.board_statuses["indeed"]["count"] == 1

    async def test_the_list_is_ordered_by_visibility_score_descending(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine, boards=["linkedin"])
        registry = BoardProviderRegistry(
            [
                make_fake_board("linkedin").queue_ok(
                    job(title="Old Role", url="https://a.test", date_posted=ago(150)),
                    job(title="Fresh Role", url="https://b.test", date_posted=ago(1)),
                    job(title="Undated Role", url="https://c.test", date_posted=None),
                )
            ]
        )

        await scan(test_db_engine, registry)

        assert [listing.title for listing in read_listings(test_db_engine)] == [
            "Fresh Role",
            "Old Role",
            "Undated Role",
        ]

    async def test_the_applicant_band_cap_hides_the_crowded_jobs_but_never_the_unknown_ones(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine, boards=["linkedin"], max_applicant_band="<25")
        registry = BoardProviderRegistry(
            [
                make_fake_board("linkedin").queue_ok(
                    job(title="Quiet Role", url="https://a.test", applicant_band="<10"),
                    job(title="Crowded Role", url="https://b.test", applicant_band="100+"),
                    job(title="Silent Board Role", url="https://c.test", applicant_band=None),
                )
            ]
        )

        await scan(test_db_engine, registry)

        titles = {listing.title for listing in read_listings(test_db_engine)}
        assert titles == {"Quiet Role", "Silent Board Role"}

    async def test_the_scan_row_records_the_counts_and_every_board_status(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine, boards=["linkedin", "indeed"])
        registry = BoardProviderRegistry(
            [
                make_fake_board("linkedin").queue_ok(
                    job(url="https://a.test"), job(title="Other", url="https://b.test")
                ),
                make_fake_board("indeed").queue_ok(job(url="https://c.test")),
            ]
        )

        outcome = await scan(test_db_engine, registry, trigger="scheduled")

        with Session(test_db_engine) as session:
            row = jobs_repo.get_scan(session, outcome.scan_id)
            assert row.trigger == "scheduled"
            assert row.listings_found == 2  # the LinkedIn and Indeed "Backend Engineer" merged
            assert row.listings_scored == 0  # no Fit in ticket 07
            statuses = jobs_repo.get_board_statuses(row)
        assert statuses["linkedin"]["count"] == 2
        assert statuses["indeed"]["count"] == 1

    async def test_every_board_receives_the_same_query_built_from_the_search_profile(
        self, test_db_engine, make_fake_board
    ):
        save_profile(
            test_db_engine,
            boards=["linkedin", "indeed"],
            roles=["Backend Engineer", "SRE"],
            locations=["Brasil"],
            remote="remote_only",
            interval_hours=6,
        )
        linkedin = make_fake_board("linkedin").queue_ok()
        indeed = make_fake_board("indeed").queue_ok()

        await scan(test_db_engine, BoardProviderRegistry([linkedin, indeed]))

        assert linkedin.queries[0] == indeed.queries[0]
        query: BoardQuery = linkedin.queries[0]
        assert query.roles == ["Backend Engineer", "SRE"]
        assert query.locations == ["Brasil"]
        assert query.remote == "remote_only"
        # Wider than the interval, so two consecutive Scans overlap.
        assert query.hours_old >= 12

    async def test_results_wanted_comes_from_config_and_is_read_at_call_time(
        self, test_db_engine, make_fake_board, monkeypatch
    ):
        monkeypatch.setenv("SCAN_RESULTS_WANTED", "7")
        save_profile(test_db_engine, boards=["linkedin"])
        linkedin = make_fake_board("linkedin").queue_ok()

        await scan(test_db_engine, BoardProviderRegistry([linkedin]))

        assert linkedin.queries[0].results_wanted == 7


# --- No Search Profile ---------------------------------------------------------------------------


class TestNoSearchProfile:
    async def test_with_no_search_profile_the_scan_does_not_run_at_all(
        self, test_db_engine, make_fake_board
    ):
        linkedin = make_fake_board("linkedin")  # unscripted: a call would fail the test
        registry = BoardProviderRegistry([linkedin])

        outcome = await scan(test_db_engine, registry)

        assert outcome is None
        assert linkedin.call_count == 0
        with Session(test_db_engine) as session:
            # Not even a Scan row: there was nothing to search for.
            assert jobs_repo.get_latest_scan(session) is None


# --- Criterion 4a: the single-flight lock --------------------------------------------------------


class _GateBoard:
    """A provider that blocks inside ``search`` until the test releases it -- the only way to
    have a Scan genuinely in flight while a second one is requested."""

    id = "linkedin"
    display_name = "LinkedIn"
    min_interval_hours = 1

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def search(self, query: BoardQuery) -> BoardResult:
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        return BoardResult(items=[job()], status="ok")


class TestSingleFlight:
    async def test_a_second_scan_while_one_is_running_is_refused_with_the_current_scan(
        self, test_db_engine
    ):
        save_profile(test_db_engine, boards=["linkedin"])
        gate = _GateBoard()
        registry = BoardProviderRegistry([gate])
        runner = ScanRunner()

        first = asyncio.create_task(scan(test_db_engine, registry, runner=runner))
        await asyncio.wait_for(gate.entered.wait(), timeout=5)
        assert runner.is_running is True

        with pytest.raises(ScanAlreadyRunning) as caught:
            await scan(test_db_engine, registry, runner=runner)

        # The 409 body needs the running Scan, not just a message.
        assert caught.value.scan_id == runner.current_scan_id
        assert isinstance(caught.value.scan, JobScan)
        assert caught.value.scan.status == "running"

        gate.release.set()
        outcome = await asyncio.wait_for(first, timeout=5)
        assert outcome.scan_id == caught.value.scan_id
        assert gate.calls == 1  # the refused request never reached a board

    async def test_the_lock_is_released_so_the_next_scan_runs(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine, boards=["linkedin"])
        runner = ScanRunner()
        for _ in range(2):
            await scan(
                test_db_engine,
                BoardProviderRegistry([make_fake_board("linkedin").queue_ok(job())]),
                runner=runner,
            )
        assert runner.is_running is False

    async def test_the_lock_is_released_even_when_the_scan_blows_up(self, test_db_engine):
        class _Exploding:
            id = "linkedin"
            display_name = "LinkedIn"
            min_interval_hours = 1

            async def search(self, query):  # pragma: no cover - never reached
                return BoardResult()

        save_profile(test_db_engine, boards=["linkedin"])
        runner = ScanRunner()
        registry = BoardProviderRegistry([_Exploding()])

        # Break the WRITE phase, which is downstream of every board call.
        import app.services.jobs.scan_service as scan_service_module

        original = scan_service_module.group_postings
        scan_service_module.group_postings = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("write blew up")
        )
        try:
            with pytest.raises(RuntimeError):
                await scan(test_db_engine, registry, runner=runner)
        finally:
            scan_service_module.group_postings = original

        assert runner.is_running is False
        with Session(test_db_engine) as session:
            # ...and the Scan row is closed, so a stale 'running' cannot block every later one.
            assert jobs_repo.get_running_scan(session) is None

    async def test_a_scan_that_failed_leaves_the_previous_list_untouched(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine, boards=["linkedin"])
        await scan(
            test_db_engine,
            BoardProviderRegistry([make_fake_board("linkedin").queue_ok(job())]),
            now=ago(5),
        )

        import app.services.jobs.scan_service as scan_service_module

        original = scan_service_module.group_postings
        scan_service_module.group_postings = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("write blew up")
        )
        try:
            with pytest.raises(RuntimeError):
                await scan(
                    test_db_engine,
                    BoardProviderRegistry(
                        [make_fake_board("linkedin").queue_ok(job(title="New", url="https://n"))]
                    ),
                )
        finally:
            scan_service_module.group_postings = original

        assert [listing.title for listing in read_listings(test_db_engine)] == ["Backend Engineer"]


# --- Criterion 4b: the scheduler -----------------------------------------------------------------


class _Recorder:
    """A stand-in for ``run_scan`` that records how it was called."""

    def __init__(self, result=None, raises: BaseException | None = None) -> None:
        self.calls: list[tuple] = []
        self.result = result
        self.raises = raises

    async def __call__(self, engine, registry, trigger, **kwargs):
        self.calls.append((trigger, kwargs))
        if self.raises is not None:
            raise self.raises
        return self.result


class _Sleeper:
    """Records every sleep and yields instead of performing it, so a loop turn costs no real
    time. It still has to YIELD (``sleep(0)``): ``run_forever`` would otherwise be a tight loop
    that never gives the event loop a chance to deliver a cancellation."""

    def __init__(self) -> None:
        self.slept: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.slept.append(seconds)
        await asyncio.sleep(0)


def make_scheduler(engine, **kwargs) -> tuple[ScanScheduler, _Recorder, _Sleeper]:
    recorder = kwargs.pop("recorder", None) or _Recorder()
    sleeper = _Sleeper()
    scheduler = ScanScheduler(
        engine,
        BoardProviderRegistry(),
        run_scan=recorder,
        sleep=sleeper,
        clock=lambda: NOW,
        check_interval_seconds=kwargs.pop("check_interval_seconds", 60),
        **kwargs,
    )
    return scheduler, recorder, sleeper


class TestScheduler:
    async def test_an_interval_of_off_never_fires_a_scan(self, test_db_engine):
        save_profile(test_db_engine, interval_hours=None)
        scheduler, recorder, sleeper = make_scheduler(test_db_engine)

        await scheduler.tick()

        assert recorder.calls == []
        assert sleeper.slept == [60]

    async def test_no_search_profile_at_all_is_also_off(self, test_db_engine):
        scheduler, recorder, sleeper = make_scheduler(test_db_engine)

        await scheduler.tick()

        assert recorder.calls == []
        assert sleeper.slept == [60]

    async def test_with_an_interval_and_no_previous_scan_it_runs_immediately(
        self, test_db_engine
    ):
        save_profile(test_db_engine, interval_hours=6)
        scheduler, recorder, _ = make_scheduler(test_db_engine)

        await scheduler.tick()

        assert [trigger for trigger, _ in recorder.calls] == ["scheduled"]

    async def test_it_waits_when_the_last_scan_is_more_recent_than_the_interval(
        self, test_db_engine
    ):
        save_profile(test_db_engine, interval_hours=6)
        with Session(test_db_engine) as session:
            row = jobs_repo.start_scan(session, trigger="immediate")
            row.started_at = ago(1)
            jobs_repo.finish_scan(session, row, board_statuses={}, listings_found=0,
                                  listings_scored=0)
            session.commit()
        scheduler, recorder, sleeper = make_scheduler(test_db_engine)

        await scheduler.tick()

        assert recorder.calls == []
        # Never longer than the check interval: the user may switch the interval off meanwhile.
        assert sleeper.slept == [60]

    async def test_it_runs_once_the_interval_has_elapsed(self, test_db_engine):
        save_profile(test_db_engine, interval_hours=6)
        with Session(test_db_engine) as session:
            row = jobs_repo.start_scan(session, trigger="scheduled")
            row.started_at = ago(7)
            jobs_repo.finish_scan(session, row, board_statuses={}, listings_found=0,
                                  listings_scored=0)
            session.commit()
        scheduler, recorder, _ = make_scheduler(test_db_engine)

        await scheduler.tick()

        assert len(recorder.calls) == 1

    async def test_the_interval_is_reread_every_turn_so_a_change_needs_no_restart(
        self, test_db_engine
    ):
        save_profile(test_db_engine, interval_hours=None)
        scheduler, recorder, _ = make_scheduler(test_db_engine)
        await scheduler.tick()
        assert recorder.calls == []

        save_profile(test_db_engine, interval_hours=1)
        await scheduler.tick()

        assert len(recorder.calls) == 1

    async def test_switching_the_interval_off_stops_the_scans_without_stopping_the_task(
        self, test_db_engine
    ):
        save_profile(test_db_engine, interval_hours=1)
        scheduler, recorder, _ = make_scheduler(test_db_engine)
        await scheduler.tick()
        assert len(recorder.calls) == 1

        save_profile(test_db_engine, interval_hours=None)
        await scheduler.tick()
        await scheduler.tick()

        assert len(recorder.calls) == 1

    async def test_a_scan_that_raises_is_logged_and_the_loop_survives(self, test_db_engine):
        save_profile(test_db_engine, interval_hours=1)
        scheduler, recorder, sleeper = make_scheduler(
            test_db_engine, recorder=_Recorder(raises=RuntimeError("board exploded"))
        )

        await scheduler.tick()  # must not raise
        await scheduler.tick()

        assert len(recorder.calls) == 2
        assert sleeper.slept == [60, 60]

    async def test_a_scan_already_running_is_a_skipped_turn_not_a_failure(self, test_db_engine):
        save_profile(test_db_engine, interval_hours=1)
        scheduler, recorder, sleeper = make_scheduler(
            test_db_engine, recorder=_Recorder(raises=ScanAlreadyRunning(None))
        )

        await scheduler.tick()

        assert sleeper.slept == [60]

    async def test_start_is_idempotent(self, test_db_engine):
        save_profile(test_db_engine, interval_hours=None)
        scheduler, _, _ = make_scheduler(test_db_engine)
        try:
            assert scheduler.start() is scheduler.start()
        finally:
            await scheduler.stop()

    async def test_stop_cancels_the_task_cleanly(self, test_db_engine):
        save_profile(test_db_engine, interval_hours=None)
        scheduler, recorder, _ = make_scheduler(test_db_engine)
        task = scheduler.start()
        await asyncio.sleep(0)

        await scheduler.stop()

        assert task.cancelled() or task.done()
        assert scheduler.is_running is False
        # No stray "Task exception was never retrieved" -- stop() awaited the cancellation.
        assert task.exception() if task.done() and not task.cancelled() else True

    async def test_stop_on_a_scheduler_that_never_started_is_a_no_op(self, test_db_engine):
        scheduler, _, _ = make_scheduler(test_db_engine)
        await scheduler.stop()  # must not raise

    async def test_the_check_interval_comes_from_config_when_not_overridden(
        self, test_db_engine, monkeypatch
    ):
        monkeypatch.setenv("SCAN_CHECK_INTERVAL_SECONDS", "5")
        scheduler = ScanScheduler(test_db_engine, BoardProviderRegistry())
        assert scheduler.check_interval_seconds() == 5.0


class TestSchedulerLifespanWiring:
    async def test_the_env_switch_keeps_the_scheduler_out_of_the_test_suite(
        self, test_db_engine, monkeypatch
    ):
        # conftest sets it to 0 for every test; this asserts the gate actually holds, which is
        # what keeps `lifespan`-driven tests from reaching a real Job Board.
        class _App:
            class state:
                db_engine = test_db_engine

        assert scheduler_module.start(_App()) is None
        assert getattr(_App.state, "scan_scheduler", None) is None

    async def test_with_the_switch_on_it_starts_and_stops_a_real_task(
        self, test_db_engine, monkeypatch
    ):
        monkeypatch.setenv("SCAN_SCHEDULER_ENABLED", "1")
        save_profile(test_db_engine, interval_hours=None)

        class _App:
            class state:
                db_engine = test_db_engine

        app = _App()
        started = scheduler_module.start(
            app, registry=BoardProviderRegistry(), check_interval_seconds=0.01
        )
        try:
            assert started is not None and started.is_running
            assert getattr(app.state, scheduler_module.STATE_ATTR) is started
        finally:
            await scheduler_module.stop(app)
        assert started.is_running is False
        assert getattr(app.state, scheduler_module.STATE_ATTR) is None

    async def test_stopping_an_app_that_never_started_one_is_a_no_op(self):
        class _App:
            class state:
                pass

        await scheduler_module.stop(_App())  # must not raise
