import json

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from app.config import max_upload_bytes
from app.db.tables import ChatSession, ImprovementProposal
from app.domain.schemas import ChatMessageRequest, CreateChatSessionRequest, RenameChatSessionRequest
from app.repositories import chat_repo, proposal_repo, resume_repo, source_document_repo
from app.routers.deps import get_session, resolve_requested_model
from app.services.analysis_service import analysis_turn_events
from app.services.chat_service import handle_chat_turn
from app.services.errors import http_error
from app.services.generation_service import ExtractionError
from app.services.llm_client import llm_backend_label
from app.services.profile_pdf import extract_pdf_text_from_bytes, truncate_for_prompt
from app.services.profile_resolution import ProfileValidationError
from app.services.secret_redaction import redact_secrets
from app.services.streaming import sse

router = APIRouter()

# v5 ticket b4: a scanned/image-only LinkedIn PDF export has no text layer -- surface an
# actionable 422 instead of handing the analysis motor an empty prompt.
_ANALYSIS_PDF_NO_TEXT_MESSAGE = (
    "Este PDF não tem texto extraível (provavelmente um scan/imagem). Reexporte o perfil do "
    "LinkedIn como PDF de texto (no perfil: 'Mais' → 'Salvar como PDF'), ou descreva a seção "
    "que quer melhorar diretamente no chat."
)


def _session_dict(row: ChatSession) -> dict:
    """Compact shape for GET /api/chat/sessions (the list endpoint) -- matches
    docs/v1-chat-experience.md exactly: {id, title, updatedAt, activeResumeVersionId}."""
    return {
        "id": row.id,
        "title": row.title,
        "updatedAt": row.updated_at.isoformat(),
        "activeResumeVersionId": row.active_resume_version_id,
        "kind": row.kind,  # v5 ticket b1
    }


def _session_detail_dict(row: ChatSession) -> dict:
    """Fuller shape for GET /api/chat/sessions/{id} -- adds locale, jobDescription and
    createdAt, which the frontend's composer needs (e.g. to default the session's input
    language) and which the list endpoint deliberately omits per the frozen contract."""
    return {
        **_session_dict(row),
        "locale": row.locale,
        "jobDescription": row.job_description,
        "createdAt": row.created_at.isoformat(),
    }


@router.post("/api/chat/sessions", status_code=201)
async def create_chat_session(body: CreateChatSessionRequest, session: Session = Depends(get_session)):
    row = chat_repo.create_session(session, title=body.title, kind=body.kind)
    session.commit()
    session.refresh(row)
    return {"id": row.id, "title": row.title, "kind": row.kind, "createdAt": row.created_at.isoformat()}


@router.get("/api/chat/sessions")
async def list_chat_sessions(kind: str = "resume", session: Session = Depends(get_session)):
    # v5 ticket b1: `?kind=` filters the list; defaults to 'resume' so the existing UI is
    # unchanged and the Profile Analysis area (kind='profile_analysis') has its own list.
    rows = chat_repo.list_sessions(session, kind=kind)
    return {"sessions": [_session_dict(r) for r in rows]}


def _source_document_link_dict(session: Session, meta_raw: str | None) -> dict | None:
    """v2 ticket 10 ("Durabilidade do ProfileUpdatedCard"): when a chat_message's ``meta``
    references a Source Document (``{"sourceDocumentId": int}`` -- written by
    routers/documents.py's upload endpoint when the upload came from this session), joins
    source_documents LIVE, at read time, for its CURRENT status/diffSummary/opsCount. This is
    the single source of truth: apply/reject only ever mutate the source_documents row, never
    this message's meta, so a reload always reflects whatever the document's real state is --
    never a stale copy. Returns None for a message with no such reference (a plain chat
    reply), or if the referenced document no longer exists (soft ref -- see db/tables.py's
    module docstring).
    """
    if not meta_raw:
        return None
    try:
        meta = json.loads(meta_raw)
    except json.JSONDecodeError:
        return None
    document_id = meta.get("sourceDocumentId")
    if document_id is None:
        return None
    row = source_document_repo.get(session, document_id)
    if row is None:
        return None
    diff_summary = json.loads(row.diff_summary) if row.diff_summary else []
    proposed_patch = json.loads(row.proposed_patch) if row.proposed_patch else []
    return {
        "documentId": row.id,
        "filename": row.filename,
        "status": row.status,
        "diffSummary": diff_summary,
        "opsCount": len(proposed_patch),
        "error": row.error,
    }


