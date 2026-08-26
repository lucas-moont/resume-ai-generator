"""Integration tests for the Fit Score and the ranking inside a real Scan (v7 ticket 08).

Real SQLite (in memory), the real repository, the real Scan transaction -- and never a real Job
Board or a real LLM: every provider is a ``FakeJobBoard`` and every model call goes through a
scripted ``FakeLlm`` handed to ``run_scan`` as ``fit_llm``.

What ``tests/unit/test_fit_service.py`` proves about the policy in isolation, this file proves
about the wiring: that the Profile is read, that the Listing Memory is what the reuse rule reads
and what stage 2 writes, that a discarded listing really leaves the list, and that the rows come
back out of the database ordered by Visibility.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from app.db.tables import JobListing
from app.domain.listing_identity import identity_key
from app.domain.schemas import RawPosting
from app.repositories import jobs_repo, profile_repo
from app.services.jobboards.provider_registry import BoardProviderRegistry
from app.services.jobs.fit_service import description_hash
from app.services.jobs.scan_service import ScanRunner, run_scan
from tests.factories import make_profile
from tests.fakes import FakeLlm

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
# A later instant for a second/third Scan. It has to clear LinkedIn's own minimum interval --
# otherwise the board is ``skipped``, no posting comes back at all, and a test that meant to
# prove "the model was not called again" would pass because nothing was scanned.
LATER = NOW + timedelta(hours=2)
LATER_STILL = NOW + timedelta(hours=4)

BACKEND_POSTING = (
    "Backend engineer. Requirements: Python, Python, FastAPI, PostgreSQL, Docker, Redis. "
    "You will own services written in Python."
)
FRONTEND_POSTING = (
    "Frontend engineer. Requirements: React, React, TypeScript, Tailwind, Storybook, Vite. "
    "You will build interfaces in React."
)


def ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


def fit(value: int) -> str:
    return '{"fit": %d}' % value


def save_profile(engine, **overrides) -> None:
    """The Search Profile -- what the Monitor searches FOR."""
    values = {
        "roles": ["Backend Engineer"],
        "locations": ["Brasil", "Remote"],
        "remote": "any",
        "languages": ["pt", "en"],
        "boards": ["linkedin"],
        "max_applicant_band": None,
        "interval_hours": None,
    }
    values.update(overrides)
    with Session(engine) as session:
        jobs_repo.put_search_profile(session, **values)
        session.commit()


def save_living_profile(engine, **overrides) -> None:
    """The Living Profile -- who the candidate IS. The Fit stage does not run without one."""
    with Session(engine) as session:
        profile_repo.insert_version(
            session, data=json.dumps(make_profile(**overrides)), source_kind="seed_disk"
        )
        session.commit()


def job(
    title="Backend Engineer",
    company="Acme Tech",
    url="https://board.test/1",
    description=BACKEND_POSTING,
    **kwargs,
) -> RawPosting:
    return RawPosting(
        title=title, company=company, url=url, description=description, **kwargs
    )


def read_listings(engine) -> list[JobListing]:
    with Session(engine) as session:
        return jobs_repo.list_listings(session)


def read_memory(engine, key: str):
    with Session(engine) as session:
        row = jobs_repo.get_memory(session, key)
        if row is not None:
            session.expunge(row)
        return row


async def scan(engine, registry, *, llm=None, now=NOW, runner=None, trigger="immediate"):
    """A private ``ScanRunner`` per call (the module-level lock is process-wide) and a pinned
    clock, so the whole Scan is deterministic."""
    return await run_scan(
        engine,
        registry,
        trigger,
        now=now,
        clock=lambda: now,
        runner=runner or ScanRunner(),
        fit_llm=llm,
    )


def one_board(*postings, board="linkedin", make_fake_board=None) -> BoardProviderRegistry:
    return BoardProviderRegistry([make_fake_board(board).queue_ok(*postings)])


# --- Criterion: only the top N reach the model ---------------------------------------------------


class TestTheLlmBudget:
    async def test_only_the_top_n_by_keyword_fit_are_sent_to_the_model(
        self, test_db_engine, make_fake_board, monkeypatch
    ):
        from app import config as config_module

        monkeypatch.setattr(config_module, "FIT_LLM_TOP_N", 2)
        save_profile(test_db_engine)
        save_living_profile(test_db_engine, skills=["Python", "FastAPI", "PostgreSQL"])
        postings = [
            job(
                title=f"Backend Engineer {index}",
                company=f"Company {index}",
                url=f"https://board.test/{index}",
                # Each posting names one fewer Python, so stage 1 ranks them deterministically.
                description="Python. " * (5 - index) + "Kubernetes. " * index,
                date_posted=ago(1),
            )
            for index in range(5)
        ]
        llm = FakeLlm([fit(90), fit(85)])  # exactly two: a third call would be unscripted

        outcome = await scan(
            test_db_engine,
            one_board(*postings, make_fake_board=make_fake_board),
            llm=llm,
        )

        assert llm.call_count == 2
        assert outcome.listings_found == 5
        scored = [listing for listing in read_listings(test_db_engine) if not listing.fit_estimated]
        assert len(scored) == 2
        assert {listing.fit_score for listing in scored} == {90, 85}
        assert outcome.listings_scored == 2

    async def test_the_rest_keep_an_honest_estimate(
        self, test_db_engine, make_fake_board, monkeypatch
    ):
        from app import config as config_module

        monkeypatch.setattr(config_module, "FIT_LLM_TOP_N", 1)
        save_profile(test_db_engine)
        save_living_profile(test_db_engine, skills=["Python"])
        postings = [
            job(company="A", url="https://a.test", description="Python. Python. Python."),
            job(company="B", url="https://b.test", description="Python. Kubernetes."),
        ]
        llm = FakeLlm([fit(90)])

        await scan(
            test_db_engine, one_board(*postings, make_fake_board=make_fake_board), llm=llm
        )

        estimated = [
            listing for listing in read_listings(test_db_engine) if listing.fit_estimated
        ]
        assert len(estimated) == 1
        assert estimated[0].company == "B"
        # An estimate is never written to the memory: doing so would look identical to a
        # paid-for score and lock the listing out of stage 2 forever.
        memory = read_memory(test_db_engine, identity_key("B", "Backend Engineer"))
        assert memory.fit_score is None and memory.fit_description_hash is None


# --- Criterion: the Listing Memory --------------------------------------------------------------


class TestTheListingMemory:
    async def test_the_score_and_its_hash_are_written_together(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine)
        save_living_profile(test_db_engine)

        await scan(
            test_db_engine,
            one_board(job(date_posted=ago(1)), make_fake_board=make_fake_board),
            llm=FakeLlm([fit(77)]),
        )

        memory = read_memory(test_db_engine, identity_key("Acme Tech", "Backend Engineer"))
        assert memory.fit_score == 77
        assert memory.fit_description_hash == description_hash(BACKEND_POSTING)

    async def test_a_second_scan_of_the_same_posting_does_not_call_the_model(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine)
        save_living_profile(test_db_engine)

        await scan(
            test_db_engine,
            one_board(job(date_posted=ago(1)), make_fake_board=make_fake_board),
            llm=FakeLlm([fit(77)]),
        )
        second = FakeLlm()  # nothing queued: a call would be an AssertionError
        outcome = await scan(
            test_db_engine,
            one_board(job(date_posted=ago(1)), make_fake_board=make_fake_board),
            llm=second,
            now=LATER,
        )

        # The board really answered and the list really was rewritten -- without this the test
        # would also pass for a Scan that skipped the board and left the old list standing.
        assert outcome.listings_replaced is True
        assert second.call_count == 0
        listing = read_listings(test_db_engine)[0]
        assert listing.fit_score == 77 and listing.fit_estimated is False

    async def test_a_rewritten_description_is_scored_again(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine)
        save_living_profile(test_db_engine)

        await scan(
            test_db_engine,
            one_board(job(date_posted=ago(30)), make_fake_board=make_fake_board),
            llm=FakeLlm([fit(77)]),
        )
        rewritten = BACKEND_POSTING + " Update: we also use Kubernetes and Terraform."
        second = FakeLlm([fit(52)])
        await scan(
            test_db_engine,
            one_board(
                # Republished AFTER the first Scan saw it: a Repost, and with new text.
                job(description=rewritten, date_posted=NOW + timedelta(hours=1)),
                make_fake_board=make_fake_board,
            ),
            llm=second,
            now=LATER,
        )

        assert second.call_count == 1
        listing = read_listings(test_db_engine)[0]
        assert listing.fit_score == 52 and listing.is_repost is True
        memory = read_memory(test_db_engine, identity_key("Acme Tech", "Backend Engineer"))
        assert memory.fit_description_hash == description_hash(rewritten)

    async def test_the_reused_score_survives_the_listing_table_being_truncated(
        self, test_db_engine, make_fake_board
    ):
        # ``job_listings`` is ephemeral; the Fit is not. That split is the whole point of the
        # Listing Memory, so it is asserted end to end rather than only in the repository.
        save_profile(test_db_engine)
        save_living_profile(test_db_engine)
        await scan(
            test_db_engine,
            one_board(job(date_posted=ago(1)), make_fake_board=make_fake_board),
            llm=FakeLlm([fit(64)]),
        )
        # A Scan that finds a DIFFERENT job wipes the list...
        await scan(
            test_db_engine,
            one_board(
                job(company="Other", url="https://other.test", date_posted=ago(1)),
                make_fake_board=make_fake_board,
            ),
            llm=FakeLlm([fit(20)]),
            now=LATER,
        )
        # ...and the original comes back with its Fit intact, unpaid for.
        third = FakeLlm()
        await scan(
            test_db_engine,
            one_board(job(date_posted=ago(1)), make_fake_board=make_fake_board),
            llm=third,
            now=LATER_STILL,
        )

        assert third.call_count == 0
        assert read_listings(test_db_engine)[0].fit_score == 64


# --- Criterion: unusable output keeps the estimate ------------------------------------------------


class TestDegradation:
    async def test_garbage_from_the_model_keeps_the_keyword_estimate(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine)
        save_living_profile(test_db_engine)

        await scan(
            test_db_engine,
            one_board(job(date_posted=ago(1)), make_fake_board=make_fake_board),
            llm=FakeLlm(["Sure! I'd rate this one pretty highly."]),
        )

        listing = read_listings(test_db_engine)[0]
        assert listing.fit_estimated is True
        assert listing.fit_score > 0  # the keyword pass's number, not a zero
        memory = read_memory(test_db_engine, identity_key("Acme Tech", "Backend Engineer"))
        assert memory.fit_score is None  # nothing was learned, so nothing is remembered

    async def test_a_provider_error_does_not_bring_the_scan_down(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine)
        save_living_profile(test_db_engine)

        outcome = await scan(
            test_db_engine,
            one_board(job(date_posted=ago(1)), make_fake_board=make_fake_board),
            llm=FakeLlm([RuntimeError("provider is down")]),
        )

        assert outcome.listings_found == 1
        assert read_listings(test_db_engine)[0].fit_estimated is True

    async def test_a_scan_with_no_living_profile_still_produces_a_ranked_list(
        self, test_db_engine, make_fake_board
    ):
        # No profile saved anywhere (``isolated_data_env`` empties the disk too): the Fit stage
        # cannot run, and the Monitor still ranks by recency and crowding.
        save_profile(test_db_engine)
        llm = FakeLlm()

        outcome = await scan(
            test_db_engine,
            BoardProviderRegistry(
                [
                    make_fake_board("linkedin").queue_ok(
                        job(company="Fresh", url="https://f.test", date_posted=ago(1)),
                        job(company="Stale", url="https://s.test", date_posted=ago(400)),
                    )
                ]
            ),
            llm=llm,
        )

        assert llm.call_count == 0
        assert outcome.listings_scored == 0
        companies = [listing.company for listing in read_listings(test_db_engine)]
        assert companies == ["Fresh", "Stale"]


# --- Criterion: the floor discards ---------------------------------------------------------------


class TestTheKeywordFloor:
    async def test_a_clear_miss_never_reaches_the_list_or_the_model(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine)
        save_living_profile(test_db_engine, skills=["Python", "FastAPI", "PostgreSQL"])
        llm = FakeLlm([fit(88)])  # one call: for the backend posting only

        outcome = await scan(
            test_db_engine,
            BoardProviderRegistry(
                [
                    make_fake_board("linkedin").queue_ok(
                        job(company="Backend Co", url="https://b.test", date_posted=ago(1)),
                        job(
                            title="Frontend Engineer",
                            company="Frontend Co",
                            url="https://f.test",
                            description=FRONTEND_POSTING,
                            date_posted=ago(1),
                        ),
                    )
                ]
            ),
            llm=llm,
        )

        assert llm.call_count == 1
        assert outcome.listings_found == 1
        assert [listing.company for listing in read_listings(test_db_engine)] == ["Backend Co"]

    async def test_a_discarded_listing_still_updates_its_memory(
        self, test_db_engine, make_fake_board
    ):
        # ``last_seen_at`` is a fact about the Monitor having FOUND the job, independent of any
        # filter hiding it -- and it is the baseline the next Repost detection compares against.
        save_profile(test_db_engine)
        save_living_profile(test_db_engine, skills=["Python", "FastAPI", "PostgreSQL"])

        await scan(
            test_db_engine,
            one_board(
                job(
                    title="Frontend Engineer",
                    company="Frontend Co",
                    url="https://f.test",
                    description=FRONTEND_POSTING,
                    date_posted=ago(1),
                ),
                make_fake_board=make_fake_board,
            ),
            llm=FakeLlm(),
        )

        memory = read_memory(test_db_engine, identity_key("Frontend Co", "Frontend Engineer"))
        assert memory is not None and memory.last_seen_at is not None


# --- Criterion: the final order is Visibility descending -------------------------------------


class TestRanking:
    async def test_the_list_comes_back_ordered_by_visibility(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine)
        save_living_profile(test_db_engine, skills=["Python"])
        postings = [
            job(company="Middling", url="https://m.test", date_posted=ago(1)),
            job(company="Best", url="https://b.test", date_posted=ago(1)),
            job(company="Worst", url="https://w.test", date_posted=ago(400)),
        ]
        # Stage 1 ties all three (same description), so the order the model is called in is by
        # identity key: "best" < "middling" < "worst".
        llm = FakeLlm([fit(95), fit(50), fit(40)])

        await scan(
            test_db_engine, one_board(*postings, make_fake_board=make_fake_board), llm=llm
        )

        listings = read_listings(test_db_engine)
        assert [listing.company for listing in listings] == ["Best", "Middling", "Worst"]
        scores = [listing.visibility_score for listing in listings]
        assert scores == sorted(scores, reverse=True)

    async def test_a_crowded_perfect_fit_ranks_below_an_empty_queue(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine)
        save_living_profile(test_db_engine, skills=["Python"])
        postings = [
            job(
                company="Crowded",
                url="https://c.test",
                date_posted=ago(1),
                applicant_band="100+",
            ),
            job(company="Quiet", url="https://q.test", date_posted=ago(1), applicant_band="<10"),
        ]
        # "crowded" sorts before "quiet", so the 100 goes to the crowded one.
        llm = FakeLlm([fit(100), fit(70)])

        await scan(
            test_db_engine, one_board(*postings, make_fake_board=make_fake_board), llm=llm
        )

        listings = read_listings(test_db_engine)
        assert listings[0].company == "Quiet"
        # 100*(0.55*1.0 + 0.25*1.0 + 0.20*0.1) = 82 against
        # 100*(0.55*0.7 + 0.25*1.0 + 0.20*1.0) = 83.5 -> 84.
        assert (listings[0].visibility_score, listings[1].visibility_score) == (84.0, 82.0)

    async def test_the_visibility_score_is_persisted_on_the_row(
        self, test_db_engine, make_fake_board
    ):
        save_profile(test_db_engine)
        save_living_profile(test_db_engine)

        await scan(
            test_db_engine,
            one_board(
                job(date_posted=ago(1), applicant_band="<25"), make_fake_board=make_fake_board
            ),
            llm=FakeLlm([fit(80)]),
        )

        listing = read_listings(test_db_engine)[0]
        # 100*(0.55*0.8 + 0.25*1.0 + 0.20*0.9) = 87.
        assert listing.visibility_score == 87.0
        assert listing.fit_score == 80 and listing.fit_estimated is False
