import json

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from app.db.tables import ChatSession
from app.domain.schemas import ChatMessageRequest, CreateChatSessionRequest
from app.repositories import chat_repo, resume_repo
from app.routers.deps import get_session, resolve_requested_model
from app.services.chat_service import handle_chat_turn
from app.services.errors import http_error
from app.services.generation_service import ExtractionError
from app.services.llm_client import llm_backend_label
from app.services.profile_service import ProfileValidationError
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
            }
            for m in messages
        ],
        "activeResume": active_resume,
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