def _proposal_dict(row: ImprovementProposal) -> dict:
    """v4 ticket B6: the wire shape shared by ChatMessageDto.proposal and
    ChatSessionDetailResponse.pendingProposal (dto.ts's ``ChatMessageProposalDto`` --
    {proposalId, status, revision, items}), built from a live ``ImprovementProposal`` row.
    Items go through `proposal_repo.get_items` (pydantic-validated) then `model_dump()`,
    same treatment as PatchOp over SourceDocument.proposed_patch."""
    return {
        "proposalId": row.id,
        "status": row.status,
        "revision": row.revision,
        "items": [item.model_dump() for item in proposal_repo.get_items(row)],
    }


def _proposal_link_dict(session: Session, meta_raw: str | None) -> dict | None:
    """v4 ticket B6: when a chat_message's ``meta`` references an Improvement Proposal
    (``{"proposalId": int}`` -- written by chat_service on the Analysis/adjust/new-JD
    turns), joins improvement_proposals LIVE, at read time, for its CURRENT
    status/revision/items -- never a stale copy (mirrors `_source_document_link_dict`
    above). Uses `proposal_repo.get` (a plain SELECT), not `Session.get()`, because a
    proposal can be cascade-deleted at the DB level (session delete) out from under an
    already-identity-mapped instance -- see that function's docstring. Returns None for a
    message with no such reference, or if the referenced proposal no longer exists."""
    if not meta_raw:
        return None
    try:
        meta = json.loads(meta_raw)
    except json.JSONDecodeError:
        return None
    proposal_id = meta.get("proposalId")
    if proposal_id is None:
        return None
    row = proposal_repo.get(session, proposal_id)
    if row is None:
        return None
    return _proposal_dict(row)


@router.get("/api/chat/sessions/{session_id}")
async def get_chat_session(session_id: int, session: Session = Depends(get_session)):
    chat_session, messages = chat_repo.get_session_with_messages(session, session_id)
    if chat_session is None:
        raise http_error(404, f"Chat session {session_id} not found")

    active_resume = None
    if chat_session.active_resume_version_id is not None:
        resume_row = resume_repo.get(session, chat_session.active_resume_version_id)
        if resume_row is not None:
            active_resume = json.loads(resume_row.data)

    pending_proposal = proposal_repo.get_pending(session, session_id)

    return {
        "session": _session_detail_dict(chat_session),
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "intent": m.intent,
                "resumeVersionId": m.resume_version_id,
                "createdAt": m.created_at.isoformat(),
                "sourceDocument": _source_document_link_dict(session, m.meta),
                "proposal": _proposal_link_dict(session, m.meta),
            }
            for m in messages
        ],
        "activeResume": active_resume,
        "pendingProposal": _proposal_dict(pending_proposal) if pending_proposal is not None else None,
    }


@router.patch("/api/chat/sessions/{session_id}")
async def rename_chat_session(
    session_id: int, body: RenameChatSessionRequest, session: Session = Depends(get_session)
):
    """v4.1-03 (frozen contract): {"title": "<1..120 trimmed, non-empty>"} -> 200 {id, title,
    updatedAt}. ``RenameChatSessionRequest`` already trimmed and length-validated the title
    (a blank/whitespace-only/over-120 title is a 422 before this handler ever runs)."""
    chat_session = session.get(ChatSession, session_id)
    if chat_session is None:
        raise http_error(404, f"Chat session {session_id} not found")
    chat_session.title = body.title
    session.add(chat_session)
    chat_repo.touch_session(session, session_id)
    session.commit()
    session.refresh(chat_session)
    return {
        "id": chat_session.id,
        "title": chat_session.title,
        "updatedAt": chat_session.updated_at.isoformat(),
    }


@router.delete("/api/chat/sessions/{session_id}", status_code=204)
async def delete_chat_session(session_id: int, session: Session = Depends(get_session)):
    deleted = chat_repo.delete_session(session, session_id)
    if not deleted:
        raise http_error(404, f"Chat session {session_id} not found")
    session.commit()
    return Response(status_code=204)


