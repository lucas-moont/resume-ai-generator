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
from app.domain.schemas import ProposalItem
from app.repositories import chat_repo, profile_repo, proposal_repo
from tests.factories import make_profile, make_resume_payload

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


# --- v4 ticket B4/B5 shared seams ("helper de fixture para criar sessão+proposta pendente
# direto via repo", ticket B4's own "Seams de teste pré-acordados") -------------------------


def _default_proposal_items() -> list[dict]:
    return [
        {
            "id": 1,
            "section": "headline",
            "current": "Senior Backend Engineer",
            "proposed": "Senior Backend Engineer especializado em APIs Python/FastAPI",
            "rationale": "A vaga pede explicitamente experiência projetando APIs escaláveis em Python.",
        },
        {
            "id": 2,
            "section": "projects",
            "current": None,
            "proposed": "Destacar o projeto metrics-dashboard e seu impacto para 50 engenheiros.",
            "rationale": "A vaga menciona colaborar com o time de frontend em contratos GraphQL.",
        },
    ]


def _seed_pending_proposal(
    test_db_engine,
    session_id: int,
    *,
    job_description: str = GENERIC_JOB_DESCRIPTION,
    items: list[dict] | None = None,
) -> int:
    """Creates a Pending Proposal directly via ``proposal_repo`` -- bypassing the Analysis
    turn entirely -- so B4/B5's conversational-turn tests are isolated from B3's own Analysis
    coverage (ticket B4's pre-agreed test seam)."""
    with Session(test_db_engine) as session:
        row = proposal_repo.create_pending(
            session,
            session_id=session_id,
            job_description=job_description,
            items=[ProposalItem.model_validate(i) for i in (items or _default_proposal_items())],
        )
        session.commit()
        return row.id


def _proposal_turn_llm_response(action: str, *, reply: str = "", items: list[dict] | None = None) -> str:
    payload: dict = {"action": action, "reply": reply}
    if items is not None:
        payload["items"] = items
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


class TestProposalTurnAdjust:
    """v4 ticket B4 (spec SS2/SS3.6): `adjust` -- the LLM returns the COMPLETE revised item
    list -- replaces the proposal's items wholesale and bumps its revision; the proposal row
    itself (id, status) never changes."""

    async def test_adjust_bumps_revision_and_replaces_items(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        write_profile(make_profile())
        created = (await client.post("/api/chat/sessions", json={})).json()
        proposal_id = _seed_pending_proposal(test_db_engine, created["id"])

        revised_items = [
            {
                "id": 1,
                "section": "headline",
                "current": "Senior Backend Engineer",
                "proposed": "Senior Backend Engineer focado em Python e FastAPI",
                "rationale": "A vaga pede experiência em APIs escaláveis em Python.",
            },
        ]
        fake_llm.queue(
            _proposal_turn_llm_response(
                "adjust", reply="Tirei o item de projetos, ficou só o headline.", items=revised_items
            )
        )

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "tira o item de projetos, mantém só o headline"},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        kinds = [e for e, _ in events]
        assert "resume" not in kinds
        proposal_index = kinds.index("proposal")
        message_index = kinds.index("message")
        assert all(k == "stage" for k in kinds[:proposal_index])
        assert proposal_index < message_index
        assert kinds[-1] == "done"

        proposal_event = next(data for e, data in events if e == "proposal")
        assert proposal_event["proposalId"] == proposal_id
        assert proposal_event["status"] == "proposed"
        assert proposal_event["revision"] == 2
        assert [item["section"] for item in proposal_event["items"]] == ["headline"]

        message_event = next(data for e, data in events if e == "message")
        assert message_event["content"] == "Tirei o item de projetos, ficou só o headline."

        done_event = next(data for e, data in events if e == "done")
        assert done_event["proposalId"] == proposal_id
        assert done_event["resumeVersionId"] is None

        assert fake_llm.call_count == 1
        prompt = fake_llm.calls[-1]["user"]
        assert "revision 1" in prompt  # the PRE-adjust revision, per build_proposal_turn_user_msg

        with Session(test_db_engine) as session:
            row = proposal_repo.get(session, proposal_id)
            assert row.status == "proposed"
            assert row.revision == 2
            assert [item.section for item in proposal_repo.get_items(row)] == ["headline"]


