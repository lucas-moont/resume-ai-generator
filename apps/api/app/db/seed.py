"""Lifespan seed step (B5): if profile_versions is empty and the on-disk profile is real
(not the shipped placeholder), insert it as v1 (source_kind="seed_disk"). Legacy endpoints
keep reading straight from disk via app/services/profile_service.py -- this seed only
populates history for v2's DB-backed profile reads and B6's chat pipeline; it never blocks
or changes v1 request handling.
"""

from __future__ import annotations

import logging

from sqlmodel import Session

from app.config import resolve_profile_json_path
from app.db.tables import ProfileVersion
from app.repositories import profile_repo
from app.services.projects_loader import load_profile, looks_like_placeholder_profile

logger = logging.getLogger(__name__)


def seed_profile_from_disk_if_empty(engine) -> ProfileVersion | None:
    with Session(engine) as session:
        if profile_repo.get_active(session) is not None:
            logger.info("profile_versions already has data; skipping disk seed")
            return None

    try:
        profile = load_profile(resolve_profile_json_path())
    except FileNotFoundError:
        logger.info("no profile JSON on disk yet; skipping disk seed")
        return None
    except Exception:
        logger.info("profile JSON on disk is invalid; skipping disk seed", exc_info=True)
        return None

    if looks_like_placeholder_profile(profile):
        logger.info("on-disk profile looks like the shipped placeholder; skipping disk seed")
        return None

    with Session(engine) as session:
        row = profile_repo.insert_version(
            session,
            data=profile.model_dump_json(),
            source_kind="seed_disk",
            change_summary="seed from disk",
        )
        session.commit()
        session.refresh(row)
        return row
