import asyncio
import logging

from botocore.exceptions import BotoCoreError, ClientError

from app.config import get_settings
from app.db import check_connection
from app.health_state import state
from app.storage import count_objects

logger = logging.getLogger(__name__)


async def run() -> None:
    logger.info("batch heartbeat: starting")
    settings = get_settings()

    try:
        await check_connection()
        db_status = "up"
    except Exception:
        logger.exception("batch heartbeat: database check failed")
        state.record("error")
        return

    try:
        object_count = await asyncio.to_thread(count_objects, settings)
    except (BotoCoreError, ClientError):
        logger.exception("batch heartbeat: minio check failed")
        state.record("error")
        return

    logger.info("batch heartbeat: database=%s minio_objects=%s", db_status, object_count)
    state.record("ok")
