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

    # Base URL docker_ingest.py's DockerClient connects to. Points at the
    # docker-socket-proxy sidecar (docker-compose.yml) rather than the raw
    # /var/run/docker.sock mount, so batch itself no longer holds direct
    # root-equivalent access to the Docker daemon — see CLAUDE.md's
    # "Security note on ingest_trigger".
    docker_proxy_url: str = "tcp://docker-socket-proxy:2375"

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

    # IMAP mailbox app/jobs/email_ingest.py polls for unread messages, from
    # which it extracts candidate tasks/appointments as DRAFT
    # (status="pending_review" / pending_review=True) rows awaiting user
    # approval. Empty IMAP_HOST disables the job entirely — same
    # optional-integration, empty-means-off convention as ntfy_topic above.
    imap_host: str = ""
    imap_username: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"

    # How often (minutes) the email_ingest job polls IMAP_FOLDER for unread
    # messages. Same order of magnitude as reminder_job_interval_minutes —
    # frequent enough to feel responsive without hammering the mailbox.
    email_ingest_interval_minutes: int = 15

    # LM Studio chat model used by app/jobs/email_ingest.py to extract
    # candidate tasks/appointments from each unread email's text. Batch has
    # no chat.py of its own to delegate to (unlike backend), so this is its
    # own direct LM Studio call — see that module's docstring. Same
    # defaults as backend/app/config.py's LMSTUDIO_BASE_URL/LMSTUDIO_MODEL
    # so one LM Studio instance can serve both containers without extra
    # configuration, but a genuinely separate setting since batch and
    # backend are different processes/containers.
    lmstudio_base_url: str = "http://host.docker.internal:1234"
    lmstudio_model: str = "google/gemma-4-26b-a4b-qat"


@lru_cache
def get_settings() -> Settings:
    return Settings()
