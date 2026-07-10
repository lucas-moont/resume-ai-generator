"""Chat orchestration (B6): deterministic intent routing over the SAME
generation_service/refine_service pipelines the legacy /api/generate and /api/refine
endpoints use, with session/message/resume persistence via the B5 repositories.

``handle_chat_turn`` is an async generator yielding ``(event, data)`` tuples where ``event``
is one of "stage" (forwarded as-is from generate/refine), "resume" ({"resume":
ResumeDocument, "resumeVersionId": int}), "message" ({"content": str} -- the assistant's chat
bubble text), "profile_update" ({"profileVersion": int, "summary": str} -- v2 ticket 05, see
below), or "done" ({"progress": 100, "messageId": int, "resumeVersionId": int | None}).
Errors propagate as exceptions (FileNotFoundError / ProfileValidationError / ExtractionError
/ TimeoutError / json.JSONDecodeError / the raw LLM exception), same as generation_service and
refine_service, for the router to translate into an SSE error frame.

Intent routing (CONTEXT.md: Intent) is deterministic -- ``app.domain.chat_intent.classify_intent``
is the single seam, no LLM call spent deciding it. Four intents: "generate" (a session with no
active resume whose message looks like a job description), "refine" (an active resume exists --
folds the last few chat turns in as context), "profile_update" (v2 ticket 05 -- the message names
a Living Profile FACT change, e.g. "I changed my phone number"; checked BEFORE generate/refine so
it wins even with an active resume), or "question" (a canned, locale-aware reply with no LLM
call). No token-by-token streaming.

As of v2 ticket 01, the "generate" branch resolves the profile ONCE via
``profile_resolution.resolve_active_profile(session)`` and threads that same
``ResolvedProfile`` into both ``generate_resume_events`` (what the LLM prompt is built from)
and the ``profile_version_id`` stamped on the resulting ``ResumeVersion`` -- closing the v1
gap where that link was a best-effort, separately-fetched ``profile_repo.get_active(session)``
call that was not guaranteed to match whatever generation_service had independently read from
disk.

As of v2 ticket 05, "profile_update" turns an LLM-adjudicated ``PatchOp[]`` (reusing
``merge_service.parse_patch_ops_from_llm_response``'s tolerant parsing -- no second, duplicate
parser) into a new ``profile_versions`` row (``source_kind="chat"``, ``chat_message_id`` set to
the triggering user message) via the SAME Patch Validator (``domain.profile_patch.apply_patch``)
every other write path goes through, with ``source_kind="chat"`` -- the one source_kind besides
"manual" allowed to ``remove`` (CONTEXT.md: Upload-never-removes only restricts uploads). It
NEVER regenerates the active resume; the "message" event that follows only *offers* regeneration
in natural language. An LLM response that yields no usable ops (garbage, or a patch that fails
final schema validation) is not an error -- it is a friendly "nothing changed" reply, profile
left untouched, exactly like a real error would leave it (the Patch Validator only ever mutates
a copy).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from sqlmodel import Session

from app.db.tables import ChatSession
from app.domain.chat_intent import classify_intent
from app.domain.locale import DEFAULT_LOCALE, SUPPORTED_LOCALES, resolve_locale
from app.domain.schemas import ResumeDocument
from app.repositories import chat_repo, resume_repo
from app.services.generation_service import generate_resume_events
from app.services.profile_resolution import resolve_active_profile
from app.services.refine_service import refine_resume_events
from app.services.secret_redaction import redact_secrets

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
    user_msg_row = chat_repo.append_message(
        session, session_id=chat_session.id, role="user", content=user_message
    )
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

    intent = classify_intent(message=user_message, has_active_resume=active_resume_row is not None)

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
            resolved_profile = resolve_active_profile(session)
            resume_doc: ResumeDocument | None = None
            async for event, data in generate_resume_events(
                resolved_profile=resolved_profile,
                job_description=jd_text,
                model=model,
                locale=locale,
                backend_label=backend_label,
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
                profile_version_id=resolved_profile.profile_version_id,
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
