import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jarvis_shared.queue import INGEST_COMPLETED_QUEUE, INGEST_REQUESTED_QUEUE, consume, publish_message


def _make_fake_connection():
    """A mock aio_pika RobustConnection usable as `async with connection:`."""
    connection = MagicMock()
    connection.__aenter__ = AsyncMock(return_value=connection)
    connection.__aexit__ = AsyncMock(return_value=False)

    channel = MagicMock()
    channel.declare_queue = AsyncMock()
    channel.default_exchange.publish = AsyncMock()
    channel.set_qos = AsyncMock()
    connection.channel = AsyncMock(return_value=channel)

    return connection, channel


@pytest.mark.asyncio
async def test_publish_message_declares_durable_queue_and_publishes():
    connection, channel = _make_fake_connection()

    with patch("jarvis_shared.queue.aio_pika.connect_robust", new=AsyncMock(return_value=connection)):
        await publish_message("amqp://test/", INGEST_REQUESTED_QUEUE, {"file_id": 1})

    channel.declare_queue.assert_awaited_once_with(INGEST_REQUESTED_QUEUE, durable=True)
    channel.default_exchange.publish.assert_awaited_once()
    (message,), kwargs = channel.default_exchange.publish.call_args
    assert json.loads(message.body) == {"file_id": 1}
    assert kwargs["routing_key"] == INGEST_REQUESTED_QUEUE


class _FakeMessage:
    def __init__(self, payload: dict):
        self.body = json.dumps(payload).encode()

    def process(self):
        return _NullContext()


class _NullContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class _FakeQueueIterator:
    def __init__(self, messages):
        self._messages = list(messages)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)


@pytest.mark.asyncio
async def test_consume_calls_handler_for_each_message():
    connection, channel = _make_fake_connection()
    queue = MagicMock()
    queue.iterator = MagicMock(
        return_value=_FakeQueueIterator([_FakeMessage({"file_id": 1}), _FakeMessage({"file_id": 2})])
    )
    channel.declare_queue = AsyncMock(return_value=queue)

    received = []

    async def handler(payload):
        received.append(payload)

    with patch("jarvis_shared.queue.aio_pika.connect_robust", new=AsyncMock(return_value=connection)):
        await consume("amqp://test/", INGEST_COMPLETED_QUEUE, handler)

    assert received == [{"file_id": 1}, {"file_id": 2}]
    channel.set_qos.assert_awaited_once_with(prefetch_count=1)
