from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from jarvis_shared.db import Base
from jarvis_shared.models import Appointment, Task
from sqlalchemy import select

from app.db import async_session, engine
from app.health_state import state
from app.jobs import email_ingest


@dataclass
class _FakeSettings:
    imap_host: str = "imap.test"
    imap_username: str = "user@test.example"
    imap_password: str = "secret"
    imap_folder: str = "INBOX"
    lmstudio_base_url: str = "http://lmstudio.test:1234"
    lmstudio_model: str = "test-chat-model"


class _FakeMessage:
    def __init__(self, uid: str, subject: str, text: str):
        self.uid = uid
        self.subject = subject
        self.text = text
        self.html = None


class _FakeMailBox:
    """Stands in for imap_tools.MailBox: login()/context-manager return
    self, fetch() yields the canned messages, flag() records what was
    flagged (and how) so tests can assert on it."""

    def __init__(self, messages: list[_FakeMessage]):
        self._messages = messages
        self.flagged: list[tuple] = []
        self.entered = False

    def login(self, username, password, initial_folder=None):
        return self

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def fetch(self, criteria=None, mark_seen=False):
        assert mark_seen is False
        return iter(self._messages)

    def flag(self, uid, flag_set, value):
        self.flagged.append((uid, flag_set, value))


@pytest.fixture
async def db():
    await engine.dispose()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


def _chat_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}]},
        request=httpx.Request("POST", "http://lmstudio.test:1234/v1/chat/completions"),
    )


@pytest.mark.asyncio
async def test_imap_host_empty_no_ops(db):
    with (
        patch("app.jobs.email_ingest.get_settings", return_value=_FakeSettings(imap_host="")),
        patch("app.jobs.email_ingest.MailBox") as mock_mailbox_cls,
    ):
        await email_ingest.run()

    mock_mailbox_cls.assert_not_called()
    assert state.last_status == "ok"

    async with async_session() as session:
        assert list((await session.execute(select(Task))).scalars().all()) == []


@pytest.mark.asyncio
async def test_well_formed_extraction_creates_pending_review_task(db):
    message = _FakeMessage(
        uid="1", subject="Quarterly report", text="Please submit the quarterly report by Friday."
    )
    fake_mailbox = _FakeMailBox([message])
    extraction_reply = (
        '[{"type": "task", "title": "Submit quarterly report", '
        '"description": "Submit the quarterly report", '
        '"due_at": "2026-08-14T17:00:00", "start_time": null, "end_time": null}]'
    )

    with (
        patch("app.jobs.email_ingest.get_settings", return_value=_FakeSettings()),
        patch("app.jobs.email_ingest.MailBox", return_value=fake_mailbox),
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=_chat_response(extraction_reply))),
    ):
        await email_ingest.run()

    async with async_session() as session:
        tasks = list((await session.execute(select(Task))).scalars().all())

    assert len(tasks) == 1
    assert tasks[0].title == "Submit quarterly report"
    assert tasks[0].status == "pending_review"
    assert tasks[0].source == "email_import"
    assert tasks[0].due_at is not None

    assert fake_mailbox.flagged == [("1", email_ingest.MailMessageFlags.SEEN, True)]
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_well_formed_extraction_creates_pending_review_appointment(db):
    message = _FakeMessage(
        uid="2", subject="Team sync", text="Let's meet Tuesday at 10am to sync up."
    )
    fake_mailbox = _FakeMailBox([message])
    extraction_reply = (
        '[{"type": "appointment", "title": "Team sync", "description": null, '
        '"due_at": null, "start_time": "2026-08-11T10:00:00", '
        '"end_time": "2026-08-11T10:30:00"}]'
    )

    with (
        patch("app.jobs.email_ingest.get_settings", return_value=_FakeSettings()),
        patch("app.jobs.email_ingest.MailBox", return_value=fake_mailbox),
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=_chat_response(extraction_reply))),
    ):
        await email_ingest.run()

    async with async_session() as session:
        appointments = list((await session.execute(select(Appointment))).scalars().all())

    assert len(appointments) == 1
    assert appointments[0].title == "Team sync"
    assert appointments[0].pending_review is True
    assert appointments[0].source == "email_import"

    assert fake_mailbox.flagged == [("2", email_ingest.MailMessageFlags.SEEN, True)]
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_malformed_extraction_reply_creates_nothing_and_does_not_raise(db):
    message = _FakeMessage(uid="3", subject="Newsletter", text="Check out our big sale!")
    fake_mailbox = _FakeMailBox([message])

    with (
        patch("app.jobs.email_ingest.get_settings", return_value=_FakeSettings()),
        patch("app.jobs.email_ingest.MailBox", return_value=fake_mailbox),
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=_chat_response("not valid JSON at all"))),
    ):
        await email_ingest.run()  # must not raise

    async with async_session() as session:
        assert list((await session.execute(select(Task))).scalars().all()) == []
        assert list((await session.execute(select(Appointment))).scalars().all()) == []

    # The message is still marked seen — a malformed reply isn't retried
    # forever, per email_ingest's module docstring.
    assert fake_mailbox.flagged == [("3", email_ingest.MailMessageFlags.SEEN, True)]
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_lmstudio_unreachable_creates_nothing_and_does_not_raise(db):
    message = _FakeMessage(uid="4", subject="Hi", text="Just saying hello.")
    fake_mailbox = _FakeMailBox([message])

    with (
        patch("app.jobs.email_ingest.get_settings", return_value=_FakeSettings()),
        patch("app.jobs.email_ingest.MailBox", return_value=fake_mailbox),
        patch(
            "httpx.AsyncClient.post",
            new=AsyncMock(side_effect=httpx.ConnectError("connection refused")),
        ),
    ):
        await email_ingest.run()  # must not raise

    async with async_session() as session:
        assert list((await session.execute(select(Task))).scalars().all()) == []

    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_no_unread_messages_creates_nothing(db):
    fake_mailbox = _FakeMailBox([])

    with (
        patch("app.jobs.email_ingest.get_settings", return_value=_FakeSettings()),
        patch("app.jobs.email_ingest.MailBox", return_value=fake_mailbox),
        patch("httpx.AsyncClient.post") as mock_post,
    ):
        await email_ingest.run()

    mock_post.assert_not_called()
    assert fake_mailbox.flagged == []
    assert state.last_status == "ok"


def test_parse_extracted_items_handles_prose_wrapped_json():
    raw = 'Sure, here you go:\n```json\n[{"type": "task", "title": "X"}]\n```'
    assert email_ingest.parse_extracted_items(raw) == [{"type": "task", "title": "X"}]


def test_parse_extracted_items_falls_back_to_empty_list_on_garbage():
    assert email_ingest.parse_extracted_items("not json") == []
    assert email_ingest.parse_extracted_items("") == []
    assert email_ingest.parse_extracted_items('{"not": "an array"}') == []


def test_parse_extracted_items_drops_non_object_entries():
    assert email_ingest.parse_extracted_items('["just a string", 42, {"type": "task", "title": "Y"}]') == [
        {"type": "task", "title": "Y"}
    ]
