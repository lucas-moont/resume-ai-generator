"""The Job Monitor's HTTP surface (v7), prefix ``/api/jobs``.

Thin HTTP-shape adapter, like every other router here: the Search Profile's defaults,
validation and suggestion rules live in ``app/services/jobs/search_profile_service.py``, and
this module only parses, delegates, commits and maps a service error onto a status code.

Sections are ordered as the spec's Backend-6 lists them -- Search Profile, boards, and (ticket
09) scans and listings -- so the file stays readable as it grows to the full surface.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.domain.schemas import BoardListOut, SearchProfileIn, SearchProfileOut
from app.routers.deps import get_session, resolve_active_profile_or_error
from app.services.errors import http_error
from app.services.jobs import search_profile_service

router = APIRouter(prefix="/api/jobs")


# --- Search Profile ----------------------------------------------------------------------------


@router.get("/search-profile", response_model=SearchProfileOut)
async def get_search_profile(session: Session = Depends(get_session)) -> SearchProfileOut:
    """The saved Search Profile, or the defaults when the user has never saved one.

    Never 404s and never writes: ``updatedAt is None`` is how the response says "these are
    defaults, nothing was saved" (see the service's module docstring for why a GET must not
    persist them).
    """
    return search_profile_service.get_search_profile(session)


@router.put("/search-profile", response_model=SearchProfileOut)
async def put_search_profile(
    body: SearchProfileIn, session: Session = Depends(get_session)
) -> SearchProfileOut:
    """Replace the whole Search Profile. A PUT, not a PATCH: the form sends every field, so an
    empty list means the user emptied it rather than "unchanged"."""
    try:
        saved = search_profile_service.put_search_profile(session, body)
    except search_profile_service.SearchProfileValidationError as e:
        raise http_error(422, str(e)) from e
    session.commit()
    return saved


@router.post("/search-profile/suggest", response_model=SearchProfileOut)
async def suggest_search_profile(session: Session = Depends(get_session)) -> SearchProfileOut:
    """A Search Profile suggested from the Profile -- deterministic, no LLM, NOT saved.

    Resolves the Profile through the same read-only seam ``GET /api/profile`` uses, so "there
    is no profile yet" is the same 404 the rest of the app already answers with, rather than a
    suggestion that would pretend to be derived from data that does not exist.
    """
    resolved = resolve_active_profile_or_error(session)
    return search_profile_service.suggest_from_profile(resolved.profile)


# --- Job Boards --------------------------------------------------------------------------------


@router.get("/boards", response_model=BoardListOut)
async def list_boards() -> BoardListOut:
    """The Job Board catalog the Search Profile form renders its checkboxes from. Static: it
    needs neither a session nor a loaded adapter."""
    return search_profile_service.list_boards()
