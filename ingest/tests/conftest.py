"""Test fixtures and mocks.

Patches app.config.get_settings before importing anything under app/ so the
test suite runs without a real .env, live Postgres, live MinIO, or live LM
Studio.
"""

from functools import cached_property

from pytest import MonkeyPatch


class _FakeSettings:
    @cached_property
    def sqlalchemy_url(self) -> str:
        return "sqlite+aiosqlite:///:memory:"

    otel_exporter_otlp_endpoint = ""
    otel_service_name = "jarvis-ingest-test"
    minio_endpoint = "http://minio.test:9000"
    minio_access_key = "test-access-key"
    minio_secret_key = "test-secret-key"
    minio_bucket = "jarvis-test"
    embedding_lmstudio_base_url = "http://lmstudio.test"
    embedding_lmstudio_model = "test-embedding-model"
    chunk_size_chars = 20
    chunk_overlap_chars = 5


_monkey = MonkeyPatch()
_monkey.setattr("app.config.get_settings", lambda: _FakeSettings())


def teardown_module() -> None:
    _monkey.undo()
