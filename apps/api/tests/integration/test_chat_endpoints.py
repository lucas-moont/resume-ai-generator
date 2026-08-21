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

import pytest
from sqlmodel import Session, select

from app.db.tables import ChatSession, ResumeVersion
from app.domain.schemas import GitHubRepoInfo
from app.repositories import chat_repo, profile_repo, resume_repo
from app.services import refine_service as refine_service_module
from tests.factories import make_profile, make_resume_payload

PHONE_UPDATE_MESSAGE_PT = "Mudei meu telefone para 11 98888-7777"
REMOVE_EXPERIENCE_MESSAGE_PT = "Remove a experiência na Acme Corp do meu perfil"

GENERIC_JOB_DESCRIPTION = (
    "We are hiring a Senior Backend Engineer to join our platform team. You will design "
    "and build scalable APIs in Python, own our PostgreSQL data layer, collaborate with "
    "the frontend team on GraphQL contracts, and help mentor junior engineers. Experience "
    "with Docker, Kubernetes, and CI/CD pipelines is a strong plus. We value clear written "
    "communication and a pragmatic approach to shipping reliable software."
)


def _stage_shape(events: list[tuple[str, dict]]) -> list[tuple[str, object, object]]:
    return [(event, data.get("step"), data.get("progress")) for event, data in events]


def _seed_active_resume(
    test_db_engine, session_id: int, resume_payload: dict, *, job_description: str = GENERIC_JOB_DESCRIPTION
) -> int:
    """v4 ticket B3: pasting a job description in chat no longer generates a resume directly --
    it runs the Analysis and proposes changes instead (``chat_service._handle_propose_turn``);
    an active resume now only exists once a proposal has been approved (ticket B5, not yet
    wired up). The tests below are about turns that assume an ALREADY-active resume (refine,
    profile_update); this recreates, directly against the DB, exactly the session shape a
    completed pre-v4 generate turn used to leave behind -- the JD as the user's first chat
    message (so history-folding tests still see it), a resume version, an assistant
    confirmation referencing it, and the session's ``active_resume_version_id`` pointed at it --
    without depending on the (now proposal-producing) chat endpoint or spending a queued
    ``fake_llm`` response on a turn that isn't the one under test.
    """
    with Session(test_db_engine) as session:
        chat_repo.append_message(session, session_id=session_id, role="user", content=job_description)
        resume_row = resume_repo.insert_version(
            session, data=json.dumps(resume_payload), session_id=session_id, provider_used="fake"
        )
        chat_repo.append_message(
            session,
            session_id=session_id,
            role="assistant",
            content="Generated a tailored resume for this job description.",
            intent="generate",
            resume_version_id=resume_row.id,
        )
        chat_session = session.get(ChatSession, session_id)
        chat_session.active_resume_version_id = resume_row.id
        session.add(chat_session)
        session.commit()
        return resume_row.id


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

    async def test_create_session_defaults_to_resume_kind(self, client):
        # v5 ticket b1: a pre-v5 caller sends no `kind` and must get a resume chat.
        body = (await client.post("/api/chat/sessions", json={})).json()
        assert body["kind"] == "resume"

    async def test_create_profile_analysis_session_and_list_is_filtered_by_kind(self, client):
        # v5 ticket b1: the two areas never show each other's conversations.
        await client.post("/api/chat/sessions", json={"title": "Meu currículo"})
        analysis = (
            await client.post("/api/chat/sessions", json={"title": "Análise", "kind": "profile_analysis"})
        ).json()
        assert analysis["kind"] == "profile_analysis"

        resume_list = (await client.get("/api/chat/sessions")).json()["sessions"]
        analysis_list = (await client.get("/api/chat/sessions?kind=profile_analysis")).json()["sessions"]

        assert [s["title"] for s in resume_list] == ["Meu currículo"]
        assert [s["title"] for s in analysis_list] == ["Análise"]
        assert all(s["kind"] == "resume" for s in resume_list)
        assert all(s["kind"] == "profile_analysis" for s in analysis_list)

    async def test_delete_is_isolated_by_kind(self, client):
        # Deleting an analysis session leaves the resume session list untouched, and vice versa.
        resume = (await client.post("/api/chat/sessions", json={"title": "R"})).json()
        analysis = (
            await client.post("/api/chat/sessions", json={"title": "A", "kind": "profile_analysis"})
        ).json()

        assert (await client.delete(f"/api/chat/sessions/{analysis['id']}")).status_code == 204

        resume_list = (await client.get("/api/chat/sessions")).json()["sessions"]
        assert [s["id"] for s in resume_list] == [resume["id"]]

    async def test_list_sessions_orders_by_updated_at_desc(self, client):
        await client.post("/api/chat/sessions", json={"title": "First"})
        await client.post("/api/chat/sessions", json={"title": "Second"})

        resp = await client.get("/api/chat/sessions")

        assert resp.status_code == 200
        sessions = resp.json()["sessions"]
        assert [s["title"] for s in sessions] == ["Second", "First"]
        assert set(sessions[0].keys()) == {"id", "title", "updatedAt", "activeResumeVersionId", "kind"}

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
            "id", "title", "updatedAt", "activeResumeVersionId", "kind", "locale", "jobDescription", "createdAt",
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