class TestProposalTurnQuestion:
    """`question` never touches the proposal -- only a `message` + `done` frame."""

    async def test_question_leaves_the_proposal_untouched(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        write_profile(make_profile())
        created = (await client.post("/api/chat/sessions", json={})).json()
        proposal_id = _seed_pending_proposal(test_db_engine, created["id"])

        with Session(test_db_engine) as session:
            before = proposal_repo.get(session, proposal_id)
            before_revision, before_updated_at = before.revision, before.updated_at

        fake_llm.queue(
            _proposal_turn_llm_response(
                "question", reply="O item de headline muda seu título para destacar APIs Python."
            )
        )

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "o que muda exatamente no headline?"},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        kinds = [e for e, _ in events]
        assert "proposal" not in kinds
        assert "resume" not in kinds
        message_event = next(data for e, data in events if e == "message")
        assert message_event["content"] == "O item de headline muda seu título para destacar APIs Python."
        done_event = next(data for e, data in events if e == "done")
        assert done_event["proposalId"] == proposal_id
        assert done_event["resumeVersionId"] is None

        with Session(test_db_engine) as session:
            after = proposal_repo.get(session, proposal_id)
            assert after.status == "proposed"
            assert after.revision == before_revision
            assert after.updated_at == before_updated_at

    async def test_blank_reply_on_a_valid_classification_falls_back_to_canned_text(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        # B4 ticket item 3: the parser never fabricates fallback prose itself (B2 decision) --
        # the caller (chat_service) is responsible for substituting the canned text when a
        # valid classification's own `reply` comes back blank.
        write_profile(make_profile())
        created = (await client.post("/api/chat/sessions", json={})).json()
        _seed_pending_proposal(test_db_engine, created["id"])
        fake_llm.queue(_proposal_turn_llm_response("question", reply=""))

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "hmm"},
        )

        events = parse_sse(resp.text)
        message_event = next(data for e, data in events if e == "message")
        assert message_event["content"]  # non-blank -- the canned fallback filled it in


class TestProposalTurnGarbageFallback:
    """v4 ticket B4 (spec SS6): unparseable LLM output for the Proposal Turn's OWN
    classification is NEVER an error frame -- unlike the Analysis's parser failure, which
    still is (see TestAnalysisTurnFailures above)."""

    async def test_non_json_llm_response_falls_back_to_a_canned_question_never_an_error(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        write_profile(make_profile())
        created = (await client.post("/api/chat/sessions", json={})).json()
        proposal_id = _seed_pending_proposal(test_db_engine, created["id"])
        fake_llm.queue("Sorry, I can't help with that request.")

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "sei lá, tanto faz"},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        kinds = [e for e, _ in events]
        assert "error" not in kinds
        assert kinds[-1] == "done"
        message_event = next(data for e, data in events if e == "message")
        assert message_event["content"]  # non-blank canned fallback

        with Session(test_db_engine) as session:
            row = proposal_repo.get(session, proposal_id)
            assert row.status == "proposed"
            assert row.revision == 1

    async def test_an_adjust_with_zero_usable_items_also_falls_back_to_question(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        # parse_proposal_turn_json returns None for an `adjust` with no usable items (B2) --
        # same fallback-question treatment as outright garbage, never an error.
        write_profile(make_profile())
        created = (await client.post("/api/chat/sessions", json={})).json()
        _seed_pending_proposal(test_db_engine, created["id"])
        fake_llm.queue(json.dumps({"action": "adjust", "reply": "ok", "items": []}))

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "tira tudo"},
        )

        events = parse_sse(resp.text)
        kinds = [e for e, _ in events]
        assert "error" not in kinds
        assert "proposal" not in kinds


