import json

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from app.db.tables import ChatSession, ImprovementProposal
from app.domain.schemas import ChatMessageRequest, CreateChatSessionRequest
from app.repositories import chat_repo, proposal_repo, resume_repo, source_document_repo
from app.routers.deps import get_session, resolve_requested_model
from app.services.chat_service import handle_chat_turn
from app.services.errors import http_error
from app.services.generation_service import ExtractionError
from app.services.llm_client import llm_backend_label
from app.services.profile_resolution import ProfileValidationError
from app.services.streaming import sse

router = APIRouter()


def _session_dict(row: ChatSession) -> dict:
    """Compact shape for GET /api/chat/sessions (the list endpoint) -- matches
    docs/v1-chat-experience.md exactly: {id, title, updatedAt, activeResumeVersionId}."""
    return {
        "id": row.id,
        "title": row.title,
        "updatedAt": row.updated_at.isoformat(),
        "activeResumeVersionId": row.active_resume_version_id,
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
    row = chat_repo.create_session(session, title=body.title)
    session.commit()
    session.refresh(row)
    return {"id": row.id, "title": row.title, "createdAt": row.created_at.isoformat()}


@router.get("/api/chat/sessions")
async def list_chat_sessions(session: Session = Depends(get_session)):
    rows = chat_repo.list_sessions(session)
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
