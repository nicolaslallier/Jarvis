"""Email ingestion job: polls IMAP_FOLDER for unread messages and asks the
LM Studio chat model to extract candidate tasks/appointments from each one,
creating them as DRAFT rows awaiting user approval — Task rows with
status="pending_review" (see backend/app/schemas.py's TaskStatus), or
Appointment rows with pending_review=True (see migration 0010) — rather
than live/trusted items. Both kinds get source="email_import" (see
migration 0011_task_source.py for Task.source).

Two blocking pieces, both isolated behind asyncio.to_thread the same way
batch/app/docker_ingest.py isolates docker-py: imap-tools (`_fetch_unread_
emails`/`_mark_seen`) is a sync library, no asyncio support. The LM Studio
call (`_extract_items`) is natively async via httpx.AsyncClient, mirroring
ingest/app/embeddings.py's direct-LM-Studio-call style rather than
backend/app/routers/chat.py's — batch has no chat.py of its own to delegate
to, so this module owns the outbound call itself.

Dedup is IMAP's own read state, not the notifications_sent table
reminders.py/upcoming_bills.py/important_dates.py use: each message is
marked seen (`_mark_seen`) right after it's processed (successfully or
not — see run()'s per-message try/except/finally-style handling below), so
it is never re-fetched on a later tick. A malformed/unreachable LM Studio
reply is treated the same as "nothing extracted from this email" rather
than left for retry, since (unlike ingest's vision-model fallback) there's
no separate signal here to tell "transient failure, retry me" apart from
"this email genuinely has nothing actionable in it" — and leaving a
never-retriable message unread forever would mean it's reprocessed, and
potentially duplicated, on every single tick.
"""

import asyncio
import dataclasses
import json
import logging
from datetime import datetime

import httpx
from imap_tools import AND, MailBox, MailMessageFlags
from jarvis_shared.models import Appointment, Task

from app.config import Settings, get_settings
from app.db import async_session
from app.health_state import state

logger = logging.getLogger(__name__)

LMSTUDIO_TIMEOUT_SECONDS = 120.0

# Modeled directly on backend/app/memory.py's EXTRACTION_SYSTEM_PROMPT: a
# tight instruction to emit ONLY a JSON array, with an explicit "nothing
# found" escape hatch, so a local model has the best chance of producing a
# reply parse_extracted_items can actually use.
EXTRACTION_SYSTEM_PROMPT = (
    "You extract actionable tasks and appointments from a single incoming "
    "email (its subject and body below). Only include items that represent "
    "something the user needs to do or attend: a deadline, a to-do, a "
    "meeting, or an event with a concrete date/time. Ignore newsletters, "
    "marketing, automated notifications, and anything with no concrete "
    "action or date attached.\n\n"
    "Respond with ONLY a JSON array of objects, each shaped as "
    '{"type": "task" or "appointment", "title": a short string, '
    '"description": a string or null, "due_at": an ISO 8601 datetime '
    'string or null, "start_time": an ISO 8601 datetime string or null, '
    '"end_time": an ISO 8601 datetime string or null}. "due_at" applies '
    'only to "task" items; "start_time"/"end_time" apply only to '
    '"appointment" items and are required for one to be created. If there '
    "is nothing worth creating, respond with []."
)


@dataclasses.dataclass
class _FetchedEmail:
    uid: str
    subject: str
    body: str


def _fetch_unread_emails(settings: Settings) -> list[_FetchedEmail]:
    """Sync imap-tools call — must be invoked via asyncio.to_thread. Opens
    its own connection, fetches every unseen message in IMAP_FOLDER without
    marking any of them seen (mark_seen=False — that only happens per
    message, after it's actually been processed, via _mark_seen below), and
    closes the connection again."""
    emails: list[_FetchedEmail] = []
    with MailBox(settings.imap_host).login(
        settings.imap_username, settings.imap_password, initial_folder=settings.imap_folder
    ) as mailbox:
        for msg in mailbox.fetch(AND(seen=False), mark_seen=False):
            emails.append(
                _FetchedEmail(uid=msg.uid, subject=msg.subject or "", body=msg.text or msg.html or "")
            )
    return emails


def _mark_seen(settings: Settings, uid: str) -> None:
    """Sync imap-tools call — must be invoked via asyncio.to_thread. Flags a
    single message as seen so it isn't re-fetched by _fetch_unread_emails on
    the next tick; this IS email_ingest's dedup mechanism."""
    with MailBox(settings.imap_host).login(
        settings.imap_username, settings.imap_password, initial_folder=settings.imap_folder
    ) as mailbox:
        mailbox.flag(uid, MailMessageFlags.SEEN, True)


