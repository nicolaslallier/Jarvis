"""RabbitMQ consumer for on-demand ingest requests from the backend.

Handles jarvis.ingest.requested messages (published by
backend/app/routers/files.py's POST /files/{id}/ingest): starts the
jarvis-ingest container, blocks until it exits, then publishes a
jarvis.ingest.completed message so the backend can relay it to the browser
over WebSocket. This is independent of ingest_trigger's periodic poll job,
which stays in place as a fallback.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import docker
from jarvis_shared.queue import INGEST_COMPLETED_QUEUE, publish_message

from app.config import get_settings
from app.docker_ingest import start_container, wait_container

logger = logging.getLogger(__name__)


async def handle_ingest_requested(payload: dict[str, Any]) -> None:
    settings = get_settings()
    file_id = payload.get("file_id")
    logger.info("ingest_consumer: request received for file_id=%s", file_id)

    exit_code: int | None = None
    error: str | None = None
    try:
        await asyncio.to_thread(start_container, settings.ingest_container_name)
        exit_code = await asyncio.to_thread(wait_container, settings.ingest_container_name)
    except docker.errors.NotFound:
        logger.error(
            "ingest_consumer: container %r not found", settings.ingest_container_name
        )
        error = "container not found"
    except docker.errors.APIError:
        logger.exception(
            "ingest_consumer: docker API error for %r", settings.ingest_container_name
        )
        error = "docker API error"

    completion: dict[str, Any] = {
        "file_id": file_id,
        "exit_code": exit_code,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    if error is not None:
        completion["error"] = error

    await publish_message(settings.rabbitmq_url, INGEST_COMPLETED_QUEUE, completion)
    logger.info("ingest_consumer: published completion for file_id=%s exit_code=%s", file_id, exit_code)
