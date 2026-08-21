"""Repository for chat_sessions and chat_messages (B5; consumed by B6's chat endpoints)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, select

from app.db.tables import ChatMessage, ChatSession


def create_session(
    session: Session,
    *,
    title: str | None = None,
    job_description: str | None = None,
    locale: str | None = None,
    kind: str = "resume",
) -> ChatSession:
    row = ChatSession(title=title, job_description=job_description, locale=locale, kind=kind)
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def list_sessions(session: Session, *, kind: str | None = "resume") -> list[ChatSession]:
    """v5 ticket b1: ``kind`` filters the list so the Profile Analysis area and the resume
    chat never show each other's conversations. Defaults to ``'resume'`` -- the retrocompatible
    behavior, since every pre-v5 session is a resume chat. Pass ``kind=None`` for no filter."""
    stmt = select(ChatSession)
    if kind is not None:
        stmt = stmt.where(ChatSession.kind == kind)
    return list(session.exec(stmt.order_by(ChatSession.updated_at.desc())).all())


def get_session_with_messages(
    session: Session, session_id: int
) -> tuple[ChatSession | None, list[ChatMessage]]:
    chat_session = session.get(ChatSession, session_id)
    if chat_session is None:
        return None, []
    messages = list(
        session.exec(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        ).all()
    )
    return chat_session, messages


def delete_session(session: Session, session_id: int) -> bool:
    """Deletes the session. Its chat_messages cascade-delete at the DB level (ON DELETE
    CASCADE); its resume_versions survive with session_id set to NULL (ON DELETE SET NULL) --
    see app/db/tables.py for why."""
    chat_session = session.get(ChatSession, session_id)
    if chat_session is None:
        return False
    session.delete(chat_session)
    session.flush()
    return True


def append_message(
    session: Session,
    *,
    session_id: int,
    role: str,
    content: str,
    intent: str | None = None,
    resume_version_id: int | None = None,
    meta: str | None = None,
) -> ChatMessage:
    row = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        intent=intent,
        resume_version_id=resume_version_id,
        meta=meta,
    )
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def touch_session(session: Session, session_id: int) -> None:
    chat_session = session.get(ChatSession, session_id)
    if chat_session is None:
        return
    chat_session.updated_at = datetime.now(timezone.utc)
    session.add(chat_session)
    session.flush()
