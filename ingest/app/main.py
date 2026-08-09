import asyncio
import logging
import sys

from app.config import get_settings
from app.db import async_session
from app.pipeline import run_pipeline
from app.telemetry import setup_telemetry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def main() -> int:
    settings = get_settings()
    setup_telemetry(
        endpoint=settings.otel_exporter_otlp_endpoint or None,
        service_name=settings.otel_service_name,
    )

    async with async_session() as session:
        succeeded, failed = await run_pipeline(session, settings)

    logger.info("ingest: pass complete succeeded=%d failed=%d", succeeded, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
