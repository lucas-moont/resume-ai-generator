"""Integration tests for the B5 lifespan: real SQLite file/table creation and the
profile-from-disk seed step (app/db/seed.py, wired into app/main.py's lifespan).

Calls app.main.lifespan(app) directly (a plain async context manager) rather than driving it
through an ASGI transport -- httpx's ASGITransport does not trigger the ASGI lifespan
protocol by default, and the seed step has no HTTP-observable surface anyway.

app.db.engine.create_db_engine() resolves its default URL from ``app.config.DATABASE_URL`` at
CALL time (module-qualified access, not a function-default value), specifically so
monkeypatching it here reaches the no-arg ``create_db_engine()`` call inside main.py's
lifespan -- see that module's docstring.
"""

from __future__ import annotations

import json

from fastapi import FastAPI
from sqlmodel import Session

from app import config as config_module
from app.main import lifespan
from app.repositories import profile_repo
from tests.factories import make_profile


def _use_tmp_sqlite_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        config_module, "DATABASE_URL", f"sqlite:///{(tmp_path / 'app.db').as_posix()}"
    )


async def test_lifespan_creates_the_sqlite_file_and_tables_with_no_profile_on_disk(
    tmp_path, monkeypatch
):
    _use_tmp_sqlite_file(tmp_path, monkeypatch)
    monkeypatch.setenv("PROFILE_JSON_PATH", str(tmp_path / "resume.json"))  # does not exist

    app = FastAPI()
    async with lifespan(app):
        assert (tmp_path / "app.db").is_file()
        with Session(app.state.db_engine) as session:
            assert profile_repo.get_active(session) is None


async def test_lifespan_seeds_v1_from_a_real_profile_on_disk(tmp_path, monkeypatch):
    _use_tmp_sqlite_file(tmp_path, monkeypatch)
    profile_path = tmp_path / "resume.json"
    profile_path.write_text(json.dumps(make_profile()), encoding="utf-8")
    monkeypatch.setenv("PROFILE_JSON_PATH", str(profile_path))

    app = FastAPI()
    async with lifespan(app):
        with Session(app.state.db_engine) as session:
            active = profile_repo.get_active(session)
            assert active is not None
            assert active.version == 1
            assert active.source_kind == "seed_disk"
            assert active.change_summary == "seed from disk"
            assert json.loads(active.data)["fullName"] == "Ana Costa"


async def test_lifespan_does_not_seed_a_placeholder_profile(tmp_path, monkeypatch):
    _use_tmp_sqlite_file(tmp_path, monkeypatch)
    profile_path = tmp_path / "resume.json"
    profile_path.write_text(
        json.dumps(
            make_profile(fullName="Alex Sample", summary="Replace this text with your real summary.")
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROFILE_JSON_PATH", str(profile_path))

    app = FastAPI()
    async with lifespan(app):
        with Session(app.state.db_engine) as session:
            assert profile_repo.get_active(session) is None


async def test_lifespan_does_not_reseed_on_a_second_boot(tmp_path, monkeypatch):
    _use_tmp_sqlite_file(tmp_path, monkeypatch)
    profile_path = tmp_path / "resume.json"
    profile_path.write_text(json.dumps(make_profile()), encoding="utf-8")
    monkeypatch.setenv("PROFILE_JSON_PATH", str(profile_path))

    app = FastAPI()
    async with lifespan(app):
        pass
    # A second boot against the SAME sqlite file (simulating a server restart) must not
    # insert a second seed row.
    async with lifespan(app):
        with Session(app.state.db_engine) as session:
            active = profile_repo.get_active(session)
            assert active is not None
            assert active.version == 1
