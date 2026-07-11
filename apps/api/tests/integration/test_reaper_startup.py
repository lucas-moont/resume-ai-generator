"""Integration test for wiring the Source Document reaper into app startup (ticket 04, debt c):
``app.main``'s lifespan calls ``services.ingestion.reaper.reconcile(engine)`` (real clock, no
overrides) right after ``init_db``/the profile seed, before the app ever serves a request.

Same approach as tests/integration/test_db_lifespan.py: calls ``app.main.lifespan(app)`` directly
(a plain async context manager) rather than through an ASGI transport -- httpx's ASGITransport
does not trigger the ASGI lifespan protocol by default, and this has no HTTP-observable surface
anyway. Kept in its own file for the same collision-avoidance reason as
test_document_session_link.py.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from sqlmodel import Session

from app import config as config_module
from app.main import lifespan
from app.repositories import source_document_repo


def _use_tmp_sqlite_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        config_module, "DATABASE_URL", f"sqlite:///{(tmp_path / 'app.db').as_posix()}"
    )


async def test_a_row_stuck_transient_from_a_previous_boot_is_reaped_on_the_next_startup(
    tmp_path, monkeypatch
):
    _use_tmp_sqlite_file(tmp_path, monkeypatch)
    monkeypatch.setenv("PROFILE_JSON_PATH", str(tmp_path / "resume.json"))

    app = FastAPI()
    async with lifespan(app):
        with Session(app.state.db_engine) as session:
            row = source_document_repo.insert(
                session,
                filename="a.json",
                media_type="json",
                sha256="a" * 64,
                size_bytes=1,
                stored_path="p",
                status="stored",
            )
            session.commit()
            row_id = row.id
        # Backdates the row past the reaper's default staleness threshold, simulating a crash
        # during THIS boot's in-flight upload -- the NEXT boot's reconcile() must catch it.
        with Session(app.state.db_engine) as session:
            row = source_document_repo.get(session, row_id)
            row.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)
            session.add(row)
            session.commit()

    # Second boot, simulating a server restart against the same on-disk DB.
    async with lifespan(app):
        with Session(app.state.db_engine) as session:
            row = source_document_repo.get(session, row_id)
            assert row.status == "failed"
            assert row.error


async def test_an_orphaned_upload_file_from_a_previous_boot_is_swept_on_the_next_startup(
    tmp_path, monkeypatch
):
    _use_tmp_sqlite_file(tmp_path, monkeypatch)
    monkeypatch.setenv("PROFILE_JSON_PATH", str(tmp_path / "resume.json"))
    uploads_dir = tmp_path / "uploads"
    monkeypatch.setenv("DATA_UPLOADS_DIR", str(uploads_dir))

    app = FastAPI()
    async with lifespan(app):
        pass

    uploads_dir.mkdir(parents=True, exist_ok=True)
    orphan = uploads_dir / "deadbeef.json"
    orphan.write_text("{}")
    old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).timestamp()
    os.utime(orphan, (old_time, old_time))

    async with lifespan(app):
        pass

    assert not orphan.exists()


async def test_a_freshly_written_file_from_the_current_boot_is_not_swept(tmp_path, monkeypatch):
    """The startup reconcile() call itself must never sweep a file the SAME boot's request just
    wrote a moment before this test's own assertions run -- the mtime-based staleness guard
    (reaper.py) protects exactly this race."""
    _use_tmp_sqlite_file(tmp_path, monkeypatch)
    monkeypatch.setenv("PROFILE_JSON_PATH", str(tmp_path / "resume.json"))
    uploads_dir = tmp_path / "uploads"
    monkeypatch.setenv("DATA_UPLOADS_DIR", str(uploads_dir))
    uploads_dir.mkdir(parents=True, exist_ok=True)
    fresh = uploads_dir / "fresh.json"
    fresh.write_text("{}")

    app = FastAPI()
    async with lifespan(app):
        pass

    assert fresh.exists()
