"""Unit tests for ``services/jobs/listing_query.py`` (v7 ticket 09) -- the composition of the
ephemeral Job Listing rows with the durable Listing Memory, and every filter of
``GET /api/jobs/listings``.

Real in-memory SQLite through the production path (``create_db_engine`` + ``init_db``), like
tests/unit/test_jobs_repo.py, but no HTTP client anywhere: the point of the module under test is
that the product rules -- what ``dismissed`` hides, what ``unknown`` passes, what opening a
listing does to its memory -- can be asserted without a router in the way.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session
from sqlmodel.pool import StaticPool

from app.db.engine import create_db_engine, init_db
from app.db.tables import JobListing, ListingSource
from app.repositories import jobs_repo
from app.services.jobs.listing_query import (
    ListingFilters,
    get_listing,
    list_listings,
    open_listing,
    set_listing_status,
)

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def engine():
    eng = create_db_engine("sqlite://", poolclass=StaticPool)
    init_db(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


def listing(
    key: str,
    *,
    visibility: float = 50.0,
    band: str = "unknown",
    boards: tuple[str, ...] = ("linkedin",),
    **overrides,
) -> tuple[JobListing, list[ListingSource]]:
    """An unsaved listing plus one source per board, with the fields a test does not care
    about already filled."""
    values = dict(
        scan_id=0,  # replace_listings owns it
        identity_key=key,
        title="Backend Engineer",
        company="Acme",
        location="Remote",
        is_remote=True,
        description="We need Python and FastAPI for this backend role.",
        description_word_count=9,
        date_posted=NOW - timedelta(hours=3),
        is_repost=False,
        applicant_band=band,
        fit_score=70,
        fit_estimated=False,
        visibility_score=visibility,
        locale="en",
    )
    values.update(overrides)
    sources = [
        ListingSource(
            listing_id=0,
            board=board,
            url=f"https://{board}.test/{key}",
            date_posted=values["date_posted"],
            applicant_band=band,
        )
        for board in boards
    ]
    return JobListing(**values), sources


def seed(session: Session, *pairs) -> list[int]:
    """Write one Scan's worth of listings and return their ids, in the order given."""
    scan = jobs_repo.start_scan(session, trigger="immediate")
    written = jobs_repo.replace_listings(
        session, scan_id=int(scan.id or 0), listings=list(pairs)
    )
    session.commit()
    return [int(row.id or 0) for row in written]


def remember(session: Session, key: str, **kwargs) -> None:
    jobs_repo.upsert_memory(session, key, **kwargs)
    session.commit()


class TestOrderAndShape:
    def test_the_list_is_ranked_by_visibility_descending(self, session):
        seed(
            session,
            listing("a", visibility=41.0),
            listing("b", visibility=91.0),
            listing("c", visibility=68.0),
        )

        assert [out.visibilityScore for out in list_listings(session)] == [91.0, 68.0, 41.0]

    def test_equal_scores_keep_a_stable_order_by_id(self, session):
        """Two listings that tie must not swap places between two requests -- the id is the
        only strictly increasing tiebreaker there is."""
        ids = seed(
            session,
            listing("a", visibility=50.0),
            listing("b", visibility=50.0),
            listing("c", visibility=50.0),
        )

        first = [out.id for out in list_listings(session)]
        second = [out.id for out in list_listings(session)]
        assert first == second == ids

    def test_the_list_omits_the_description_but_keeps_the_word_count(self, session):
        """Fifty full postings is a payload nobody reads; the count is what lets a card
        pre-disable One-click without carrying the text."""
        seed(session, listing("a"))

        [out] = list_listings(session)
        assert out.description is None
        assert out.descriptionWordCount == 9

    def test_every_source_travels_with_the_listing(self, session):
        """A Job Listing always keeps every source link -- dedup must not cost the user the
        board they would rather apply on."""
        seed(session, listing("a", boards=("linkedin", "remotive"), band="<25"))

        [out] = list_listings(session)
        assert [(s.board, s.url) for s in out.sources] == [
            ("linkedin", "https://linkedin.test/a"),
            ("remotive", "https://remotive.test/a"),
        ]
        assert out.applicantBand == "<25"
        assert out.sources[0].applicantBand == "<25"

    def test_a_listing_with_no_memory_reads_as_new(self, session):
        seed(session, listing("a"))

        [out] = list_listings(session)
        assert out.status == "new"
        assert out.hasOneClickResume is False

    def test_status_and_one_click_come_from_the_memory(self, session):
        seed(session, listing("a"))
        remember(session, "a", status="applied", resume_version_id=7)

        [out] = list_listings(session)
        assert out.status == "applied"
        assert out.hasOneClickResume is True

    def test_an_empty_scan_returns_an_empty_list(self, session):
        assert list_listings(session) == []