class TestProposalTurnNewJdViaHeuristic:
    """`looks_like_job_description(message)` short-circuits straight into another Analysis --
    zero LLM calls spent on classification, only the Analysis itself."""

    async def test_pasting_a_new_job_description_supersedes_the_pending_proposal(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        write_profile(make_profile())
        created = (await client.post("/api/chat/sessions", json={})).json()
        old_proposal_id = _seed_pending_proposal(test_db_engine, created["id"])
        fake_llm.queue(_proposal_llm_response())

        new_jd = (
            "We are hiring a Staff Frontend Engineer to lead our design system team. You will "
            "build accessible React components, own our Storybook and visual regression "
            "pipeline, and collaborate closely with product designers. Experience with "
            "TypeScript, Vite, and CSS architecture is a strong plus. We value craftsmanship "
            "and clear written communication."
        )
        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": new_jd},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        kinds = [e for e, _ in events]
        assert "error" not in kinds
        assert kinds[-1] == "done"
        proposal_event = next(data for e, data in events if e == "proposal")
        new_proposal_id = proposal_event["proposalId"]
        assert new_proposal_id != old_proposal_id
        assert proposal_event["status"] == "proposed"
        assert proposal_event["revision"] == 1

        assert fake_llm.call_count == 1  # only the new Analysis -- no classification call spent

        with Session(test_db_engine) as session:
            old_row = proposal_repo.get(session, old_proposal_id)
            new_row = proposal_repo.get(session, new_proposal_id)
            assert old_row.status == "superseded"
            assert new_row.status == "proposed"
            assert new_row.job_description == new_jd


class TestProposalTurnNewJdViaLlm:
    """A message that does NOT look like a JD by the heuristic, but the classification LLM
    itself decides is a new job description (`action=new_jd`) -- costs 2 LLM calls
    (classification + the Analysis it triggers)."""

    async def test_llm_classified_new_jd_supersedes_the_pending_proposal(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        write_profile(make_profile())
        created = (await client.post("/api/chat/sessions", json={})).json()
        old_proposal_id = _seed_pending_proposal(test_db_engine, created["id"])

        short_new_jd_mention = "Na verdade surgiu outra vaga, deixa eu colar a descrição dela."
        fake_llm.queue(
            _proposal_turn_llm_response(
                "new_jd", reply="Beleza, vou analisar a nova vaga."
            ),
            _proposal_llm_response(),
        )

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": short_new_jd_mention},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        kinds = [e for e, _ in events]
        assert "error" not in kinds
        proposal_event = next(data for e, data in events if e == "proposal")
        new_proposal_id = proposal_event["proposalId"]
        assert new_proposal_id != old_proposal_id

        assert fake_llm.call_count == 2  # classification + the Analysis it triggers
        assert "outra vaga" in fake_llm.calls[0]["user"]  # the classification saw the message

        with Session(test_db_engine) as session:
            old_row = proposal_repo.get(session, old_proposal_id)
            assert old_row.status == "superseded"


class TestApproveViaButton:
    """v4 ticket B5 (spec SS2/SS3.6): the "Aprovar e gerar" button -- `proposalAction ==
    "approve"` -- takes the approve branch with ZERO LLM classification spent; only the
    generation pipeline itself calls the LLM."""

    async def test_approve_button_generates_the_resume_and_marks_the_proposal_approved(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        write_profile(make_profile())
        created = (await client.post("/api/chat/sessions", json={})).json()
        proposal_id = _seed_pending_proposal(test_db_engine, created["id"])

        fake_llm.queue(json.dumps(make_resume_payload()))  # generation only -- no quality pass

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "Aprovar e gerar", "proposalAction": "approve"},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        kinds = [e for e, _ in events]
        assert "error" not in kinds
        # message(confirmation) -> stage(s) -> resume -> message(final) -> done, per spec SS3.6.
        assert kinds[0] == "message"
        resume_index = kinds.index("resume")
        assert all(k in ("message", "stage") for k in kinds[:resume_index])
        assert kinds[-1] == "done"
        assert kinds.count("message") == 2

        done_event = next(data for e, data in events if e == "done")
        assert done_event["proposalId"] == proposal_id
        assert isinstance(done_event["resumeVersionId"], int)

        assert fake_llm.call_count == 1
        prompt = fake_llm.calls[-1]["user"]
        assert "APPROVED IMPROVEMENT PLAN" in prompt
        assert "Senior Backend Engineer especializado em APIs Python/FastAPI" in prompt
        assert "Destacar o projeto metrics-dashboard" in prompt

        with Session(test_db_engine) as session:
            row = proposal_repo.get(session, proposal_id)
            assert row.status == "approved"
            assert row.resume_version_id == done_event["resumeVersionId"]

        body = (await client.get(f"/api/chat/sessions/{created['id']}")).json()
        assert body["session"]["jobDescription"] == GENERIC_JOB_DESCRIPTION
        assert body["session"]["activeResumeVersionId"] == done_event["resumeVersionId"]
        assert body["pendingProposal"] is None


class TestApproveViaNaturalLanguage:
    """A clear natural-language approval ("sim, pode gerar") takes the SAME approve branch,
    reached via the Proposal Turn's own classification (`action=approve`) -- 2-3 LLM calls
    (classification + generation [+ quality pass])."""

    async def test_natural_language_approval_generates_the_resume(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        write_profile(make_profile())
        created = (await client.post("/api/chat/sessions", json={})).json()
        proposal_id = _seed_pending_proposal(test_db_engine, created["id"])

        fake_llm.queue(
            _proposal_turn_llm_response("approve", reply="Perfeito, vou gerar agora."),
            json.dumps(make_resume_payload()),
        )

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "sim, pode gerar"},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        kinds = [e for e, _ in events]
        assert "error" not in kinds
        assert "resume" in kinds
        message_events = [data for e, data in events if e == "message"]
        # The confirmation bubble is the LLM's OWN reply, not the canned copy -- unlike the
        # button shortcut above.
        assert message_events[0]["content"] == "Perfeito, vou gerar agora."
        assert kinds[-1] == "done"

        assert fake_llm.call_count == 2  # classification + generation

        with Session(test_db_engine) as session:
            row = proposal_repo.get(session, proposal_id)
            assert row.status == "approved"


class TestApproveGenerationFailure:
    """spec SS6: a generation failure post-approve leaves the proposal `proposed` (reapprovable)
    -- `mark_approved` only ever runs once generation actually succeeds."""

    async def test_generation_failure_keeps_the_proposal_proposed_and_reapproval_works(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        write_profile(make_profile())
        created = (await client.post("/api/chat/sessions", json={})).json()
        proposal_id = _seed_pending_proposal(test_db_engine, created["id"])

        fake_llm.queue("Sorry, I can't generate that.")  # not valid resume JSON

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "aprova", "proposalAction": "approve"},
        )
        events = parse_sse(resp.text)
        assert events[-1][0] == "error"

        with Session(test_db_engine) as session:
            row = proposal_repo.get(session, proposal_id)
            assert row.status == "proposed"

        # Reapproval: the button is still live, and it works.
        fake_llm.queue(json.dumps(make_resume_payload()))
        resp2 = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "aprova de novo", "proposalAction": "approve"},
        )
        events2 = parse_sse(resp2.text)
        assert events2[-1][0] == "done"

        with Session(test_db_engine) as session:
            row = proposal_repo.get(session, proposal_id)
            assert row.status == "approved"


class TestProposalActionIgnoredWithoutPendingProposal:
    """spec SS3.1: `proposalAction` on a session with no Pending Proposal is silently ignored
    -- the turn routes normally, exactly as if the field had never been sent."""

    async def test_proposal_action_without_a_pending_proposal_falls_through_to_normal_routing(
        self, client, fake_llm, write_profile, parse_sse
    ):
        write_profile(make_profile())
        created = (await client.post("/api/chat/sessions", json={})).json()

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "oi", "proposalAction": "approve"},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        kinds = [e for e, _ in events]
        # No active resume, no pending proposal, a short greeting -- plain v1 "question"
        # routing, spending no LLM call at all (proves the shortcut never fired).
        assert kinds == ["message", "done"]
        assert fake_llm.call_count == 0
