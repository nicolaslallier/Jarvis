from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.config import Settings
from app.jobs import (
    email_ingest,
    heartbeat,
    important_dates,
    ingest_trigger,
    proactive_suggestions,
    reminders,
    upcoming_bills,
    weekly_review,
)


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
        JobSpec(
            id="upcoming_bills",
            func=upcoming_bills.run,
            # Same cadence as reminders — no urgency finer-grained than
            # this buys, since both dedupe per local calendar day anyway.
            interval_minutes=settings.reminder_job_interval_minutes,
        ),
        JobSpec(
            id="important_dates",
            func=important_dates.run,
            # Same cadence as reminders/upcoming_bills — contact dates
            # change rarely and the job dedupes per local calendar day
            # anyway, so nothing finer-grained is needed.
            interval_minutes=settings.reminder_job_interval_minutes,
        ),
        JobSpec(
            id="email_ingest",
            func=email_ingest.run,
            interval_minutes=settings.email_ingest_interval_minutes,
        ),
        JobSpec(
            id="proactive_suggestions",
            func=proactive_suggestions.run,
            # Same cadence as reminders/upcoming_bills/important_dates —
            # both checks dedupe (per local day for conflicts, per local
            # week for stale tasks) so nothing finer-grained is needed.
            interval_minutes=settings.reminder_job_interval_minutes,
        ),
        JobSpec(
            id="weekly_review",
            func=weekly_review.run,
            # A fairly frequent tick (60 min) is fine even though the
            # summary only ever sends once a week: weekly_review.run()
            # itself gates on being Sunday evening (local time) before
            # doing any work, and the notifications_sent dedup table
            # (kind="weekly_review") stops a second send within the same
            # Sunday-evening window if the interval doesn't line up
            # exactly with when "evening" starts.
            interval_minutes=60,
        ),
    ]
