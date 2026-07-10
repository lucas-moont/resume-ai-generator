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

As of v2 ticket 11, ``handle_chat_turn``'s optional ``client_resume`` lets a "refine" turn start
from the document the user is actually looking at (post inline-edit, never persisted) instead of
the DB's ``active_resume_version_id`` -- see ``_handle_refine_turn``. It is validated the same
way any other request field is (pydantic, at the router boundary) and ignored entirely by every
other intent; the resulting ``ResumeVersion`` still chains off the previously-active version as
``parent_version_id`` (unchanged provenance), with the fact that it started from a client
override recorded honestly on the assistant message's ``meta`` JSON
(``{"clientResumeOverride": true}``) rather than inventing a new column.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from sqlmodel import Session

from app.config import PROMPTS_DIR
from app.db.tables import ChatMessage, ChatSession
from app.domain.chat_intent import classify_intent
from app.domain.locale import DEFAULT_LOCALE, SUPPORTED_LOCALES, resolve_locale
from app.domain.profile_patch import PatchOp, PatchValidationFailed, apply_patch
from app.domain.schemas import ProfileMaster, ResumeDocument
from app.prompt_loader import load_profile_update_system_prompt
from app.repositories import chat_repo, profile_repo, resume_repo
from app.services import llm_client
from app.services.generation_service import generate_resume_events
from app.services.ingestion.merge_service import parse_patch_ops_from_llm_response, resolve_profile_for_merge
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

# v2 ticket 05: the profile_update turn has its own reply copy -- it is never a resume
# confirmation (generate/refine above), so it does not fit _REPLY_TEXT's per-intent-static
# shape (its content is templated with a per-turn summary, and branches on whether there is an
# active resume to offer regenerating).
_PROFILE_UPDATE_NOTHING_TEXT = {
    "en": (
        "I couldn't find a clear profile change in that message, so your profile is unchanged. "
        'Try naming exactly what changed (e.g. "my phone is now 555-0100").'
    ),
    "pt-BR": (
        "Não encontrei uma mudança clara de perfil nessa mensagem, então nada foi alterado. "
        'Tenta dizer exatamente o que mudou (ex.: "meu telefone agora é 11 99999-0000").'
    ),
}
_PROFILE_UPDATE_OFFER_REGENERATE = {
    "en": " Want me to update your resume with this change?",
    "pt-BR": " Quer que eu atualize seu currículo com essa mudança?",
}
_PROFILE_UPDATE_APPLIED_TEXT = {
    "en": "Updated your profile: {summary}.",
    "pt-BR": "Atualizei seu perfil: {summary}.",
}


def _reply_text_for_locale(intent: str, locale: str) -> str:
    """``locale`` must already be a concrete language, not run through resolve_locale here --
    see the two call sites below for why."""
    resolved = locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE
    return _REPLY_TEXT[intent][resolved]


def _resolve_concrete_locale(locale: str | None, user_message: str, profile_locale: str | None) -> str:
    resolved = resolve_locale(locale, user_message, profile_locale)
    return resolved if resolved in SUPPORTED_LOCALES else DEFAULT_LOCALE


def _format_history(messages: list, limit: int) -> str:
    recent = messages[-limit:]
    if not recent:
        return ""
    lines = [f"{m.role.capitalize()}: {m.content}" for m in recent]
    return "Conversation so far:\n" + "\n".join(lines)


def _finalize_resume_turn(
    session: Session,
    *,
    chat_session: ChatSession,
    resume_doc: ResumeDocument,
    intent: str,
    model: str | None,
    backend_label: str,
    profile_version_id: int | None,
    parent_version_id: int | None = None,
    extra_meta: dict | None = None,
):
    """Shared tail of the generate/refine turns (v2 ticket 05 AC: "insert_version deduplicado
    entre generate/refine"): inserts the new ``ResumeVersion``, points the session's active
    resume at it, appends the assistant confirmation message, and persists. Returns
    ``(resume_row, content, assistant_msg)`` for the caller to build its own SSE frames from --
    kept a plain function (not a generator) since it never yields, only the two callers do.

    ``extra_meta`` (v2 ticket 11) lets a caller record turn-specific provenance on the
    assistant message's ``meta`` JSON -- e.g. ``{"clientResumeOverride": True}`` for a refine
    that started from the client's in-memory doc rather than the DB's active version -- without
    ``resume_versions`` itself needing a new column for it.
    """
    resume_row = resume_repo.insert_version(
        session,
        data=resume_doc.model_dump_json(),
        session_id=chat_session.id,
        parent_version_id=parent_version_id,
        profile_version_id=profile_version_id,
        model_used=model,
        provider_used=backend_label,
    )
    chat_session.active_resume_version_id = resume_row.id
    session.add(chat_session)

    # Follows the RESULTING resume's own locale, not the session/request locale: a refine
    # turn can itself change the document's language (e.g. "translate this to English"),
    # which would otherwise leave the confirmation bubble in the stale, pre-turn language.
    content = _reply_text_for_locale(intent, resume_doc.locale)
    meta = {"model": model, "provider": backend_label}
    if extra_meta:
        meta.update(extra_meta)
    assistant_msg = chat_repo.append_message(
        session,
        session_id=chat_session.id,
        role="assistant",
        content=content,
        intent=intent,
        resume_version_id=resume_row.id,
        meta=json.dumps(meta),
    )
    chat_repo.touch_session(session, chat_session.id)
    session.commit()
    return resume_row, content, assistant_msg


