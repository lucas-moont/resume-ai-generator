"""Unit tests for the Source Document reaper (ticket 04, debt c): reconciling the two crash
windows the upload pipeline can leave behind (see app/services/ingestion/reaper.py's module
docstring for the full rationale) -- exercised here against an in-memory engine and a real
temp directory, with an injectable clock/threshold (never the real clock -- pre-agreed test
seam, ticket 04).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session
from sqlmodel.pool import StaticPool

from app.db.engine import create_db_engine, init_db
from app.repositories import source_document_repo
from app.services.ingestion import reaper


def _set_mtime(path, dt: datetime) -> None:
    """File mtimes are real UTC epoch seconds -- ``dt`` (this module's ``NOW``-relative, naive)
    must be interpreted as UTC explicitly, matching reaper.py's own ``_epoch_utc`` convention,
    or the comparison would silently depend on the host machine's local timezone."""
    ts = dt.replace(tzinfo=timezone.utc).timestamp()
    os.utime(path, (ts, ts))


@pytest.fixture
def engine():
    eng = create_db_engine("sqlite://", poolclass=StaticPool)
    init_db(eng)
    return eng


NOW = datetime(2026, 7, 11, 12, 0, 0)
STALE_AFTER = timedelta(hours=1)


def _insert_row(engine, *, status: str, created_at: datetime, stored_path: str = "p", sha256: str = "a" * 64):
    with Session(engine) as session:
        row = source_document_repo.insert(
            session,
            filename="a.json",
            media_type="json",
            sha256=sha256,
            size_bytes=1,
            stored_path=stored_path,
            status=status,
        )
        row.created_at = created_at
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


class TestStaleTransientRowsAreReaped:
    def test_a_row_stuck_in_stored_past_the_threshold_becomes_failed(self, engine):
        row_id = _insert_row(engine, status="stored", created_at=NOW - timedelta(hours=2))

        result = reaper.reconcile(engine, now=NOW, stale_after=STALE_AFTER)

        with Session(engine) as session:
            row = source_document_repo.get(session, row_id)
            assert row.status == "failed"
            assert row.error  # a recorded, actionable reason
        assert result["reapedRows"] == 1

    def test_a_row_stuck_in_extracted_past_the_threshold_becomes_failed(self, engine):
        row_id = _insert_row(engine, status="extracted", created_at=NOW - timedelta(hours=2))

        reaper.reconcile(engine, now=NOW, stale_after=STALE_AFTER)

        with Session(engine) as session:
            row = source_document_repo.get(session, row_id)
            assert row.status == "failed"

    def test_a_recent_transient_row_within_the_threshold_is_left_alone(self, engine):
        row_id = _insert_row(engine, status="stored", created_at=NOW - timedelta(minutes=10))

        result = reaper.reconcile(engine, now=NOW, stale_after=STALE_AFTER)

        with Session(engine) as session:
            row = source_document_repo.get(session, row_id)
            assert row.status == "stored"
        assert result["reapedRows"] == 0

    @pytest.mark.parametrize("status", ["proposed", "applied", "rejected", "failed"])
    def test_terminal_statuses_are_never_touched_regardless_of_age(self, engine, status):
        row_id = _insert_row(engine, status=status, created_at=NOW - timedelta(days=30))

        reaper.reconcile(engine, now=NOW, stale_after=STALE_AFTER)

        with Session(engine) as session:
            row = source_document_repo.get(session, row_id)
            assert row.status == status


class TestOrphanedUploadFilesAreSwept:
    def test_a_file_with_no_referencing_row_past_the_threshold_is_removed(self, engine, tmp_path):
        orphan = tmp_path / "deadbeef.json"
        orphan.write_text("{}")
        _set_mtime(orphan, NOW - timedelta(hours=2))

        result = reaper.reconcile(engine, now=NOW, stale_after=STALE_AFTER, uploads_dir=tmp_path)

        assert not orphan.exists()
        assert result["sweptFiles"] == 1

    def test_a_very_recent_unreferenced_file_is_left_alone(self, engine, tmp_path):
        """A file written moments ago could still be mid-upload (stored but the DB insert
        hasn't committed yet) -- the sweep must not race an in-flight request. Sets the file's
        mtime relative to the injected ``now`` (never the real wall clock) so the test is not
        coupled to whatever time it happens to run at."""
        fresh = tmp_path / "freshfile.json"
        fresh.write_text("{}")
        _set_mtime(fresh, NOW - timedelta(minutes=10))

        result = reaper.reconcile(engine, now=NOW, stale_after=STALE_AFTER, uploads_dir=tmp_path)

        assert fresh.exists()
        assert result["sweptFiles"] == 0

    def test_a_file_referenced_by_a_row_is_kept_regardless_of_age(self, engine, tmp_path):
        referenced = tmp_path / "referenced.json"
        referenced.write_text("{}")
        _set_mtime(referenced, NOW - timedelta(hours=2))
        _insert_row(
            engine,
            status="applied",
            created_at=NOW - timedelta(hours=2),
            stored_path=str(referenced),
        )

        result = reaper.reconcile(engine, now=NOW, stale_after=STALE_AFTER, uploads_dir=tmp_path)

        assert referenced.exists()
        assert result["sweptFiles"] == 0

    def test_a_missing_uploads_dir_is_a_no_op_not_an_error(self, engine, tmp_path):
        missing = tmp_path / "does-not-exist"

        result = reaper.reconcile(engine, now=NOW, stale_after=STALE_AFTER, uploads_dir=missing)

        assert result["sweptFiles"] == 0


class TestReconcileDefaults:
    def test_reconcile_with_no_args_runs_against_the_real_clock_and_configured_uploads_dir(
        self, engine, tmp_path, monkeypatch
    ):
        """Sanity check that the injectable params are genuinely optional (production callers
        -- main.py's lifespan -- call reconcile(engine) with no overrides) without needing to
        assert anything about real time itself."""
        monkeypatch.setenv("DATA_UPLOADS_DIR", str(tmp_path))

        result = reaper.reconcile(engine)

        assert result == {"reapedRows": 0, "sweptFiles": 0}
