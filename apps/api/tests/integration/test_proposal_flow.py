"""Integration tests for the v4 Analysis turn (ticket B3, docs/v4-improvement-proposal.md SS0,
SS2, SS3.6): pasting a job description into a chat session with neither an active resume nor a
Pending Proposal no longer generates a resume directly -- it runs the Analysis instead, comparing
the Living Profile against the job and proposing a detailed, itemized Improvement Proposal
(``chat_service._handle_propose_turn``) for the user to converse about before anything is
generated.

The "JD paste -> resume" and "generate uses the DB active profile, not the disk decoy" coverage
that used to live in ``test_chat_endpoints.py`` (pre-v4) moves here, adapted to the new
"proposal" event and to the fact that an Analysis never stamps a ``profile_version_id`` onto
anything (only an approved generation, ticket B5, does that) -- there is no ``ResumeVersion`` for
an Analysis turn to provenance-link in the first place.
"""

from __future__ import annotations

import json

from sqlmodel import Session, select

from app.db.tables import ImprovementProposal
from app.repositories import chat_repo, profile_repo
from tests.factories import make_profile

GENERIC_JOB_DESCRIPTION = (
    "We are hiring a Senior Backend Engineer to join our platform team. You will design "
    "and build scalable APIs in Python, own our PostgreSQL data layer, collaborate with "
    "the frontend team on GraphQL contracts, and help mentor junior engineers. Experience "
    "with Docker, Kubernetes, and CI/CD pipelines is a strong plus. We value clear written "
    "communication and a pragmatic approach to shipping reliable software."
)


def _proposal_llm_response(**overrides) -> str:
    payload = {
        "message": (
            "Aqui estão algumas melhorias que encontrei para alinhar seu currículo a esta vaga:\n\n"
            "1. **Headline** -- deixar mais específico para Backend.\n"
            "2. **Summary** -- destacar experiência com APIs escaláveis.\n\n"
            "Quer que eu aplique essas mudanças, ajuste algo, ou tem alguma dúvida?"
        ),
        "items": [
            {
                "id": 1,
                "section": "headline",
                "current": "Senior Backend Engineer",
                "proposed": "Senior Backend Engineer especializado em APIs Python/FastAPI",
                "rationale": "A vaga pede explicitamente experiência projetando APIs escaláveis em Python.",
            },
            {
                "id": 2,
                "section": "summary",
                "current": None,
                "proposed": "Adicionar menção a mentoria de engenheiros júnior.",
                "rationale": "A vaga menciona ajudar a mentorar engenheiros juniores.",
            },
        ],
    }
    payload.update(overrides)
    return json.dumps(payload)


class TestAnalysisTurnHappyPath:
    async def test_pasting_a_job_description_with_no_active_resume_or_pending_proposal_proposes(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        write_profile(make_profile())
        fake_llm.queue(_proposal_llm_response())
        created = (await client.post("/api/chat/sessions", json={})).json()

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": GENERIC_JOB_DESCRIPTION},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        kinds = [e for e, _ in events]

        # Exact sequence per spec SS3.6 -- heartbeat may emit 1..N `stage` frames (an instant
        # FakeLlm response, as here, legitimately yields ZERO ticks -- see
        # streaming.run_with_heartbeat's own docstring -- so frame COUNT is never asserted,
        # only that whatever precedes `proposal` is exclusively `stage`, `proposal` precedes
        # `message`, and `done` is terminal. NO `resume` event at all.
        assert "resume" not in kinds
        proposal_index = kinds.index("proposal")
        message_index = kinds.index("message")
        assert all(k == "stage" for k in kinds[:proposal_index])
        assert proposal_index < message_index
        assert kinds[-1] == "done"
        stage_events = [data for e, data in events if e == "stage"]
        assert all(data["step"] == "analyzing_job" for data in stage_events)

        proposal_event = next(data for e, data in events if e == "proposal")
        assert isinstance(proposal_event["proposalId"], int)
        assert proposal_event["status"] == "proposed"
        assert proposal_event["revision"] == 1
        assert [item["section"] for item in proposal_event["items"]] == ["headline", "summary"]

        message_event = next(data for e, data in events if e == "message")
        assert isinstance(message_event["content"], str) and message_event["content"]

        done_event = next(data for e, data in events if e == "done")
        assert done_event["resumeVersionId"] is None
        assert done_event["proposalId"] == proposal_event["proposalId"]
        assert isinstance(done_event["messageId"], int)

        assert fake_llm.call_count == 1
        prompt = fake_llm.calls[-1]["user"]
        assert "Ana Costa" in prompt  # the profile
        assert "Senior Backend Engineer to join our platform team" in prompt  # the JD

        with Session(test_db_engine) as session:
            rows = list(session.exec(select(ImprovementProposal)))
            assert len(rows) == 1
            assert rows[0].status == "proposed"
            assert rows[0].job_description == GENERIC_JOB_DESCRIPTION

            _, messages = chat_repo.get_session_with_messages(session, created["id"])
            assistant_msg = next(m for m in messages if m.role == "assistant")
            assert assistant_msg.intent == "propose"
            assert assistant_msg.content == message_event["content"]
            meta = json.loads(assistant_msg.meta)
            assert meta["proposalId"] == proposal_event["proposalId"]

    async def test_does_not_write_job_description_onto_the_chat_session(
        self, client, fake_llm, write_profile, test_db_engine
    ):
        # Acceptance criterion (B3 ticket): the JD lives on the ImprovementProposal row, not on
        # chat_sessions.job_description -- that field is only written once a proposal is
        # actually approved (ticket B5).
        write_profile(make_profile())
        fake_llm.queue(_proposal_llm_response())
        created = (await client.post("/api/chat/sessions", json={})).json()

        await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": GENERIC_JOB_DESCRIPTION},
        )

        body = (await client.get(f"/api/chat/sessions/{created['id']}")).json()
        assert body["session"]["jobDescription"] is None
        assert body["session"]["activeResumeVersionId"] is None

    async def test_uses_the_db_active_profile_not_the_disk_decoy(
        self, client, fake_llm, write_profile, test_db_engine
    ):
        write_profile(make_profile(fullName="Disk Decoy Person"))  # must NOT be used
        with Session(test_db_engine) as session:
            profile_repo.insert_version(
                session,
                data=json.dumps(make_profile(fullName="DB Active Person")),
                source_kind="seed_disk",
            )
            session.commit()

        fake_llm.queue(_proposal_llm_response())
        created = (await client.post("/api/chat/sessions", json={})).json()

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": GENERIC_JOB_DESCRIPTION},
        )

        assert resp.status_code == 200
        prompt = fake_llm.calls[-1]["user"]
        assert "DB Active Person" in prompt
        assert "Disk Decoy Person" not in prompt


