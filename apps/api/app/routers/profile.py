from fastapi import APIRouter, HTTPException

from app.config import resolve_profile_json_path
from app.services.errors import http_error
from app.services.github_client import fetch_user_repos
from app.services.projects_loader import load_profile

router = APIRouter()


@router.get("/api/profile")
async def get_profile():
    try:
        profile = load_profile(resolve_profile_json_path())
    except FileNotFoundError as e:
        raise http_error(404, str(e)) from e
    except Exception as e:
        raise http_error(400, f"Invalid profile JSON: {e}") from e
    return profile.model_dump()


@router.get("/api/github/repos")
async def github_repos(username: str | None = None):
    try:
        profile = load_profile(resolve_profile_json_path())
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Profile JSON not found — see README (data/profile/resume.json).",
        ) from None
    user = username or profile.githubUsername
    if not user:
        return {"repos": [], "warning": "No githubUsername in profile and no username query"}
    repos, warn = await fetch_user_repos(user)
    return {
        "repos": [r.model_dump() for r in repos],
        "warning": warn,
    }
