"""Profile resolution (v2 ticket 01 — "Perfil vivo como fonte de leitura").

Replaces the v1 policy in the now-deleted ``profile_service.py`` (disk-only, no notion of the
DB-backed Living Profile) with a single seam every reader of "the active profile" goes
through: ``resolve_active_profile(session)``. Three callers converge on it, each dropping
their own bespoke version of this policy:

- ``app/routers/profile.py`` (``GET /api/profile``, ``GET /api/github/repos``) used to read
  disk directly with no notion of profile history.
- ``app/services/generation_service.py`` used to call the old disk-only
  ``load_active_profile_or_placeholder_pdf`` internally; it now receives an already-resolved
  ``ResolvedProfile`` from its caller (see that module).
- ``app/db/seed.py`` used to duplicate the disk-load + placeholder-check policy inline; it now
  calls ``load_real_profile_from_disk_or_none`` below, which shares the same disk-loading
  primitives (``load_profile`` / ``looks_like_placeholder_profile``) but keeps its own
  never-raise contract, since a bad on-disk profile must never crash server boot.

Policy, in order: the highest ``profile_versions`` row in the DB wins (source="db"); when the
DB has no versions yet, fall back to disk (source="disk") — same placeholder/PDF-extraction
policy v1 had (``needs_extraction`` tells the caller whether the on-disk profile looks like the
shipped placeholder and must be extracted from a Profile.pdf before it can be used; the caller
decides how to react — the router just serves the placeholder as-is, generation_service raises
if there is no PDF to extract from). A PDF text excerpt is loaded and returned unconditionally,
independent of DB/disk source, because generation reuses it as prompt context even when the
profile itself came from the DB (unchanged from v1's behavior); a PDF present but unreadable is
always a hard error, regardless of whether extraction is actually needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlmodel import Session

from app.config import resolve_profile_json_path
from app.domain.schemas import ProfileMaster, ResumeDocument
from app.repositories import profile_repo
from app.services.profile_pdf import load_profile_pdf_excerpt
from app.services.projects_loader import load_profile, looks_like_placeholder_profile


class ProfileValidationError(Exception):
    """A profile-resolution problem that is not "profile JSON missing" (see
    ``FileNotFoundError``, which callers should keep handling as a 404): invalid profile JSON
    content, a PDF that failed to extract, or (see ``finish_profile_from_extraction``) an
    extraction that produced too little data. Routers translate this to HTTP 400 / an SSE
    error message."""


@dataclass(frozen=True)
class ResolvedProfile:
    """What ``resolve_active_profile`` hands every caller: the profile itself, where it came
    from, and everything the generation pipeline's placeholder/PDF-extraction policy needs."""

    profile: ProfileMaster
    profile_version_id: int | None  # the profile_versions.id it came from; None when source="disk"
    source: Literal["db", "disk"]
    pdf_text: str
    pdf_path: Path | None
    needs_extraction: bool


def resolve_active_profile(session: Session) -> ResolvedProfile:
    """DB active version -> disk fallback -> placeholder/PDF policy (see module docstring).

    Raises ``FileNotFoundError`` when the DB is empty and no profile JSON exists on disk
    either, and ``ProfileValidationError`` for a broken Profile.pdf or invalid on-disk JSON.
    """
    pdf_text, pdf_path, pdf_err = load_profile_pdf_excerpt()
    if pdf_err and pdf_path is not None:
        raise ProfileValidationError(
            f"Profile PDF found at {pdf_path} but text extraction failed: {pdf_err}"
        )

    active = profile_repo.get_active(session)
    if active is not None:
        profile = ProfileMaster.model_validate_json(active.data)
        return ResolvedProfile(
            profile=profile,
            profile_version_id=active.id,
            source="db",
            pdf_text=pdf_text,
            pdf_path=pdf_path,
            needs_extraction=False,
        )

    try:
        profile = load_profile(resolve_profile_json_path())
    except FileNotFoundError:
        raise
    except Exception as e:
        raise ProfileValidationError(f"Invalid profile: {e}") from e

    return ResolvedProfile(
        profile=profile,
        profile_version_id=None,
        source="disk",
        pdf_text=pdf_text,
        pdf_path=pdf_path,
        needs_extraction=looks_like_placeholder_profile(profile),
    )


def finish_profile_from_extraction(extracted: ResumeDocument) -> ProfileMaster:
    """Validate an LLM-extracted profile and adopt it as the working ``ProfileMaster``."""
    if not extracted.fullName.strip() or not extracted.summary.strip():
        raise ProfileValidationError(
            "Could not extract enough data from Profile.pdf. "
            "Please complete data/profile/resume.json with your real details."
        )
    return ProfileMaster.model_validate({**extracted.model_dump(), "githubUsername": None})


def load_real_profile_from_disk_or_none() -> ProfileMaster | None:
    """Boot-time seeding helper (``app/db/seed.py``): loads the on-disk profile only when it
    is present, valid, and not the shipped placeholder. Never raises -- a missing file,
    invalid JSON, or placeholder content all just mean "nothing to seed", since a bad on-disk
    profile must never crash server boot."""
    try:
        profile = load_profile(resolve_profile_json_path())
    except FileNotFoundError:
        return None
    except Exception:
        return None
    if looks_like_placeholder_profile(profile):
        return None
    return profile