class TestAnalysisTurnFailures:
    async def test_non_json_llm_response_is_an_error_frame_with_zero_proposals_committed(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        write_profile(make_profile())
        fake_llm.queue("Sorry, I can't help with that request.")  # not JSON at all
        created = (await client.post("/api/chat/sessions", json={})).json()

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": GENERIC_JOB_DESCRIPTION},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        assert events[-1][0] == "error"

        with Session(test_db_engine) as session:
            rows = list(session.exec(select(ImprovementProposal)))
            assert rows == []
            # The user's message is still persisted (existing error-handling behavior).
            _, messages = chat_repo.get_session_with_messages(session, created["id"])
            assert any(m.role == "user" and m.content == GENERIC_JOB_DESCRIPTION for m in messages)

    async def test_zero_valid_items_is_an_error_frame_with_zero_proposals_committed(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        # Well-formed JSON, but every item fails ProposalItem validation (unrecognized
        # section) -- parse_proposal_json (B2) returns None for this, same as broken JSON.
        write_profile(make_profile())
        fake_llm.queue(
            json.dumps(
                {
                    "message": "some prose",
                    "items": [{"id": 1, "section": "not-a-real-section", "proposed": "x", "rationale": "y"}],
                }
            )
        )
        created = (await client.post("/api/chat/sessions", json={})).json()

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": GENERIC_JOB_DESCRIPTION},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        assert events[-1][0] == "error"

        with Session(test_db_engine) as session:
            rows = list(session.exec(select(ImprovementProposal)))
            assert rows == []

    async def test_llm_exception_is_an_error_frame_with_zero_proposals_committed(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine, monkeypatch
    ):
        write_profile(make_profile())
        secret = "sk-ant-fake-proposal-secret-0123456789abcdef"  # pragma: allowlist secret
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

        with Session(test_db_engine) as session:
            rows = list(session.exec(select(ImprovementProposal)))
            assert rows == []


class TestChatRouterForwardsProposalEvent:
    async def test_proposal_event_is_forwarded_as_its_own_sse_frame(self, client, fake_llm, write_profile):
        # Router-level check (B3 acceptance criterion): routers/chat.py's generic `else: yield
        # sse(event, data)` branch must not special-case "proposal" away -- it already doesn't
        # (only "resume" gets bespoke handling), but this pins that the raw SSE text really
        # contains an `event: proposal` frame, not just that parse_sse's dict-based lookup
        # happens to construct one.
        write_profile(make_profile())
        fake_llm.queue(_proposal_llm_response())
        created = (await client.post("/api/chat/sessions", json={})).json()

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": GENERIC_JOB_DESCRIPTION},
        )

        assert "event: proposal\n" in resp.text
