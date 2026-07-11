from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import Session
from sqlmodel.pool import StaticPool

from app import config as config_module
from app.db.engine import create_db_engine, init_db
from app.main import create_app
from app.routers import deps
from app.services import llm_client as llm_client_module
from app.services import model_catalog as model_catalog_module
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
    # v2 ticket 03: Source Document uploads land under DATA_UPLOADS_DIR (read at call time by
    # app.services.ingestion.storage) -- sandboxed so upload tests never touch the real
    # data/uploads/ directory.
    monkeypatch.setenv("DATA_UPLOADS_DIR", str(tmp_path / "uploads"))
    return tmp_path


@pytest.fixture
def write_profile(isolated_data_env: Path) -> Callable[[dict], Path]:
    def _write(profile: dict) -> Path:
        path = isolated_data_env / "resume.json"
        path.write_text(json.dumps(profile), encoding="utf-8")
        return path

    return _write


def _blackhole_transport_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError(
        "network access is disabled in tests by default (see "
        "_no_real_network_for_model_catalog in tests/conftest.py)",
        request=request,
    )


@pytest.fixture(autouse=True)
def _no_real_network_for_model_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """v3 ticket 03: the dynamic model catalog makes a real HTTP call (Anthropic/Gemini/Ollama
    listing) whenever a usable key/server is configured -- and this repo's own root ``.env``
    ships a real ``GEMINI_API_KEY`` (loaded into the process env by ``app.config`` at import
    time), so simply not mocking anything would let a test make a genuine call to Google's API
    with that real key. This autouse fixture forces every test onto a transport that always
    fails closed (the catalog degrades to its static fallback / reports Ollama unreachable),
    regardless of what secrets happen to be configured (env OR OS keychain) on the machine
    running the suite. Tests exercising the real success/failure parsing paths (see
    tests/unit/test_model_catalog.py) explicitly monkeypatch ``model_catalog._transport`` to
    their own ``httpx.MockTransport``, which simply overrides this default for their scope.
    """
    monkeypatch.setattr(
        model_catalog_module, "_transport", httpx.MockTransport(_blackhole_transport_handler)
    )
    model_catalog_module.invalidate_catalog_cache()


@pytest.fixture(autouse=True)
def isolated_runtime_settings_engine():
    """Point config.py's app_settings resolution (get_runtime_config, set/delete_app_setting)
    at a throwaway in-memory DB for every test (v3 ticket 01).

    Without this, any test that transitively calls get_runtime_config() -- e.g. GET /api/models
    -> model_catalog.default_model_for_active_backend() -> resolve_active_provider() -- falls
    through to config._get_settings_engine()'s lazy default, which opens a real engine on
    config.DATABASE_URL: the actual on-disk data/app.db this repo ships with. That bit a real
    test run while building this fixture (empty app_settings table created on disk, no rows --
    see tests/unit/test_runtime_config_isolation.py for the regression test). set_settings_engine
    is the test seam, module-qualified like resolve_uploads_dir/test_db_engine above.
    """
    engine = create_db_engine("sqlite://", poolclass=StaticPool)
    init_db(engine)
    config_module.set_settings_engine(engine)
    yield engine
    config_module.set_settings_engine(None)


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
