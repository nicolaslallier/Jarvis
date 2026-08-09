import logging
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings, get_settings
from app.db import get_db
from app.memory import (
    EXTRACTION_SYSTEM_PROMPT,
    fetch_relevant_memories,
    format_memory_context,
    parse_extracted_facts,
    store_memories,
)
from app.models import ChatMessageRecord, ChatSession
from app.rag import fetch_relevant_chunks, format_context
from app.schemas import (
    ChatMessageRead,
    ChatSendRequest,
    ChatSendResponse,
    ChatSessionCreate,
    ChatSessionDetail,
    ChatSessionRead,
)

logger = logging.getLogger(__name__)

router = APIRouter()

LMSTUDIO_TIMEOUT_SECONDS = 120.0
EMBEDDING_TIMEOUT_SECONDS = 30.0
MEMORY_EXTRACTION_TIMEOUT_SECONDS = 30.0
DEFAULT_SESSION_TITLE = "New chat"
TITLE_MAX_LENGTH = 50

# Always the first message sent to the model, establishing the assistant's
# persona. Memory/RAG context (below) is appended after this, not folded
# into it, so this stays constant regardless of what gets retrieved.
SECRETARY_SYSTEM_PROMPT = (
    "You are the user's personal secretary: an assistant who helps them run "
    "their day, week, and life — scheduling, tasks, priorities, follow-ups, "
    "and everyday life admin. Be proactive, warm, and concise: surface what "
    "needs attention, ask clarifying questions when a request is ambiguous, "
    "and default to practical next steps over long explanations. When facts "
    "remembered from earlier conversations or excerpts from the user's "
    "documents are provided below as context, weave them in naturally "
    "without mentioning that they were 'retrieved' or 'remembered'."
)


async def _embed_text(settings: Settings, query: str) -> list[float] | None:
    """Best-effort: embeds `query` via LM Studio. Shared by RAG file-chunk
    retrieval and memory retrieval below so a single incoming message only
    costs one embeddings call for both lookups combined. Any failure (LM
    Studio unreachable, bad response) just means no context gets added —
    this must never be the reason a chat message fails to send.
    """
    try:
        async with httpx.AsyncClient(timeout=EMBEDDING_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{settings.embedding_lmstudio_base_url}/v1/embeddings",
                json={"model": settings.embedding_lmstudio_model, "input": [query]},
            )
        if response.status_code != 200:
            logger.warning("Embedding call returned %s", response.status_code)
            return None
        return response.json()["data"][0]["embedding"]
    except Exception:
        logger.warning("Embedding call failed", exc_info=True)
        return None


async def _build_rag_context(
    db: AsyncSession, settings: Settings, embedding: list[float] | None
) -> str | None:
    """Best-effort: looks up the closest file_chunks to `embedding` so the
    model can ground its reply in the user's uploaded documents. Any
    failure here (vector extension/table not available yet, no chunks at
    all) just means no context gets added — RAG is a quality boost, not a
    chat dependency.
    """
    if embedding is None:
        return None
    try:
        chunks = await fetch_relevant_chunks(db, embedding, top_k=settings.rag_top_k)
        if not chunks:
            return None
        return format_context(chunks)
    except Exception:
        logger.warning("RAG context retrieval failed", exc_info=True)
        return None


async def _build_memory_context(
    db: AsyncSession, settings: Settings, embedding: list[float] | None
) -> str | None:
    """Best-effort counterpart to _build_rag_context, for facts remembered
    from earlier conversations instead of uploaded documents."""
    if embedding is None:
        return None
    try:
        memories = await fetch_relevant_memories(db, embedding, top_k=settings.memory_top_k)
        if not memories:
            return None
        return format_memory_context(memories)
    except Exception:
        logger.warning("Memory context retrieval failed", exc_info=True)
        return None


async def _record_memories(
    db: AsyncSession, settings: Settings, session_id: int, user_content: str, assistant_content: str
) -> None:
    """Best-effort: asks the chat model to pull any durable facts out of
    this exchange, embeds them, and stores them for retrieval on later
    messages/sessions (see app/memory.py). Runs after the reply has already
    been generated and persisted, so any failure here (LM Studio
    unreachable, unparseable extraction reply, embedding failure) never
    blocks the chat send that's already succeeded.
    """
    try:
        exchange = f"User: {user_content}\nAssistant: {assistant_content}"
        async with httpx.AsyncClient(timeout=MEMORY_EXTRACTION_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{settings.lmstudio_base_url}/v1/chat/completions",
                json={
                    "model": settings.lmstudio_model,
                    "messages": [
                        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                        {"role": "user", "content": exchange},
                    ],
                },
            )
        if response.status_code != 200:
            logger.warning("Memory extraction call returned %s", response.status_code)
            return

        raw_content = response.json()["choices"][0]["message"]["content"]
        facts = parse_extracted_facts(raw_content)
        if not facts:
            return

        async with httpx.AsyncClient(timeout=EMBEDDING_TIMEOUT_SECONDS) as client:
            embed_response = await client.post(
                f"{settings.embedding_lmstudio_base_url}/v1/embeddings",
                json={"model": settings.embedding_lmstudio_model, "input": facts},
            )
        if embed_response.status_code != 200:
            logger.warning("Memory embedding call returned %s", embed_response.status_code)
            return

        items = sorted(embed_response.json()["data"], key=lambda item: item["index"])
        embeddings = [item["embedding"] for item in items]

        await store_memories(db, session_id, facts, embeddings)
    except Exception:
        logger.warning("Memory extraction/storage failed", exc_info=True)


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

    embedding = await _embed_text(settings, payload.content)
    memory_context = await _build_memory_context(db, settings, embedding)
    rag_context = await _build_rag_context(db, settings, embedding)

    context_messages = [{"role": "system", "content": SECRETARY_SYSTEM_PROMPT}]
    if memory_context is not None:
        context_messages.append({"role": "system", "content": memory_context})
    if rag_context is not None:
        context_messages.append({"role": "system", "content": rag_context})
    messages_for_model = context_messages + history

    try:
        async with httpx.AsyncClient(timeout=LMSTUDIO_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{settings.lmstudio_base_url}/v1/chat/completions",
                json={"model": settings.lmstudio_model, "messages": messages_for_model},
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

    await _record_memories(db, settings, session.id, payload.content, content)

    return ChatSendResponse(
        session=ChatSessionRead.model_validate(session),
        user_message=ChatMessageRead.model_validate(user_message),
        assistant_message=ChatMessageRead.model_validate(assistant_message),
    )
