"""Lifespan seed step (B5): if profile_versions is empty and the on-disk profile is real
(not the shipped placeholder), insert it as v1 (source_kind="seed_disk"). As of v2 ticket 01,
reads (GET /api/profile, generation) go through app/services/profile_resolution.py, which
resolves the DB's active version first and only falls back to disk when profile_versions is
empty -- this seed step is what populates that DB history in the first place.
"""

from __future__ import annotations

import logging

from sqlmodel import Session

from app.db.tables import ProfileVersion
from app.repositories import profile_repo
from app.services.profile_resolution import load_real_profile_from_disk_or_none

logger = logging.getLogger(__name__)


def seed_profile_from_disk_if_empty(engine) -> ProfileVersion | None:
    with Session(engine) as session:
        if profile_repo.get_active(session) is not None:
            logger.info("profile_versions already has data; skipping disk seed")
            return None

    profile = load_real_profile_from_disk_or_none()
    if profile is None:
        logger.info(
            "no usable profile JSON on disk (missing, invalid, or the shipped placeholder); "
            "skipping disk seed"
        )
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
