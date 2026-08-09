import asyncio
import json
import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import calendar_service, task_service
from app.config import Settings, get_settings
from app.db import async_session, get_db
from app.memory import (
    EXTRACTION_SYSTEM_PROMPT,
    fetch_relevant_memories,
    format_memory_context,
    parse_extracted_facts,
    store_memories,
)
from app.models import Appointment, ChatMessageRecord, ChatSession, Task
from app.rag import RetrievedChunk, fetch_relevant_chunks, format_context
from app.schemas import (
    ChatMessageRead,
    ChatSendRequest,
    ChatSessionCreate,
    ChatSessionDetail,
    ChatSessionRead,
)

logger = logging.getLogger(__name__)

router = APIRouter()

LMSTUDIO_TIMEOUT_SECONDS = 120.0
EMBEDDING_TIMEOUT_SECONDS = 30.0
MEMORY_EXTRACTION_TIMEOUT_SECONDS = 30.0
TITLE_GENERATION_TIMEOUT_SECONDS = 15.0
DEFAULT_SESSION_TITLE = "New chat"
TITLE_MAX_LENGTH = 50

# Safety cap on how many times the model can chain tool calls (list, then
# act on what it saw, etc.) before we force a final natural-language answer
# without offering tools. Without a cap, a model stuck calling tools in a
# loop would never return a reply to the user.
MAX_TOOL_ITERATIONS = 5

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
    "without mentioning that they were 'retrieved' or 'remembered'. "
    "You can only create, move, or cancel calendar appointments by calling "
    "the list_appointments/create_appointment/update_appointment/"
    "delete_appointment tools — you have no other way to change the "
    "calendar. You can only create, update, complete, or list the user's "
    "tasks by calling the list_tasks/create_task/update_task/complete_task "
    "tools — you have no other way to change their tasks. When a request "
    "naturally breaks into several steps (e.g. \"organize Sunday dinner\"), "
    "create one parent task and add the steps as separate tasks with "
    "parent_id set to the parent's id. Never tell the user an appointment "
    "or task was added, changed, or completed unless you actually called "
    "the matching tool in this turn and it returned success; if you didn't "
    "call it, say so instead of confirming the change."
)

TITLE_GENERATION_SYSTEM_PROMPT = (
    "Summarize the user's message as a short chat title of 3 to 6 words. "
    "Respond with only the title text — no quotes, no punctuation at the "
    "end, no preamble."
)

# OpenAI-compatible tool schema letting the model manage the user's calendar
# directly (create/reschedule/cancel/list appointments) instead of only
# being able to discuss the upcoming-appointments context injected below.
# Not every LM Studio model/version supports tool calling — see
# _stream_attempt's _ToolsRejected handling, which retries without this if
# the model rejects it, so calendar tools are a capability boost, never a
# chat dependency.
CALENDAR_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_appointments",
            "description": "List the user's calendar appointments, optionally filtered to a date range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {
                        "type": "string",
                        "description": "ISO 8601 datetime. Only appointments ending on/after this are included.",
                    },
                    "end": {
                        "type": "string",
                        "description": "ISO 8601 datetime. Only appointments starting on/before this are included.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_appointment",
            "description": "Create a new appointment on the user's calendar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start_time": {"type": "string", "description": "ISO 8601 datetime"},
                    "end_time": {"type": "string", "description": "ISO 8601 datetime"},
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                    "all_day": {"type": "boolean"},
                },
                "required": ["title", "start_time", "end_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_appointment",
            "description": "Update an existing appointment. Only the fields provided are changed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "title": {"type": "string"},
                    "start_time": {"type": "string", "description": "ISO 8601 datetime"},
                    "end_time": {"type": "string", "description": "ISO 8601 datetime"},
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                    "all_day": {"type": "boolean"},
                },
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_appointment",
            "description": "Delete/cancel an appointment.",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "integer"}},
                "required": ["id"],
            },
        },
    },
]

