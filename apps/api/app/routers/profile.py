"""GET /api/profile[, /versions[, /versions/{n}]] and POST /api/profile/revert (v2 ticket
01 -- "Perfil vivo como fonte de leitura").

Every route here goes through ``profile_resolution.resolve_active_profile`` for reads (DB
active version first, disk fallback when profile_versions is empty -- see that module's
docstring) instead of the v1 raw disk read this router used to do. ``/versions`` and
``/versions/{n}`` expose the append-only version history directly via ``profile_repo``;
``/revert`` never rewrites history -- it inserts a new version (source_kind="revert") whose
data copies the target version's.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db.tables import ProfileVersion
from app.domain.schemas import RevertProfileRequest
from app.repositories import profile_repo
from app.routers.deps import get_session
from app.services.errors import http_error
from app.services.github_client import fetch_user_repos
from app.services.profile_resolution import ProfileValidationError, resolve_active_profile

router = APIRouter()


def _version_dict(row: ProfileVersion) -> dict:
    return {
        "version": row.version,
        "sourceKind": row.source_kind,
        "changeSummary": row.change_summary,
        "createdAt": row.created_at.isoformat(),
    }


@router.get("/api/profile")
async def get_profile(session: Session = Depends(get_session)):
    try:
        resolved = resolve_active_profile(session)
    except FileNotFoundError as e:
        raise http_error(404, str(e)) from e
    except ProfileValidationError as e:
        raise http_error(400, str(e)) from e
    return resolved.profile.model_dump()


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


@router.get("/api/github/repos")
async def github_repos(username: str | None = None, session: Session = Depends(get_session)):
    try:
        resolved = resolve_active_profile(session)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Profile JSON not found — see README (data/profile/resume.json).",
        ) from None
    except ProfileValidationError as e:
        raise http_error(400, str(e)) from e
    user = username or resolved.profile.githubUsername
    if not user:
        return {"repos": [], "warning": "No githubUsername in profile and no username query"}
    repos, warn = await fetch_user_repos(user)
    return {
        "repos": [r.model_dump() for r in repos],
        "warning": warn,
    }
