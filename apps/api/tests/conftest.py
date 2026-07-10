from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest
from httpx import ASGITransport, AsyncClient

from app import main as main_module
from app.main import app as fastapi_app
from app.services import llm_client as llm_client_module

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
    """
    monkeypatch.setattr(main_module, "STREAM_HEARTBEAT_SECONDS", 0.01)


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
    monkeypatch.setattr(main_module, "PROJECTS_DIR", tmp_path / "projects")
    return tmp_path


@pytest.fixture
def write_profile(isolated_data_env: Path) -> Callable[[dict], Path]:
    def _write(profile: dict) -> Path:
        path = isolated_data_env / "resume.json"
        path.write_text(json.dumps(profile), encoding="utf-8")
        return path

    return _write


@pytest.fixture
async def client():
    transport = ASGITransport(app=fastapi_app)
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
