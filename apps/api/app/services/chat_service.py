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

As of v4 ticket B3 (docs/v4-improvement-proposal.md -- "Proposta Conversacional de Melhorias"),
pasting a job description no longer generates a resume directly: ``handle_chat_turn`` also fetches
the session's Pending Proposal (``proposal_repo.get_pending``) and threads it into
``classify_intent`` as ``has_pending_proposal``. A session with neither an active resume nor a
pending proposal whose message looks like a job description still classifies as "generate", but
that intent now runs the **Analysis** (``_handle_propose_turn``) instead of
``_handle_generate_turn``: it compares the Living Profile against the job and proposes a detailed,
itemized Improvement Proposal (new "proposal" event, ``{proposalId, status, revision, items}``) for
the user to converse about, rather than generating anything yet.

As of v4 ticket B4, the fifth intent, "proposal_turn" (any turn in a session with a Pending
Proposal, MINUS the ``_looks_like_profile_update`` guard's own proposal-scope exemption --
``app.domain.chat_intent``), is the real conversational classification
(``_handle_proposal_turn``): a message that itself reads like a brand-new job description
short-circuits straight into another Analysis (superseding the pending one); otherwise ONE
combined LLM call (``proposal_turn.md``) decides approve/adjust/question/new_jd against the
current proposal + recent history. `adjust` replaces the proposal's items wholesale
(``proposal_repo.revise``) and bumps its revision; `question` (real or a canned fallback for
unparseable LLM output -- NEVER an error frame, spec SS6) leaves the proposal untouched; `new_jd`
takes the same short-circuit Analysis route; `approve` hands off to ticket B5's approve branch.

