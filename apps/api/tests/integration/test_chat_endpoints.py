"""Characterization/contract tests for the B6 chat endpoints (docs/v1-chat-experience.md
"Contrato de API do chat"). Session/message/resume persistence goes through the B5
repositories against the in-memory engine wired in tests/conftest.py's ``client`` fixture
(dependency_overrides on deps.get_session) -- no real data/app.db is ever touched.

Intent routing is deterministic (docs/v1-chat-experience.md): no active resume + message
looks like a job description -> generate; active resume exists -> refine (with recent chat
history folded into the refine instruction); neither -> a canned "question" reply with no LLM
call at all.
"""

from __future__ import annotations

import json

from tests.factories import make_profile, make_resume_payload

GENERIC_JOB_DESCRIPTION = (
    "We are hiring a Senior Backend Engineer to join our platform team. You will design "
    "and build scalable APIs in Python, own our PostgreSQL data layer, collaborate with "
    "the frontend team on GraphQL contracts, and help mentor junior engineers. Experience "
    "with Docker, Kubernetes, and CI/CD pipelines is a strong plus. We value clear written "
    "communication and a pragmatic approach to shipping reliable software."
)


def _stage_shape(events: list[tuple[str, dict]]) -> list[tuple[str, object, object]]:
    return [(event, data.get("step"), data.get("progress")) for event, data in events]


