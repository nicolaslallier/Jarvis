import asyncio
import logging

import docker
from jarvis_shared.models import StoredFile
from sqlalchemy import select

from app.config import get_settings
from app.db import async_session
from app.docker_ingest import start_container
from app.health_state import state

logger = logging.getLogger(__name__)


async def _has_pending_files() -> bool:
    async with async_session() as session:
        result = await session.execute(
            select(StoredFile.id).where(StoredFile.ingested_at.is_(None)).limit(1)
        )
        return result.scalar_one_or_none() is not None


async def run() -> None:
    logger.info("ingest_trigger: checking for pending files")
    settings = get_settings()

    try:
        pending = await _has_pending_files()
    except Exception:
        logger.exception("ingest_trigger: failed to query pending files")
        state.record("error")
        return

    if not pending:
        logger.info("ingest_trigger: nothing to ingest")
        state.record("ok")
        return

    try:
        outcome = await asyncio.to_thread(start_container, settings.ingest_container_name)
    except docker.errors.NotFound:
        # Most likely `docker compose up` hasn't created the ingest service
        # yet — not a crash-worthy condition, just nothing to start.
        logger.error(
            "ingest_trigger: container %r not found", settings.ingest_container_name
        )
        state.record("error")
        return
    except docker.errors.APIError:
        logger.exception(
            "ingest_trigger: docker API error starting %r", settings.ingest_container_name
        )
        state.record("error")
        return

    if outcome == "already-running":
        logger.info("ingest_trigger: %r already running, skipping", settings.ingest_container_name)
    else:
        logger.info("ingest_trigger: started %r", settings.ingest_container_name)
    state.record("ok")
