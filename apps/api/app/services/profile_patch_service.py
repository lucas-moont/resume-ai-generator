"""Shared write-path helper for the two Patch Validator consumers that append a new Profile
Version and respond with the same shape: ``PATCH /api/profile`` (routers/profile.py, manual
edit) and ``POST /api/profile/documents/{id}/apply`` (routers/documents.py). Extracted out of
routers/profile.py (ticket 04 prefactor) since it is domain/persistence logic, not HTTP wiring.
"""

from __future__ import annotations

import json

from sqlmodel import Session

from app.domain.profile_patch import PatchResult
from app.repositories import profile_repo


def persist_patch_result(
    session: Session,
    result: PatchResult,
    *,
    source_kind: str,
    change_summary: str,
    source_document_id: int | None = None,
    skipped: int | None = None,
) -> dict:
    """Appends the new Profile Version a Patch Validator result produces and returns the
    ``{profileVersion, applied, skipped}`` shape both callers respond with. ``skipped``
    overrides the plain ``len(result.skipped)`` count -- the apply-document caller uses this to
    fold in ops a ``{ops: [indices]}`` subset excluded before the Patch Validator ever saw them,
    so ``applied + skipped`` always equals the number of ops in the proposal it started from,
    not just the ones actually submitted.
    """
    new_version = profile_repo.insert_version(
        session,
        data=result.profile.model_dump_json(),
        source_kind=source_kind,
        patch=json.dumps([op.model_dump() for op in result.applied]),
        source_document_id=source_document_id,
        change_summary=change_summary,
    )
    session.commit()
    session.refresh(new_version)
    return {
        "profileVersion": new_version.version,
        "applied": len(result.applied),
        "skipped": len(result.skipped) if skipped is None else skipped,
    }