# Same idea as CALENDAR_TOOLS, for the user's task list. Kept as a separate
# list (both are passed together to the model, see TOOLS below) so each
# domain's tool set stays easy to read on its own.
TASK_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "List the user's tasks, optionally filtered by status or project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["todo", "doing", "done", "cancelled"],
                    },
                    "project": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": (
                "Create a new task. For a multi-step request, first create the parent "
                "task, then create each step as its own task with parent_id set to the "
                "parent's id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "due_at": {"type": "string", "description": "ISO 8601 datetime"},
                    "priority": {"type": "string", "enum": ["low", "normal", "high"]},
                    "project": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "parent_id": {"type": "integer", "description": "Id of the parent task, if this is a subtask"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task",
            "description": "Update an existing task. Only the fields provided are changed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "due_at": {"type": "string", "description": "ISO 8601 datetime"},
                    "status": {"type": "string", "enum": ["todo", "doing", "done", "cancelled"]},
                    "priority": {"type": "string", "enum": ["low", "normal", "high"]},
                    "project": {"type": "string"},
                },
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": "Mark a task as done.",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "integer"}},
                "required": ["id"],
            },
        },
    },
]

TOOLS = CALENDAR_TOOLS + TASK_TOOLS


# Fire-and-forget tasks (memory extraction, title generation) are started
# with asyncio.create_task rather than awaited, so they can't add latency to
# the response. asyncio only holds a *weak* reference to a task that isn't
# stored anywhere, so without this module-level set the task can be garbage
# collected mid-run — keeping a strong reference here (discarded via the
# done callback once it finishes) is the standard workaround.
_background_tasks: set[asyncio.Task] = set()


def _fire_and_forget(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _sse(payload: dict) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode()


class LMStudioStreamError(Exception):
    """A streaming LM Studio call failed in a way that isn't recoverable —
    raised from inside the SSE generator after the HTTP response (200,
    text/event-stream) has already been sent, so it's caught and turned
    into an in-band `{"type": "error"}` SSE event rather than an HTTP error
    status, which can no longer be changed at that point."""


class _ToolsRejected(Exception):
    """Raised when a streaming call made with `tools` set fails outright —
    some LM Studio model/version combinations reject the field entirely.
    Caught one level up so the caller can retry once without tools."""

    def __init__(self, body: str) -> None:
        self.body = body


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
) -> tuple[str | None, list[RetrievedChunk]]:
    """Best-effort: looks up the closest file_chunks to `embedding` so the
    model can ground its reply in the user's uploaded documents. Any
    failure here (vector extension/table not available yet, no chunks at
    all) just means no context gets added — RAG is a quality boost, not a
    chat dependency. Returns both the formatted context string (injected as
    a system message) and the raw chunk list (so the caller can also surface
    which sources were used, for display, without a second retrieval call).
    """
    if embedding is None:
        return None, []
    try:
        chunks = await fetch_relevant_chunks(db, embedding, top_k=settings.rag_top_k)
        if not chunks:
            return None, []
        return format_context(chunks), chunks
    except Exception:
        logger.warning("RAG context retrieval failed", exc_info=True)
        return None, []


