"""Repository for improvement_proposals (v4 ticket B1 -- "Proposta Conversacional de
Melhorias"). This is the ONLY path allowed to transition an ImprovementProposal's status --
routers/services must go through here rather than mutating `.status` directly, so the
invariants in docs/v4-improvement-proposal.md SS1.3 hold everywhere:

  - At most one 'proposed' row per session: `create_pending` supersedes any prior 'proposed'
    row for the same session in the SAME flush as the insert (see its docstring).
  - `revise`/`mark_approved` only apply to a row currently 'proposed'; any other status raises
    `IllegalProposalTransition` -- an illegal transition is a bug, never silently ignored.

Same convention as the other repositories here: callers own the transaction (commit/
rollback); functions only add/flush so multiple calls on the same Session compose into one
transaction.
"""

from __future__ import annotations

import json

from sqlmodel import Session, select

from app.db.tables import ImprovementProposal
from app.domain.schemas import ProposalItem


class IllegalProposalTransition(Exception):
    """Raised when a caller attempts to `revise`/`mark_approved` a proposal that is not
    currently 'proposed' (e.g. already approved or superseded)."""


def _serialize_items(items: list[ProposalItem]) -> str:
    return json.dumps([item.model_dump() for item in items])


def get_items(row: ImprovementProposal) -> list[ProposalItem]:
    """Deserializes `row.items`, validating each entry with pydantic -- same pattern as
    PatchOp.model_validate(...) over SourceDocument.proposed_patch (routers/documents.py)."""
    return [ProposalItem.model_validate(item) for item in json.loads(row.items)]


def create_pending(
    session: Session,
    *,
    session_id: int,
    job_description: str,
    items: list[ProposalItem],
    model_used: str | None = None,
) -> ImprovementProposal:
    """Inserts a new 'proposed' row for `session_id`. If the session already has a 'proposed'
    row (a prior Analysis, or a pending proposal about to be replaced by a New JD), that row
    is marked 'superseded' in the SAME flush as this insert -- both changes land in one
    `session.flush()` call, so there is never an intermediate state (within the transaction or
    after commit) with two 'proposed' rows for the same session, nor a window with zero rows
    while the old one is being retired.
    """
    previous = get_pending(session, session_id)
    if previous is not None:
        previous.status = "superseded"
        session.add(previous)

    row = ImprovementProposal(
        session_id=session_id,
        job_description=job_description,
        items=_serialize_items(items),
        model_used=model_used,
    )
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def get(session: Session, proposal_id: int) -> ImprovementProposal | None:
    """Looks up a proposal by id via a plain SELECT (not `Session.get()`): callers such as
    the session GET endpoint's live join (SS1.3 -- `meta.proposalId`) may ask about a
    proposal id whose row was cascade-deleted at the DB level out from under an
    already-identity-mapped instance from earlier in the same Session; `Session.get()` would
    raise `ObjectDeletedError` in that case instead of returning None."""
    return session.exec(
        select(ImprovementProposal).where(ImprovementProposal.id == proposal_id)
    ).first()


def get_pending(session: Session, session_id: int) -> ImprovementProposal | None:
    """The session's current 'proposed' row, if any -- the invariant (SS1.3) guarantees at
    most one."""
    return session.exec(
        select(ImprovementProposal).where(
            ImprovementProposal.session_id == session_id,
            ImprovementProposal.status == "proposed",
        )
    ).first()


def revise(
    session: Session, row: ImprovementProposal, *, items: list[ProposalItem]
) -> ImprovementProposal:
    """An `adjust` turn: replaces `items` wholesale (never a delta/merge) and bumps
    `revision`. Only legal while `row.status == 'proposed'`."""
    if row.status != "proposed":
        raise IllegalProposalTransition(
            f"cannot revise proposal {row.id}: status is {row.status!r}, not 'proposed'"
        )
    row.items = _serialize_items(items)
    row.revision += 1
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def mark_approved(session: Session, row: ImprovementProposal, *, resume_version_id: int) -> ImprovementProposal:
    """Records the approve branch's outcome: `resume_version_id` is a soft ref (Provenance),
    same treatment as the other soft refs in app/db/tables.py's module docstring. Only legal
    while `row.status == 'proposed'`."""
    if row.status != "proposed":
        raise IllegalProposalTransition(
            f"cannot approve proposal {row.id}: status is {row.status!r}, not 'proposed'"
        )
    row.status = "approved"
    row.resume_version_id = resume_version_id
    session.add(row)
    session.flush()
    session.refresh(row)
    return row
