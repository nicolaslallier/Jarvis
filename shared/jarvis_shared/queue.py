"""Thin aio-pika wrapper for the queues shared between backend/batch.

Mirrors how storage.py wraps boto3: callers pass a RabbitMQ URL (from
SharedSettings.rabbitmq_url) and a queue name, this module handles the
connection/channel/queue plumbing.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aio_pika

logger = logging.getLogger(__name__)

INGEST_REQUESTED_QUEUE = "jarvis.ingest.requested"
INGEST_COMPLETED_QUEUE = "jarvis.ingest.completed"


async def publish_message(rabbitmq_url: str, queue_name: str, payload: dict[str, Any]) -> None:
    """Publish one JSON message to `queue_name` via the default exchange.

    Opens and closes its own connection — fine for infrequent, user-triggered
    events; a persistent publisher connection isn't worth the complexity here.
    """
    connection = await aio_pika.connect_robust(rabbitmq_url)
    async with connection:
        channel = await connection.channel()
        await channel.declare_queue(queue_name, durable=True)
        await channel.default_exchange.publish(
            aio_pika.Message(
                body=json.dumps(payload).encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=queue_name,
        )


async def consume(
    rabbitmq_url: str,
    queue_name: str,
    handler: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    """Consume `queue_name` forever, awaiting `handler(payload)` per message.

    Intended to run as a long-lived background asyncio task. Uses
    connect_robust so transient broker/network drops reconnect on their own.
    A message is acked only if the handler succeeds; a raised exception nacks
    and requeues it. Cancel the owning task to stop consuming.
    """
    connection = await aio_pika.connect_robust(rabbitmq_url)
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=1)
        queue = await channel.declare_queue(queue_name, durable=True)

        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process():
                    payload = json.loads(message.body)
                    await handler(payload)
