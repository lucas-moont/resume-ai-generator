"""Profile Analysis motor (v5, ticket b3): drives one Analysis Turn end to end.

An Analysis Turn is the ONLY thing a ``profile_analysis`` session ever does -- the resume
Intent classifier never runs here (chat_service.handle_chat_turn branches on
``chat_session.kind`` before it). One LLM call returns either an Analysis (per-section items +
summary) or a Clarifying Question; unusable output (``parse_analysis_json`` -> ``None``) falls
back to a canned, locale-aware reply -- never an error frame, mirroring the Proposal Turn's
tolerance.

Read-only: this turn appends exactly one assistant ``chat_message`` (carrying the structured
payload in ``meta`` for rehydration) and never writes a ResumeVersion, a ProfileVersion, or the
Living Profile. SSE per docs/v5-profile-analysis.md §Contrato SSE: an analysis turn emits
``analysis`` (the card) before the ``message`` bubble it attaches to; a question turn emits only
the ``message`` bubble.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from app.config import LLM_TIMEOUT_SECONDS, PROMPTS_DIR
from app.db.tables import ChatSession
from app.domain.locale import DEFAULT_LOCALE, resolve_locale
from app.domain.prompts_builder import build_analysis_user_msg
from app.prompt_loader import load_linkedin_analysis_system_prompt
from app.repositories import chat_repo
from app.services import llm_client, streaming
from app.services.llm.analysis_json_parser import (
    ParsedAnalysisQuestion,
    ParsedAnalysisResult,
    parse_analysis_json,
)
from app.services.streaming import run_with_heartbeat

# Canned, locale-aware reply used ONLY when the LLM output is unusable (parse_analysis_json ->
# None): the turn never produces an error frame over garbage, same policy as the Proposal Turn.
_ANALYSIS_FALLBACK_TEXT = {
    "en": (
        "I couldn't turn that into concrete LinkedIn advice. Tell me which section you want to "
        "improve (headline, About, experience, skills) and paste its current text, or upload "
        "your LinkedIn PDF export."
    ),
    "pt-BR": (
        "Não consegui transformar isso em conselhos concretos de LinkedIn. Me diga qual seção "
        "você quer melhorar (headline, Sobre, experiência, competências) e cole o texto atual, "
        "ou envie o PDF exportado do seu LinkedIn."
    ),
}


async def analysis_turn_events(
    *,
    session,
    chat_session: ChatSession,
    user_message: str,
    model: str | None,
    locale: str | None,
    backend_label: str,
    linkedin_pdf_block: str = "",
) -> AsyncIterator[tuple[str, dict]]:
    """One Analysis Turn. ``linkedin_pdf_block`` (default empty) carries the text extracted from
    an uploaded LinkedIn PDF export in the full-profile mode -- ticket b4 wires it; the
    conversational mode leaves it empty."""
    resolved_locale = resolve_locale(locale, user_message, chat_session.locale or DEFAULT_LOCALE)

    system = load_linkedin_analysis_system_prompt(PROMPTS_DIR)
    user_msg = build_analysis_user_msg(
        message=user_message, locale=resolved_locale, linkedin_pdf_block=linkedin_pdf_block
    )

    yield "stage", {"step": "analyzing_profile", "progress": 40, "message": "Analyzing your profile"}

    llm_task = asyncio.create_task(llm_client.chat_json(system, user_msg, model=model))
    async for is_timeout, data in run_with_heartbeat(
        llm_task,
        heartbeat_seconds=streaming.HEARTBEAT_SECONDS,
        timeout_seconds=LLM_TIMEOUT_SECONDS,
        tick=lambda elapsed: {
            "step": "analyzing_profile",
            "progress": 60,
            "message": f"Analyzing your profile... ({elapsed}s)",
        },
        on_timeout=lambda elapsed: {
            "message": f"Timed out waiting for LLM response after {LLM_TIMEOUT_SECONDS}s."
        },
    ):
        if is_timeout:
            raise TimeoutError(data["message"])
        yield "stage", data
    raw = llm_task.result()

    parsed = parse_analysis_json(raw)

    if isinstance(parsed, ParsedAnalysisResult):
        payload = {
            "items": [item.model_dump() for item in parsed.items],
            "summary": parsed.summary,
        }
        assistant_msg = chat_repo.append_message(
            session,
            session_id=chat_session.id,
            role="assistant",
            content=parsed.summary,
            intent="analysis",
            meta=json.dumps({"analysis": payload, "model": model, "provider": backend_label}),
        )
        chat_repo.touch_session(session, chat_session.id)
        session.commit()
        yield "analysis", payload
        yield "message", {"content": parsed.summary}
        yield "done", {"progress": 100, "messageId": assistant_msg.id, "resumeVersionId": None}
        return

    # A Clarifying Question, or the canned fallback for unusable output -- both are just a
    # message bubble (no card), same terminal shape.
    if isinstance(parsed, ParsedAnalysisQuestion):
        reply = parsed.reply
    else:
        reply = _ANALYSIS_FALLBACK_TEXT.get(resolved_locale, _ANALYSIS_FALLBACK_TEXT["en"])
    assistant_msg = chat_repo.append_message(
        session,
        session_id=chat_session.id,
        role="assistant",
        content=reply,
        intent="analysis",
        meta=json.dumps({"model": model, "provider": backend_label}),
    )
    chat_repo.touch_session(session, chat_session.id)
    session.commit()
    yield "message", {"content": reply}
    yield "done", {"progress": 100, "messageId": assistant_msg.id, "resumeVersionId": None}