def parse_extracted_items(raw_content: str) -> list[dict]:
    """Lenient JSON-array parsing of the extraction model's reply, porting
    the exact bracket-finding/json.loads-with-fallback-to-[] discipline of
    backend/app/memory.py's parse_extracted_facts: local models sometimes
    wrap the array in prose or a code fence despite the prompt asking for
    JSON only. Falls back to an empty list rather than raising, so a
    malformed extraction reply can never crash the job or block the rest of
    the messages in the same run. Also drops any array entry that isn't a
    JSON object, on the same "never raise on a weird reply" principle.
    """
    stripped = raw_content.strip()
    start, end = stripped.find("["), stripped.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        parsed = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _parse_datetime(value: object) -> datetime | None:
    """Same tolerant ISO-8601 parsing as backend/app/routers/chat.py's own
    _parse_datetime (accepts a trailing "Z" as UTC), but never raises: a
    malformed/missing date from the extraction model just means the field
    comes back None instead of failing the whole item."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def _extract_items(settings: Settings, subject: str, body: str) -> list[dict]:
    """Calls LM Studio's OpenAI-compatible /v1/chat/completions endpoint
    directly — batch has no chat.py of its own to delegate to, so this
    mirrors ingest/app/embeddings.py's direct-call style rather than
    backend/app/routers/chat.py's. Raises on any transport/response-shape
    failure; run() below treats that the same as "extracted nothing"."""
    user_content = f"Subject: {subject}\n\n{body}"
    async with httpx.AsyncClient(timeout=LMSTUDIO_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"{settings.lmstudio_base_url}/v1/chat/completions",
            json={
                "model": settings.lmstudio_model,
                "messages": [
                    {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
            },
        )
    response.raise_for_status()
    data = response.json()
    raw_content = data["choices"][0]["message"]["content"]
    return parse_extracted_items(raw_content)


async def _store_items(items: list[dict]) -> int:
    """Creates a pending-review Task or Appointment row per extracted item,
    source="email_import". Returns the count actually created — an item
    missing a usable title, or an "appointment" item missing a usable
    start_time, is silently skipped rather than guessed at."""
    created = 0
    async with async_session() as session:
        for item in items:
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            raw_description = item.get("description")
            description = str(raw_description).strip() if raw_description else None

            if item.get("type") == "appointment":
                start_time = _parse_datetime(item.get("start_time"))
                if start_time is None:
                    continue
                end_time = _parse_datetime(item.get("end_time")) or start_time
                session.add(
                    Appointment(
                        title=title,
                        description=description,
                        start_time=start_time,
                        end_time=end_time,
                        source="email_import",
                        pending_review=True,
                    )
                )
            else:
                session.add(
                    Task(
                        title=title,
                        description=description,
                        due_at=_parse_datetime(item.get("due_at")),
                        status="pending_review",
                        source="email_import",
                    )
                )
            created += 1
        await session.commit()
    return created


async def run() -> None:
    settings = get_settings()
    if not settings.imap_host:
        logger.info("email_ingest: IMAP_HOST not configured, skipping")
        state.record("ok")
        return

    logger.info("email_ingest: checking %s for unread messages", settings.imap_folder)

    try:
        emails = await asyncio.to_thread(_fetch_unread_emails, settings)
    except Exception:
        logger.exception("email_ingest: failed to fetch unread messages")
        state.record("error")
        return

    if not emails:
        logger.info("email_ingest: no unread messages")
        state.record("ok")
        return

    total_created = 0
    for email in emails:
        try:
            items = await _extract_items(settings, email.subject, email.body)
        except Exception:
            logger.exception("email_ingest: extraction failed for message uid=%s", email.uid)
            items = []

        try:
            total_created += await _store_items(items)
        except Exception:
            logger.exception(
                "email_ingest: failed to store extracted items for message uid=%s", email.uid
            )

        try:
            await asyncio.to_thread(_mark_seen, settings, email.uid)
        except Exception:
            # The message stays unread on the server, so it'll be re-fetched
            # (and, worst case, re-processed) on the next tick — safe, just
            # noisy, same trade-off as reminders.py's post-send dedup-write
            # failure handling.
            logger.exception("email_ingest: failed to mark message uid=%s as seen", email.uid)

    logger.info(
        "email_ingest: processed %d message(s), created %d item(s)", len(emails), total_created
    )
    state.record("ok")
