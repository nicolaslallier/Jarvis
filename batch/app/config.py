from functools import lru_cache

from jarvis_shared.config import SharedSettings


class Settings(SharedSettings):
    otel_service_name: str = "jarvis-batch"

    # How often (minutes) the internal scheduler runs registered jobs.
    batch_job_interval_minutes: int = 15

    # Port the stdlib health server listens on inside the container.
    batch_health_port: int = 8080

    # Fixed name of the ingest container (see docker-compose.yml's
    # `container_name: jarvis-ingest`) that ingest_trigger starts via the
    # Docker socket when there are unprocessed files.
    ingest_container_name: str = "jarvis-ingest"

    # ntfy.sh (or a self-hosted ntfy instance) base URL and topic used by
    # app/jobs/reminders.py to push overdue-task/tomorrow-appointment
    # notifications. Empty topic disables reminders entirely — ntfy is
    # optional, not a hard dependency (see app/notifier.py's send_ntfy).
    ntfy_url: str = "https://ntfy.sh"
    ntfy_topic: str = ""

    # How often (minutes) the reminders job runs. Deliberately less frequent
    # than the default batch_job_interval_minutes (15) to avoid notification
    # spam, since reminders.py dedupes per local calendar day anyway.
    reminder_job_interval_minutes: int = 30

    # IANA timezone name used to compute "tomorrow" (for appointment
    # reminders) in local time instead of UTC — mirrors backend/app/config.py's
    # own `timezone` field/reasoning: relative-date resolution (here, which
    # calendar day an appointment's start_time falls on) needs a local
    # reference point, not naive UTC-day math.
    timezone: str = "America/Toronto"


@lru_cache
def get_settings() -> Settings:
    return Settings()