async def _build_memory_context(
    db: AsyncSession, settings: Settings, embedding: list[float] | None
) -> str | None:
    """Best-effort counterpart to _build_rag_context, for facts learned
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


def _build_datetime_context(settings: Settings) -> str:
    """Grounds the model in the real current date/time, in the user's own
    timezone rather than UTC — otherwise relative expressions like "today"
    or "tonight" can resolve to the wrong calendar day whenever it's
    already tomorrow in UTC but still today locally (or vice versa).
    Computed fresh per request, unlike the constant SECRETARY_SYSTEM_PROMPT,
    since "now" changes on every call.
    """
    now_utc = datetime.now(UTC)
    try:
        tz = ZoneInfo(settings.timezone)
    except Exception:
        logger.warning("Unknown TIMEZONE %r, falling back to UTC", settings.timezone)
        tz = UTC
    now_local = now_utc.astimezone(tz)
    return (
        f"The current date and time is {now_local.isoformat()} ({settings.timezone}), "
        f"{now_local.strftime('%A, %B %d, %Y')} at {now_local.strftime('%H:%M')}. Use this "
        "as the true current date/time — already in the user's local timezone — when "
        "resolving relative expressions like \"today\", \"tonight\", \"tomorrow\", \"next "
        "week\", or \"in two days\". Do not assume any other current date or timezone."
    )


async def _build_calendar_context(db: AsyncSession, settings: Settings) -> str | None:
    """Best-effort: surfaces the user's upcoming appointments so the model
    can answer day/week-planning questions without needing a tool call.
    Unlike RAG/memory context, this needs no embedding — it's a plain
    date-range query — so it runs unconditionally rather than depending on
    _embed_text having succeeded.
    """
    try:
        appointments = await calendar_service.fetch_upcoming(db, settings.calendar_upcoming_days)
        if not appointments:
            return None
        return calendar_service.format_upcoming_context(appointments)
    except Exception:
        logger.warning("Calendar context retrieval failed", exc_info=True)
        return None


async def _build_task_context(db: AsyncSession) -> str | None:
    """Best-effort counterpart to _build_calendar_context, surfacing the
    user's open tasks so the model can answer "what's on my plate" style
    questions without needing a tool call."""
    try:
        tasks = await task_service.fetch_active(db)
        if not tasks:
            return None
        return task_service.format_active_context(tasks)
    except Exception:
        logger.warning("Task context retrieval failed", exc_info=True)
        return None


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _appointment_to_dict(appointment: Appointment) -> dict:
    return {
        "id": appointment.id,
        "title": appointment.title,
        "description": appointment.description,
        "location": appointment.location,
        "start_time": appointment.start_time.isoformat(),
        "end_time": appointment.end_time.isoformat(),
        "all_day": appointment.all_day,
    }


async def _execute_calendar_tool_call(db: AsyncSession, name: str, arguments: dict) -> dict:
    """Runs one calendar tool call the model requested and returns a
    JSON-serializable result to feed back to it as a `role: tool` message.
    Errors (bad arguments, appointment not found) are returned as an error
    payload rather than raised, so one bad tool call doesn't abort the
    whole chat send — the model sees the error and can retry or explain it.
    """
    try:
        if name == "list_appointments":
            start = _parse_datetime(arguments["start"]) if arguments.get("start") else None
            end = _parse_datetime(arguments["end"]) if arguments.get("end") else None
            appointments = await calendar_service.list_appointments(db, start=start, end=end)
            return {"appointments": [_appointment_to_dict(a) for a in appointments]}
        if name == "create_appointment":
            appointment = await calendar_service.create_appointment(
                db,
                title=arguments["title"],
                start_time=_parse_datetime(arguments["start_time"]),
                end_time=_parse_datetime(arguments["end_time"]),
                description=arguments.get("description"),
                location=arguments.get("location"),
                all_day=arguments.get("all_day", False),
            )
            return {"appointment": _appointment_to_dict(appointment)}
        if name == "update_appointment":
            fields = {k: v for k, v in arguments.items() if k != "id"}
            if "start_time" in fields:
                fields["start_time"] = _parse_datetime(fields["start_time"])
            if "end_time" in fields:
                fields["end_time"] = _parse_datetime(fields["end_time"])
            appointment = await calendar_service.update_appointment(db, arguments["id"], **fields)
            if appointment is None:
                return {"error": f"no appointment with id {arguments['id']}"}
            return {"appointment": _appointment_to_dict(appointment)}
        if name == "delete_appointment":
            deleted = await calendar_service.delete_appointment(db, arguments["id"])
            if not deleted:
                return {"error": f"no appointment with id {arguments['id']}"}
            return {"deleted": True}
        return {"error": f"unknown tool {name}"}
    except Exception as exc:
        logger.warning("Calendar tool call %s failed", name, exc_info=True)
        return {"error": str(exc)}


def _task_to_dict(task: Task) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "status": task.status,
        "priority": task.priority,
        "project": task.project,
        "tags": task.tags,
        "parent_id": task.parent_id,
    }


async def _execute_task_tool_call(db: AsyncSession, name: str, arguments: dict) -> dict:
    """Runs one task tool call the model requested, same error-as-payload
    convention as _execute_calendar_tool_call above."""
    try:
        if name == "list_tasks":
            tasks = await task_service.list_tasks(
                db, status=arguments.get("status"), project=arguments.get("project")
            )
            return {"tasks": [_task_to_dict(t) for t in tasks]}
        if name == "create_task":
            task = await task_service.create_task(
                db,
                title=arguments["title"],
                description=arguments.get("description"),
                due_at=_parse_datetime(arguments["due_at"]) if arguments.get("due_at") else None,
                priority=arguments.get("priority", "normal"),
                project=arguments.get("project"),
                tags=arguments.get("tags"),
                parent_id=arguments.get("parent_id"),
            )
            return {"task": _task_to_dict(task)}
        if name == "update_task":
            fields = {k: v for k, v in arguments.items() if k != "id"}
            if "due_at" in fields:
                fields["due_at"] = _parse_datetime(fields["due_at"])
            task = await task_service.update_task(db, arguments["id"], **fields)
            if task is None:
                return {"error": f"no task with id {arguments['id']}"}
            return {"task": _task_to_dict(task)}
        if name == "complete_task":
            task = await task_service.complete_task(db, arguments["id"])
            if task is None:
                return {"error": f"no task with id {arguments['id']}"}
            return {"task": _task_to_dict(task)}
        return {"error": f"unknown tool {name}"}
    except Exception as exc:
        logger.warning("Task tool call %s failed", name, exc_info=True)
        return {"error": str(exc)}


_TASK_TOOL_NAMES = {"list_tasks", "create_task", "update_task", "complete_task"}


async def _execute_tool_call(db: AsyncSession, name: str, arguments: dict) -> dict:
    """Dispatches a model-requested tool call to the calendar or task
    executor based on its name."""
    if name in _TASK_TOOL_NAMES:
        return await _execute_task_tool_call(db, name, arguments)
    return await _execute_calendar_tool_call(db, name, arguments)


async def _stream_attempt(settings: Settings, messages: list[dict], tools: list[dict] | None):
    """Opens one streaming LM Studio chat-completion call and yields event
    dicts as the response arrives:
      {"kind": "delta", "text": str}                         -- a content chunk
      {"kind": "final", "content": str, "tool_calls": list | None}  -- always
        the last event yielded, once the stream ends normally.

    Raises `_ToolsRejected` if the call was made with `tools` set and LM
    Studio rejected it outright (some model/version combos don't support
    tool calling) — the caller retries once without tools. Raises
    `LMStudioStreamError` for anything else that goes wrong (network error,
    non-200 without tools).
    """
    payload: dict = {"model": settings.lmstudio_model, "messages": messages, "stream": True}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    content_parts: list[str] = []
    tool_call_acc: dict[int, dict] = {}

    try:
        async with httpx.AsyncClient(timeout=LMSTUDIO_TIMEOUT_SECONDS) as client:
            async with client.stream(
                "POST", f"{settings.lmstudio_base_url}/v1/chat/completions", json=payload
            ) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode(errors="replace")
                    if tools:
                        raise _ToolsRejected(body)
                    raise LMStudioStreamError(f"LM Studio returned {response.status_code}: {body}")

                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if not data:
                        continue
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    choices = chunk.get("choices") or []
                    delta = choices[0].get("delta", {}) if choices else {}

                    text = delta.get("content")
                    if text:
                        content_parts.append(text)
                        yield {"kind": "delta", "text": text}

                    for tool_call_delta in delta.get("tool_calls") or []:
                        index = tool_call_delta.get("index", 0)
                        acc = tool_call_acc.setdefault(
                            index,
                            {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                        )
                        if tool_call_delta.get("id"):
                            acc["id"] = tool_call_delta["id"]
                        function_delta = tool_call_delta.get("function") or {}
                        if function_delta.get("name"):
                            acc["function"]["name"] = function_delta["name"]
                        if function_delta.get("arguments"):
                            acc["function"]["arguments"] += function_delta["arguments"]
    except httpx.RequestError as exc:
        raise LMStudioStreamError(
            f"Could not reach LM Studio at {settings.lmstudio_base_url}: {exc}"
        ) from exc

    tool_calls = [tool_call_acc[i] for i in sorted(tool_call_acc)] or None
    yield {"kind": "final", "content": "".join(content_parts), "tool_calls": tool_calls}


async def _generate_title(settings: Settings, content: str) -> str | None:
    """Best-effort: asks the chat model to summarize the first message into
    a short title, replacing the naive first-N-characters truncation once
    it's ready (see _generate_title_task). Any failure just means the
    fallback title sticks around."""
    try:
        async with httpx.AsyncClient(timeout=TITLE_GENERATION_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{settings.lmstudio_base_url}/v1/chat/completions",
                json={
                    "model": settings.lmstudio_model,
                    "messages": [
                        {"role": "system", "content": TITLE_GENERATION_SYSTEM_PROMPT},
                        {"role": "user", "content": content},
                    ],
                    "max_tokens": 20,
                },
            )
        if response.status_code != 200:
            logger.warning("Title generation call returned %s", response.status_code)
            return None
        title = response.json()["choices"][0]["message"]["content"]
        title = title.strip().strip('"').strip()
        if not title:
            return None
        return _title_from_content(title)
    except Exception:
        logger.warning("Title generation failed", exc_info=True)
        return None


async def _generate_title_task(settings: Settings, session_id: int, content: str) -> None:
    title = await _generate_title(settings, content)
    if not title:
        return
    fallback_title = _title_from_content(content)
    async with async_session() as db:
        session = await db.get(ChatSession, session_id)
        if session is None:
            return
        # Only overwrite the title if it's still whatever send_message set
        # as an instant fallback — if the user (or a future rename feature)
        # changed it in the meantime, don't clobber that.
        if session.title not in (DEFAULT_SESSION_TITLE, fallback_title):
            return
        session.title = title
        await db.commit()


async def _record_memories(
    db: AsyncSession, settings: Settings, session_id: int, user_content: str, assistant_content: str
) -> None:
    """Best-effort: asks the chat model to pull any durable facts out of
    this exchange, embeds them, and stores them for retrieval on later
    messages/sessions (see app/memory.py)."""
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


async def _record_memories_task(
    settings: Settings, session_id: int, user_content: str, assistant_content: str
) -> None:
    """Runs _record_memories with its own DB session, since this fires via
    asyncio.create_task and keeps running after the request's own `db`
    session (from Depends(get_db)) has already been closed."""
    async with async_session() as db:
        await _record_memories(db, settings, session_id, user_content, assistant_content)


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


async def _stream_send_message(
    db: AsyncSession,
    settings: Settings,
    session: ChatSession,
    user_message: ChatMessageRecord,
    messages_for_model: list[dict],
    sources: list[dict],
):
    """The SSE response body for POST /chat/sessions/{id}/messages. Runs the
    tool-calling loop (up to MAX_TOOL_ITERATIONS) against streaming LM
    Studio calls, relaying content deltas to the client as they arrive, then
    persists the assistant's reply and fires memory extraction off the
    critical path before sending the final `done` event.

    `sources` is the lightweight, display-only view of the RAG chunks (if
    any) used to build the RAG context system message already folded into
    `messages_for_model` — relayed to the client as its own `sources` event
    so the UI can show which files/excerpts were used, without re-sending
    the (already-truncated) context string itself.
    """
    yield _sse(
        {"type": "user_message", "message": ChatMessageRead.model_validate(user_message).model_dump(mode="json")}
    )
    yield _sse({"type": "session", "session": ChatSessionRead.model_validate(session).model_dump(mode="json")})
    if sources:
        yield _sse({"type": "sources", "sources": sources})

    messages = list(messages_for_model)
    tools_supported = True
    final_content: str | None = None
    final_tool_calls: list[dict] | None = None

    def _consume(stream):
        async def _gen():
            nonlocal final_content, final_tool_calls
            async for event in stream:
                if event["kind"] == "delta":
                    yield _sse({"type": "delta", "content": event["text"]})
                else:
                    final_content = event["content"]
                    final_tool_calls = event["tool_calls"]

        return _gen()

    try:
        for _ in range(MAX_TOOL_ITERATIONS):
            final_content, final_tool_calls = None, None
            tools_to_offer = TOOLS if tools_supported else None
            try:
                async for sse_event in _consume(_stream_attempt(settings, messages, tools_to_offer)):
                    yield sse_event
            except _ToolsRejected:
                tools_supported = False
                async for sse_event in _consume(_stream_attempt(settings, messages, None)):
                    yield sse_event

            if not final_tool_calls:
                break

            assistant_tool_message = {
                "role": "assistant",
                "content": final_content,
                "tool_calls": final_tool_calls,
            }
            tool_result_messages = []
            for call in final_tool_calls:
                function = call.get("function", {})
                yield _sse({"type": "tool_call", "name": function.get("name", "")})
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                result = await _execute_tool_call(db, function.get("name", ""), arguments)
                tool_result_messages.append(
                    {"role": "tool", "tool_call_id": call.get("id", ""), "content": json.dumps(result)}
                )
            messages = messages + [assistant_tool_message] + tool_result_messages
        else:
            # Exhausted MAX_TOOL_ITERATIONS and the model is still trying to
            # call tools — force a final natural-language answer.
            final_content, final_tool_calls = None, None
            async for sse_event in _consume(_stream_attempt(settings, messages, None)):
                yield sse_event
    except LMStudioStreamError as exc:
        logger.exception("LM Studio streaming failed", exc_info=exc)
        yield _sse({"type": "error", "detail": "An internal error occurred while streaming the response."})
        return

    if not isinstance(final_content, str):
        yield _sse({"type": "error", "detail": "Unexpected response shape from LM Studio"})
        return

    assistant_message = ChatMessageRecord(session_id=session.id, role="assistant", content=final_content)
    db.add(assistant_message)
    await db.commit()
    await db.refresh(session)
    await db.refresh(assistant_message)

    _fire_and_forget(
        _record_memories_task(settings, session.id, user_message.content, final_content)
    )

    yield _sse(
        {
            "type": "done",
            "assistant_message": ChatMessageRead.model_validate(assistant_message).model_dump(mode="json"),
            "session": ChatSessionRead.model_validate(session).model_dump(mode="json"),
        }
    )


@router.post("/chat/sessions/{session_id}/messages")
async def send_message(
    session_id: int, payload: ChatSendRequest, db: AsyncSession = Depends(get_db)
) -> StreamingResponse:
    session = await db.get(ChatSession, session_id, options=[selectinload(ChatSession.messages)])
    if session is None:
        raise HTTPException(status_code=404, detail="chat session not found")

    user_message = ChatMessageRecord(session_id=session.id, role="user", content=payload.content)
    session.messages.append(user_message)
    is_first_message = session.title == DEFAULT_SESSION_TITLE
    if is_first_message:
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

    if is_first_message:
        _fire_and_forget(_generate_title_task(settings, session.id, payload.content))

    history = [{"role": m.role, "content": m.content} for m in session.messages]
    if settings.chat_history_max_messages > 0:
        history = history[-settings.chat_history_max_messages :]

    embedding = await _embed_text(settings, payload.content)
    memory_context = await _build_memory_context(db, settings, embedding)
    rag_context, rag_chunks = await _build_rag_context(db, settings, embedding)
    calendar_context = await _build_calendar_context(db, settings)
    task_context = await _build_task_context(db)
    sources = [
        {"filename": c.filename, "chunk_index": c.chunk_index, "excerpt": c.chunk_text[:200]}
        for c in rag_chunks
    ]

    context_messages = [
        {"role": "system", "content": SECRETARY_SYSTEM_PROMPT},
        {"role": "system", "content": _build_datetime_context(settings)},
    ]
    if memory_context is not None:
        context_messages.append({"role": "system", "content": memory_context})
    if rag_context is not None:
        context_messages.append({"role": "system", "content": rag_context})
    if calendar_context is not None:
        context_messages.append({"role": "system", "content": calendar_context})
    if task_context is not None:
        context_messages.append({"role": "system", "content": task_context})
    messages_for_model = context_messages + history

    return StreamingResponse(
        _stream_send_message(db, settings, session, user_message, messages_for_model, sources),
        media_type="text/event-stream",
    )
