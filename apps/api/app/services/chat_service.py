"""Chat orchestration (B6): deterministic intent routing over the SAME
generation_service/refine_service pipelines the legacy /api/generate and /api/refine
endpoints use, with session/message/resume persistence via the B5 repositories.

``handle_chat_turn`` is an async generator yielding ``(event, data)`` tuples where ``event``
is one of "stage" (forwarded as-is from generate/refine), "resume" ({"resume":
ResumeDocument, "resumeVersionId": int}), "message" ({"content": str} -- the assistant's chat
bubble text), or "done" ({"progress": 100, "messageId": int, "resumeVersionId": int | None}).
Errors propagate as exceptions (FileNotFoundError / ProfileValidationError / ExtractionError
/ TimeoutError / json.JSONDecodeError / the raw LLM exception), same as generation_service and
refine_service, for the router to translate into an SSE error frame.

Intent routing (v1, deterministic -- see docs/v1-chat-experience.md): a session with no
active resume whose message looks like a job description (heuristic: length + JD-keyword
density, ``looks_like_job_description`` below) routes to generate; a session with an active
resume routes to refine, folding the last few chat turns in as context; anything else (no
resume, message doesn't look like a JD -- e.g. a greeting) is a "question" intent: a canned,
locale-aware reply with no LLM call at all. No token-by-token streaming in v1.

Known v1 limitation: the generate pipeline's profile still comes from disk (see
generation_service.py / profile_service.py, unchanged by B6 -- switching that to the DB is a
v2 change), so the ``profile_version_id`` linked onto the resulting ResumeVersion is simply
whichever profile_versions row happens to be active in the DB (usually the B5 disk seed); it
is a best-effort provenance link in v1, not a guarantee that it is byte-identical to what the
LLM actually saw.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from sqlmodel import Session

from app.db.tables import ChatSession
from app.domain.keywords import extract_jd_keywords
from app.domain.locale import DEFAULT_LOCALE, SUPPORTED_LOCALES, resolve_locale
from app.domain.schemas import ResumeDocument
from app.repositories import chat_repo, profile_repo, resume_repo
from app.services.generation_service import generate_resume_events
from app.services.refine_service import refine_resume_events
from app.services.secret_redaction import redact_secrets

# A message needs to be substantial to be treated as a pasted job description outright; a
# shorter message can still count if it is dense with recognizable tech/role keywords (e.g.
# someone pasting just the "Requirements" bullet list rather than the full posting).
_JD_MIN_WORDS_STRONG_SIGNAL = 30
_JD_MIN_WORDS_WEAK_SIGNAL = 12
_JD_MIN_KEYWORDS_WEAK_SIGNAL = 3

# How many of the most recent messages (user + assistant, combined) are folded into a refine
# turn's instruction as context.
_HISTORY_MESSAGES_FOR_REFINE = 10

_REPLY_TEXT = {
    "generate": {
        "en": "Generated a tailored resume for this job description.",
        "pt-BR": "Currículo gerado com base na vaga.",
    },
    "refine": {
        "en": "Updated your resume.",
        "pt-BR": "Atualizei seu currículo.",
    },
    "question": {
        "en": (
            "Paste a job description to generate a tailored resume, or tell me what you'd "
            "like to change in an existing one."
        ),
        "pt-BR": (
            "Cole a descrição de uma vaga para eu gerar um currículo, ou me diga o que você "
            "quer mudar em um currículo já existente."
        ),
    },
}


def looks_like_job_description(message: str) -> bool:
    words = message.split()
    if len(words) >= _JD_MIN_WORDS_STRONG_SIGNAL:
        return True
    if len(words) >= _JD_MIN_WORDS_WEAK_SIGNAL:
        return len(extract_jd_keywords(message)) >= _JD_MIN_KEYWORDS_WEAK_SIGNAL
    return False


def _reply_text_for_locale(intent: str, locale: str) -> str:
    """``locale`` must already be a concrete language, not run through resolve_locale here --
    see the two call sites below for why."""
    resolved = locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE
    return _REPLY_TEXT[intent][resolved]


def _format_history(messages: list, limit: int) -> str:
    recent = messages[-limit:]
    if not recent:
        return ""
    lines = [f"{m.role.capitalize()}: {m.content}" for m in recent]
    return "Conversation so far:\n" + "\n".join(lines)


async def handle_chat_turn(
    *,
    session: Session,
    chat_session: ChatSession,
    user_message: str,
    model: str | None,
    locale: str | None,
    job_description: str | None,
    backend_label: str,
) -> AsyncIterator[tuple[str, dict]]:
    _, prior_messages = chat_repo.get_session_with_messages(session, chat_session.id)
    chat_repo.append_message(session, session_id=chat_session.id, role="user", content=user_message)
    if locale is not None:
        # Persisted regardless of intent so GET /api/chat/sessions/{id} can feed the
        # frontend's composer (e.g. defaulting the input language) even before any resume
        # has been generated.
        chat_session.locale = locale
        session.add(chat_session)
    session.commit()

    active_resume_row = None
    if chat_session.active_resume_version_id is not None:
        active_resume_row = resume_repo.get(session, chat_session.active_resume_version_id)

    if active_resume_row is None and looks_like_job_description(user_message):
        intent = "generate"
    elif active_resume_row is not None:
        intent = "refine"
    else:
        intent = "question"

    if intent == "question":
        # No resume is involved in this turn, so the session/request locale (falling back to
        # auto-detection from the user's own message) is the only signal available.
        content = _reply_text_for_locale("question", resolve_locale(locale, user_message, None))
        assistant_msg = chat_repo.append_message(
            session, session_id=chat_session.id, role="assistant", content=content, intent="question"
        )
        chat_repo.touch_session(session, chat_session.id)
        session.commit()
        yield "message", {"content": content}
        yield "done", {"progress": 100, "messageId": assistant_msg.id, "resumeVersionId": None}
        return

    try:
        if intent == "generate":
            jd_text = job_description or user_message
            resume_doc: ResumeDocument | None = None
            async for event, data in generate_resume_events(
                job_description=jd_text, model=model, locale=locale, backend_label=backend_label
            ):
                if event == "done":
                    resume_doc = data["resume"]
                else:
                    yield event, data
            assert resume_doc is not None
            active_profile = profile_repo.get_active(session)
            resume_row = resume_repo.insert_version(
                session,
                data=resume_doc.model_dump_json(),
                session_id=chat_session.id,
                profile_version_id=active_profile.id if active_profile else None,
                model_used=model,
                provider_used=backend_label,
            )
            chat_session.job_description = jd_text
        else:  # refine
            history_text = _format_history(prior_messages, _HISTORY_MESSAGES_FOR_REFINE)
            enriched_message = f"{history_text}\n\nUser: {user_message}" if history_text else user_message
            base_resume = ResumeDocument.model_validate_json(active_resume_row.data)
            resume_doc = None
            async for event, data in refine_resume_events(
                resume=base_resume, message=enriched_message, model=model, backend_label=backend_label
            ):
                if event == "done":
                    resume_doc = data["resume"]
                else:
                    yield event, data
            assert resume_doc is not None
            resume_row = resume_repo.insert_version(
                session,
                data=resume_doc.model_dump_json(),
                session_id=chat_session.id,
                parent_version_id=active_resume_row.id,
                profile_version_id=active_resume_row.profile_version_id,
                model_used=model,
                provider_used=backend_label,
            )
    except Exception as e:
        chat_repo.append_message(
            session,
            session_id=chat_session.id,
            role="assistant",
            content="",
            intent=intent,
            meta=json.dumps({"model": model, "provider": backend_label, "error": redact_secrets(str(e))}),
        )
        chat_repo.touch_session(session, chat_session.id)
        session.commit()
        raise

    chat_session.active_resume_version_id = resume_row.id
    session.add(chat_session)

    # Follows the RESULTING resume's own locale, not the session/request locale: a refine
    # turn can itself change the document's language (e.g. "translate this to English"),
    # which would otherwise leave the confirmation bubble in the stale, pre-turn language.
    content = _reply_text_for_locale(intent, resume_doc.locale)
    assistant_msg = chat_repo.append_message(
        session,
        session_id=chat_session.id,
        role="assistant",
        content=content,
        intent=intent,
        resume_version_id=resume_row.id,
        meta=json.dumps({"model": model, "provider": backend_label}),
    )
    chat_repo.touch_session(session, chat_session.id)
    session.commit()

    yield "resume", {"resume": resume_doc, "resumeVersionId": resume_row.id}
    yield "message", {"content": content}
    yield "done", {"progress": 100, "messageId": assistant_msg.id, "resumeVersionId": resume_row.id}
