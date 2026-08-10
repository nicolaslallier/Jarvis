"""Test fixtures and mocks.

The ``get_settings`` call in ``app.db`` reads ``.env`` at import time.  We
patch it **before** importing ``app.main`` so the test suite can run without
a real ``.env`` file or a live Postgres.
"""

import asyncio
from functools import cached_property

import pytest
from pytest import MonkeyPatch


class _FakeSettings:
    """Minimal stub so ``app.db`` and ``app.main`` can initialize without a real .env."""

    @cached_property
    def sqlalchemy_url(self) -> str:
        return "sqlite+aiosqlite:///:memory:"

    @property
    def cors_origin_list(self) -> list[str]:
        return ["*"]

    lmstudio_base_url = "http://lmstudio.test"
    lmstudio_model = "test-model"
    embedding_lmstudio_base_url = "http://lmstudio.test"
    embedding_lmstudio_model = "test-embedding-model"
    rag_top_k = 4
    memory_top_k = 6
    search_chunk_top_k = 10
    search_memory_top_k = 10
    calendar_upcoming_days = 7
    timezone = "America/Toronto"
    chat_history_max_messages = 40
    otel_exporter_otlp_endpoint = ""
    otel_service_name = "jarvis-api-test"
    minio_endpoint = "http://minio.test:9000"
    minio_access_key = "test-access-key"
    minio_secret_key = "test-secret-key"
    minio_bucket = "jarvis-test"
    rabbitmq_url = "amqp://guest:guest@rabbitmq.test:5672/"


# Patch before any app import — fixtures don't run during module load.
_monkey = MonkeyPatch()
_monkey.setattr("app.config.get_settings", lambda: _FakeSettings())

# Now safe to import the FastAPI app under test.
from httpx import ASGITransport, AsyncClient

from app.db import Base, engine
from app.main import app, lifespan


async def _fake_consume(rabbitmq_url, queue_name, handler) -> None:
    """Stand-in for jarvis_shared.queue.consume — blocks (like the real
    consumer would) without touching a real broker, until cancelled on
    lifespan shutdown."""
    await asyncio.Event().wait()


# The lifespan starts a background RabbitMQ consumer task; tests never have
# a live broker, so replace it with a no-op that just blocks until cancelled.
_monkey.setattr("app.main.consume", _fake_consume)


def teardown_module() -> None:
    _monkey.undo()


@pytest.fixture
async def client() -> AsyncClient:
    # ``engine`` is a module-level singleton, so its connection pool would
    # otherwise carry the same in-memory SQLite database (and its rows)
    # across tests. Dispose it first so ``lifespan``'s create_all opens a
    # brand new, empty in-memory database for this test.
    await engine.dispose()
    async with lifespan(app):
        # lifespan's own create_all only creates the pre-Alembic baseline
        # tables (see main.py's _ALEMBIC_MANAGED_TABLE_NAMES) — there's no
        # live Alembic run against this in-memory SQLite DB, so tests that
        # exercise an Alembic-managed table (e.g. appointments) need it
        # created too. create_all is idempotent per table (checkfirst), so
        # this only adds the tables lifespan skipped.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
