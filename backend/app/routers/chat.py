from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import get_db
from app.models import ChatMessageRecord, ChatSession
from app.schemas import (
    ChatMessageRead,
    ChatSendRequest,
    ChatSendResponse,
    ChatSessionCreate,
    ChatSessionDetail,
    ChatSessionRead,
)

router = APIRouter()

LMSTUDIO_TIMEOUT_SECONDS = 120.0
DEFAULT_SESSION_TITLE = "New chat"
TITLE_MAX_LENGTH = 50


def _title_from_content(content: str) -> str:
    content = content.strip()
    if len(content) <= TITLE_MAX_LENGTH:
        return content
    return content[:TITLE_MAX_LENGTH].rstrip() + "…"


@router.post("/chat/sessions", response_model=ChatSessionRead)
async def create_session(payload: ChatSessionCreate, db: AsyncSession = Depends(get_db)) -> ChatSession:
    session = ChatSession(title=payload.title or DEFAULT_SESSION_TITLE)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/chat/sessions", response_model=list[ChatSessionRead])
async def list_sessions(db: AsyncSession = Depends(get_db)) -> list[ChatSession]:
    result = await db.execute(select(ChatSession).order_by(ChatSession.updated_at.desc()))
    return list(result.scalars().all())


@router.get("/chat/sessions/{session_id}", response_model=ChatSessionDetail)
async def get_session(session_id: int, db: AsyncSession = Depends(get_db)) -> ChatSession:
    session = await db.get(ChatSession, session_id, options=[selectinload(ChatSession.messages)])
    if session is None:
        raise HTTPException(status_code=404, detail="chat session not found")
    return session


@router.delete("/chat/sessions/{session_id}", status_code=204)
async def delete_session(session_id: int, db: AsyncSession = Depends(get_db)) -> None:
    session = await db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="chat session not found")
    await db.delete(session)
    await db.commit()


@router.post("/chat/sessions/{session_id}/messages", response_model=ChatSendResponse)
async def send_message(
    session_id: int, payload: ChatSendRequest, db: AsyncSession = Depends(get_db)
) -> ChatSendResponse:
    session = await db.get(ChatSession, session_id, options=[selectinload(ChatSession.messages)])
    if session is None:
        raise HTTPException(status_code=404, detail="chat session not found")

    user_message = ChatMessageRecord(session_id=session.id, role="user", content=payload.content)
    session.messages.append(user_message)
    if session.title == DEFAULT_SESSION_TITLE:
        session.title = _title_from_content(payload.content)
    # Appending a child message doesn't dirty the parent row on its own, so
    # `updated_at`'s onupdate wouldn't fire — touch it explicitly to keep
    # the session list sorted by most recently active.
    session.updated_at = datetime.now(UTC)

    # Persist the user's message before calling out to LM Studio, so it
    # isn't lost if that call fails.
    await db.commit()
    await db.refresh(session, attribute_names=["messages"])
    await db.refresh(user_message)

    settings = get_settings()
    history = [{"role": m.role, "content": m.content} for m in session.messages]

    try:
        async with httpx.AsyncClient(timeout=LMSTUDIO_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{settings.lmstudio_base_url}/v1/chat/completions",
                json={"model": settings.lmstudio_model, "messages": history},
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502, detail=f"Could not reach LM Studio at {settings.lmstudio_base_url}: {exc}"
        ) from exc

    if response.status_code != 200:
        raise HTTPException(
            status_code=502, detail=f"LM Studio returned {response.status_code}: {response.text}"
        )

    data = response.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="Unexpected response shape from LM Studio") from exc

    assistant_message = ChatMessageRecord(session_id=session.id, role="assistant", content=content)
    db.add(assistant_message)
    await db.commit()
    await db.refresh(session)
    await db.refresh(assistant_message)

    return ChatSendResponse(
        session=ChatSessionRead.model_validate(session),
        user_message=ChatMessageRead.model_validate(user_message),
        assistant_message=ChatMessageRead.model_validate(assistant_message),
    )
