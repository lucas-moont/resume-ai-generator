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

from app.db.tables import ChatSession, ImprovementProposal
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

    async def test_the_proposal_carries_the_detected_locale_on_the_event_and_on_reload(
        self, client, fake_llm, write_profile, parse_sse
    ):
        # The approval step shows "Vou gerar em [pt-BR ...]" pre-filled with
        # the language detected from the posting, so the detected locale must reach the client --
        # live on the `proposal` event, and after a reload on `pendingProposal`. The profile is
        # locale "en", but a Portuguese posting must still be detected as pt-BR (detection wins).
        pt_jd = (
            "Estamos contratando uma pessoa desenvolvedora back-end sênior para o time de "
            "plataforma. Você vai projetar e construir APIs escaláveis em Python, cuidar da nossa "
            "camada de dados em PostgreSQL e orientar pessoas desenvolvedoras juniores. "
            "Requisitos: experiência sólida com Docker e boa comunicação escrita."
        )
        write_profile(make_profile())
        fake_llm.queue(_proposal_llm_response())
        created = (await client.post("/api/chat/sessions", json={})).json()

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": pt_jd},
        )
        events = parse_sse(resp.text)
        proposal_event = next(data for e, data in events if e == "proposal")
        assert proposal_event["detectedLocale"] == "pt-BR"

        detail = (await client.get(f"/api/chat/sessions/{created['id']}")).json()
        assert detail["pendingProposal"]["detectedLocale"] == "pt-BR"

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


class TestAnalysisTurnTitle:
    """v4.1-02: the Analysis's own JSON may name the job via an optional `title` -- when
    present, it becomes the chat session's own title (replacing whatever excerpt-based title
    it had before), written in the SAME commit as the rest of the turn. Covers both the plain
    Analysis (``_handle_propose_turn``, reached directly with no pending proposal) and the
    `new_jd` short-circuit (the SAME function, reached via the Proposal Turn's classification)."""

    async def test_title_in_llm_response_renames_the_session(
        self, client, fake_llm, write_profile, test_db_engine
    ):
        write_profile(make_profile())
        fake_llm.queue(_proposal_llm_response(title="Senior Backend Engineer — Platform Team"))
        created = (await client.post("/api/chat/sessions", json={"title": "Untitled chat"})).json()

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": GENERIC_JOB_DESCRIPTION},
        )

        assert resp.status_code == 200
        with Session(test_db_engine) as session:
            row = session.get(ChatSession, created["id"])
            assert row.title == "Senior Backend Engineer — Platform Team"

        listed = (await client.get("/api/chat/sessions")).json()["sessions"]
        assert listed[0]["title"] == "Senior Backend Engineer — Platform Team"

    async def test_no_title_in_llm_response_leaves_the_existing_title_untouched(
        self, client, fake_llm, write_profile, test_db_engine
    ):
        write_profile(make_profile())
        fake_llm.queue(_proposal_llm_response())  # the default response has no "title" key
        created = (await client.post("/api/chat/sessions", json={"title": "My original title"})).json()

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": GENERIC_JOB_DESCRIPTION},
        )

        assert resp.status_code == 200
        with Session(test_db_engine) as session:
            row = session.get(ChatSession, created["id"])
            assert row.title == "My original title"

    async def test_new_jd_with_a_title_renames_the_session(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        write_profile(make_profile())
        created = (await client.post("/api/chat/sessions", json={"title": "Old job chat"})).json()
        _seed_pending_proposal(test_db_engine, created["id"])

        fake_llm.queue(
            _proposal_turn_llm_response("new_jd", reply="Beleza, vou analisar a nova vaga."),
            _proposal_llm_response(title="Staff Frontend Engineer — Design Systems"),
        )

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "Na verdade surgiu outra vaga, deixa eu colar a descrição dela."},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        assert "error" not in [e for e, _ in events]

        with Session(test_db_engine) as session:
            row = session.get(ChatSession, created["id"])
            assert row.title == "Staff Frontend Engineer — Design Systems"


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


