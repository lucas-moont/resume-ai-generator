"""Shared router dependencies -- extracted from app/main.py (B4); get_session added in B5."""

from collections.abc import Iterator

from fastapi import Request
from sqlmodel import Session

from app.db.engine import new_session


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