@router.post("/api/chat/sessions/{session_id}/messages/stream")
async def post_chat_message_stream(
    session_id: int, body: ChatMessageRequest, session: Session = Depends(get_session)
):
    chat_session = session.get(ChatSession, session_id)
    if chat_session is None:
        raise http_error(404, f"Chat session {session_id} not found")

    model = resolve_requested_model(body.model)

    async def event_stream():
        try:
            async for event, data in handle_chat_turn(
                session=session,
                chat_session=chat_session,
                user_message=body.message,
                model=model,
                locale=body.locale,
                job_description=body.jobDescription,
                backend_label=llm_backend_label(),
                client_resume=body.resume,
                proposal_action=body.proposalAction,
            ):
                if event == "resume":
                    yield sse(
                        "resume",
                        {"resume": data["resume"].model_dump(), "resumeVersionId": data["resumeVersionId"]},
                    )
                else:
                    yield sse(event, data)
        except FileNotFoundError as e:
            yield sse("error", {"message": str(e)})
        except ProfileValidationError as e:
            yield sse("error", {"message": str(e)})
        except ExtractionError as e:
            yield sse(
                "error",
                {"message": f"LLM error ({llm_backend_label()}) extracting Profile.pdf: {e.original}"},
            )
        except TimeoutError as e:
            yield sse("error", {"message": str(e)})
        except json.JSONDecodeError as e:
            yield sse("error", {"message": f"LLM returned invalid JSON: {e}"})
        except Exception as e:
            yield sse("error", {"message": f"LLM error ({llm_backend_label()}): {e}"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/api/chat/sessions/{session_id}/analysis/pdf/stream")
async def post_analysis_pdf_stream(
    session_id: int,
    file: UploadFile = File(...),
    model: str | None = Form(None),
    locale: str | None = Form(None),
    session: Session = Depends(get_session),
):
    """v5 ticket b4: upload a LinkedIn-exported PDF into a Profile Analysis session and stream a
    full-profile Analysis Turn. Reuses ONLY the PDF text extraction (never the Ingestion/Merge
    pipeline): no Source Document is stored and no Profile Version is written -- the PDF is the
    user's LinkedIn, analyzed, not profile truth to ingest."""
    chat_session = session.get(ChatSession, session_id)
    if chat_session is None:
        raise http_error(404, f"Chat session {session_id} not found")
    if chat_session.kind != "profile_analysis":
        raise http_error(400, "PDF analysis is only available in a Profile Analysis session.")

    content = await file.read()
    if len(content) > max_upload_bytes():
        raise http_error(413, "This PDF is too large.")
    try:
        text = extract_pdf_text_from_bytes(content)
    except Exception as e:
        raise http_error(422, f"Could not read this PDF: {e}. Try re-exporting it as a text-based PDF.")
    if not text.strip():
        raise http_error(422, _ANALYSIS_PDF_NO_TEXT_MESSAGE)
    pdf_block = truncate_for_prompt(text)

    resolved_model = resolve_requested_model(model)
    display = f"Analisar meu perfil do LinkedIn (PDF: {file.filename or 'linkedin.pdf'})"

    # Persist the user turn (mirrors handle_chat_turn's head) before streaming the assistant turn.
    chat_repo.append_message(session, session_id=chat_session.id, role="user", content=display)
    if locale is not None:
        chat_session.locale = locale
        session.add(chat_session)
    session.commit()

    async def event_stream():
        try:
            async for event, data in analysis_turn_events(
                session=session,
                chat_session=chat_session,
                user_message=display,
                model=resolved_model,
                locale=locale,
                backend_label=llm_backend_label(),
                linkedin_pdf_block=pdf_block,
            ):
                yield sse(event, data)
        except TimeoutError as e:
            yield sse("error", {"message": str(e)})
        except Exception as e:
            chat_repo.append_message(
                session,
                session_id=chat_session.id,
                role="assistant",
                content="",
                intent="analysis",
                meta=json.dumps(
                    {"model": resolved_model, "provider": llm_backend_label(), "error": redact_secrets(str(e))}
                ),
            )
            chat_repo.touch_session(session, chat_session.id)
            session.commit()
            yield sse("error", {"message": f"LLM error ({llm_backend_label()}): {e}"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
