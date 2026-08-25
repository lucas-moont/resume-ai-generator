"""Repository tests for the Job Monitor's tables (v7 ticket 02 -- "Tabelas e migrações do
Monitor").

Same setup as tests/unit/test_source_document_repo.py: a real in-memory SQLite engine built by
the production code path (``app.db.engine.create_db_engine`` + ``init_db``), so what these tests
exercise is the actual schema -- FK cascades, the unique index on ``listing_memory``, the
singleton primary key -- and not an ORM-only approximation of it. Kept in its own module so
this ticket does not collide with concurrent edits to the shared repository test files.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from sqlmodel.pool import StaticPool

from app.db.engine import create_db_engine, init_db
from app.db.tables import SEARCH_PROFILE_ID, JobListing, ListingMemory, ListingSource, SearchProfile
from app.repositories import jobs_repo, resume_repo


@pytest.fixture
def engine():
    eng = create_db_engine("sqlite://", poolclass=StaticPool)
    init_db(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


def _listing(identity_key: str, **overrides) -> JobListing:
    """An unsaved JobListing with the fields a test does not care about already filled."""
    defaults = dict(
        scan_id=0,  # replace_listings overwrites this -- see its docstring
        identity_key=identity_key,
        title="Backend Engineer",
        company="ACME",
        description="a posting",
        description_word_count=2,
    )
    defaults.update(overrides)
    return JobListing(**defaults)


def _source(board: str = "linkedin", url: str = "https://example.test/1", **overrides) -> ListingSource:
    return ListingSource(listing_id=0, board=board, url=url, **overrides)


class TestSearchProfile:
    def test_get_returns_none_before_the_user_ever_saves(self, session):
        """Not an error state: the suggestion endpoint renders a Search Profile that was never
        persisted, and a scheduled Scan with no row here has nothing to search for."""
        assert jobs_repo.get_search_profile(session) is None

    def test_put_creates_the_row_and_round_trips_every_field(self, session):
        row = jobs_repo.put_search_profile(
            session,
            roles=["Backend Engineer", "Engenheiro de Dados"],
            locations=["Brasil", "Remote"],
            remote="remote_only",
            languages=["pt", "en"],
            boards=["linkedin", "remotive"],
            max_applicant_band="<25",
            interval_hours=6,
        )

        assert row.id == SEARCH_PROFILE_ID
        assert jobs_repo.get_roles(row) == ["Backend Engineer", "Engenheiro de Dados"]
        assert jobs_repo.get_locations(row) == ["Brasil", "Remote"]
        assert jobs_repo.get_languages(row) == ["pt", "en"]
        assert jobs_repo.get_boards(row) == ["linkedin", "remotive"]
        assert row.remote == "remote_only"
        assert row.max_applicant_band == "<25"
        assert row.interval_hours == 6

    def test_put_twice_updates_the_same_single_row(self, session):
        jobs_repo.put_search_profile(
            session,
            roles=["Backend Engineer"],
            locations=["Brasil"],
            remote="any",
            languages=["pt"],
            boards=["linkedin"],
            max_applicant_band=None,
            interval_hours=1,
        )
        session.commit()

        jobs_repo.put_search_profile(
            session,
            roles=["Staff Engineer"],
            locations=["Remote"],
            remote="onsite_ok",
            languages=["en"],
            boards=["indeed"],
            max_applicant_band="<10",
            interval_hours=None,
        )
        session.commit()

        rows = session.exec(select(SearchProfile)).all()
        assert len(rows) == 1
        assert jobs_repo.get_roles(rows[0]) == ["Staff Engineer"]
        assert rows[0].interval_hours is None  # 'off' -- not "unchanged"

    def test_put_is_a_replace_so_an_empty_list_really_empties_the_field(self, session):
        """"The user unchecked every board" has to be expressible; a PATCH-shaped write would
        silently keep the old boards and keep scanning them."""
        jobs_repo.put_search_profile(
            session,
            roles=["Backend Engineer"],
            locations=["Brasil"],
            remote="any",
            languages=["pt"],
            boards=["linkedin", "indeed"],
            max_applicant_band="<50",
            interval_hours=3,
        )
        session.commit()

        row = jobs_repo.put_search_profile(
            session,
            roles=[],
            locations=[],
            remote="any",
            languages=[],
            boards=[],
            max_applicant_band=None,
            interval_hours=3,
        )

        assert jobs_repo.get_boards(row) == []
        assert jobs_repo.get_roles(row) == []
        assert row.max_applicant_band is None

    def test_a_second_search_profile_row_collides_on_the_primary_key(self, session):
        """The singleton is enforced by the PK default, not by convention (SearchProfile's
        docstring): a second insert must fail loudly rather than give the Scan two profiles."""
        session.add(SearchProfile())
        session.flush()
        session.add(SearchProfile())

        with pytest.raises(IntegrityError):
            session.flush()


class TestScans:
    def test_start_scan_opens_a_running_row(self, session):
        scan = jobs_repo.start_scan(session, trigger="immediate")

        assert scan.id is not None
        assert scan.status == "running"
        assert scan.trigger == "immediate"
        assert scan.finished_at is None
        assert jobs_repo.get_board_statuses(scan) == {}
        assert jobs_repo.get_running_scan(session).id == scan.id

    def test_finish_scan_closes_it_with_the_per_board_report(self, session):
        scan = jobs_repo.start_scan(session, trigger="scheduled")

        closed = jobs_repo.finish_scan(
            session,
            scan,
            board_statuses={
                "linkedin": {"status": "blocked", "message": "429", "count": 0},
                "remotive": {"status": "ok", "message": None, "count": 12},
            },
            listings_found=9,
            listings_scored=4,
        )

        assert closed.status == "done"
        assert closed.finished_at is not None
        assert closed.listings_found == 9
        assert closed.listings_scored == 4
        assert jobs_repo.get_board_statuses(closed)["linkedin"]["status"] == "blocked"
        assert jobs_repo.get_board_statuses(closed)["remotive"]["count"] == 12
        assert jobs_repo.get_running_scan(session) is None

    def test_a_scan_where_every_board_broke_is_still_done(self, session):
        """CONTEXT.md: a Scan is partial, never failed -- there is no 'failed' status."""
        scan = jobs_repo.start_scan(session, trigger="immediate")

        closed = jobs_repo.finish_scan(
            session,
            scan,
            board_statuses={"linkedin": {"status": "error", "message": "timeout", "count": 0}},
            listings_found=0,
            listings_scored=0,
        )

        assert closed.status == "done"

    def test_get_latest_scan_returns_the_most_recent_started(self, session):
        first = jobs_repo.start_scan(session, trigger="scheduled")
        jobs_repo.finish_scan(session, first, board_statuses={}, listings_found=0, listings_scored=0)
        second = jobs_repo.start_scan(session, trigger="immediate")

        assert jobs_repo.get_latest_scan(session).id == second.id

    def test_get_latest_scan_returns_none_on_an_empty_db(self, session):
        assert jobs_repo.get_latest_scan(session) is None


class TestReplaceListings:
    def test_writes_listings_with_their_sources_linked(self, session):
        scan = jobs_repo.start_scan(session, trigger="immediate")

        written = jobs_repo.replace_listings(
            session,
            scan_id=scan.id,
            listings=[
                (
                    _listing("acme|backend engineer", visibility_score=80.0),
                    [
                        _source("linkedin", "https://li.test/1", applicant_band="<25"),
                        _source("indeed", "https://in.test/1"),
                    ],
                ),
                (_listing("globex|data engineer", company="Globex", visibility_score=40.0), []),
            ],
        )
        session.commit()

        assert [listing.scan_id for listing in written] == [scan.id, scan.id]
        sources = jobs_repo.get_listing_sources(session, written[0].id)
        assert [s.board for s in sources] == ["linkedin", "indeed"]
        assert all(s.listing_id == written[0].id for s in sources)
        assert sources[0].applicant_band == "<25"
        assert jobs_repo.get_listing_sources(session, written[1].id) == []

    def test_the_second_scan_replaces_the_list_entirely(self, session):
        """The list IS the last Scan (CONTEXT.md: Job Listing) -- a job that did not come back
        disappears immediately, and its sources go with it."""
        first_scan = jobs_repo.start_scan(session, trigger="scheduled")
        old = jobs_repo.replace_listings(
            session,
            scan_id=first_scan.id,
            listings=[(_listing("acme|backend engineer"), [_source()])],
        )
        old_id = old[0].id
        jobs_repo.finish_scan(
            session, first_scan, board_statuses={}, listings_found=1, listings_scored=0
        )
        session.commit()

        second_scan = jobs_repo.start_scan(session, trigger="scheduled")
        jobs_repo.replace_listings(
            session,
            scan_id=second_scan.id,
            listings=[(_listing("globex|data engineer", company="Globex"), [_source("remotive")])],
        )
        session.commit()

        remaining = jobs_repo.list_listings(session)
        assert [row.identity_key for row in remaining] == ["globex|data engineer"]
        assert remaining[0].scan_id == second_scan.id
        assert jobs_repo.get_listing(session, old_id) is None
        assert session.exec(select(ListingSource).where(ListingSource.listing_id == old_id)).all() == []

    def test_a_listing_id_from_a_previous_scan_is_never_reused(self, session):
        """SQLite recycles the rowid of a deleted row, and this table is emptied by every Scan.
        ``sqlite_autoincrement`` is what stops the first listing of Scan N+1 from inheriting id 1
        and answering, as a different job, to a link the user opened seconds earlier."""
        first_scan = jobs_repo.start_scan(session, trigger="scheduled")
        old = jobs_repo.replace_listings(
            session, scan_id=first_scan.id, listings=[(_listing("acme|backend engineer"), [])]
        )
        old_id = old[0].id
        session.commit()

        second_scan = jobs_repo.start_scan(session, trigger="scheduled")
        new_rows = jobs_repo.replace_listings(
            session,
            scan_id=second_scan.id,
            listings=[(_listing("globex|data engineer", company="Globex"), [])],
        )
        session.commit()

        assert new_rows[0].id != old_id
        assert jobs_repo.get_listing(session, old_id) is None

    def test_a_failure_before_commit_leaves_the_previous_list_intact(self, session):
        """Truncate+write is atomic because it rides the caller's transaction: the user keeps
        the previous Scan's list rather than being left with an empty Job Monitor."""
        first_scan = jobs_repo.start_scan(session, trigger="scheduled")
        jobs_repo.replace_listings(
            session,
            scan_id=first_scan.id,
            listings=[(_listing("acme|backend engineer"), [_source()])],
        )
        session.commit()

        second_scan = jobs_repo.start_scan(session, trigger="immediate")
        jobs_repo.replace_listings(
            session,
            scan_id=second_scan.id,
            listings=[(_listing("globex|data engineer", company="Globex"), [_source("remotive")])],
        )
        session.rollback()  # anything downstream (Fit, memory update) blowing up looks like this

        surviving = jobs_repo.list_listings(session)
        assert [row.identity_key for row in surviving] == ["acme|backend engineer"]
        assert len(jobs_repo.get_listing_sources(session, surviving[0].id)) == 1

    def test_deleting_the_scan_cascades_to_listings_and_sources(self, session):
        """``scan_id`` is a REAL foreign key (unlike the soft refs): a listing has no meaning
        without the Scan that found it."""
        scan = jobs_repo.start_scan(session, trigger="immediate")
        jobs_repo.replace_listings(
            session,
            scan_id=scan.id,
            listings=[(_listing("acme|backend engineer"), [_source()])],
        )
        session.commit()

        session.delete(scan)
        session.commit()

        assert session.exec(select(JobListing)).all() == []
        assert session.exec(select(ListingSource)).all() == []

    def test_replace_with_an_empty_list_clears_everything(self, session):
        scan = jobs_repo.start_scan(session, trigger="immediate")
        jobs_repo.replace_listings(
            session, scan_id=scan.id, listings=[(_listing("acme|backend engineer"), [_source()])]
        )
        session.commit()

        jobs_repo.replace_listings(session, scan_id=scan.id, listings=[])
        session.commit()

        assert jobs_repo.list_listings(session) == []
        assert session.exec(select(ListingSource)).all() == []