async def _handle_question_turn(
    *, session: Session, chat_session: ChatSession, locale: str | None, user_message: str
) -> AsyncIterator[tuple[str, dict]]:
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


async def _handle_generate_turn(
    *,
    session: Session,
    chat_session: ChatSession,
    user_message: str,
    job_description: str | None,
    model: str | None,
    locale: str | None,
    backend_label: str,
) -> AsyncIterator[tuple[str, dict]]:
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
    chat_session.job_description = jd_text

    resume_row, content, assistant_msg = _finalize_resume_turn(
        session,
        chat_session=chat_session,
        resume_doc=resume_doc,
        intent="generate",
        model=model,
        backend_label=backend_label,
        profile_version_id=resolved_profile.profile_version_id,
    )
    yield "resume", {"resume": resume_doc, "resumeVersionId": resume_row.id}
    yield "message", {"content": content}
    yield "done", {"progress": 100, "messageId": assistant_msg.id, "resumeVersionId": resume_row.id}


async def _handle_refine_turn(
    *,
    session: Session,
    chat_session: ChatSession,
    user_message: str,
    prior_messages: list,
    active_resume_row,
    model: str | None,
    backend_label: str,
    client_resume_override: ResumeDocument | None = None,
) -> AsyncIterator[tuple[str, dict]]:
    history_text = _format_history(prior_messages, _HISTORY_MESSAGES_FOR_REFINE)
    enriched_message = f"{history_text}\n\nUser: {user_message}" if history_text else user_message
    # v2 ticket 11: an inline edit made only in the client (never persisted) must not be lost by
    # a chat refine -- prefer the client's own in-memory doc over the DB's active version when
    # the request carried one. It has already been through the SAME pydantic model_validate as
    # any other request field (ChatMessageRequest.resume); a shape that fails validation is a
    # plain 422 raised before this function -- or handle_chat_turn -- ever runs.
    base_resume = (
        client_resume_override
        if client_resume_override is not None
        else ResumeDocument.model_validate_json(active_resume_row.data)
    )
    resume_doc: ResumeDocument | None = None
    async for event, data in refine_resume_events(
        resume=base_resume, message=enriched_message, model=model, backend_label=backend_label
    ):
        if event == "done":
            resume_doc = data["resume"]
        else:
            yield event, data
    assert resume_doc is not None

    resume_row, content, assistant_msg = _finalize_resume_turn(
        session,
        chat_session=chat_session,
        resume_doc=resume_doc,
        intent="refine",
        model=model,
        backend_label=backend_label,
        profile_version_id=active_resume_row.profile_version_id,
        parent_version_id=active_resume_row.id,
        extra_meta={"clientResumeOverride": True} if client_resume_override is not None else None,
    )
    yield "resume", {"resume": resume_doc, "resumeVersionId": resume_row.id}
    yield "message", {"content": content}
    yield "done", {"progress": 100, "messageId": assistant_msg.id, "resumeVersionId": resume_row.id}


def _describe_patch_op(op: PatchOp) -> str:
    """Deterministic, non-LLM-authored one-liner for a single applied op -- same spirit as
    ``profile_diff.DiffResult.summary()``'s upload diff lines, but for a chat patch there is no
    Diff to summarize: it describes what actually landed in ``result.applied``."""
    field = op.path.strip("/").split("/")[0]
    if op.op == "remove":
        return f"removed {field}"
    if op.op == "add":
        label = None
        if isinstance(op.value, dict):
            label = op.value.get("company") or op.value.get("institution") or op.value.get("name")
        elif isinstance(op.value, str):
            label = op.value
        return f"added {field}" + (f": {label}" if label else "")
    return f"updated {field}"


def _summarize_applied_ops(ops: list[PatchOp]) -> str:
    return "; ".join(_describe_patch_op(op) for op in ops)


def _build_profile_update_user_message(profile: ProfileMaster, message: str) -> str:
    return (
        "The user's CURRENT profile (JSON) -- match any replace/remove target to an existing "
        "index in these lists; only 'add' may use '-':\n"
        f"{profile.model_dump_json(indent=2)}\n\n"
        f'User message: "{message}"\n\n'
        "Return PatchOp[] JSON only."
    )


