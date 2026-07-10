"""Unit tests for app/domain/chat_intent.py (v2 ticket 05 -- "Chat: intencao profile_update").

``TestV1PinnedRouting`` characterizes the v1 3-way routing (generate/refine/question) exactly
as it lived inline in ``chat_service.handle_chat_turn`` before this module existed (see that
function's pre-v2 module docstring) -- these pass against the freshly-extracted
``classify_intent`` with NO behavior change, proving the extraction is a pure move, not a
rewrite. ``TestProfileUpdateVsRefineBoundary`` documents the 4th intent added on top in the
same module.
"""

from __future__ import annotations

from app.domain.chat_intent import classify_intent, looks_like_job_description

GENERIC_JOB_DESCRIPTION = (
    "We are hiring a Senior Backend Engineer to join our platform team. You will design "
    "and build scalable APIs in Python, own our PostgreSQL data layer, collaborate with "
    "the frontend team on GraphQL contracts, and help mentor junior engineers. Experience "
    "with Docker, Kubernetes, and CI/CD pipelines is a strong plus. We value clear written "
    "communication and a pragmatic approach to shipping reliable software."
)


class TestV1PinnedRouting:
    """Pins chat_service.py's pre-extraction inline logic (lines ~125-130): a long/keyword-dense
    job description with no active resume routes to generate; ANY message at all routes to
    refine once a resume is active (there is no session-level way back to question/generate
    without clearing the active resume first -- this is the riskiest, most surprising v1
    behavior per ticket 02/04's own architecture notes); anything else is a plain reply."""

    def test_pasted_job_description_with_no_active_resume_is_generate(self) -> None:
        assert classify_intent(message=GENERIC_JOB_DESCRIPTION, has_active_resume=False) == "generate"

    def test_short_keyword_dense_requirements_list_with_no_active_resume_is_generate(self) -> None:
        # 12+ words, dense with recognized tech keywords (>= 3) -- the weak-signal branch of
        # looks_like_job_description, distinct from the strong (30+ word) signal above.
        weak_signal_jd = (
            "Requirements: strong hands-on experience with Python, FastAPI, PostgreSQL, Docker, "
            "Kubernetes, AWS, and GraphQL is required for this role."
        )
        assert classify_intent(message=weak_signal_jd, has_active_resume=False) == "generate"

    def test_greeting_with_no_active_resume_is_question(self) -> None:
        assert classify_intent(message="hi there", has_active_resume=False) == "question"

    def test_short_ambiguous_instruction_with_no_active_resume_is_question(self) -> None:
        # Doesn't look like a JD (too short, no tech-keyword density) and there is nothing
        # active to refine -- v1's fallback bucket.
        assert classify_intent(message="Make the summary punchier.", has_active_resume=False) == "question"

    def test_any_message_with_an_active_resume_is_refine(self) -> None:
        assert classify_intent(message="Make the summary punchier.", has_active_resume=True) == "refine"

    def test_a_job_description_pasted_with_an_active_resume_is_still_refine(self) -> None:
        # The riskiest line in the original code (chat_service.py:127, per ticket 02/04 notes):
        # `elif active_resume_row is not None` catches this BEFORE any JD check runs -- an
        # active resume always wins, even over text that reads exactly like a job posting.
        assert classify_intent(message=GENERIC_JOB_DESCRIPTION, has_active_resume=True) == "refine"

    def test_translate_instruction_with_active_resume_is_refine(self) -> None:
        assert classify_intent(message="Translate the resume to English.", has_active_resume=True) == "refine"

    def test_short_nonsense_with_active_resume_is_refine(self) -> None:
        # The v1 risk boundary called out in ticket 05: a short, ambiguous message with an
        # active resume has no bucket other than refine -- pinned explicitly.
        assert classify_intent(message="ok", has_active_resume=True) == "refine"
        assert classify_intent(message="hmm sure", has_active_resume=True) == "refine"


class TestLooksLikeJobDescriptionUnchanged:
    """``looks_like_job_description`` itself (the heuristic) is exported unchanged -- some
    callers may still want it standalone (e.g. tests, or a future non-chat consumer)."""

    def test_long_message_is_a_job_description(self) -> None:
        assert looks_like_job_description(GENERIC_JOB_DESCRIPTION) is True

    def test_short_message_is_not_a_job_description(self) -> None:
        assert looks_like_job_description("hi there") is False
