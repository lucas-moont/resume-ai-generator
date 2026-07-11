"""GET /api/github/repos -- extracted from routers/profile.py (ticket 04 prefactor); this
route only ever reads the active profile (for its ``githubUsername`` fallback) and has no other
relationship to the Living Profile read/write routes profile.py still owns.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.routers.deps import get_session, resolve_active_profile_or_error
from app.services.github_client import fetch_user_repos

router = APIRouter()


@router.get("/api/github/repos")
async def github_repos(username: str | None = None, session: Session = Depends(get_session)):
    resolved = resolve_active_profile_or_error(session)
    user = username or resolved.profile.githubUsername
    if not user:
        return {"repos": [], "warning": "No githubUsername in profile and no username query"}
    repos, warn = await fetch_user_repos(user)
    return {
        "repos": [r.model_dump() for r in repos],
        "warning": warn,
    }