class TestRenameChatSession:
    """v4.1-03 (frozen contract): PATCH /api/chat/sessions/{id} {"title": "<1..120 trimmed,
    non-empty>"} -> 200 {id, title, updatedAt}; 404 for a missing session; 422 for an
    empty/whitespace-only/over-120-char title (pydantic validation, before any DB write)."""

    async def test_rename_returns_200_and_updates_the_db(self, client, test_db_engine):
        created = (await client.post("/api/chat/sessions", json={"title": "Old title"})).json()

        resp = await client.patch(
            f"/api/chat/sessions/{created['id']}", json={"title": "New title"}
        )

        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"id", "title", "updatedAt"}
        assert body["id"] == created["id"]
        assert body["title"] == "New title"

        with Session(test_db_engine) as session:
            row = session.get(ChatSession, created["id"])
            assert row.title == "New title"

    async def test_rename_trims_surrounding_whitespace(self, client, test_db_engine):
        created = (await client.post("/api/chat/sessions", json={})).json()

        resp = await client.patch(
            f"/api/chat/sessions/{created['id']}", json={"title": "  Trimmed title  "}
        )

        assert resp.status_code == 200
        assert resp.json()["title"] == "Trimmed title"
        with Session(test_db_engine) as session:
            row = session.get(ChatSession, created["id"])
            assert row.title == "Trimmed title"

    async def test_rename_bumps_updated_at(self, client, test_db_engine):
        created = (await client.post("/api/chat/sessions", json={})).json()
        with Session(test_db_engine) as session:
            before = session.get(ChatSession, created["id"]).updated_at

        resp = await client.patch(
            f"/api/chat/sessions/{created['id']}", json={"title": "New title"}
        )

        assert resp.status_code == 200
        with Session(test_db_engine) as session:
            after = session.get(ChatSession, created["id"]).updated_at
            assert after >= before
        assert resp.json()["updatedAt"] == after.isoformat()

    async def test_rename_missing_session_is_404(self, client):
        resp = await client.patch("/api/chat/sessions/999999", json={"title": "New title"})
        assert resp.status_code == 404

    async def test_rename_with_empty_title_is_422(self, client):
        created = (await client.post("/api/chat/sessions", json={"title": "Old title"})).json()

        resp = await client.patch(f"/api/chat/sessions/{created['id']}", json={"title": ""})

        assert resp.status_code == 422

    async def test_rename_with_whitespace_only_title_is_422(self, client):
        created = (await client.post("/api/chat/sessions", json={"title": "Old title"})).json()

        resp = await client.patch(f"/api/chat/sessions/{created['id']}", json={"title": "   "})

        assert resp.status_code == 422

    async def test_rename_with_121_char_title_is_422(self, client):
        created = (await client.post("/api/chat/sessions", json={"title": "Old title"})).json()

        resp = await client.patch(
            f"/api/chat/sessions/{created['id']}", json={"title": "A" * 121}
        )

        assert resp.status_code == 422

    async def test_rename_with_exactly_120_char_title_succeeds(self, client):
        created = (await client.post("/api/chat/sessions", json={"title": "Old title"})).json()

        resp = await client.patch(
            f"/api/chat/sessions/{created['id']}", json={"title": "A" * 120}
        )

        assert resp.status_code == 200
        assert resp.json()["title"] == "A" * 120

    async def test_rename_422_does_not_touch_the_db(self, client, test_db_engine):
        created = (await client.post("/api/chat/sessions", json={"title": "Old title"})).json()

        resp = await client.patch(f"/api/chat/sessions/{created['id']}", json={"title": "   "})

        assert resp.status_code == 422
        with Session(test_db_engine) as session:
            row = session.get(ChatSession, created["id"])
            assert row.title == "Old title"