class TestChatSessionCrud:
    async def test_create_session_returns_201_with_id_title_created_at(self, client):
        resp = await client.post("/api/chat/sessions", json={"title": "My resume chat"})

        assert resp.status_code == 201
        body = resp.json()
        assert isinstance(body["id"], int)
        assert body["title"] == "My resume chat"
        assert "createdAt" in body

    async def test_create_session_without_title(self, client):
        resp = await client.post("/api/chat/sessions", json={})

        assert resp.status_code == 201
        assert resp.json()["title"] is None

    async def test_list_sessions_orders_by_updated_at_desc(self, client):
        await client.post("/api/chat/sessions", json={"title": "First"})
        await client.post("/api/chat/sessions", json={"title": "Second"})

        resp = await client.get("/api/chat/sessions")

        assert resp.status_code == 200
        sessions = resp.json()["sessions"]
        assert [s["title"] for s in sessions] == ["Second", "First"]
        assert set(sessions[0].keys()) == {"id", "title", "updatedAt", "activeResumeVersionId"}

    async def test_get_session_returns_session_messages_and_null_active_resume(self, client):
        created = (await client.post("/api/chat/sessions", json={"title": "Fresh"})).json()

        resp = await client.get(f"/api/chat/sessions/{created['id']}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["session"]["id"] == created["id"]
        assert body["messages"] == []
        assert body["activeResume"] is None

    async def test_get_session_detail_includes_locale_job_description_and_created_at(self, client):
        # The single-session GET is a SUPERSET of the list endpoint's compact shape (frozen
        # contract): {id, title, updatedAt, activeResumeVersionId} plus locale, jobDescription,
        # createdAt -- the frontend composer needs these (e.g. to default the input language).
        created = (await client.post("/api/chat/sessions", json={"title": "Fresh"})).json()

        resp = await client.get(f"/api/chat/sessions/{created['id']}")

        session_obj = resp.json()["session"]
        assert set(session_obj.keys()) == {
            "id", "title", "updatedAt", "activeResumeVersionId", "locale", "jobDescription", "createdAt",
        }
        assert session_obj["createdAt"] == created["createdAt"]
        assert session_obj["locale"] is None
        assert session_obj["jobDescription"] is None

    async def test_get_missing_session_is_404(self, client):
        resp = await client.get("/api/chat/sessions/999999")
        assert resp.status_code == 404

    async def test_delete_session_returns_204_and_then_404(self, client):
        created = (await client.post("/api/chat/sessions", json={})).json()

        resp = await client.delete(f"/api/chat/sessions/{created['id']}")
        assert resp.status_code == 204

        resp = await client.get(f"/api/chat/sessions/{created['id']}")
        assert resp.status_code == 404

    async def test_delete_missing_session_is_404(self, client):
        resp = await client.delete("/api/chat/sessions/999999")
        assert resp.status_code == 404


class TestChatMessageStreamGenerateIntent:
    async def test_pasting_a_job_description_with_no_active_resume_generates(
        self, client, fake_llm, write_profile, parse_sse
    ):
        write_profile(make_profile())
        strong_resume = make_resume_payload()
        fake_llm.queue(json.dumps(strong_resume))
        created = (await client.post("/api/chat/sessions", json={})).json()

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": GENERIC_JOB_DESCRIPTION},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        kinds = [e for e, _ in events]
        assert "resume" in kinds
        assert "message" in kinds
        assert kinds[-1] == "done"

        resume_event = next(data for e, data in events if e == "resume")
        assert resume_event["resume"]["fullName"] == strong_resume["fullName"]
        assert isinstance(resume_event["resumeVersionId"], int)

        message_event = next(data for e, data in events if e == "message")
        assert isinstance(message_event["content"], str) and message_event["content"]

        done_event = next(data for e, data in events if e == "done")
        assert done_event["resumeVersionId"] == resume_event["resumeVersionId"]
        assert isinstance(done_event["messageId"], int)
        assert fake_llm.call_count == 1

    async def test_generate_turn_updates_the_session_active_resume_and_history(
        self, client, fake_llm, write_profile
    ):
        write_profile(make_profile())
        strong_resume = make_resume_payload()
        fake_llm.queue(json.dumps(strong_resume))
        created = (await client.post("/api/chat/sessions", json={})).json()

        await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": GENERIC_JOB_DESCRIPTION},
        )

        resp = await client.get(f"/api/chat/sessions/{created['id']}")
        body = resp.json()
        assert body["activeResume"]["fullName"] == strong_resume["fullName"]
        assert body["session"]["activeResumeVersionId"] is not None
        roles = [m["role"] for m in body["messages"]]
        assert roles == ["user", "assistant"]
        assert body["messages"][0]["content"] == GENERIC_JOB_DESCRIPTION
        assert body["messages"][1]["resumeVersionId"] == body["session"]["activeResumeVersionId"]

    async def test_generate_turn_persists_locale_and_job_description_on_the_session(
        self, client, fake_llm, write_profile
    ):
        write_profile(make_profile())
        fake_llm.queue(json.dumps(make_resume_payload()))
        created = (await client.post("/api/chat/sessions", json={})).json()

        await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": GENERIC_JOB_DESCRIPTION, "locale": "en"},
        )

        body = (await client.get(f"/api/chat/sessions/{created['id']}")).json()
        assert body["session"]["locale"] == "en"
        assert body["session"]["jobDescription"] == GENERIC_JOB_DESCRIPTION

    async def test_generate_confirmation_follows_the_resulting_resume_locale(
        self, client, fake_llm, write_profile, parse_sse
    ):
        write_profile(make_profile())
        fake_llm.queue(json.dumps(make_resume_payload(locale="pt-BR")))
        created = (await client.post("/api/chat/sessions", json={})).json()

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": GENERIC_JOB_DESCRIPTION},
        )

        message_event = next(data for e, data in parse_sse(resp.text) if e == "message")
        assert message_event["content"] == "Currículo gerado com base na vaga."


