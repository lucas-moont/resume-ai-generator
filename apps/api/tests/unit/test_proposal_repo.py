"""Repository tests for improvement_proposals (v4 ticket B1 -- "Proposta Conversacional de
Melhorias"). Mirrors the fixture setup in tests/unit/test_source_document_repo.py (in-memory
SQLite engine via app.db.engine.create_db_engine(), same production code path) but kept in its
own module so this ticket's tests don't collide with concurrent edits to shared files.
"""

from __future__ import annotations

import json

import pytest
from sqlmodel import Session
from sqlmodel.pool import StaticPool

from app.db.engine import create_db_engine, init_db
from app.domain.schemas import ProposalItem
from app.repositories import chat_repo, proposal_repo


@pytest.fixture
def engine():
    eng = create_db_engine("sqlite://", poolclass=StaticPool)
    init_db(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


def _items(*, id_=1, section="headline", proposed="Backend Engineer"):
    return [
        ProposalItem(
            id=id_,
            section=section,
            current="Dev Backend",
            proposed=proposed,
            rationale="A vaga pede exatamente isso.",
        )
    ]


class TestCreatePending:
    def test_create_pending_inserts_a_proposed_row(self, session):
        chat_session = chat_repo.create_session(session, title="Vaga X")
        session.commit()

        row = proposal_repo.create_pending(
            session,
            session_id=chat_session.id,
            job_description="Senior Backend Engineer, Python...",
            items=_items(),
            model_used="claude-fable-5",
        )
        session.commit()

        assert row.id is not None
        assert row.session_id == chat_session.id
        assert row.status == "proposed"
        assert row.revision == 1
        assert row.resume_version_id is None
        assert row.model_used == "claude-fable-5"
        assert row.job_description.startswith("Senior Backend Engineer")
        loaded_items = json.loads(row.items)
        assert loaded_items[0]["section"] == "headline"

    def test_create_pending_supersedes_the_previous_pending_proposal(self, session):
        chat_session = chat_repo.create_session(session, title="Vaga X")
        session.commit()
        first = proposal_repo.create_pending(
            session, session_id=chat_session.id, job_description="JD 1", items=_items()
        )
        session.commit()

        second = proposal_repo.create_pending(
            session, session_id=chat_session.id, job_description="JD 2", items=_items(id_=2)
        )
        session.commit()

        session.refresh(first)
        assert first.status == "superseded"
        assert second.status == "proposed"
        assert second.id != first.id

    def test_create_pending_supersede_and_insert_happen_in_the_same_flush(self, session):
        """Atomicity: after create_pending (before any explicit commit), there must be exactly
        one 'proposed' row and the old one must already read as 'superseded' within the same
        transaction -- never a window with 2 pending or 0 pending."""
        chat_session = chat_repo.create_session(session, title="Vaga X")
        session.commit()
        first = proposal_repo.create_pending(
            session, session_id=chat_session.id, job_description="JD 1", items=_items()
        )
        session.commit()

        second = proposal_repo.create_pending(
            session, session_id=chat_session.id, job_description="JD 2", items=_items(id_=2)
        )
        # No commit() here yet -- inspect state within the same still-open transaction.

        session.refresh(first)
        pending = proposal_repo.get_pending(session, chat_session.id)
        assert first.status == "superseded"
        assert pending is not None
        assert pending.id == second.id

    def test_create_pending_does_not_touch_other_sessions_pending_proposal(self, session):
        session_a = chat_repo.create_session(session, title="A")
        session_b = chat_repo.create_session(session, title="B")
        session.commit()
        proposal_a = proposal_repo.create_pending(
            session, session_id=session_a.id, job_description="JD A", items=_items()
        )
        session.commit()

        proposal_repo.create_pending(
            session, session_id=session_b.id, job_description="JD B", items=_items(id_=2)
        )
        session.commit()

        session.refresh(proposal_a)
        assert proposal_a.status == "proposed"

    def test_create_pending_supersede_bumps_the_previous_rows_updated_at(self, session):
        chat_session = chat_repo.create_session(session, title="Vaga X")
        session.commit()
        first = proposal_repo.create_pending(
            session, session_id=chat_session.id, job_description="JD 1", items=_items()
        )
        session.commit()
        original_updated_at = first.updated_at
        original_created_at = first.created_at

        proposal_repo.create_pending(
            session, session_id=chat_session.id, job_description="JD 2", items=_items(id_=2)
        )
        session.commit()
        session.refresh(first)

        assert first.updated_at > original_updated_at
        assert first.created_at == original_created_at


class TestGet:
    def test_get_returns_the_row_by_id(self, session):
        chat_session = chat_repo.create_session(session, title="Vaga X")
        session.commit()
        created = proposal_repo.create_pending(
            session, session_id=chat_session.id, job_description="JD", items=_items()
        )
        session.commit()

        found = proposal_repo.get(session, created.id)

        assert found is not None
        assert found.id == created.id

    def test_get_returns_none_for_missing_id(self, session):
        assert proposal_repo.get(session, 999) is None


class TestGetPending:
    def test_get_pending_returns_the_proposed_row(self, session):
        chat_session = chat_repo.create_session(session, title="Vaga X")
        session.commit()
        created = proposal_repo.create_pending(
            session, session_id=chat_session.id, job_description="JD", items=_items()
        )
        session.commit()

        found = proposal_repo.get_pending(session, chat_session.id)

        assert found is not None
        assert found.id == created.id

    def test_get_pending_returns_none_when_no_proposal_exists(self, session):
        chat_session = chat_repo.create_session(session, title="Vaga X")
        session.commit()

        assert proposal_repo.get_pending(session, chat_session.id) is None

    def test_get_pending_returns_none_after_approval(self, session):
        chat_session = chat_repo.create_session(session, title="Vaga X")
        session.commit()
        row = proposal_repo.create_pending(
            session, session_id=chat_session.id, job_description="JD", items=_items()
        )
        session.commit()
        proposal_repo.mark_approved(session, row, resume_version_id=42)
        session.commit()

        assert proposal_repo.get_pending(session, chat_session.id) is None


class TestRevise:
    def test_revise_replaces_items_and_increments_revision(self, session):
        chat_session = chat_repo.create_session(session, title="Vaga X")
        session.commit()
        row = proposal_repo.create_pending(
            session, session_id=chat_session.id, job_description="JD", items=_items()
        )
        session.commit()

        new_items = _items(id_=1, proposed="Staff Backend Engineer")
        updated = proposal_repo.revise(session, row, items=new_items)
        session.commit()

        assert updated.revision == 2
        loaded_items = json.loads(updated.items)
        assert loaded_items[0]["proposed"] == "Staff Backend Engineer"
        assert updated.status == "proposed"

    def test_revise_twice_increments_revision_each_time(self, session):
        chat_session = chat_repo.create_session(session, title="Vaga X")
        session.commit()
        row = proposal_repo.create_pending(
            session, session_id=chat_session.id, job_description="JD", items=_items()
        )
        session.commit()

        proposal_repo.revise(session, row, items=_items(proposed="v2"))
        session.commit()
        updated = proposal_repo.revise(session, row, items=_items(proposed="v3"))
        session.commit()

        assert updated.revision == 3

    def test_revise_bumps_updated_at_but_not_created_at(self, session):
        chat_session = chat_repo.create_session(session, title="Vaga X")
        session.commit()
        row = proposal_repo.create_pending(
            session, session_id=chat_session.id, job_description="JD", items=_items()
        )
        session.commit()
        original_updated_at = row.updated_at
        original_created_at = row.created_at

        updated = proposal_repo.revise(session, row, items=_items(proposed="v2"))
        session.commit()

        assert updated.updated_at > original_updated_at
        assert updated.created_at == original_created_at

    def test_revise_raises_when_status_is_not_proposed(self, session):
        chat_session = chat_repo.create_session(session, title="Vaga X")
        session.commit()
        row = proposal_repo.create_pending(
            session, session_id=chat_session.id, job_description="JD", items=_items()
        )
        session.commit()
        proposal_repo.mark_approved(session, row, resume_version_id=1)
        session.commit()

        with pytest.raises(proposal_repo.IllegalProposalTransition):
            proposal_repo.revise(session, row, items=_items(proposed="too late"))


class TestMarkApproved:
    def test_mark_approved_sets_status_and_resume_version_id(self, session):
        chat_session = chat_repo.create_session(session, title="Vaga X")
        session.commit()
        row = proposal_repo.create_pending(
            session, session_id=chat_session.id, job_description="JD", items=_items()
        )
        session.commit()

        updated = proposal_repo.mark_approved(session, row, resume_version_id=99)
        session.commit()

        assert updated.status == "approved"
        assert updated.resume_version_id == 99

    def test_mark_approved_bumps_updated_at_but_not_created_at(self, session):
        chat_session = chat_repo.create_session(session, title="Vaga X")
        session.commit()
        row = proposal_repo.create_pending(
            session, session_id=chat_session.id, job_description="JD", items=_items()
        )
        session.commit()
        original_updated_at = row.updated_at
        original_created_at = row.created_at

        updated = proposal_repo.mark_approved(session, row, resume_version_id=99)
        session.commit()

        assert updated.updated_at > original_updated_at
        assert updated.created_at == original_created_at

    def test_mark_approved_raises_when_status_is_not_proposed(self, session):
        chat_session = chat_repo.create_session(session, title="Vaga X")
        session.commit()
        row = proposal_repo.create_pending(
            session, session_id=chat_session.id, job_description="JD", items=_items()
        )
        session.commit()
        proposal_repo.mark_approved(session, row, resume_version_id=1)
        session.commit()

        with pytest.raises(proposal_repo.IllegalProposalTransition):
            proposal_repo.mark_approved(session, row, resume_version_id=2)


class TestGetItems:
    def test_get_items_validates_with_pydantic(self, session):
        chat_session = chat_repo.create_session(session, title="Vaga X")
        session.commit()
        row = proposal_repo.create_pending(
            session, session_id=chat_session.id, job_description="JD", items=_items()
        )
        session.commit()

        items = proposal_repo.get_items(row)

        assert isinstance(items[0], ProposalItem)
        assert items[0].section == "headline"


class TestCascadeDelete:
    def test_deleting_the_session_cascades_the_proposal(self, session):
        chat_session = chat_repo.create_session(session, title="Vaga X")
        session.commit()
        row = proposal_repo.create_pending(
            session, session_id=chat_session.id, job_description="JD", items=_items()
        )
        session.commit()
        proposal_id = row.id  # captured before the cascade delete expires/removes `row`

        chat_repo.delete_session(session, chat_session.id)
        session.commit()

        assert proposal_repo.get(session, proposal_id) is None
