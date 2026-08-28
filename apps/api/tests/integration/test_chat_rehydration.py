"""Integration tests for v4 ticket B6 -- GET /api/chat/sessions/{id}'s rehydration of the
Improvement Proposal (docs/v4-improvement-proposal.md SS3.7): each message whose ``meta``
carries a ``proposalId`` gets a live-joined ``proposal`` field, and the response gets a
top-level ``pendingProposal`` (the session's single 'proposed' row, if any). Both mirror
``_source_document_link_dict``'s live-join contract -- CURRENT status/revision/items, never
a stale copy -- so this suite builds proposals directly via ``proposal_repo``/``chat_repo``
(no LLM turn) and asserts the GET response reflects whatever those rows say *right now*,
including after a supersede or an approve mutates them out from under an existing message.

Kept in its own file (not ``test_chat_endpoints.py``) per the v4 B6/B45 file-split: another
builder is adding cases to that file and ``test_proposal_flow.py`` concurrently.
"""

from __future__ import annotations

import json

from sqlmodel import Session

from app.domain.schemas import ProposalItem
from app.repositories import chat_repo, proposal_repo

GENERIC_JOB_DESCRIPTION = (
    "We are hiring a Senior Backend Engineer to join our platform team. You will design "
    "and build scalable APIs in Python and collaborate closely with the frontend team."
)

# Deliberately written WITHOUT the v6 ``op``/``targets`` fields: these dicts stand in for the
# item blobs already persisted in ``improvement_proposals.items`` before the Relevance Filter
# existed. What the API serves back for them (``SAMPLE_ITEMS_REHYDRATED``) is the backward
# compatibility contract -- an old proposal still reads as exactly what it meant then, a rewrite
# with no targets, rather than failing validation or losing its fields on the way out.
SAMPLE_ITEMS = [
    {
        "id": 1,
        "section": "headline",
        "current": "Backend Engineer",
        "proposed": "Senior Backend Engineer",
        "rationale": "The job description asks for a senior-level backend owner.",
    },
    {
        "id": 2,
        "section": "skills",
        "current": None,
        "proposed": "Kubernetes",
        "rationale": "The job description lists Kubernetes as a strong plus.",
    },
]

SAMPLE_ITEMS_REHYDRATED = [{**item, "op": "rewrite", "targets": []} for item in SAMPLE_ITEMS]


def _create_session(test_db_engine) -> int:
    with Session(test_db_engine) as session:
        row = chat_repo.create_session(session)
        session.commit()
        return row.id


def _create_pending_proposal_with_message(test_db_engine, session_id: int) -> int:
    """Creates a proposal via ``proposal_repo.create_pending`` and an assistant message
    referencing it via ``meta.proposalId`` -- the exact shape ``chat_service`` leaves behind
    after an Analysis turn (B3), without spending a queued LLM response on it."""
    with Session(test_db_engine) as session:
        proposal = proposal_repo.create_pending(
            session,
            session_id=session_id,
            job_description=GENERIC_JOB_DESCRIPTION,
            items=[ProposalItem(**i) for i in SAMPLE_ITEMS],
        )
        chat_repo.append_message(
            session,
            session_id=session_id,
            role="assistant",
            content="Here is my analysis of your profile against the job description.",
            intent="propose_improvements",
            meta=json.dumps({"proposalId": proposal.id}),
        )
        session.commit()
        return proposal.id


class TestChatSessionRehydratesProposal:
    async def test_pending_proposal_rehydrates_on_message_and_top_level(self, client, test_db_engine):
        session_id = _create_session(test_db_engine)
        proposal_id = _create_pending_proposal_with_message(test_db_engine, session_id)

        resp = await client.get(f"/api/chat/sessions/{session_id}")

        assert resp.status_code == 200
        body = resp.json()
        proposal_message = next(m for m in body["messages"] if m["intent"] == "propose_improvements")
        expected = {
            "proposalId": proposal_id,
            "status": "proposed",
            "revision": 1,
            "items": SAMPLE_ITEMS_REHYDRATED,
            # Recomputed from the (English) GENERIC_JOB_DESCRIPTION for the approval
            # picker's pre-fill; no profile is written in this test, so detection reads the posting.
            "detectedLocale": "en",
        }
        assert proposal_message["proposal"] == expected
        assert body["pendingProposal"] == expected

    async def test_supersede_flips_old_message_to_superseded_and_pending_points_to_new(
        self, client, test_db_engine
    ):
        session_id = _create_session(test_db_engine)
        old_proposal_id = _create_pending_proposal_with_message(test_db_engine, session_id)

        with Session(test_db_engine) as session:
            new_proposal = proposal_repo.create_pending(
                session,
                session_id=session_id,
                job_description="A different job description entirely.",
                items=[ProposalItem(**SAMPLE_ITEMS[0])],
            )
            chat_repo.append_message(
                session,
                session_id=session_id,
                role="assistant",
                content="You pasted a new job description -- here is the updated analysis.",
                intent="propose_improvements",
                meta=json.dumps({"proposalId": new_proposal.id}),
            )
            session.commit()
            new_proposal_id = new_proposal.id

        resp = await client.get(f"/api/chat/sessions/{session_id}")

        assert resp.status_code == 200
        body = resp.json()
        proposal_messages = [m for m in body["messages"] if m["intent"] == "propose_improvements"]
        assert len(proposal_messages) == 2

        old_message = next(m for m in proposal_messages if m["proposal"]["proposalId"] == old_proposal_id)
        new_message = next(m for m in proposal_messages if m["proposal"]["proposalId"] == new_proposal_id)
        assert old_message["proposal"]["status"] == "superseded"
        assert new_message["proposal"]["status"] == "proposed"

        assert body["pendingProposal"]["proposalId"] == new_proposal_id
        assert body["pendingProposal"]["status"] == "proposed"

    async def test_approve_flips_message_to_approved_and_pending_is_null(self, client, test_db_engine):
        session_id = _create_session(test_db_engine)
        proposal_id = _create_pending_proposal_with_message(test_db_engine, session_id)

        with Session(test_db_engine) as session:
            row = proposal_repo.get(session, proposal_id)
            proposal_repo.mark_approved(session, row, resume_version_id=999)
            session.commit()

        resp = await client.get(f"/api/chat/sessions/{session_id}")

        assert resp.status_code == 200
        body = resp.json()
        proposal_message = next(m for m in body["messages"] if m["intent"] == "propose_improvements")
        assert proposal_message["proposal"]["status"] == "approved"
        assert body["pendingProposal"] is None

    async def test_message_without_proposal_meta_and_session_without_any_proposal(
        self, client, test_db_engine
    ):
        session_id = _create_session(test_db_engine)
        with Session(test_db_engine) as session:
            chat_repo.append_message(
                session, session_id=session_id, role="user", content=GENERIC_JOB_DESCRIPTION
            )
            session.commit()

        resp = await client.get(f"/api/chat/sessions/{session_id}")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["messages"]) == 1
        assert body["messages"][0]["proposal"] is None
        assert body["pendingProposal"] is None
        # v3 shape intact
        assert body["messages"][0]["sourceDocument"] is None
        assert "content" in body["messages"][0]