class TestChatMessageStreamRefineIntent:
    async def test_a_short_instruction_refines_the_active_resume(
        self, client, fake_llm, write_profile, parse_sse
    ):
        write_profile(make_profile())
        strong_resume = make_resume_payload()
        fake_llm.queue(json.dumps(strong_resume))  # the generate turn
        created = (await client.post("/api/chat/sessions", json={})).json()
        await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": GENERIC_JOB_DESCRIPTION},
        )

        updated = make_resume_payload(summary="A punchier summary for the resume.")
        fake_llm.queue(json.dumps(updated))  # the refine turn

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "Make the summary punchier."},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        resume_event = next(data for e, data in events if e == "resume")
        assert resume_event["resume"]["summary"] == updated["summary"]
        assert fake_llm.call_count == 2  # 1 generate + 1 refine

        # The new resume version is a distinct, later version than the generate turn's.
        after = (await client.get(f"/api/chat/sessions/{created['id']}")).json()
        assert after["session"]["activeResumeVersionId"] == resume_event["resumeVersionId"]
        assert after["activeResume"]["summary"] == updated["summary"]

    async def test_refine_confirmation_follows_the_resulting_resume_locale_not_the_session_locale(
        self, client, fake_llm, write_profile, parse_sse
    ):
        # Real QA-found bug: pt-BR resume, user asks to translate it to English. The document
        # correctly flips to locale="en", but the confirmation bubble used to stay in
        # Portuguese because it derived its language from the session/request locale (still
        # unset/pt-BR here) instead of the resulting resume's own locale field.
        write_profile(make_profile())
        fake_llm.queue(json.dumps(make_resume_payload(locale="pt-BR")))
        created = (await client.post("/api/chat/sessions", json={})).json()
        await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": GENERIC_JOB_DESCRIPTION},  # no explicit locale in the request
        )

        translated = make_resume_payload(locale="en", summary="An English-language summary.")
        fake_llm.queue(json.dumps(translated))

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "Translate the resume to English."},
        )

        events = parse_sse(resp.text)
        resume_event = next(data for e, data in events if e == "resume")
        assert resume_event["resume"]["locale"] == "en"
        message_event = next(data for e, data in events if e == "message")
        assert message_event["content"] == "Updated your resume."

    async def test_refine_folds_recent_history_into_the_llm_instruction(
        self, client, fake_llm, write_profile
    ):
        write_profile(make_profile())
        strong_resume = make_resume_payload()
        fake_llm.queue(json.dumps(strong_resume))
        created = (await client.post("/api/chat/sessions", json={})).json()
        await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": GENERIC_JOB_DESCRIPTION},
        )

        updated = make_resume_payload(summary="A punchier summary for the resume.")
        fake_llm.queue(json.dumps(updated))
        await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "Make the summary punchier."},
        )

        refine_call = fake_llm.calls[-1]
        assert GENERIC_JOB_DESCRIPTION[:40] in refine_call["user"]
        assert "Make the summary punchier." in refine_call["user"]


class TestChatMessageStreamQuestionIntent:
    async def test_a_short_greeting_with_no_active_resume_does_not_call_the_llm(
        self, client, fake_llm, parse_sse
    ):
        created = (await client.post("/api/chat/sessions", json={})).json()

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "hi there"},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        kinds = [e for e, _ in events]
        assert "resume" not in kinds
        assert "message" in kinds
        assert kinds[-1] == "done"
        done_event = next(data for e, data in events if e == "done")
        assert done_event["resumeVersionId"] is None
        assert fake_llm.call_count == 0


class TestChatMessageStreamErrors:
    async def test_generate_llm_error_emits_redacted_error_event(
        self, client, fake_llm, write_profile, parse_sse, monkeypatch
    ):
        write_profile(make_profile())
        secret = "sk-ant-fake-chat-secret-0123456789abcdef"  # pragma: allowlist secret
        monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
        fake_llm.queue(RuntimeError(f"upstream rejected the request: {secret}"))
        created = (await client.post("/api/chat/sessions", json={})).json()

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": GENERIC_JOB_DESCRIPTION},
        )

        assert resp.status_code == 200
        assert secret not in resp.text
        events = parse_sse(resp.text)
        assert events[-1][0] == "error"
        assert "«redacted»" in events[-1][1]["message"]

    async def test_message_stream_for_missing_session_is_404(self, client):
        resp = await client.post(
            "/api/chat/sessions/999999/messages/stream",
            json={"message": "hi"},
        )
        assert resp.status_code == 404
