"""Profile resolution (disk-backed in v1; a DB-backed version arrives in v2) -- extracted
from app/main.py (B4).

Splits the "load the working profile, falling back to LLM extraction from Profile.pdf when
it looks like the shipped placeholder" concern that was duplicated between /api/generate and
/api/generate/stream into two plain (non-generator) steps a caller can sequence around its own
LLM-call strategy (plain await for the sync endpoint, heartbeat-wrapped for the stream one):

1. ``load_active_profile_or_placeholder_pdf()`` -- disk-only, fast, no LLM call. Tells the
   caller whether extraction is needed and hands back the PDF text to extract from.
2. ``finish_profile_from_extraction(...)`` -- validates the LLM's extraction result (the
   caller is responsible for actually calling ``extract_profile_from_text`` in between, so it
   can wrap that specific call with progress reporting when streaming).
"""

from pathlib import Path

from app.config import resolve_profile_json_path
from app.domain.schemas import ProfileMaster, ResumeDocument
from app.services.profile_pdf import load_profile_pdf_excerpt
from app.services.projects_loader import load_profile, looks_like_placeholder_profile


class ProfileValidationError(Exception):
    """A profile-resolution problem that is not "profile JSON missing" (see
    ``FileNotFoundError``, which callers should keep handling as a 404): invalid profile JSON
    content, a PDF that failed to extract, a placeholder profile with no PDF to fall back to,
    or (see ``finish_profile_from_extraction``) an extraction that produced too little data.
    Routers translate this to HTTP 400 / an SSE error message."""


def load_active_profile_or_placeholder_pdf() -> tuple[ProfileMaster, str, Path | None, bool]:
    """Returns ``(profile, pdf_text, pdf_path, needs_extraction)``.

    ``needs_extraction`` is True when the on-disk profile looks like the shipped placeholder
    and a Profile.pdf was found -- the caller must then call ``extract_profile_from_text``
    itself and pass the result to ``finish_profile_from_extraction`` below. ``pdf_text``/
    ``pdf_path`` are also returned unconditionally (even when extraction isn't needed) because
    the generation pipeline reuses the same PDF excerpt as supporting context in its prompt.
    """
    try:
        profile = load_profile(resolve_profile_json_path())
    except FileNotFoundError:
        raise
    except Exception as e:
        raise ProfileValidationError(f"Invalid profile: {e}") from e

    pdf_text, pdf_path, pdf_err = load_profile_pdf_excerpt()
    if pdf_err and pdf_path is not None:
        raise ProfileValidationError(
            f"Profile PDF found at {pdf_path} but text extraction failed: {pdf_err}"
        )

    needs_extraction = looks_like_placeholder_profile(profile)
    if needs_extraction and not (pdf_text and pdf_path is not None):
        raise ProfileValidationError(
            "Profile appears to be the example template. Add real data to "
            "data/profile/resume.json or provide data/profile/Profile.pdf for extraction."
        )
    return profile, pdf_text, pdf_path, needs_extraction


def finish_profile_from_extraction(extracted: ResumeDocument) -> ProfileMaster:
    """Validate an LLM-extracted profile and adopt it as the working ``ProfileMaster``."""
    if not extracted.fullName.strip() or not extracted.summary.strip():
        raise ProfileValidationError(
            "Could not extract enough data from Profile.pdf. "
            "Please complete data/profile/resume.json with your real details."
        )
    return ProfileMaster.model_validate({**extracted.model_dump(), "githubUsername": None})