# NOTE (v4 ticket B3): pasting a job description with no active resume and no Pending Proposal
# no longer generates a resume directly -- it runs the Analysis and proposes changes instead.
# ``TestChatMessageStreamGenerateIntent`` and ``TestChatGenerateProfileProvenance`` (the "JD paste
# -> resume" and "generate uses the DB profile, not the disk decoy" coverage) moved to
# tests/integration/test_proposal_flow.py, which exercises the same profile-provenance and
# locale/message concerns against the new "proposal" event and _handle_propose_turn instead.
# The refine/profile_update classes below now seed their "already has an active resume"
# precondition directly via ``_seed_active_resume`` rather than through a chat-turn JD paste,
# since that turn no longer produces a resume (see that helper's docstring).


class TestChatMessageStreamRefineIntent:
    async def test_a_short_instruction_refines_the_active_resume(
        self, client, fake_llm, parse_sse, test_db_engine, write_profile
    ):
        write_profile(make_profile())
        strong_resume = make_resume_payload()
        created = (await client.post("/api/chat/sessions", json={})).json()
        _seed_active_resume(test_db_engine, created["id"], strong_resume)

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
        assert fake_llm.call_count == 1  # only the refine call -- the active resume was DB-seeded

        # The new resume version is a distinct, later version than the seeded one.
        after = (await client.get(f"/api/chat/sessions/{created['id']}")).json()
        assert after["session"]["activeResumeVersionId"] == resume_event["resumeVersionId"]
        assert after["activeResume"]["summary"] == updated["summary"]

    async def test_refine_confirmation_follows_the_resulting_resume_locale_not_the_session_locale(
        self, client, fake_llm, parse_sse, test_db_engine, write_profile
    ):
        # Real QA-found bug: pt-BR resume, user asks to translate it to English. The document
        # correctly flips to locale="en", but the confirmation bubble used to stay in
        # Portuguese because it derived its language from the session/request locale (still
        # unset/pt-BR here) instead of the resulting resume's own locale field.
        write_profile(make_profile())
        created = (await client.post("/api/chat/sessions", json={})).json()
        _seed_active_resume(test_db_engine, created["id"], make_resume_payload(locale="pt-BR"))

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
        # English wording (naming the changed section), not the pt-BR session/seed locale.
        assert message_event["content"] == "Updated your resume: summary."

    async def test_refine_folds_recent_history_into_the_llm_instruction(
        self, client, fake_llm, test_db_engine, write_profile
    ):
        write_profile(make_profile())
        strong_resume = make_resume_payload()
        created = (await client.post("/api/chat/sessions", json={})).json()
        _seed_active_resume(test_db_engine, created["id"], strong_resume)

        updated = make_resume_payload(summary="A punchier summary for the resume.")
        fake_llm.queue(json.dumps(updated))
        await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "Make the summary punchier."},
        )

        refine_call = fake_llm.calls[-1]
        assert GENERIC_JOB_DESCRIPTION[:40] in refine_call["user"]
        assert "Make the summary punchier." in refine_call["user"]


