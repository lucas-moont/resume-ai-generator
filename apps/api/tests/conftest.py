from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import Session
from sqlmodel.pool import StaticPool

from app.db.engine import create_db_engine, init_db
from app.main import create_app
from app.routers import deps
from app.services import llm_client as llm_client_module
from app.services import streaming as streaming_module
from app.services import generation_service as generation_service_module

from tests.fakes import FakeLlm


@pytest.fixture(autouse=True)
def _fast_stream_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shrink the SSE heartbeat interval so streaming tests stay fast.

    As of B3, ``app.services.streaming.run_with_heartbeat`` checks task completion
    immediately (``asyncio.wait({task}, timeout=heartbeat_seconds)``), so an instant FakeLlm
    response no longer pays the ~5s-per-call tax the pre-B3 inline loops had (see the NOTE in
    ``tests/integration/test_generate_endpoints_compat.py`` for that history). This fixture is
    kept anyway as headroom for any test that simulates a slow LLM (multiple ticks before
    completion, or an actual timeout) so it still runs fast.

    As of B4, generation_service.py and refine_service.py both read the interval as
    ``streaming.HEARTBEAT_SECONDS`` (module-qualified), so patching it once on
    ``app.services.streaming`` shrinks it for both -- there is no longer a
    ``app.main.STREAM_HEARTBEAT_SECONDS`` (main.py is now just the app factory).
    """
    monkeypatch.setattr(streaming_module, "HEARTBEAT_SECONDS", 0.01)


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> FakeLlm:
    """Replace the LLM call used by the endpoints under test with a scripted fake.

    As of B3, every LLM call in the app (main.py's direct calls and
    extraction_service.extract_profile_from_text) goes through the module-qualified
    ``llm_client.chat_json(...)`` rather than a bare name bound per-importer, so patching the
    attribute on ``app.services.llm_client`` intercepts all of them from this single place.
    """
    fake = FakeLlm()
    monkeypatch.setattr(llm_client_module, "chat_json", fake)
    return fake


@pytest.fixture(autouse=True)
def isolated_data_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point profile/PDF/project-markdown resolution at an empty sandbox.

    Prevents tests from depending on the developer's real ``data/`` directory (real profile,
    real ``Profile.pdf``, real project markdown files). Autouse: ``/api/refine`` reads the
    profile PDF unconditionally, so even refine-only tests must not see the real
    ``data/profile/Profile.pdf`` that ships in this repo's working copy.
    """
    monkeypatch.setenv("PROFILE_JSON_PATH", str(tmp_path / "resume.json"))
    # A PDF path that does not exist makes load_profile_pdf_excerpt() return ("", None, None).
    monkeypatch.setenv("PROFILE_PDF_PATH", str(tmp_path / "no-profile.pdf"))
    # PROJECTS_DIR is read (module-qualified, at call time) only inside generation_service.py
    # as of B4 -- main.py no longer touches project markdown files at all.
    monkeypatch.setattr(generation_service_module, "PROJECTS_DIR", tmp_path / "projects")
    return tmp_path


@pytest.fixture
def write_profile(isolated_data_env: Path) -> Callable[[dict], Path]:
    def _write(profile: dict) -> Path:
        path = isolated_data_env / "resume.json"
        path.write_text(json.dumps(profile), encoding="utf-8")
        return path

    return _write


@pytest.fixture
def test_db_engine():
    """A fresh in-memory SQLite engine per test (StaticPool keeps the single in-memory DB
    alive across the multiple connections a Session/request cycle can open)."""
    engine = create_db_engine("sqlite://", poolclass=StaticPool)
    init_db(engine)
    return engine


@pytest.fixture
async def client(test_db_engine):
    """Builds a fresh app per test (not the module-level ``app.main.app`` singleton) and
    overrides ``deps.get_session`` to yield from an in-memory engine (B5). The legacy
    generate/refine/profile endpoints exercised by most of this suite don't depend on
    get_session at all yet (B6's chat routes are the first real consumer) -- this fixture
    exists so DB-backed tests and B6's future ones get the same isolated-per-test setup
    without needing their own client fixture, and so ASGITransport never touches the real
    on-disk data/app.db.
    """
    app = create_app()

    def _override_get_session():
        with Session(test_db_engine) as session:
            yield session

    app.dependency_overrides[deps.get_session] = _override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """Parse an SSE body (``event: x\\ndata: {...}\\n\\n`` frames) into ``(event, data)`` pairs."""
    events: list[tuple[str, dict]] = []
    for frame in text.split("\n\n"):
        if not frame.strip():
            continue
        event = None
        data_lines: list[str] = []
        for line in frame.splitlines():
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].strip())
        if event is None:
            continue
        data = json.loads("".join(data_lines)) if data_lines else {}
        events.append((event, data))
    return events


@pytest.fixture
def parse_sse() -> Callable[[str], list[tuple[str, dict]]]:
    return _parse_sse