class TestListingQueries:
    def test_list_listings_is_ordered_by_visibility_desc_then_id(self, session):
        scan = jobs_repo.start_scan(session, trigger="immediate")
        jobs_repo.replace_listings(
            session,
            scan_id=scan.id,
            listings=[
                (_listing("a|x", visibility_score=10.0), []),
                (_listing("b|x", visibility_score=90.5), []),
                (_listing("c|x", visibility_score=90.5), []),
            ],
        )
        session.commit()

        assert [row.identity_key for row in jobs_repo.list_listings(session)] == ["b|x", "c|x", "a|x"]

    def test_get_listing_returns_none_for_an_id_the_latest_scan_no_longer_has(self, session):
        assert jobs_repo.get_listing(session, 4242) is None


class TestListingMemory:
    def test_first_upsert_creates_the_memory_as_new(self, session):
        row = jobs_repo.upsert_memory(session, "acme|backend engineer")

        assert row.status == "new"
        assert row.fit_score is None
        assert row.resume_version_id is None
        assert row.first_seen_at == row.last_seen_at == row.status_changed_at

    def test_upsert_is_idempotent_by_identity_key(self, session):
        first_seen = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
        later = first_seen + timedelta(hours=3)

        jobs_repo.upsert_memory(session, "acme|backend engineer", seen_at=first_seen)
        jobs_repo.upsert_memory(session, "acme|backend engineer", seen_at=later)
        session.commit()

        rows = session.exec(select(ListingMemory)).all()
        assert len(rows) == 1
        assert rows[0].first_seen_at.replace(tzinfo=timezone.utc) == first_seen
        assert rows[0].last_seen_at.replace(tzinfo=timezone.utc) == later
        assert rows[0].status == "new"

    def test_a_dismissed_memory_survives_being_seen_again_by_a_later_scan(self, session):
        """The whole point of the Listing Memory: a dismissed job stays dismissed when the next
        Scan finds it again."""
        jobs_repo.upsert_memory(session, "acme|backend engineer", status="dismissed")
        session.commit()

        reattached = jobs_repo.upsert_memory(session, "acme|backend engineer")

        assert reattached.status == "dismissed"

    def test_status_changed_at_moves_only_when_the_status_actually_changes(self, session):
        created = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
        changed = created + timedelta(days=1)
        rescanned = changed + timedelta(days=1)

        jobs_repo.upsert_memory(session, "acme|backend engineer", seen_at=created)
        jobs_repo.upsert_memory(session, "acme|backend engineer", status="seen", seen_at=changed)
        after_change = jobs_repo.upsert_memory(
            session, "acme|backend engineer", status="seen", seen_at=rescanned
        )

        assert after_change.status_changed_at.replace(tzinfo=timezone.utc) == changed
        assert after_change.last_seen_at.replace(tzinfo=timezone.utc) == rescanned

    def test_omitted_fields_are_kept_and_none_clears_them(self, session):
        jobs_repo.upsert_memory(
            session,
            "acme|backend engineer",
            fit_score=87,
            fit_description_hash="a" * 64,
            resume_version_id=3,
        )

        untouched = jobs_repo.upsert_memory(session, "acme|backend engineer", status="seen")
        assert untouched.fit_score == 87
        assert untouched.fit_description_hash == "a" * 64
        assert untouched.resume_version_id == 3

        # A Repost whose description changed: the stale score must go, so the listing re-enters
        # the LLM scoring stage instead of carrying a number computed for different text.
        invalidated = jobs_repo.upsert_memory(
            session, "acme|backend engineer", fit_score=None, fit_description_hash=None
        )
        assert invalidated.fit_score is None
        assert invalidated.fit_description_hash is None
        assert invalidated.resume_version_id == 3  # not asked about, not touched

    def test_get_memories_bulk_lookup_skips_identities_with_no_memory(self, session):
        jobs_repo.upsert_memory(session, "acme|backend engineer", status="applied")
        jobs_repo.upsert_memory(session, "globex|data engineer")
        session.commit()

        found = jobs_repo.get_memories(
            session, ["acme|backend engineer", "initech|qa analyst", "globex|data engineer"]
        )

        assert set(found) == {"acme|backend engineer", "globex|data engineer"}
        assert found["acme|backend engineer"].status == "applied"

    def test_get_memories_with_no_keys_hits_no_query(self, session):
        assert jobs_repo.get_memories(session, []) == {}

    def test_duplicate_identity_key_is_rejected_by_the_unique_index(self, session):
        jobs_repo.upsert_memory(session, "acme|backend engineer")
        session.add(ListingMemory(identity_key="acme|backend engineer"))

        with pytest.raises(IntegrityError):
            session.flush()

    def test_memory_survives_the_deletion_of_the_resume_version_it_points_at(self, session):
        """``resume_version_id`` is a soft ref (app/db/tables.py's module docstring): deleting
        the One-click Resume must not raise and must not cost the user the Listing Status or the
        Fit Score -- only the offer to download that PDF."""
        version = resume_repo.insert_version(session, data="{}")
        memory = jobs_repo.upsert_memory(
            session, "acme|backend engineer", status="applied", fit_score=91,
            resume_version_id=version.id,
        )
        session.commit()

        session.delete(version)
        session.commit()  # must not raise -- no real FK enforces this reference

        reloaded = jobs_repo.get_memory(session, "acme|backend engineer")
        assert reloaded.resume_version_id == memory.resume_version_id  # dangling, preserved
        assert resume_repo.get(session, reloaded.resume_version_id) is None
        assert reloaded.status == "applied"
        assert reloaded.fit_score == 91