def _resume_version_count(test_db_engine, session_id: int) -> int:
    with Session(test_db_engine) as session:
        rows = session.exec(
            select(ResumeVersion).where(ResumeVersion.session_id == session_id)
        ).all()
        return len(rows)


class TestChatMessageStreamRefineSimSimHomemFix:
    """v4.1-05 plan (giggly-prancing-wilkes): refine must confirm based on a REAL diff (not a
    static "done" reply), may ask a clarifying question instead of always returning a resume,
    and threads local project notes + on-demand GitHub context into its own prompt -- see
    ``chat_service._diff_resume_sections``/``_handle_refine_turn`` and
    ``refine_service.refine_resume_events``.
    """

    @pytest.fixture(autouse=True)
    def _no_real_project_markdown_for_refine(self, isolated_data_env, monkeypatch: pytest.MonkeyPatch) -> None:
        # ``isolated_data_env`` only sandboxes generation_service_module.PROJECTS_DIR --
        # refine_service.py imports the same name directly from app.config, so it still reads
        # this repo's real data/projects/*.md unless independently sandboxed here too.
        monkeypatch.setattr(refine_service_module, "PROJECTS_DIR", isolated_data_env / "no-projects-here")

    async def test_refine_that_changes_nothing_reports_honestly_with_no_new_version(
        self, client, fake_llm, parse_sse, test_db_engine, write_profile
    ):
        write_profile(make_profile())
        strong_resume = make_resume_payload()
        created = (await client.post("/api/chat/sessions", json={})).json()
        active_resume_version_id = _seed_active_resume(test_db_engine, created["id"], strong_resume)

        fake_llm.queue(json.dumps(strong_resume))  # the LLM claims a resume but nothing differs

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "Ajusta um pouco o texto."},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        kinds = [e for e, _ in events]
        assert "resume" not in kinds
        message_event = next(data for e, data in events if e == "message")
        assert message_event["content"] == (
            "I didn't find a real change to apply from that -- can you tell me more "
            "specifically what to change?"
        )
        done_event = next(data for e, data in events if e == "done")
        assert done_event["resumeVersionId"] is None

        assert _resume_version_count(test_db_engine, created["id"]) == 1  # only the seeded one
        after = (await client.get(f"/api/chat/sessions/{created['id']}")).json()
        assert after["session"]["activeResumeVersionId"] == active_resume_version_id

    async def test_refine_that_changes_only_projects_names_the_section_and_creates_a_new_version(
        self, client, fake_llm, parse_sse, test_db_engine, write_profile
    ):
        write_profile(make_profile())
        seeded_resume = make_resume_payload(locale="pt-BR")
        created = (await client.post("/api/chat/sessions", json={})).json()
        active_resume_version_id = _seed_active_resume(test_db_engine, created["id"], seeded_resume)

        updated = make_resume_payload(
            locale="pt-BR",
            projects=[
                {
                    "name": "novo-projeto",
                    "description": "Um projeto novo, diferente do que já estava no currículo.",
                }
            ],
        )
        fake_llm.queue(json.dumps(updated))

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "Troca o projeto do currículo por um mais relevante."},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        message_event = next(data for e, data in events if e == "message")
        assert message_event["content"] == "Atualizei seu currículo: projetos."
        resume_event = next(data for e, data in events if e == "resume")
        assert resume_event["resume"]["projects"][0]["name"] == "novo-projeto"
        assert resume_event["resumeVersionId"] != active_resume_version_id

        assert _resume_version_count(test_db_engine, created["id"]) == 2
        after = (await client.get(f"/api/chat/sessions/{created['id']}")).json()
        assert after["session"]["activeResumeVersionId"] == resume_event["resumeVersionId"]

    async def test_refine_can_ask_a_clarifying_question_instead_of_returning_a_resume(
        self, client, fake_llm, parse_sse, test_db_engine, write_profile
    ):
        write_profile(make_profile())
        created = (await client.post("/api/chat/sessions", json={})).json()
        _seed_active_resume(test_db_engine, created["id"], make_resume_payload())

        reply = "Which project would you like me to feature instead?"
        fake_llm.queue(json.dumps({"type": "question", "reply": reply}))

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "Swap in a better project."},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        assert "resume" not in [e for e, _ in events]
        message_event = next(data for e, data in events if e == "message")
        assert message_event["content"] == reply
        done_event = next(data for e, data in events if e == "done")
        assert done_event["resumeVersionId"] is None

        assert _resume_version_count(test_db_engine, created["id"]) == 1  # only the seeded one
        with Session(test_db_engine) as session:
            _, messages = chat_repo.get_session_with_messages(session, created["id"])
            assistant_msg = next(
                m for m in messages if m.role == "assistant" and m.content == reply
            )
            assert assistant_msg.intent == "refine_question"

    async def test_refine_mentioning_github_with_a_configured_username_fetches_and_merges_repos(
        self, client, fake_llm, test_db_engine, write_profile, monkeypatch: pytest.MonkeyPatch
    ):
        write_profile(make_profile(githubUsername="anacosta"))
        strong_resume = make_resume_payload()
        created = (await client.post("/api/chat/sessions", json={})).json()
        _seed_active_resume(test_db_engine, created["id"], strong_resume)

        fetch_calls: list[str] = []
        merge_calls: list[tuple[list, list]] = []
        fake_repo = GitHubRepoInfo(
            name="cool-repo",
            full_name="anacosta/cool-repo",
            html_url="https://github.com/anacosta/cool-repo",
            description="A cool repo",
        )

        async def fake_fetch_user_repos(username, limit=50):
            fetch_calls.append(username)
            return [fake_repo], None

        def fake_merge_github_with_markdown(md_entries, repos):
            merge_calls.append((md_entries, repos))
            return "GITHUB_SOURCES_MARKER"

        monkeypatch.setattr(refine_service_module, "fetch_user_repos", fake_fetch_user_repos)
        monkeypatch.setattr(
            refine_service_module, "merge_github_with_markdown", fake_merge_github_with_markdown
        )

        fake_llm.queue(json.dumps(strong_resume))

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "Pode conferir meus repositórios do GitHub e sugerir melhorias?"},
        )

        assert resp.status_code == 200
        assert fetch_calls == ["anacosta"]
        assert len(merge_calls) == 1
        assert merge_calls[0][1] == [fake_repo]

        refine_call = fake_llm.calls[-1]["user"]
        assert "GITHUB_SOURCES_MARKER" in refine_call
        assert "Supporting sources" in refine_call

    async def test_refine_mentioning_github_without_a_configured_username_warns_and_skips_the_network(
        self, client, fake_llm, test_db_engine, write_profile, monkeypatch: pytest.MonkeyPatch
    ):
        write_profile(make_profile())  # githubUsername stays None (factory default)
        strong_resume = make_resume_payload()
        created = (await client.post("/api/chat/sessions", json={})).json()
        _seed_active_resume(test_db_engine, created["id"], strong_resume)

        fetch_calls: list[str] = []
        merge_calls: list[tuple[list, list]] = []

        async def fake_fetch_user_repos(username, limit=50):
            fetch_calls.append(username)
            return [], None

        def fake_merge_github_with_markdown(md_entries, repos):
            merge_calls.append((md_entries, repos))
            return "GITHUB_SOURCES_MARKER"

        monkeypatch.setattr(refine_service_module, "fetch_user_repos", fake_fetch_user_repos)
        monkeypatch.setattr(
            refine_service_module, "merge_github_with_markdown", fake_merge_github_with_markdown
        )

        fake_llm.queue(json.dumps(strong_resume))

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "Pode conferir meus repositórios do GitHub e sugerir melhorias?"},
        )

        assert resp.status_code == 200
        assert fetch_calls == []  # no network call: no githubUsername configured
        assert merge_calls == []

        refine_call = fake_llm.calls[-1]["user"]
        assert "GitHub username not configured" in refine_call


