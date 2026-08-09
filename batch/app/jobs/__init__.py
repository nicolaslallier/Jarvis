from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.config import Settings
from app.jobs import heartbeat


@dataclass(frozen=True)
class JobSpec:
    id: str
    func: Callable[[], Awaitable[None]]
    interval_minutes: int


def registered_jobs(settings: Settings) -> list[JobSpec]:
    return [
        JobSpec(id="heartbeat", func=heartbeat.run, interval_minutes=settings.batch_job_interval_minutes),
    ]