class TestFilters:
    def test_dismissed_is_hidden_by_default(self, session):
        """That is what dismissing a job means. The Scan already leaves a dismissed listing out
        of ``job_listings``; the ones this filter catches were dismissed AFTER the Scan."""
        kept, dismissed = seed(session, listing("a", visibility=90.0), listing("b", visibility=10.0))
        remember(session, "b", status="dismissed")

        assert [out.id for out in list_listings(session)] == [kept]
        assert dismissed not in [out.id for out in list_listings(session, ListingFilters())]

    def test_include_dismissed_brings_it_back(self, session):
        seed(session, listing("a", visibility=90.0), listing("b", visibility=10.0))
        remember(session, "b", status="dismissed")

        out = list_listings(session, ListingFilters(include_dismissed=True))
        assert [item.status for item in out] == ["new", "dismissed"]

    def test_the_status_filter_narrows_within_what_is_visible(self, session):
        seed(session, listing("a"), listing("b"), listing("c"))
        remember(session, "b", status="seen")
        remember(session, "c", status="applied")

        assert [o.status for o in list_listings(session, ListingFilters(status="seen"))] == ["seen"]
        assert [o.status for o in list_listings(session, ListingFilters(status="new"))] == ["new"]

    def test_asking_for_dismissed_alone_returns_nothing(self, session):
        """Two independent filters, composed honestly: hiding dismissed listings happens
        first, so narrowing to them needs ``include_dismissed`` as well. Same composition the
        web client's own mock encodes."""
        seed(session, listing("a"))
        remember(session, "a", status="dismissed")

        assert list_listings(session, ListingFilters(status="dismissed")) == []
        assert (
            len(list_listings(session, ListingFilters(status="dismissed", include_dismissed=True)))
            == 1
        )

    def test_the_board_filter_matches_any_source(self, session):
        multi, single = seed(
            session,
            listing("a", boards=("linkedin", "remotive"), visibility=90.0),
            listing("b", boards=("indeed",), visibility=10.0),
        )

        # The second source counts as much as the first: a listing is "on" every board it was
        # found on, not only the one that answered first.
        assert [o.id for o in list_listings(session, ListingFilters(board="remotive"))] == [multi]
        assert [o.id for o in list_listings(session, ListingFilters(board="linkedin"))] == [multi]
        assert [o.id for o in list_listings(session, ListingFilters(board="indeed"))] == [single]
        assert list_listings(session, ListingFilters(board="glassdoor")) == []

    @pytest.mark.parametrize(
        ("band", "cap", "kept"),
        [
            ("<10", "<25", True),
            ("<25", "<25", True),
            ("<50", "<25", False),
            ("100+", "<100", False),
            ("unknown", "<10", True),
            ("<100", None, True),
        ],
        ids=[
            "below the cap",
            "exactly the cap",
            "above the cap",
            "100+ fails every cap",
            "unknown never excludes",
            "no cap is qualquer",
        ],
    )
    def test_the_band_cap(self, session, band, cap, kept):
        """CONTEXT.md (Applicant Band): an absent number is not evidence of a crowd. The rule
        is ``scan_service.passes_band_cap``, shared with the Scan rather than restated."""
        seed(session, listing("a", band=band))

        assert bool(list_listings(session, ListingFilters(max_band=cap))) is kept

    def test_filters_compose(self, session):
        seed(
            session,
            listing("a", band="<10", boards=("linkedin",), visibility=90.0),
            listing("b", band="<10", boards=("indeed",), visibility=80.0),
            listing("c", band="100+", boards=("linkedin",), visibility=70.0),
        )
        remember(session, "a", status="seen")
        remember(session, "b", status="seen")

        out = list_listings(
            session, ListingFilters(status="seen", board="linkedin", max_band="<25")
        )
        assert len(out) == 1
        assert out[0].visibilityScore == 90.0