class TestProposalTurnQA05LongAdjustNotHijacked:
    """v4 ticket QA-05 (P2, QA live): a long, natural-language `adjust` message used to trip
    `looks_like_job_description`'s strong-word-count signal (30+ words, content-blind) and get
    short-circuited straight into a brand-new Analysis -- DESTROYING the pending proposal
    (supersede) instead of revising it. The classification LLM is now the ONLY thing deciding
    `new_jd` vs `adjust` with a pending proposal (see `_handle_proposal_turn`'s docstring)."""

    async def test_long_adjust_message_revises_instead_of_superseding(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        write_profile(make_profile())
        created = (await client.post("/api/chat/sessions", json={})).json()
        proposal_id = _seed_pending_proposal(test_db_engine, created["id"])

        long_adjust_message = (
            "na proposta, adiciona também FastAPI como item de skills, sem remover nenhuma "
            "skill existente da lista, e muda o item de projetos para reordenar colocando "
            "Space Tourism Website em primeiro lugar entre todos"
        )
        assert len(long_adjust_message.split()) >= 30  # must trip the OLD heuristic's strong signal

        revised_items = [
            {
                "id": 1,
                "section": "skills",
                "current": None,
                "proposed": "Python, FastAPI, PostgreSQL",
                "rationale": "Adicionado FastAPI sem remover as skills existentes.",
            },
            {
                "id": 2,
                "section": "projects",
                "current": None,
                "proposed": "Space Tourism Website (reordenado para primeiro lugar)",
                "rationale": "Reordenado conforme pedido do usuário.",
            },
        ]
        fake_llm.queue(
            _proposal_turn_llm_response(
                "adjust",
                reply="Adicionei FastAPI às skills e reordenei os projetos.",
                items=revised_items,
            )
        )

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": long_adjust_message},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        kinds = [e for e, _ in events]
        assert "error" not in kinds

        proposal_event = next(data for e, data in events if e == "proposal")
        assert proposal_event["proposalId"] == proposal_id  # NEVER a new id -- revised, not superseded
        assert proposal_event["status"] == "proposed"
        assert proposal_event["revision"] == 2

        assert fake_llm.call_count == 1  # classification only -- `adjust` never triggers a 2nd call

        with Session(test_db_engine) as session:
            row = proposal_repo.get(session, proposal_id)
            assert row.status == "proposed"  # NEVER "superseded"
            assert row.revision == 2
            assert [item.section for item in proposal_repo.get_items(row)] == ["skills", "projects"]


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


# v4 ticket QA-05 (P2, QA live): `TestProposalTurnNewJdViaHeuristic` used to live here, asserting
# that a real JD paste with a pending proposal short-circuited straight into a new Analysis at
# only 1 LLM call (zero spent on classification). That SAME content-blind, 30+-word heuristic
# also hijacked long, ordinary `adjust` messages and destroyed the pending proposal -- the bug
# QA-05 fixes (see `TestProposalTurnQA05LongAdjustNotHijacked` above and `_handle_proposal_turn`'s
# docstring). The short-circuit is gone; a real JD paste with a pending proposal now ALWAYS goes
# through classification first, at the accepted cost of 2 LLM calls instead of 1 -- see
# `TestProposalTurnNewJdViaLlm.test_pasting_a_real_job_description_with_pending_still_costs_two_llm_calls`
# below, which replaces the removed heuristic test's coverage.


class TestProposalTurnNewJdViaLlm:
    """v4 ticket QA-05 fix: with a pending proposal, `new_jd` is decided ONLY by the
    classification LLM -- never by the `looks_like_job_description` heuristic (which stays
    intact for the NO-pending routing, v1's 3-way heuristic, but no longer gets a say once a
    proposal is pending). Always costs 2 LLM calls (classification + the Analysis it triggers),
    whether the message is a short mention of a new job or an obvious, full JD paste."""

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

    async def test_pasting_a_real_job_description_with_pending_still_costs_two_llm_calls(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        write_profile(make_profile())
        created = (await client.post("/api/chat/sessions", json={})).json()
        old_proposal_id = _seed_pending_proposal(test_db_engine, created["id"])

        new_jd = (
            "We are hiring a Staff Frontend Engineer to lead our design system team. You will "
            "build accessible React components, own our Storybook and visual regression "
            "pipeline, and collaborate closely with product designers. Experience with "
            "TypeScript, Vite, and CSS architecture is a strong plus. We value craftsmanship "
            "and clear written communication."
        )
        fake_llm.queue(
            _proposal_turn_llm_response("new_jd", reply="Beleza, vou analisar a nova vaga."),
            _proposal_llm_response(),
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

        # QA-05: classification is NEVER skipped now, even for an obvious, full JD paste.
        assert fake_llm.call_count == 2

        with Session(test_db_engine) as session:
            old_row = proposal_repo.get(session, old_proposal_id)
            new_row = proposal_repo.get(session, new_proposal_id)
            assert old_row.status == "superseded"
            assert new_row.status == "proposed"
            assert new_row.job_description == new_jd


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

    async def test_approved_skill_item_survives_the_automatic_quality_pass(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        """QA-04 (v4 gate, root cause of Bug 2): a skill approved in the Improvement Plan must
        survive even when the FIRST generation pass is thin enough to trigger the automatic
        quality-guard refine pass (``auto_improve_if_needed``) -- that second LLM call's own
        JSON output goes through the SAME ``agreed_improvements``-aware anchor, or a
        plan-approved skill introduced only there would be silently dropped exactly like the
        un-threaded main-pass case."""
        write_profile(make_profile())
        created = (await client.post("/api/chat/sessions", json={})).json()
        items = [
            {
                "id": 1,
                "section": "skills",
                "current": None,
                "proposed": "Adicionar GraphQL, já que a vaga pede contratos GraphQL com o time de frontend.",
                "rationale": "A vaga menciona GraphQL explicitamente.",
            }
        ]
        proposal_id = _seed_pending_proposal(test_db_engine, created["id"], items=items)

        # Thin first pass: only 1 highlight on the sole role triggers quality_issues (< 3
        # bullets), which is what makes generation_service call auto_improve_if_needed at all.
        thin_pass = make_resume_payload(
            experience=[
                {
                    "company": "Acme Corp",
                    "title": "Senior Backend Engineer",
                    "location": "Remote",
                    "start": "2021",
                    "end": None,
                    "highlights": ["Shipped the billing migration"],
                }
            ],
        )
        # Refine pass introduces the approved-but-not-in-profile skill.
        refine_pass = make_resume_payload(skills=["Python", "GraphQL"])
        fake_llm.queue(json.dumps(thin_pass), json.dumps(refine_pass))

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "Aprovar e gerar", "proposalAction": "approve"},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        kinds = [e for e, _ in events]
        assert "error" not in kinds
        assert kinds[-1] == "done"
        assert fake_llm.call_count == 2  # generation pass + the auto quality pass

        resume_event = next(data for e, data in events if e == "resume")
        assert "GraphQL" in resume_event["resume"]["skills"]

        with Session(test_db_engine) as session:
            row = proposal_repo.get(session, proposal_id)
            assert row.status == "approved"


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


class TestApproveHonorsTheRelevanceFilter:
    """v6 (Relevance Filter), end to end: the reported bug was that a resume tailored for a job
    with no analytics requirement still listed the candidate's analytics stack, no matter what
    the LLM returned. Two independent mechanisms put it back — the anchor's skill tail pass, and
    the quality gate's "aim for 8-16" issue driving the auto-improve refine pass — so a unit test
    on either one alone would not have caught the behavior the user actually sees.
    """

    # The profile's own relevant stack PLUS three analytics tools the job never mentions. Built
    # from make_profile() rather than hand-listed so the surviving set still covers the generic
    # JD's keywords -- otherwise the quality gate fires on a MISSING keyword (not on the drop)
    # and the test would be measuring the wrong mechanism.
    _NOISY_SKILLS = [
        *make_profile()["skills"],
        "Google Analytics",
        "Google Tag Manager",
        "Power BI",
    ]

    def _drop_items(self) -> list[dict]:
        return [
            {
                "id": 1,
                "section": "skills",
                "op": "drop",
                "current": "Google Analytics, Google Tag Manager, Power BI",
                "proposed": "Remover as ferramentas de analytics e BI da lista de skills.",
                "targets": ["Google Analytics", "Google Tag Manager", "Power BI"],
                "rationale": "A vaga é de backend Python/FastAPI e não menciona analytics ou BI.",
            }
        ]

    async def test_an_approved_skill_drop_never_reaches_the_generated_resume(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        write_profile(make_profile(skills=self._NOISY_SKILLS))
        created = (await client.post("/api/chat/sessions", json={})).json()
        proposal_id = _seed_pending_proposal(test_db_engine, created["id"], items=self._drop_items())

        # Adversarial: the model ignores the plan and re-emits the whole noisy list.
        fake_llm.queue(json.dumps(make_resume_payload(skills=self._NOISY_SKILLS)))

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "Aprovar e gerar", "proposalAction": "approve"},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        assert "error" not in [e for e, _ in events], [d for e, d in events if e == "error"]
        assert fake_llm.call_count == 1  # no quality pass: the lean list is the intended result

        skills = next(data for e, data in events if e == "resume")["resume"]["skills"]
        assert "Google Analytics" not in skills
        assert "Google Tag Manager" not in skills
        assert "Power BI" not in skills
        assert "Python" in skills
        assert "FastAPI" in skills

        # The plan reached the LLM as an imperative removal, not as a text swap.
        prompt = fake_llm.calls[-1]["user"]
        assert 'DROP (remove from the resume entirely): "Google Analytics"' in prompt

        with Session(test_db_engine) as session:
            assert proposal_repo.get(session, proposal_id).status == "approved"

    async def test_the_quality_pass_does_not_re_inflate_a_dropped_skill(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        """The second mechanism, in isolation: dropping 3 of 8 skills leaves 5, which trips the
        `len(skills) < 6` quality issue. Un-suppressed, that issue tells the refine pass to grow
        the list back — and the refine pass is exactly where an off-topic skill would return."""
        write_profile(make_profile(skills=self._NOISY_SKILLS))
        created = (await client.post("/api/chat/sessions", json={})).json()
        _seed_pending_proposal(test_db_engine, created["id"], items=self._drop_items())

        # A thin FIRST pass still triggers the quality gate on its own (1 bullet on the sole
        # role), so the refine pass runs and gets its chance to re-add the analytics stack.
        thin_pass = make_resume_payload(
            skills=["Python", "FastAPI", "PostgreSQL"],
            experience=[
                {
                    "company": "Acme Corp",
                    "title": "Senior Backend Engineer",
                    "location": "Remote",
                    "start": "2021",
                    "end": None,
                    "highlights": ["Shipped the billing migration"],
                }
            ],
        )
        refine_pass = make_resume_payload(skills=self._NOISY_SKILLS)
        fake_llm.queue(json.dumps(thin_pass), json.dumps(refine_pass))

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "Aprovar e gerar", "proposalAction": "approve"},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        assert "error" not in [e for e, _ in events]
        assert fake_llm.call_count == 2  # the quality pass did run

        skills = next(data for e, data in events if e == "resume")["resume"]["skills"]
        assert "Google Analytics" not in skills

        # The refine call was told what not to bring back, instead of being asked to pad.
        refine_prompt = fake_llm.calls[-1]["user"]
        assert "do NOT reintroduce them" in refine_prompt
        assert "Google Analytics" in refine_prompt
        assert "aim for 8-16" not in refine_prompt


class TestBaselineResumeFlow:
    """v6 (Baseline Resume), end to end: a request with no posting behind it runs the SAME
    Analysis -> Proposal -> generate pipeline, on a synthetic Target Brief.

    The reported bug was not a misroute — it was a missing capability. "Preciso de um currículo um
    pouco mais generalista pra pôr no meu indeed" got the canned "paste a job description" reply
    because every generation path in the app was anchored to a pasted posting.
    """

    _REPORTED = "Preciso de um currículo um pouco mais generalista pra pôr no meu indeed."

    async def test_a_baseline_request_produces_a_proposal_not_the_canned_reply(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        write_profile(make_profile(headline="Desenvolvedor Full Stack", locale="pt-BR"))
        created = (await client.post("/api/chat/sessions", json={})).json()
        fake_llm.queue(_proposal_llm_response())

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": self._REPORTED},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        kinds = [e for e, _ in events]
        assert "error" not in kinds
        assert "proposal" in kinds, "a baseline request must reach the Analysis, not a canned reply"

        with Session(test_db_engine) as session:
            pending = proposal_repo.get_pending(session, created["id"])
            assert pending is not None

    async def test_the_analysis_receives_a_target_brief_carrying_the_career_target(
        self, client, fake_llm, write_profile, parse_sse
    ):
        write_profile(make_profile(headline="Desenvolvedor Full Stack", locale="pt-BR"))
        created = (await client.post("/api/chat/sessions", json={})).json()
        fake_llm.queue(_proposal_llm_response())

        await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": self._REPORTED},
        )

        prompt = fake_llm.calls[-1]["user"]
        assert "TARGET BRIEF" in prompt
        assert "no specific job posting" in prompt
        assert "Career target: Desenvolvedor Full Stack" in prompt
        # The user's own words travel verbatim, so a narrower target in them can still win.
        assert "generalista" in prompt

    async def test_the_baseline_locale_comes_from_the_user_not_from_the_english_brief(
        self, client, fake_llm, write_profile, parse_sse
    ):
        """The brief is English prompt text (like every system prompt here), so reading the output
        language off it would make every baseline resume come out in English. The locale is
        resolved from the user's own message, falling back to the Profile's."""
        write_profile(make_profile(headline="Desenvolvedor Full Stack", locale="pt-BR"))
        created = (await client.post("/api/chat/sessions", json={})).json()
        fake_llm.queue(_proposal_llm_response())

        await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": self._REPORTED},
        )

        prompt = fake_llm.calls[-1]["user"]
        assert "pt-BR" in prompt
        assert 'locale for "message"' in prompt or "Target locale" in prompt

    async def test_a_profile_with_no_headline_is_asked_for_a_target_instead(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        # Broad is not unfocused: an open resume still argues for ONE kind of role, and the
        # headline is where that comes from. With none, inventing a career direction for someone
        # is not a guess worth making — and no LLM call is spent finding that out.
        write_profile(make_profile(headline="", locale="pt-BR"))
        created = (await client.post("/api/chat/sessions", json={})).json()

        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": self._REPORTED},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        assert "error" not in [e for e, _ in events]
        assert "proposal" not in [e for e, _ in events]
        assert fake_llm.call_count == 0

        message = next(data for e, data in events if e == "message")
        assert "headline" in message["content"].lower()

        with Session(test_db_engine) as session:
            assert proposal_repo.get_pending(session, created["id"]) is None

    async def test_approving_a_baseline_proposal_generates_a_resume(
        self, client, fake_llm, write_profile, parse_sse, test_db_engine
    ):
        # The whole point of routing baselines through the existing pipeline: approve works
        # unchanged, so the invariant "no Resume without an approved Proposal" still holds.
        #
        # This also exercises the v6 language gate inside the baseline flow. make_resume_payload()
        # is English prose while the resolved locale is pt-BR (the Profile's), so the generation
        # trips wrong_language_issue and a third LLM call runs to rewrite it -- asserted below.
        write_profile(make_profile(headline="Desenvolvedor Full Stack", locale="pt-BR"))
        created = (await client.post("/api/chat/sessions", json={})).json()
        fake_llm.queue(
            _proposal_llm_response(),
            json.dumps(make_resume_payload()),
            json.dumps(make_resume_payload(locale="pt-BR")),
        )

        await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": self._REPORTED},
        )
        resp = await client.post(
            f"/api/chat/sessions/{created['id']}/messages/stream",
            json={"message": "Aprovar e gerar", "proposalAction": "approve"},
        )

        assert resp.status_code == 200
        events = parse_sse(resp.text)
        assert "error" not in [e for e, _ in events], [d for e, d in events if e == "error"]
        assert "resume" in [e for e, _ in events]

        # The generation prompt was anchored on the brief, exactly where a posting would go.
        generation_prompt = fake_llm.calls[1]["user"]
        assert "TARGET BRIEF" in generation_prompt
        assert "Target locale for labels and prose: pt-BR" in generation_prompt

        # ...and the language gate caught the English output and asked for pt-BR, rather than
        # letting a Portuguese-targeted baseline ship in English.
        assert fake_llm.call_count == 3
        correction_prompt = fake_llm.calls[2]["user"]
        assert "written in en but this job requires pt-BR" in correction_prompt

        with Session(test_db_engine) as session:
            assert proposal_repo.get_pending(session, created["id"]) is None
