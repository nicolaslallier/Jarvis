from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.config import Settings
from app.jobs import heartbeat, ingest_trigger, reminders


@dataclass(frozen=True)
class JobSpec:
    id: str
    func: Callable[[], Awaitable[None]]
    interval_minutes: int


def registered_jobs(settings: Settings) -> list[JobSpec]:
    return [
        JobSpec(id="heartbeat", func=heartbeat.run, interval_minutes=settings.batch_job_interval_minutes),
        JobSpec(
            id="ingest_trigger",
            func=ingest_trigger.run,
            interval_minutes=settings.batch_job_interval_minutes,
        ),
        JobSpec(
            id="reminders",
            func=reminders.run,
            interval_minutes=settings.reminder_job_interval_minutes,
        ),
    ]