class TestDetail:
    def test_the_detail_carries_the_description(self, session):
        [listing_id] = seed(session, listing("a"))

        out = get_listing(session, listing_id)
        assert out is not None
        assert out.description == "We need Python and FastAPI for this backend role."
        assert out.sources[0].board == "linkedin"

    def test_an_unknown_id_is_none(self, session):
        seed(session, listing("a"))

        assert get_listing(session, 9999) is None
        assert open_listing(session, 9999) is None
        assert set_listing_status(session, 9999, "applied") is None

    def test_reading_the_detail_does_not_mark_seen(self, session):
        """``get_listing`` is the pure read; only ``open_listing`` has the side effect."""
        [listing_id] = seed(session, listing("a"))

        assert get_listing(session, listing_id).status == "new"
        assert jobs_repo.get_memory(session, "a") is None


class TestOpenListing:
    def test_opening_a_new_listing_marks_it_seen(self, session):
        [listing_id] = seed(session, listing("a"))

        out = open_listing(session, listing_id)
        session.commit()

        assert out.status == "seen"
        assert jobs_repo.get_memory(session, "a").status == "seen"

    def test_it_creates_the_memory_when_there_is_none(self, session):
        [listing_id] = seed(session, listing("a"))
        assert jobs_repo.get_memory(session, "a") is None

        open_listing(session, listing_id)
        session.commit()

        assert jobs_repo.get_memory(session, "a") is not None

    @pytest.mark.parametrize("status", ["applied", "dismissed", "seen"])
    def test_it_never_overwrites_a_verdict_the_user_already_gave(self, session, status):
        [listing_id] = seed(session, listing("a"))
        remember(session, "a", status=status)

        out = open_listing(session, listing_id)
        session.commit()

        assert out.status == status
        assert jobs_repo.get_memory(session, "a").status == status

    def test_opening_does_not_move_last_seen_at(self, session):
        """``last_seen_at`` is the baseline Repost detection compares a posting's date against
        (``scan_service.is_repost``). If a click moved it forward, a job reposted between the
        Scan and the click would read as not-a-Repost on the next Scan."""
        [listing_id] = seed(session, listing("a"))
        scanned_at = NOW - timedelta(hours=2)
        remember(session, "a", seen_at=scanned_at)

        open_listing(session, listing_id)
        session.commit()

        memory = jobs_repo.get_memory(session, "a")
        assert memory.status == "seen"
        assert memory.last_seen_at.replace(tzinfo=timezone.utc) == scanned_at
        # ...while the status genuinely changed now, which is what that column records.
        assert memory.status_changed_at.replace(tzinfo=timezone.utc) > scanned_at


class TestSetStatus:
    @pytest.mark.parametrize("status", ["seen", "applied", "dismissed"])
    def test_it_stores_the_status_and_returns_the_updated_listing(self, session, status):
        [listing_id] = seed(session, listing("a"))

        out = set_listing_status(session, listing_id, status)
        session.commit()

        assert out.status == status
        assert out.description is not None  # the detail shape, so a card re-renders from it
        assert jobs_repo.get_memory(session, "a").status == status

    def test_the_status_is_stored_by_identity_so_it_outlives_the_listing_row(self, session):
        """The listing row is ephemeral; the verdict is not. Dismissing a job today is what
        keeps it hidden when a Scan finds it again next week."""
        [listing_id] = seed(session, listing("a"))
        set_listing_status(session, listing_id, "dismissed")
        session.commit()

        # A second Scan rewrites the table wholesale -- new row, new id, same identity.
        [new_id] = seed(session, listing("a", visibility=99.0))

        assert new_id != listing_id
        assert get_listing(session, new_id).status == "dismissed"

    def test_setting_a_status_does_not_move_last_seen_at_either(self, session):
        [listing_id] = seed(session, listing("a"))
        scanned_at = NOW - timedelta(hours=5)
        remember(session, "a", seen_at=scanned_at)

        set_listing_status(session, listing_id, "applied")
        session.commit()

        memory = jobs_repo.get_memory(session, "a")
        assert memory.last_seen_at.replace(tzinfo=timezone.utc) == scanned_at