As of v4 ticket B5, ``_handle_generate_turn`` -- unchanged and un-deleted since B3 specifically
for this -- is what the approve branch (``_handle_approve_branch``) calls once a proposal is
actually agreed to, reached two ways with zero LLM classification spent: the "Aprovar e gerar"
button (``ChatMessageRequest.proposalAction == "approve"``, checked BEFORE ordinary intent
routing, ignored when there is no Pending Proposal) and a natural-language approval the Proposal
Turn's own classification already recognized. Either way: an assistant confirmation message,
then the SAME generation pipeline every other "generate"/"refine" turn uses, with the proposal's
items injected into the prompt as an APPROVED IMPROVEMENT PLAN
(``generation_service.generate_resume_events``'s ``agreed_improvements`` -- v4 ticket B2's
``build_generation_user_msg`` parameter, finally threaded end to end). The proposal is marked
`approved` (``proposal_repo.mark_approved``) in the SAME commit as the new ``ResumeVersion`` (see
``_finalize_resume_turn``'s ``on_before_commit`` hook) -- so a generation failure, raised before
that point is ever reached, leaves the proposal `proposed` and reapprovable, per spec SS6.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable

from sqlmodel import Session

from app.config import LLM_TIMEOUT_SECONDS, PROMPTS_DIR
from app.db.tables import ChatMessage, ChatSession, ImprovementProposal, ResumeVersion, SourceDocument
from app.domain.chat_intent import classify_intent
from app.domain.locale import DEFAULT_LOCALE, SUPPORTED_LOCALES, resolve_locale
from app.domain.profile_patch import PatchOp, PatchValidationFailed, apply_patch
from app.domain.prompts_builder import build_proposal_analysis_user_msg, build_proposal_turn_user_msg
from app.domain.schemas import ProfileMaster, ProposalItem, ResumeDocument
from app.prompt_loader import (
    load_profile_update_system_prompt,
    load_proposal_turn_system_prompt,
    load_propose_improvements_system_prompt,
)
from app.repositories import chat_repo, profile_repo, proposal_repo, resume_repo
from app.services import llm_client, streaming
from app.services.analysis_service import analysis_turn_events
from app.services.html_sanitize import sanitize_resume_for_display
from app.services.generation_service import generate_resume_events
from app.services.ingestion.merge_service import parse_patch_ops_from_llm_response, resolve_profile_for_merge
from app.services.llm.proposal_json_parser import parse_proposal_json, parse_proposal_turn_json
from app.services.profile_resolution import resolve_active_profile
from app.services.refine_service import refine_resume_events
from app.services.secret_redaction import redact_secrets
from app.services.streaming import run_with_heartbeat

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
    # v6 (Second Posting): the gray zone between "this is a new job" and "this is an edit to the
    # resume I already have". Asking costs one turn; guessing wrong costs either a discarded
    # refine session or -- the bug this exists for -- a second posting silently treated as an
    # edit of the first one's resume.
    "clarify_scope": {
        "en": (
            "Before I touch anything: is that a **new job posting** you want a fresh resume "
            "for, or a **change to the resume** already open here? Say \"new job\" and I'll "
            "analyze it from scratch, or tell me the change and I'll apply it to this one."
        ),
        "pt-BR": (
            "Antes de eu mexer em qualquer coisa: isso é uma **vaga nova** para eu gerar um "
            "currículo do zero, ou é uma **mudança no currículo** que já está aberto aqui? "
            "Diga \"vaga nova\" e eu analiso desde o começo, ou me diga a mudança e eu "
            "aplico neste aqui."
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

# v4 ticket B4 (spec SS2/SS6): the Proposal Turn classification LLM call NEVER produces an error
# frame over garbage output -- unparseable JSON, an unknown `action`, or an `adjust` with no
# usable items (`parse_proposal_turn_json` -> None) all fall back to this canned, locale-aware
# `question` reply, proposal left completely untouched. It also fills in for a *valid*
# classification whose own `reply` came back blank (B2 decision: the parser itself never
# fabricates fallback prose for the Proposal Turn, unlike the Analysis's `_fallback_message` --
# so the caller here is the one place responsible for it).
_PROPOSAL_TURN_FALLBACK_TEXT = {
    "en": (
        "I didn't quite catch that -- want me to apply the proposal, adjust something in it, "
        "or do you have another question?"
    ),
    "pt-BR": (
        "Não entendi -- quer que eu aplique a proposta, ajuste algo nela, ou tem outra dúvida?"
    ),
}

# v4 ticket B5 (spec SS2 approve branch): the confirmation bubble the approve branch sends
# BEFORE generation starts -- used verbatim for the "Aprovar e gerar" button shortcut (no LLM
# involved) and as the fallback when a natural-language approval's own LLM `reply` came back
# blank (same blank-reply policy as the fallback text above).
_PROPOSAL_APPROVE_CONFIRMATION_TEXT = {
    "en": "Generating your resume from the approved plan now...",
    "pt-BR": "Gerando seu currículo com o plano aprovado agora...",
}

# Mirrors apps/web/src/features/resume/diffResumeSections.ts's RESUME_SECTION_KEYS -- same
# order, same shallow section-level comparison -- so the refine confirmation names exactly
# what that card would show, instead of an LLM-authored guess.
_RESUME_SECTION_KEYS = (
    "fullName",
    "headline",
    "location",
    "email",
    "phone",
    "links",
    "summary",
    "experience",
    "projects",
    "skills",
    "education",
)

_RESUME_SECTION_LABELS = {
    "fullName": {"en": "name", "pt-BR": "nome"},
    "headline": {"en": "headline", "pt-BR": "título"},
    "location": {"en": "location", "pt-BR": "localização"},
    "email": {"en": "email", "pt-BR": "email"},
    "phone": {"en": "phone", "pt-BR": "telefone"},
    "links": {"en": "links", "pt-BR": "links"},
    "summary": {"en": "summary", "pt-BR": "resumo"},
    "experience": {"en": "experience", "pt-BR": "experiências"},
    "projects": {"en": "projects", "pt-BR": "projetos"},
    "skills": {"en": "skills", "pt-BR": "habilidades"},
    "education": {"en": "education", "pt-BR": "formação"},
}

# v4 ticket (refine "sim-sim-homem" fix): refine's own "nothing changed" reply -- same spirit
# as `_PROFILE_UPDATE_NOTHING_TEXT` but for a resume turn, and distinct wording since the
# trigger is a no-op diff, not unparseable LLM output.
_REFINE_NOTHING_CHANGED_TEXT = {
    "en": (
        "I didn't find a real change to apply from that -- can you tell me more specifically "
        "what to change?"
    ),
    "pt-BR": (
        "Não percebi nenhuma mudança real a partir desse pedido -- pode detalhar melhor o que "
        "você quer alterar?"
    ),
}
_REFINE_UPDATED_TEXT = {
    "en": "Updated your resume: {sections}.",
    "pt-BR": "Atualizei seu currículo: {sections}.",
}


def _diff_resume_sections(prev: ResumeDocument, next_: ResumeDocument) -> list[str]:
    """Deterministic, non-LLM-authored section-level diff -- ports
    diffResumeSections.ts's shallow JSON-equality comparison so refine's confirmation names
    what ACTUALLY changed instead of trusting the LLM's own claim."""
    prev_dump = prev.model_dump()
    next_dump = next_.model_dump()
    return [
        key
        for key in _RESUME_SECTION_KEYS
        if json.dumps(prev_dump[key], sort_keys=True) != json.dumps(next_dump[key], sort_keys=True)
    ]


def _refine_updated_text(changed: list[str], locale: str) -> str:
    resolved = locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE
    labels = [_RESUME_SECTION_LABELS[key][resolved] for key in changed]
    return _REFINE_UPDATED_TEXT[resolved].format(sections=", ".join(labels))


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


# --- Source Document upload -> chat session linking (v2 ticket 10, moved here in ticket 04's
# backend prefactor: this is chat-domain logic -- persisting a durable assistant chat_message --
# that had been misfiled in routers/profile.py alongside the upload HTTP handler. The public
# seam, ``link_upload_to_session``, is called by routers/documents.py's upload endpoint.


def _document_link_message_text(row: SourceDocument) -> str:
    """Mirrors the frontend's client-only synthetic copy (ChatPanel.tsx's
    profileUpdateMessageText) so the durable, backend-persisted message (v2 ticket 10) reads
    the same as the live one it exists to survive a session reload for."""
    if row.status == "failed":
        return f"Couldn't process {row.filename}."
    diff_summary = json.loads(row.diff_summary) if row.diff_summary else []
    if not diff_summary:
        return f"Checked {row.filename} — nothing new to merge."
    return f"Reviewed {row.filename} — here's what I found."


def link_upload_to_session(session: Session, chat_session_id: int | None, row: SourceDocument) -> None:
    """v2 ticket 10 ("Durabilidade do ProfileUpdatedCard"): when the upload came from an
    active chat session, persists a durable assistant chat_message referencing this Source
    Document, so its ProfileUpdatedCard survives a session reload -- today that card is a
    client-only synthetic message a reload loses entirely. ``meta`` stores ONLY
    ``sourceDocumentId`` -- never a copy of ``status`` -- so GET /api/chat/sessions/{id} can
    join source_documents LIVE at read time for whatever the CURRENT status/diffSummary/
    opsCount is (routers/chat.py's ``_source_document_link_dict``); apply/reject never need to
    touch this message, so there is no second, driftable source of truth. An unknown or
    missing ``chat_session_id`` is silently ignored: the upload itself already succeeded and
    must not fail over an unrelated (possibly stale) chat session id.
    """
    if chat_session_id is None:
        return
    chat_session = session.get(ChatSession, chat_session_id)
    if chat_session is None:
        return
    chat_repo.append_message(
        session,
        session_id=chat_session.id,
        role="assistant",
        content=_document_link_message_text(row),
        intent="profile_update",
        meta=json.dumps({"sourceDocumentId": row.id}),
    )
    chat_repo.touch_session(session, chat_session.id)
    session.commit()


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
    on_before_commit: Callable[[ResumeVersion], None] | None = None,
    content_override: str | None = None,
):
    """Shared tail of the generate/refine turns (v2 ticket 05 AC: "insert_version deduplicado
    entre generate/refine"): inserts the new ``ResumeVersion``, points the session's active
    resume at it, appends the assistant confirmation message, and persists. Returns
    ``(resume_row, content, assistant_msg)`` for the caller to build its own SSE frames from --
    kept a plain function (not a generator) since it never yields, only the two callers do.

    ``content_override`` (refine "sim-sim-homem" fix): lets ``_handle_refine_turn`` pass a
    confirmation that NAMES the sections that actually changed (``_refine_updated_text``)
    instead of the static per-intent copy below -- ``_handle_generate_turn``/
    ``_handle_approve_branch`` never pass it, so their confirmation is unchanged.

    ``extra_meta`` (v2 ticket 11) lets a caller record turn-specific provenance on the
    assistant message's ``meta`` JSON -- e.g. ``{"clientResumeOverride": True}`` for a refine
    that started from the client's in-memory doc rather than the DB's active version -- without
    ``resume_versions`` itself needing a new column for it.

    ``on_before_commit`` (v4 ticket B5): lets the approve branch fold
    ``proposal_repo.mark_approved(resume_version_id=...)`` into this SAME commit -- spec SS2
    requires the ResumeVersion insert, the assistant message, and the proposal's approval to
    land atomically, but ``mark_approved`` needs the just-inserted ``resume_row.id`` that only
    exists once THIS function is already mid-flight. Called with the freshly-flushed
    ``resume_row`` right before ``session.commit()``; every other caller leaves it ``None``
    (no behavior change).
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
    content = content_override if content_override is not None else _reply_text_for_locale(intent, resume_doc.locale)
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
    if on_before_commit is not None:
        on_before_commit(resume_row)
    session.commit()
    return resume_row, content, assistant_msg


async def _handle_question_turn(
    *,
    session: Session,
    chat_session: ChatSession,
    locale: str | None,
    user_message: str,
    intent: str = "question",
) -> AsyncIterator[tuple[str, dict]]:
    """A canned, locale-aware reply that touches nothing: no LLM call, no resume, no profile.

    ``intent`` (v6, default ``"question"`` so every pre-v6 call site is unchanged) also serves
    ``clarify_scope`` -- the two turns are mechanically identical (one deterministic message,
    nothing written) and differ only in the copy and the intent stamped on the message row.
    """
    # No resume is involved in this turn, so the session/request locale (falling back to
    # auto-detection from the user's own message) is the only signal available.
    content = _reply_text_for_locale(intent, resolve_locale(locale, user_message, None))
    assistant_msg = chat_repo.append_message(
        session, session_id=chat_session.id, role="assistant", content=content, intent=intent
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
    agreed_improvements: list[ProposalItem] | None = None,
    on_before_commit: Callable[[ResumeVersion], None] | None = None,
    extra_done_data: dict | None = None,
) -> AsyncIterator[tuple[str, dict]]:
    """The v1-v3 "paste a JD, get a resume" pipeline -- unused by the "generate" intent as of
    v4 ticket B3 (that now runs the Analysis instead, see ``_handle_propose_turn``), but kept
    alive for v4 ticket B5's approve branch (``_handle_approve_branch``), which calls this once
    a Pending Proposal is actually agreed to: ``agreed_improvements`` threads the proposal's
    items into the generation prompt (spec SS4.3), ``on_before_commit`` lets that same caller
    fold ``proposal_repo.mark_approved`` into this function's own commit (see
    ``_finalize_resume_turn``'s docstring), and ``extra_done_data`` lets it add ``proposalId``
    to the terminal ``done`` frame -- all three default to ``None``/unused, so this function's
    behavior for its own hypothetical direct callers is unchanged.
    """
    jd_text = job_description or user_message
    resolved_profile = resolve_active_profile(session)
    resume_doc: ResumeDocument | None = None
    async for event, data in generate_resume_events(
        resolved_profile=resolved_profile,
        job_description=jd_text,
        model=model,
        locale=locale,
        backend_label=backend_label,
        agreed_improvements=agreed_improvements,
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
        on_before_commit=on_before_commit,
    )
    yield "resume", {"resume": resume_doc, "resumeVersionId": resume_row.id}
    yield "message", {"content": content}
    done_data = {"progress": 100, "messageId": assistant_msg.id, "resumeVersionId": resume_row.id}
    if extra_done_data:
        done_data.update(extra_done_data)
    yield "done", done_data


async def _handle_propose_turn(
    *,
    session: Session,
    chat_session: ChatSession,
    user_message: str,
    job_description: str | None,
    model: str | None,
    locale: str | None,
    backend_label: str,
) -> AsyncIterator[tuple[str, dict]]:
    """v4 ticket B3 ("Analysis"): a pasted job description in a session with neither an active
    resume nor a Pending Proposal no longer generates a resume directly (that was v1-v3's
    ``_handle_generate_turn``, still used unchanged by the approve branch B5 wires up inside the
    Proposal Turn) -- it runs the Analysis instead, comparing the Living Profile against the job
    and proposing a detailed, itemized set of changes for the user to converse about before
    anything is generated (docs/v4-improvement-proposal.md SS0/SS3.6).

    Unlike ``_handle_generate_turn``, this does NOT write ``chat_session.job_description`` --
    the JD that produced THIS proposal lives on the ``ImprovementProposal`` row itself (the
    source of truth the eventual approve turn reads from); the session-level field is only
    written once a proposal is actually approved (B5), mirroring how ``active_resume_version_id``
    only ever points at a resume that was actually generated, never a merely-proposed one.
    """
    jd_text = job_description or user_message
    resolved_profile = resolve_active_profile(session)
    resolved_locale = resolve_locale(locale, jd_text, resolved_profile.profile.locale)

    system = load_propose_improvements_system_prompt(PROMPTS_DIR)
    user_msg = build_proposal_analysis_user_msg(
        profile=resolved_profile.profile, job_description=jd_text, locale=resolved_locale
    )

    llm_task = asyncio.create_task(llm_client.chat_json(system, user_msg, model=model))
    async for is_timeout, data in run_with_heartbeat(
        llm_task,
        heartbeat_seconds=streaming.HEARTBEAT_SECONDS,
        timeout_seconds=LLM_TIMEOUT_SECONDS,
        tick=lambda elapsed: {
            "step": "analyzing_job",
            "progress": 50,
            "message": f"Analyzing job description... ({elapsed}s)",
        },
        on_timeout=lambda elapsed: {
            "message": f"Timed out waiting for LLM response after {LLM_TIMEOUT_SECONDS}s."
        },
    ):
        if is_timeout:
            raise TimeoutError(data["message"])
        yield "stage", data
    raw = llm_task.result()

    parsed = parse_proposal_json(raw)
    if parsed is None:
        # Analysis-specific failure (spec SS6): garbage/unusable LLM output is an error frame,
        # same as any other main-generation LLM failure -- unlike the Proposal Turn's OWN
        # parser (B4), which never treats garbage as an error. Zero rows are committed: nothing
        # below this point has run yet.
        raise ValueError(
            "LLM returned an unusable Improvement Proposal (invalid JSON or no valid items)."
        )

    proposal_row = proposal_repo.create_pending(
        session,
        session_id=chat_session.id,
        job_description=jd_text,
        items=parsed.items,
        model_used=model,
    )
    assistant_msg = chat_repo.append_message(
        session,
        session_id=chat_session.id,
        role="assistant",
        content=parsed.message,
        intent="propose",
        meta=json.dumps({"proposalId": proposal_row.id}),
    )
    if parsed.title:
        # v4.1-02: the Analysis's own JSON names the job -- use it as the session's title,
        # in the SAME commit as the rest of this turn (also covers new_jd: a fresh job
        # description renames the session, which is the point). A session that was already
        # named keeps getting renamed here -- the LLM's title is always the freshest signal.
        chat_session.title = parsed.title
        session.add(chat_session)
    chat_repo.touch_session(session, chat_session.id)
    session.commit()

    yield "proposal", {
        "proposalId": proposal_row.id,
        "status": proposal_row.status,
        "revision": proposal_row.revision,
        "items": [item.model_dump() for item in parsed.items],
    }
    yield "message", {"content": parsed.message}
    yield "done", {
        "progress": 100,
        "messageId": assistant_msg.id,
        "proposalId": proposal_row.id,
        "resumeVersionId": None,
    }


async def _handle_approve_branch(
    *,
    session: Session,
    chat_session: ChatSession,
    proposal: ImprovementProposal,
    confirmation_text: str | None,
    model: str | None,
    locale: str | None,
    backend_label: str,
) -> AsyncIterator[tuple[str, dict]]:
    """v4 ticket B5 (spec SS2/SS3.6 approve branch): reached two ways -- the "Aprovar e gerar"
    button (``proposalAction == "approve"``, ``confirmation_text=None`` so the canned copy
    below is used) and a natural-language approval the Proposal Turn's own classification
    recognized (``confirmation_text=parsed.reply`` -- still falls back to the same canned copy
    if that reply came back blank, same policy as the fallback/question text). Either way, ZERO
    further LLM classification is spent here; only the generation pipeline itself calls the LLM.

    Reuses ``_handle_generate_turn`` (the v1-v3 pipeline, un-deleted since B3 precisely for
    this) rather than duplicating it: ``agreed_improvements`` injects the proposal's items into
    the generation prompt (spec SS4.3), and ``on_before_commit`` marks the proposal `approved`
    in the SAME commit as the new ``ResumeVersion`` -- so a generation failure (raised before
    that point is ever reached) leaves the proposal `proposed` and reapprovable, exactly as spec
    SS6 requires, with no extra try/except needed here: ``mark_approved`` simply never runs.
    """
    resolved_locale = _resolve_concrete_locale(locale, proposal.job_description, None)
    confirmation = confirmation_text or _PROPOSAL_APPROVE_CONFIRMATION_TEXT[resolved_locale]
    chat_repo.append_message(
        session,
        session_id=chat_session.id,
        role="assistant",
        content=confirmation,
        intent="proposal_approve",
        meta=json.dumps({"proposalId": proposal.id}),
    )
    chat_repo.touch_session(session, chat_session.id)
    session.commit()
    yield "message", {"content": confirmation}

    async for event, data in _handle_generate_turn(
        session=session,
        chat_session=chat_session,
        user_message="",
        job_description=proposal.job_description,
        model=model,
        locale=locale,
        backend_label=backend_label,
        agreed_improvements=proposal_repo.get_items(proposal),
        on_before_commit=lambda resume_row: proposal_repo.mark_approved(
            session, proposal, resume_version_id=resume_row.id
        ),
        extra_done_data={"proposalId": proposal.id},
    ):
        yield event, data


async def _handle_proposal_turn(
    *,
    session: Session,
    chat_session: ChatSession,
    user_message: str,
    prior_messages: list,
    proposal: ImprovementProposal,
    model: str | None,
    locale: str | None,
    backend_label: str,
) -> AsyncIterator[tuple[str, dict]]:
    """v4 ticket B4 (spec SS2), revised by QA-05 (P2, QA live): with a Pending Proposal, the
    turn is conversational rather than routed by the v1 3-way heuristic. Two ways in, evaluated
    in order:

    1. One combined classification LLM call (``proposal_turn.md``) decides
       approve/adjust/question/new_jd against the CURRENT proposal + recent history. `new_jd`
       takes the same route as the Analysis (``_handle_propose_turn``), whose OWN
       ``proposal_repo.create_pending`` supersedes THIS proposal atomically; `approve` takes the
       SAME branch the button shortcut does (``_handle_approve_branch``, B5).
    2. Garbage/unparseable classification output (``parse_proposal_turn_json`` -> ``None``) is
       NEVER an error frame here (unlike the Analysis's OWN parser failure, which still is) --
       it falls back to a canned, locale-aware `question` reply, proposal completely untouched
       (spec SS6).

    QA-05: this used to short-circuit straight into a new Analysis, zero classification calls
    spent, whenever the message itself read like a brand-new job description
    (``looks_like_job_description`` -- the SAME deterministic, content-blind heuristic "generate"
    uses for a session with no pending proposal). That heuristic trips on word count alone (30+
    words), so a long, perfectly ordinary natural-language `adjust` message ("add FastAPI to my
    skills, don't remove anything else, and reorder projects...") tripped it exactly like a real
    JD paste -- DESTROYING the pending proposal (supersede) instead of revising it. The
    short-circuit is gone: with a pending proposal, EVERY message (except the button's
    ``proposalAction`` shortcut) goes through classification first, and `new_jd` from the LLM is
    the ONLY way left to supersede. Accepted cost: a real JD pasted while a proposal is pending
    now spends 2 LLM calls (classification + Analysis) instead of 1.
    ``looks_like_job_description`` is untouched for the NO-pending routing (v1's heuristic).

    `adjust` replaces the proposal's items wholesale (``proposal_repo.revise`` -- never a
    delta) and bumps its revision; `question` (real or fallback) never touches the proposal.
    """
    resolved_locale = _resolve_concrete_locale(locale, user_message, None)
    items = proposal_repo.get_items(proposal)
    history_text = _format_history(prior_messages, _HISTORY_MESSAGES_FOR_REFINE)
    system = load_proposal_turn_system_prompt(PROMPTS_DIR)
    user_msg = build_proposal_turn_user_msg(
        items=items,
        revision=proposal.revision,
        history_text=history_text,
        message=user_message,
        locale=resolved_locale,
    )

    llm_task = asyncio.create_task(llm_client.chat_json(system, user_msg, model=model))
    async for is_timeout, data in run_with_heartbeat(
        llm_task,
        heartbeat_seconds=streaming.HEARTBEAT_SECONDS,
        timeout_seconds=LLM_TIMEOUT_SECONDS,
        tick=lambda elapsed: {
            "step": "analyzing_job",
            "progress": 50,
            "message": f"Thinking about your message... ({elapsed}s)",
        },
        on_timeout=lambda elapsed: {
            "message": f"Timed out waiting for LLM response after {LLM_TIMEOUT_SECONDS}s."
        },
    ):
        if is_timeout:
            raise TimeoutError(data["message"])
        yield "stage", data
    raw = llm_task.result()

    parsed = parse_proposal_turn_json(raw)
    if parsed is None:
        content = _PROPOSAL_TURN_FALLBACK_TEXT[resolved_locale]
        assistant_msg = chat_repo.append_message(
            session,
            session_id=chat_session.id,
            role="assistant",
            content=content,
            intent="proposal_question",
            meta=json.dumps({"proposalId": proposal.id}),
        )
        chat_repo.touch_session(session, chat_session.id)
        session.commit()
        yield "message", {"content": content}
        yield "done", {
            "progress": 100,
            "messageId": assistant_msg.id,
            "proposalId": proposal.id,
            "resumeVersionId": None,
        }
        return

    # A valid classification whose own `reply` came back blank falls back to the SAME canned
    # copy as outright garbage (B2 decision: the parser never fabricates fallback prose here,
    # unlike the Analysis's `_fallback_message` -- ticket B4 item 3).
    reply = parsed.reply or _PROPOSAL_TURN_FALLBACK_TEXT[resolved_locale]

    if parsed.action == "approve":
        async for event, data in _handle_approve_branch(
            session=session,
            chat_session=chat_session,
            proposal=proposal,
            confirmation_text=parsed.reply or None,
            model=model,
            locale=locale,
            backend_label=backend_label,
        ):
            yield event, data
        return

    if parsed.action == "new_jd":
        async for event, data in _handle_propose_turn(
            session=session,
            chat_session=chat_session,
            user_message=user_message,
            job_description=user_message,
            model=model,
            locale=locale,
            backend_label=backend_label,
        ):
            yield event, data
        return

    if parsed.action == "adjust":
        assert parsed.items is not None  # guaranteed by parse_proposal_turn_json for `adjust`
        updated = proposal_repo.revise(session, proposal, items=parsed.items)
        assistant_msg = chat_repo.append_message(
            session,
            session_id=chat_session.id,
            role="assistant",
            content=reply,
            intent="proposal_adjust",
            meta=json.dumps({"proposalId": updated.id}),
        )
        chat_repo.touch_session(session, chat_session.id)
        session.commit()
        yield "proposal", {
            "proposalId": updated.id,
            "status": updated.status,
            "revision": updated.revision,
            "items": [item.model_dump() for item in parsed.items],
        }
        yield "message", {"content": reply}
        yield "done", {
            "progress": 100,
            "messageId": assistant_msg.id,
            "proposalId": updated.id,
            "resumeVersionId": None,
        }
        return

    # action == "question"
    assistant_msg = chat_repo.append_message(
        session,
        session_id=chat_session.id,
        role="assistant",
        content=reply,
        intent="proposal_question",
        meta=json.dumps({"proposalId": proposal.id}),
    )
    chat_repo.touch_session(session, chat_session.id)
    session.commit()
    yield "message", {"content": reply}
    yield "done", {
        "progress": 100,
        "messageId": assistant_msg.id,
        "proposalId": proposal.id,
        "resumeVersionId": None,
    }


def _sanitize_client_resume_override(resume: ResumeDocument) -> ResumeDocument:
    """v2 ticket 11 review fix: the client-supplied refine override is untrusted input arriving
    fresh at this seam (unlike the DB's active row, already sanitized by construction), and it
    is embedded straight into the LLM prompt by ``build_refine_user_msg`` -- BEFORE
    ``parse_resume_json``'s own ``sanitize_resume_for_display`` pass on the merged output ever
    runs. Runs the SAME choke point the rest of the app uses, on a dict copy, then re-validates
    -- never mutates ``resume`` itself."""
    dumped = resume.model_dump()
    sanitize_resume_for_display(dumped)
    return ResumeDocument.model_validate(dumped)


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
    # plain 422 raised before this function -- or handle_chat_turn -- ever runs. Unlike the DB
    # row (already sanitized by construction -- every write path runs sanitize_resume_for_display
    # before persisting), this doc is untrusted input arriving fresh at this seam, so it is
    # sanitized HERE, before it ever reaches build_refine_user_msg's prompt -- not left to
    # parse_resume_json's later sanitize_resume_for_display pass on the LLM's merged output,
    # which only cleans what ends up in the final document, not what was sent to the model.
    base_resume = (
        _sanitize_client_resume_override(client_resume_override)
        if client_resume_override is not None
        else ResumeDocument.model_validate_json(active_resume_row.data)
    )
    resolved_profile = resolve_active_profile(session)
    resume_doc: ResumeDocument | None = None
    question_text: str | None = None
    async for event, data in refine_resume_events(
        resume=base_resume,
        message=enriched_message,
        model=model,
        backend_label=backend_label,
        profile=resolved_profile.profile,
    ):
        if event == "done":
            resume_doc = data["resume"]
            question_text = data.get("question")
        else:
            yield event, data

    if question_text:
        # Same shape as _handle_proposal_turn's own `question` branch: no new ResumeVersion,
        # the active resume is left completely untouched.
        assistant_msg = chat_repo.append_message(
            session,
            session_id=chat_session.id,
            role="assistant",
            content=question_text,
            intent="refine_question",
        )
        chat_repo.touch_session(session, chat_session.id)
        session.commit()
        yield "message", {"content": question_text}
        yield "done", {"progress": 100, "messageId": assistant_msg.id, "resumeVersionId": None}
        return

    assert resume_doc is not None
    changed = _diff_resume_sections(base_resume, resume_doc)

    if not changed:
        # "sim-sim-homem" fix: the LLM claims a resume but nothing actually differs -- same
        # policy as _PROFILE_UPDATE_NOTHING_TEXT, no new ResumeVersion, active resume untouched.
        content = _REFINE_NOTHING_CHANGED_TEXT[
            resume_doc.locale if resume_doc.locale in SUPPORTED_LOCALES else DEFAULT_LOCALE
        ]
        assistant_msg = chat_repo.append_message(
            session,
            session_id=chat_session.id,
            role="assistant",
            content=content,
            intent="refine",
        )
        chat_repo.touch_session(session, chat_session.id)
        session.commit()
        yield "message", {"content": content}
        yield "done", {"progress": 100, "messageId": assistant_msg.id, "resumeVersionId": None}
        return

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
        content_override=_refine_updated_text(changed, resume_doc.locale),
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
    proposal_action: str | None = None,
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

    # v5 (ticket b3): a Profile Analysis session bypasses intent classification entirely --
    # every turn is a read-only Analysis Turn. Branched here, before any resume-flow state
    # (active resume, pending proposal) is even loaded, so nothing about the resume pipeline
    # can be reached from this area. Its own try/except mirrors the intent path below: a
    # failure persists an error assistant message (so the turn is visible on reload) and
    # re-raises for the endpoint to frame as an `error` SSE event.
    if chat_session.kind == "profile_analysis":
        try:
            async for event, data in analysis_turn_events(
                session=session,
                chat_session=chat_session,
                user_message=user_message,
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
                intent="analysis",
                meta=json.dumps({"model": model, "provider": backend_label, "error": redact_secrets(str(e))}),
            )
            chat_repo.touch_session(session, chat_session.id)
            session.commit()
            raise
        return

    active_resume_row = None
    if chat_session.active_resume_version_id is not None:
        active_resume_row = resume_repo.get(session, chat_session.active_resume_version_id)
    pending_proposal = proposal_repo.get_pending(session, chat_session.id)

    intent = classify_intent(
        message=user_message,
        has_active_resume=active_resume_row is not None,
        has_pending_proposal=pending_proposal is not None,
    )

    if intent in ("question", "clarify_scope"):
        async for event, data in _handle_question_turn(
            session=session,
            chat_session=chat_session,
            locale=locale,
            user_message=user_message,
            intent=intent,
        ):
            yield event, data
        return

    try:
        # v4 ticket B5 (spec SS2/SS3.1): the "Aprovar e gerar" button shortcut wins over
        # classification entirely -- zero LLM calls spent deciding it -- whenever there is a
        # Pending Proposal to approve, regardless of what `intent` resolved to (the button
        # always sends a fixed confirmation message that would not usually misroute anyway).
        # `proposalAction` on a session with NO Pending Proposal is silently ignored (spec
        # SS3.1) -- falls through to ordinary intent-based routing below.
        if pending_proposal is not None and proposal_action == "approve":
            async for event, data in _handle_approve_branch(
                session=session,
                chat_session=chat_session,
                proposal=pending_proposal,
                confirmation_text=None,
                model=model,
                locale=locale,
                backend_label=backend_label,
            ):
                yield event, data
        elif intent == "generate":
            async for event, data in _handle_propose_turn(
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
        elif intent == "proposal_turn":
            assert pending_proposal is not None  # guaranteed by classify_intent's own contract
            async for event, data in _handle_proposal_turn(
                session=session,
                chat_session=chat_session,
                user_message=user_message,
                prior_messages=prior_messages,
                proposal=pending_proposal,
                model=model,
                locale=locale,
                backend_label=backend_label,
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