class TestChatMessageStreamRefineClientResumeOverride:
    """v2 ticket 11: an inline edit made only in the client (never persisted) must not be lost
    by a chat refine -- the refine turn now prefers a client-supplied `resume` override (the
    request's optional `resume` field) over the DB's active_resume_version_id when present."""

    async def test_refine_uses_the_client_supplied_override_as_the_refine_base(
        self, client, fake_llm, parse_sse, test_db_engine, write_profile
    ):
        write_profile(make_profile())
        created = (await client.post("/api/chat/sessions", json={})).json()
        active_resume_version_id = _seed_active_resume(test_db_engine, created["id"], make_resume_payload())

        # Simulates an inline edit made client-side but never persisted: the DB's active
        # version still has the ORIGINAL summary; the client sends its own edited copy.
        edited_resume = make_resume_payload(summary="An inline-edited summary the DB has never seen.")
        updated = make_resume_payload(summary="A punchier summary for the resume.")
        fake_llm.queue(json.dumps(updated))  # the refine turn

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "Make the summary punchier.", "resume": edited_resume},
        )

        assert resp.status_code == 200
        # The LLM prompt was built from the CLIENT override, not the DB's active version.
        refine_call = fake_llm.calls[-1]["user"]
        assert "An inline-edited summary the DB has never seen." in refine_call

        events = parse_sse(resp.text)
        resume_event = next(data for e, data in events if e == "resume")
        assert resume_event["resume"]["summary"] == updated["summary"]

        with Session(test_db_engine) as session:
            new_version = resume_repo.get(session, resume_event["resumeVersionId"])
            assert new_version is not None
            # Provenance: the new version still chains off the previously-active version as
            # parent, exactly like a non-override refine would.
            assert new_version.parent_version_id == active_resume_version_id

            _, messages = chat_repo.get_session_with_messages(session, created["id"])
            assistant_msg = next(
                m for m in messages if m.role == "assistant" and m.resume_version_id == new_version.id
            )
            meta = json.loads(assistant_msg.meta)
            assert meta["clientResumeOverride"] is True

    async def test_refine_sanitizes_the_client_override_before_it_reaches_the_llm_prompt(
        self, client, fake_llm, test_db_engine, write_profile
    ):
        # Real gap found on review: the override used to flow into build_refine_user_msg's
        # prompt raw -- sanitize_resume_for_display only ran LATER, on parse_resume_json's
        # merged output. Before the DB was the only source at this point (already sanitized by
        # construction); the client override is new, untrusted input at exactly this seam.
        write_profile(make_profile())
        created = (await client.post("/api/chat/sessions", json={})).json()
        _seed_active_resume(test_db_engine, created["id"], make_resume_payload())

        malicious_resume = make_resume_payload()
        malicious_resume["experience"][0]["highlights"][0] = (
            "Shipped a feature <script>alert(1)</script> ahead of schedule"
        )
        fake_llm.queue(json.dumps(make_resume_payload(summary="A punchier summary for the resume.")))

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "Make the summary punchier.", "resume": malicious_resume},
        )

        assert resp.status_code == 200
        refine_call = fake_llm.calls[-1]["user"]
        assert "<script>" not in refine_call
        assert "Shipped a feature" in refine_call  # sanitized, not dropped wholesale

    async def test_refine_without_override_uses_the_db_active_resume_and_no_override_flag(
        self, client, fake_llm, parse_sse, test_db_engine, write_profile
    ):
        write_profile(make_profile())
        created = (await client.post("/api/chat/sessions", json={})).json()
        _seed_active_resume(test_db_engine, created["id"], make_resume_payload())

        updated = make_resume_payload(summary="A punchier summary for the resume.")
        fake_llm.queue(json.dumps(updated))
        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "Make the summary punchier."},
        )

        resume_event = next(data for e, data in parse_sse(resp.text) if e == "resume")
        with Session(test_db_engine) as session:
            _, messages = chat_repo.get_session_with_messages(session, created["id"])
            assistant_msg = next(
                m
                for m in messages
                if m.role == "assistant" and m.resume_version_id == resume_event["resumeVersionId"]
            )
            meta = json.loads(assistant_msg.meta)
            assert "clientResumeOverride" not in meta

    async def test_invalid_client_resume_override_is_a_clean_422_with_no_stream_started(
        self, client, fake_llm, test_db_engine
    ):
        created = (await client.post("/api/chat/sessions", json={})).json()
        _seed_active_resume(test_db_engine, created["id"], make_resume_payload())

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "Make the summary punchier.", "resume": {}},
        )

        assert resp.status_code == 422
        assert "detail" in resp.json()
        assert fake_llm.call_count == 0  # refine never ran -- the override failed validation first


