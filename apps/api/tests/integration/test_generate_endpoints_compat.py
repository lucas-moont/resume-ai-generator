"""Characterization tests for the legacy /api/generate, /api/refine, /api/models etc.
endpoints (originally all defined inline in app/main.py; as of B4 they live in
app/routers/*.py + app/services/*.py, but the observable HTTP/SSE contract this file freezes
is unchanged).

These tests capture what the current implementation DOES (not an idealized spec) and act as
the oracle across the B2->B6 refactor: any divergence in path, status code, event sequence, or
payload shape here is a blocking regression. Nothing in this file calls a real LLM or hits the
network -- the LLM boundary (`app.services.llm_client.chat_json`) is replaced with
`tests.fakes.FakeLlm`, and profile/PDF/project-markdown resolution is sandboxed by the autouse
`isolated_data_env` fixture in `tests/conftest.py`.

NOTE -- a genuine quirk of the current heartbeat implementation, discovered while writing
these tests (not something B1 fixes, just documented here): `/api/generate/stream` and
`/api/refine/stream` poll the in-flight LLM task with
    while not task.done():
        await asyncio.sleep(STREAM_HEARTBEAT_SECONDS)
        ...
        yield stage(...)
Because `task.done()` is always False immediately after `asyncio.create_task(...)` (the task
has not had a chance to run yet), this loop *always* runs at least one iteration -- i.e. every
streamed LLM call re-emits one extra "calling_ai"/heartbeat `stage` event and sleeps a full
heartbeat interval -- even when the LLM responds instantly. In production
(STREAM_HEARTBEAT_SECONDS=5) this means every generate/refine stream request pays a minimum
~5s tax beyond actual LLM latency. `tests/conftest.py` shrinks the interval to 0.01s so this
suite stays fast; `_dedup_heartbeat_repeats` below collapses that one guaranteed repeat so
assertions target real pipeline transitions instead of the incidental repeat count.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.factories import make_profile, make_resume_payload

GENERIC_JOB_DESCRIPTION = (
    "We are hiring a friendly teammate to join our growing team. You will work closely "
    "with your colleagues and help us deliver great results for our customers."
)


def _dedup_heartbeat_repeats(events: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for event, data in events:
        if event == "stage" and out and out[-1][0] == "stage":
            prev = out[-1][1]
            if prev.get("step") == data.get("step") and prev.get("progress") == data.get("progress"):
                continue
        out.append((event, data))
    return out


def _stage_shape(events: list[tuple[str, dict]]) -> list[tuple[str, object, object]]:
    return [(event, data.get("step"), data.get("progress")) for event, data in events]


class TestHealthAndModels:
    async def test_health_returns_ok(self, client):
        resp = await client.get("/api/health")

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    async def test_list_models_returns_default_and_deduplicated_model_list(self, client, monkeypatch):
        from app.services import model_catalog as model_catalog_module

        async def fake_list_installed_models() -> list[str]:
            # "claude-sonnet-5" collides on purpose with a built-in suggestion, to pin down
            # the endpoint's dedup behavior.
            return ["llama3.2:latest", "claude-sonnet-5"]

        monkeypatch.setattr(model_catalog_module, "list_installed_models", fake_list_installed_models)

        resp = await client.get("/api/models")

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["default"], str) and body["default"]
        assert isinstance(body["models"], list) and body["models"]
        for m in body["models"]:
            assert set(m.keys()) == {"value", "label"}
            assert isinstance(m["value"], str) and isinstance(m["label"], str)
        values = [m["value"] for m in body["models"]]
        assert values.count("claude-sonnet-5") == 1
        assert "llama3.2:latest" in values


class TestGenerateEndpoint:
    async def test_happy_path_returns_resume_without_a_second_llm_call(
        self, client, fake_llm, write_profile
    ):
        profile = make_profile()
        write_profile(profile)
        strong_resume = make_resume_payload()
        fake_llm.queue(json.dumps(strong_resume))

        resp = await client.post(
            "/api/generate", json={"job_description": GENERIC_JOB_DESCRIPTION}
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["fullName"] == profile["fullName"]
        assert body["summary"] == strong_resume["summary"]
        assert len(body["experience"][0]["highlights"]) == 3
        assert fake_llm.call_count == 1  # zero quality issues -> no auto-refine pass

    async def test_weak_draft_triggers_one_auto_refine_call(self, client, fake_llm, write_profile):
        write_profile(make_profile())
        weak_patch = make_resume_payload(
            summary="Resumo curto.",
            experience=[
                {
                    "company": "Acme Corp",
                    "title": "Senior Backend Engineer",
                    "location": "Remote",
                    "start": "2021",
                    "end": None,
                    "highlights": ["Did stuff"],
                }
            ],
        )
        strong_resume = make_resume_payload()
        fake_llm.queue(json.dumps(weak_patch), json.dumps(strong_resume))

        resp = await client.post(
            "/api/generate", json={"job_description": GENERIC_JOB_DESCRIPTION}
        )

        assert resp.status_code == 200
        body = resp.json()
        assert fake_llm.call_count == 2  # the quality guard consumed the 2nd scripted reply
        assert body["summary"] == strong_resume["summary"]
        assert body["summary"] != "Resumo curto."
        assert len(body["experience"][0]["highlights"]) == 3


class TestGenerateStreamEndpoint:
    async def test_happy_path_event_sequence(self, client, fake_llm, write_profile, parse_sse):
        write_profile(make_profile())
        strong_resume = make_resume_payload()
        fake_llm.queue(json.dumps(strong_resume))

        resp = await client.post(
            "/api/generate/stream", json={"job_description": GENERIC_JOB_DESCRIPTION}
        )

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")

        events = _dedup_heartbeat_repeats(parse_sse(resp.text))
        assert _stage_shape(events) == [
            ("stage", "preparing_context", 10),
            ("stage", "preparing_context", 35),
            ("stage", "calling_ai", 60),
            ("stage", "validating_response", 85),
            ("stage", "finalizing", 95),
            ("done", None, 100),
        ]
        progresses = [data["progress"] for _, data in events]
        assert progresses == sorted(progresses)  # monotonically non-decreasing
        for event, data in events[:-1]:
            assert isinstance(data.get("message"), str) and data["message"]

        assert events[-1][1]["resume"]["fullName"] == "Ana Costa"
        assert fake_llm.call_count == 1

    async def test_weak_draft_adds_a_quality_pass_stage(self, client, fake_llm, write_profile, parse_sse):
        write_profile(make_profile())
        weak_patch = make_resume_payload(
            summary="Resumo curto.",
            experience=[
                {
                    "company": "Acme Corp",
                    "title": "Senior Backend Engineer",
                    "location": "Remote",
                    "start": "2021",
                    "end": None,
                    "highlights": ["Did stuff"],
                }
            ],
        )
        strong_resume = make_resume_payload()
        fake_llm.queue(json.dumps(weak_patch), json.dumps(strong_resume))

        resp = await client.post(
            "/api/generate/stream", json={"job_description": GENERIC_JOB_DESCRIPTION}
        )

        assert resp.status_code == 200
        events = _dedup_heartbeat_repeats(parse_sse(resp.text))
        assert _stage_shape(events) == [
            ("stage", "preparing_context", 10),
            ("stage", "preparing_context", 35),
            ("stage", "calling_ai", 60),
            ("stage", "validating_response", 85),
            ("stage", "validating_response", 90),  # "Applying automatic quality pass"
            ("stage", "finalizing", 95),
            ("done", None, 100),
        ]
        progresses = [data["progress"] for _, data in events]
        assert progresses == sorted(progresses)
        assert events[-1][1]["resume"]["summary"] == strong_resume["summary"]
        assert fake_llm.call_count == 2

    async def test_llm_error_emits_error_event_with_secret_redacted(
        self, client, fake_llm, write_profile, parse_sse, monkeypatch
    ):
        write_profile(make_profile())
        secret = "sk-ant-fake-secret-0123456789abcdef"  # pragma: allowlist secret
        monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
        fake_llm.queue(RuntimeError(f"upstream rejected the request: {secret}"))

        resp = await client.post(
            "/api/generate/stream", json={"job_description": GENERIC_JOB_DESCRIPTION}
        )

        assert resp.status_code == 200  # StreamingResponse always starts with 200
        assert secret not in resp.text
        events = parse_sse(resp.text)
        assert events[-1][0] == "error"
        assert "«redacted»" in events[-1][1]["message"]


class TestGeneratePlaceholderExtraction:
    """The B4 refactor split /api/generate's "profile looks like the placeholder -> extract
    from Profile.pdf" branch across profile_service.py and generation_service.py. These tests
    exercise that branch specifically: an earlier version of the B4 refactor pre-formatted the
    extraction-error message inside generation_service.py AND let the router's generic
    except-Exception wrap it a second time, producing a doubled "LLM error (...): LLM error
    (...) extracting Profile.pdf: ..." message -- a real bug the B1-era tests (which only ever
    use a populated, non-placeholder profile) could not have caught. These tests would fail
    against that regression.
    """

    def _write_placeholder_profile(self, write_profile) -> None:
        write_profile(
            make_profile(fullName="Alex Sample", summary="Replace this text with your real summary.")
        )

    def _mock_pdf_excerpt(self, monkeypatch, text: str = "Real PDF text about the candidate.") -> None:
        from app.services import profile_service as profile_service_module

        monkeypatch.setattr(
            profile_service_module,
            "load_profile_pdf_excerpt",
            lambda: (text, Path("/fake/Profile.pdf"), None),
        )

    async def test_extracts_profile_and_generates_normally(
        self, client, fake_llm, write_profile, monkeypatch
    ):
        self._write_placeholder_profile(write_profile)
        self._mock_pdf_excerpt(monkeypatch)
        extracted = make_resume_payload()
        fake_llm.queue(json.dumps(extracted), json.dumps(extracted))  # extraction, then generate

        resp = await client.post("/api/generate", json={"job_description": GENERIC_JOB_DESCRIPTION})

        assert resp.status_code == 200
        body = resp.json()
        assert body["fullName"] == extracted["fullName"]
        assert fake_llm.call_count == 2

    async def test_extraction_failure_is_a_single_wrapped_502(
        self, client, fake_llm, write_profile, monkeypatch
    ):
        self._write_placeholder_profile(write_profile)
        self._mock_pdf_excerpt(monkeypatch)
        fake_llm.queue(RuntimeError("upstream boom"))

        resp = await client.post("/api/generate", json={"job_description": GENERIC_JOB_DESCRIPTION})

        assert resp.status_code == 502
        detail = resp.json()["detail"]
        assert detail.count("LLM error (") == 1  # would be 2 under the double-wrap regression
        assert "extracting Profile.pdf" in detail
        assert "upstream boom" in detail

    async def test_extraction_failure_stream_error_is_a_single_wrapped_message(
        self, client, fake_llm, write_profile, parse_sse, monkeypatch
    ):
        self._write_placeholder_profile(write_profile)
        self._mock_pdf_excerpt(monkeypatch)
        fake_llm.queue(RuntimeError("upstream boom"))

        resp = await client.post(
            "/api/generate/stream", json={"job_description": GENERIC_JOB_DESCRIPTION}
        )

        events = parse_sse(resp.text)
        assert events[-1][0] == "error"
        message = events[-1][1]["message"]
        assert message.count("LLM error (") == 1
        assert "extracting Profile.pdf" in message
        assert "upstream boom" in message


class TestRefineEndpoint:
    async def test_happy_path_returns_updated_resume(self, client, fake_llm):
        resume = make_resume_payload()
        updated = make_resume_payload(
            summary="Updated summary reflecting the requested change to the resume."
        )
        fake_llm.queue(json.dumps(updated))

        resp = await client.post(
            "/api/refine",
            json={"resume": resume, "message": "Make the summary punchier."},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["summary"] == updated["summary"]
        assert fake_llm.call_count == 1


class TestRefineStreamEndpoint:
    async def test_happy_path_event_sequence(self, client, fake_llm, parse_sse):
        resume = make_resume_payload()
        updated = make_resume_payload(
            summary="Updated summary reflecting the requested change to the resume."
        )
        fake_llm.queue(json.dumps(updated))

        resp = await client.post(
            "/api/refine/stream",
            json={"resume": resume, "message": "Make the summary punchier."},
        )

        assert resp.status_code == 200
        events = _dedup_heartbeat_repeats(parse_sse(resp.text))
        assert _stage_shape(events) == [
            ("stage", "preparing_context", 20),
            ("stage", "calling_ai", 60),
            ("stage", "validating_response", 85),
            ("done", None, 100),
        ]
        progresses = [data["progress"] for _, data in events]
        assert progresses == sorted(progresses)
        assert events[-1][1]["resume"]["summary"] == updated["summary"]
        assert fake_llm.call_count == 1


class TestExportPdfEndpoint:
    async def test_invalid_template_is_rejected_before_rendering(self, client):
        # PdfExportRequest.template is a Literal[...]; pydantic rejects an out-of-set value at
        # the request-body validation stage, before render_resume_pdf()/Playwright ever runs.
        resp = await client.post(
            "/api/export/pdf",
            json={"resume": make_resume_payload(), "template": "totally-invalid-template"},
        )

        assert resp.status_code == 422

    @pytest.mark.e2e
    async def test_renders_a_real_pdf_smoke(self, client):
        resp = await client.post(
            "/api/export/pdf",
            json={"resume": make_resume_payload(), "template": "modern"},
        )

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content.startswith(b"%PDF")