async def _handle_profile_update_turn(
    *,
    session: Session,
    chat_session: ChatSession,
    user_message: str,
    user_msg_row: ChatMessage,
    model: str | None,
    locale: str | None,
    backend_label: str,
) -> AsyncIterator[tuple[str, dict]]:
    profile = resolve_profile_for_merge(session)
    raw = await llm_client.chat_json(
        load_profile_update_system_prompt(PROMPTS_DIR),
        _build_profile_update_user_message(profile, user_message),
        model=model,
    )
    ops = parse_patch_ops_from_llm_response(raw)

    applied: list[PatchOp] = []
    new_profile: ProfileMaster | None = None
    if ops:
        try:
            result = apply_patch(profile, ops, source_kind="chat")
            applied = result.applied
            new_profile = result.profile
        except PatchValidationFailed:
            applied = []  # LLM output that doesn't validate -- see module docstring

    resolved_locale = _resolve_concrete_locale(locale, user_message, profile.locale)

    if not applied:
        # "LLM devolvendo lixo" (module docstring): a friendly reply, never an SSE error --
        # the profile was never mutated (apply_patch only ever operates on a copy, and it was
        # not even called when `ops` came back empty).
        content = _PROFILE_UPDATE_NOTHING_TEXT[resolved_locale]
        assistant_msg = chat_repo.append_message(
            session,
            session_id=chat_session.id,
            role="assistant",
            content=content,
            intent="profile_update",
            meta=json.dumps({"model": model, "provider": backend_label}),
        )
        chat_repo.touch_session(session, chat_session.id)
        session.commit()
        yield "message", {"content": content}
        yield "done", {"progress": 100, "messageId": assistant_msg.id, "resumeVersionId": None}
        return

    assert new_profile is not None
    summary = _summarize_applied_ops(applied)
    new_version = profile_repo.insert_version(
        session,
        data=new_profile.model_dump_json(),
        source_kind="chat",
        patch=json.dumps([op.model_dump() for op in applied]),
        chat_message_id=user_msg_row.id,
        change_summary=f"Chat update: {summary}",
    )

    # Offers regeneration in natural language -- it never happens automatically (module
    # docstring / CONTEXT.md: profile_update). No offer at all when there is nothing yet to
    # regenerate.
    content = _PROFILE_UPDATE_APPLIED_TEXT[resolved_locale].format(summary=summary)
    if chat_session.active_resume_version_id is not None:
        content += _PROFILE_UPDATE_OFFER_REGENERATE[resolved_locale]

    assistant_msg = chat_repo.append_message(
        session,
        session_id=chat_session.id,
        role="assistant",
        content=content,
        intent="profile_update",
        meta=json.dumps({"model": model, "provider": backend_label}),
    )
    chat_repo.touch_session(session, chat_session.id)
    session.commit()

    yield "profile_update", {"profileVersion": new_version.version, "summary": summary}
    yield "message", {"content": content}
    # Unlike generate/refine, no resume was produced or touched by THIS turn (CONTEXT.md:
    # profile_update never regenerates automatically) -- mirrors the "question" intent's own
    # precedent of `resumeVersionId: None` for "no resume produced this turn", rather than
    # echoing back whatever the session's (unchanged) active resume already was.
    yield "done", {"progress": 100, "messageId": assistant_msg.id, "resumeVersionId": None}


async def handle_chat_turn(
    *,
    session: Session,
    chat_session: ChatSession,
    user_message: str,
    model: str | None,
    locale: str | None,
    job_description: str | None,
    backend_label: str,
    client_resume: ResumeDocument | None = None,
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
        async for event, data in _handle_question_turn(
            session=session, chat_session=chat_session, locale=locale, user_message=user_message
        ):
            yield event, data
        return

    try:
        if intent == "generate":
            async for event, data in _handle_generate_turn(
                session=session,
                chat_session=chat_session,
                user_message=user_message,
                job_description=job_description,
                model=model,
                locale=locale,
                backend_label=backend_label,
            ):
                yield event, data
        elif intent == "refine":
            async for event, data in _handle_refine_turn(
                session=session,
                chat_session=chat_session,
                user_message=user_message,
                prior_messages=prior_messages,
                active_resume_row=active_resume_row,
                model=model,
                backend_label=backend_label,
                client_resume_override=client_resume,
            ):
                yield event, data
        else:  # profile_update
            async for event, data in _handle_profile_update_turn(
                session=session,
                chat_session=chat_session,
                user_message=user_message,
                user_msg_row=user_msg_row,
                model=model,
                locale=locale,
                backend_label=backend_label,
            ):
                yield event, data
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