class TestChatMessageStreamProfileUpdateIntent:
    """v2 ticket 05: "Mudei meu telefone para X" turns an LLM-adjudicated PatchOp[] into a new
    profile_versions row (source_kind='chat') via the SAME Patch Validator every other write
    path uses -- it never regenerates the active resume, and the frontend (ticket 09, already
    shipped against this exact shape) is the seam: the `profile_update` SSE event MUST stay
    `{"profileVersion": int, "summary": str}` byte-for-byte.
    """

    async def test_profile_update_turn_creates_a_chat_provenanced_version_and_sse_event(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        write_profile(make_profile(phone=None))
        fake_llm.queue(
            json.dumps(
                [
                    {
                        "op": "replace",
                        "path": "/phone",
                        "value": "11 98888-7777",
                        "reason": "user stated their new phone number",
                        "confidence": 0.95,
                        "sourceExcerpt": PHONE_UPDATE_MESSAGE_PT,
                    }
                ]
            )
        )
        created = (await client.post("/api/chat/sessions", json={})).json()

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": PHONE_UPDATE_MESSAGE_PT},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        kinds = [e for e, _ in events]
        assert "resume" not in kinds  # never regenerates the active resume (there is none here)
        assert "profile_update" in kinds
        assert kinds[-1] == "done"
        assert fake_llm.call_count == 1

        pu_event = next(data for e, data in events if e == "profile_update")
        # Byte-for-byte contract with the frontend (ticket 09) -- exactly these two keys.
        assert set(pu_event.keys()) == {"profileVersion", "summary"}
        assert pu_event["profileVersion"] == 1
        assert isinstance(pu_event["summary"], str) and pu_event["summary"]

        message_event = next(data for e, data in events if e == "message")
        assert isinstance(message_event["content"], str) and message_event["content"]

        done_event = next(data for e, data in events if e == "done")
        assert done_event["resumeVersionId"] is None  # no resume produced by this turn

        with Session(test_db_engine) as session:
            version = profile_repo.get_by_version(session, 1)
            assert version is not None
            assert version.source_kind == "chat"
            assert version.chat_message_id is not None
            data = json.loads(version.data)
            assert data["phone"] == "11 98888-7777"

            # The chat_message_id really is the triggering USER message, not the assistant reply.
            _, messages = chat_repo.get_session_with_messages(session, created["id"])
            user_msg = next(m for m in messages if m.role == "user")
            assert version.chat_message_id == user_msg.id

    async def test_profile_update_leaves_the_active_resume_untouched_and_offers_regeneration(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        write_profile(make_profile(phone=None))
        strong_resume = make_resume_payload()
        created = (await client.post("/api/chat/sessions", json={})).json()
        active_resume_version_id = _seed_active_resume(test_db_engine, created["id"], strong_resume)

        fake_llm.queue(
            json.dumps(
                [
                    {
                        "op": "replace",
                        "path": "/phone",
                        "value": "11 98888-7777",
                        "reason": "user stated their new phone number",
                        "confidence": 0.95,
                        "sourceExcerpt": PHONE_UPDATE_MESSAGE_PT,
                    }
                ]
            )
        )

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": PHONE_UPDATE_MESSAGE_PT},
        )

        events = parse_sse(resp.text)
        assert "resume" not in [e for e, _ in events]
        message_event = next(data for e, data in events if e == "message")
        # Active resume exists -> the reply OFFERS regeneration, in natural language, never
        # automatically (module docstring / CONTEXT.md: profile_update).
        assert "atualize seu currículo" in message_event["content"]

        after = (await client.get(f"/api/chat/sessions/{created['id']}")).json()
        assert after["session"]["activeResumeVersionId"] == active_resume_version_id
        assert after["activeResume"]["summary"] == strong_resume["summary"]

    async def test_profile_update_with_no_active_resume_does_not_offer_regeneration(
        self, client, fake_llm, write_profile, parse_sse
    ):
        write_profile(make_profile(phone=None))
        fake_llm.queue(
            json.dumps(
                [
                    {
                        "op": "replace",
                        "path": "/phone",
                        "value": "11 98888-7777",
                        "reason": "user stated their new phone number",
                        "confidence": 0.95,
                        "sourceExcerpt": PHONE_UPDATE_MESSAGE_PT,
                    }
                ]
            )
        )
        created = (await client.post("/api/chat/sessions", json={})).json()

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": PHONE_UPDATE_MESSAGE_PT},
        )

        message_event = next(data for e, data in parse_sse(resp.text) if e == "message")
        assert "atualize seu currículo" not in message_event["content"]

    async def test_llm_garbage_response_leaves_the_profile_untouched_with_a_friendly_reply(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        write_profile(make_profile(phone=None))
        fake_llm.queue("Sorry, I can't help with that request.")  # not JSON at all
        created = (await client.post("/api/chat/sessions", json={})).json()

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": PHONE_UPDATE_MESSAGE_PT},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        kinds = [e for e, _ in events]
        assert "profile_update" not in kinds  # never an error either -- just no change
        assert "message" in kinds
        assert kinds[-1] == "done"
        done_event = next(data for e, data in events if e == "done")
        assert done_event["resumeVersionId"] is None

        message_event = next(data for e, data in events if e == "message")
        assert "nada foi alterado" in message_event["content"]

        with Session(test_db_engine) as session:
            assert profile_repo.list_versions(session) == []  # profile untouched

    async def test_remove_via_chat_is_permitted_unlike_upload(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        write_profile(make_profile())  # one experience entry: Acme Corp
        fake_llm.queue(
            json.dumps(
                [
                    {
                        "op": "remove",
                        "path": "/experience/0",
                        "value": None,
                        "reason": "user asked to remove this job entry",
                        "confidence": 0.9,
                        "sourceExcerpt": REMOVE_EXPERIENCE_MESSAGE_PT,
                    }
                ]
            )
        )
        created = (await client.post("/api/chat/sessions", json={})).json()

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": REMOVE_EXPERIENCE_MESSAGE_PT},
        )

        assert resp.status_code == 200
        pu_event = next(data for e, data in parse_sse(resp.text) if e == "profile_update")
        assert pu_event["profileVersion"] == 1

        with Session(test_db_engine) as session:
            version = profile_repo.get_by_version(session, 1)
            assert json.loads(version.data)["experience"] == []


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
