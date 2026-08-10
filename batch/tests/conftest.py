"""Test fixtures and mocks.

Patches app.config.get_settings before importing anything under app/ so the
test suite runs without a real .env, live Postgres, or live MinIO.
"""

from functools import cached_property

from pytest import MonkeyPatch


class _FakeSettings:
    @cached_property
    def sqlalchemy_url(self) -> str:
        return "sqlite+aiosqlite:///:memory:"

    otel_exporter_otlp_endpoint = ""
    otel_service_name = "jarvis-batch-test"
    minio_endpoint = "http://minio.test:9000"
    minio_access_key = "test-access-key"
    minio_secret_key = "test-secret-key"
    minio_bucket = "jarvis-test"
    batch_job_interval_minutes = 15
    batch_health_port = 0  # OS-assigned free port for tests
    ingest_container_name = "jarvis-ingest-test"
    docker_proxy_url = "tcp://docker-socket-proxy.test:2375"
    rabbitmq_url = "amqp://guest:guest@rabbitmq.test:5672/"


_monkey = MonkeyPatch()
_monkey.setattr("app.config.get_settings", lambda: _FakeSettings())


def teardown_module() -> None:
    _monkey.undo()
