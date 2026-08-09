import asyncio
import logging
import signal
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.healthserver import start_health_server
from app.jobs import registered_jobs
from app.telemetry import setup_telemetry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()


async def main() -> None:
    setup_telemetry(
        endpoint=settings.otel_exporter_otlp_endpoint or None,
        service_name=settings.otel_service_name,
    )

    health_server = start_health_server(settings.batch_health_port)

    jobs = registered_jobs(settings)
    scheduler = AsyncIOScheduler()
    for job in jobs:
        scheduler.add_job(
            job.func,
            trigger=IntervalTrigger(minutes=job.interval_minutes),
            id=job.id,
            next_run_time=datetime.now(),  # run once immediately on startup
            max_instances=1,  # don't overlap runs if a job is slow
            coalesce=True,
        )
    scheduler.start()
    logger.info("jarvis-batch scheduler started with %d job(s)", len(jobs))

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    await stop_event.wait()
    logger.info("shutting down")
    scheduler.shutdown(wait=False)
    health_server.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
