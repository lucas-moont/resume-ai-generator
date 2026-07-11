"""Shared router dependencies -- extracted from app/main.py (B4); get_session added in B5."""

from collections.abc import Iterator

from fastapi import Request
from sqlmodel import Session

from app.db.engine import new_session
from app.services.errors import http_error
from app.services.profile_resolution import ProfileValidationError, ResolvedProfile, resolve_active_profile


def resolve_requested_model(model: str | None) -> str | None:
    if model is None:
        return None
    normalized = model.strip()
    return normalized or None


def get_session(request: Request) -> Iterator[Session]:
    """Real DB session dependency (B5), used by every profile/generate/refine/chat route as of
    v2 ticket 01. Yields a session from the factory bound to the engine main.py's lifespan
    stores on ``app.state.db_engine``. Tests override this via
    ``app.dependency_overrides[get_session]`` (see tests/conftest.py).
    """
    with new_session(request.app.state.db_engine) as session:
        yield session


def resolve_active_profile_or_error(session: Session) -> ResolvedProfile:
    """Shared by this app's two READ-ONLY consumers of "the active profile" -- routers/profile.py's
    ``GET /api/profile`` and routers/github.py's ``GET /api/github/repos`` -- extracted from two
    near-identical ``try/except FileNotFoundError/ProfileValidationError`` blocks (ticket 01
    review) that had drifted into different styles (one used ``http_error``, the other a bare
    ``HTTPException`` with a custom message). Moved here (ticket 04 prefactor) since it is now
    shared across two separate router modules rather than living in either one.

    NOT used by the write paths ticket 04 added (``PATCH /api/profile``,
    ``POST .../{id}/apply``): those call ``resolve_profile_for_merge`` instead
    (``services/ingestion/merge_service.py``), which additionally falls back to a blank
    ``ProfileMaster`` when neither a DB version nor a disk profile exists yet (bootstrapping a
    user's very first manual edit or upload) -- a fallback ``GET /api/profile`` deliberately
    does NOT get, since serving a fabricated blank profile as if it were real data would be
    wrong for a read.
    """
    try:
        return resolve_active_profile(session)
    except FileNotFoundError as e:
        raise http_error(404, str(e)) from e
    except ProfileValidationError as e:
        raise http_error(400, str(e)) from e
