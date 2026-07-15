"""GET /api/profile[, /versions[, /versions/{n}]], PATCH /api/profile, and POST
/api/profile/revert (v2 ticket 01 -- "Perfil vivo como fonte de leitura"; PATCH added ticket 04).

Every read route here goes through ``profile_resolution.resolve_active_profile`` (DB active
version first, disk fallback when profile_versions is empty -- see that module's docstring)
instead of the v1 raw disk read this router used to do. ``/versions`` and ``/versions/{n}``
expose the append-only version history directly via ``profile_repo``; ``/revert`` never
rewrites history -- it inserts a new version (source_kind="revert") whose data copies the
target version's.

As of ticket 04's backend prefactor, this router owns ONLY the Living Profile's own reads,
versions, revert, and manual-edit write -- the Source Document upload pipeline lives in
routers/documents.py, and GET /api/github/repos in routers/github.py (both used to be inlined
here; see those modules' docstrings for why).
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from app.db.tables import ProfileVersion
from app.domain.profile_patch import PatchOp, PatchValidationFailed, apply_patch
from app.domain.schemas import RevertProfileRequest
from app.repositories import profile_repo
from app.routers.deps import get_session, resolve_active_profile_or_error
from app.services.errors import http_error
from app.services.ingestion.merge_service import resolve_profile_for_merge
from app.services.profile_patch_service import persist_patch_result
from app.services.profile_resolution import ProfileValidationError

router = APIRouter()


class PatchProfileRequest(BaseModel):
    ops: list[PatchOp]


class SetGithubUsernameRequest(BaseModel):
    githubUsername: str | None


def _version_dict(row: ProfileVersion) -> dict:
    return {
        "version": row.version,
        "sourceKind": row.source_kind,
        "changeSummary": row.change_summary,
        "createdAt": row.created_at.isoformat(),
    }


@router.get("/api/profile")
async def get_profile(session: Session = Depends(get_session)):
    resolved = resolve_active_profile_or_error(session)
    return resolved.profile.model_dump()


@router.patch("/api/profile")
async def patch_profile(body: PatchProfileRequest, session: Session = Depends(get_session)):
    """Manual/direct profile edit (docs/v2-living-profile.md item 5): the same Patch Validator
    every other write path goes through, with ``source_kind="manual"`` (so, unlike an upload,
    a ``remove`` op is allowed -- CONTEXT.md: Upload-never-removes only restricts uploads).
    """
    try:
        profile = resolve_profile_for_merge(session)
    except ProfileValidationError as e:
        raise http_error(400, str(e)) from e
    try:
        result = apply_patch(profile, body.ops, source_kind="manual")
    except PatchValidationFailed as e:
        raise http_error(422, f"Patch produced an invalid profile: {e}") from e

    return persist_patch_result(
        session,
        result,
        source_kind="manual",
        change_summary=f"Manual edit: {len(result.applied)} change(s)",
    )


@router.get("/api/profile/versions")
async def list_profile_versions(session: Session = Depends(get_session)):
    rows = profile_repo.list_versions(session)
    return {"versions": [_version_dict(r) for r in rows]}


@router.get("/api/profile/versions/{n}")
async def get_profile_version(n: int, session: Session = Depends(get_session)):
    row = profile_repo.get_by_version(session, n)
    if row is None:
        raise http_error(404, f"Profile version {n} not found")
    return {**_version_dict(row), "data": json.loads(row.data)}


@router.put("/api/profile/github-username")
async def set_github_username(
    body: SetGithubUsernameRequest, session: Session = Depends(get_session)
):
    """Dedicated write path for ``githubUsername`` -- deliberately bypasses ``apply_patch``
    (see profile_patch.py's module docstring: this field is excluded from the patch
    whitelist on purpose, populated only by this GitHub-linking flow, never by
    upload/chat/manual patches). Same insert-a-new-version pattern as ``revert_profile``.
    """
    try:
        profile = resolve_profile_for_merge(session)
    except ProfileValidationError as e:
        raise http_error(400, str(e)) from e

    normalized = body.githubUsername.strip() if body.githubUsername else None
    normalized = normalized or None
    updated = profile.model_copy(update={"githubUsername": normalized})

    new_row = profile_repo.insert_version(
        session,
        data=updated.model_dump_json(),
        source_kind="manual",
        change_summary=(
            f"Set GitHub username to {normalized}" if normalized else "Cleared GitHub username"
        ),
    )
    session.commit()
    session.refresh(new_row)
    return {"profileVersion": new_row.version, "githubUsername": normalized}


@router.post("/api/profile/revert")
async def revert_profile(body: RevertProfileRequest, session: Session = Depends(get_session)):
    target = profile_repo.get_by_version(session, body.toVersion)
    if target is None:
        raise http_error(404, f"Profile version {body.toVersion} not found")

    new_row = profile_repo.insert_version(
        session,
        data=target.data,
        source_kind="revert",
        change_summary=f"Reverted to version {body.toVersion}",
    )
    session.commit()
    session.refresh(new_row)
    return _version_dict(new_row)
