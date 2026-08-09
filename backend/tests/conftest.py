"""Test fixtures and mocks.

The ``get_settings`` call in ``app.db`` reads ``.env`` at import time.  We
patch it **before** importing ``app.main`` so the test suite can run without
a real ``.env`` file or a live Postgres.
"""

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
    otel_exporter_otlp_endpoint = ""
    otel_service_name = "jarvis-api-test"


# Patch before any app import — fixtures don't run during module load.
_monkey = MonkeyPatch()
_monkey.setattr("app.config.get_settings", lambda: _FakeSettings())

# Now safe to import the FastAPI app under test.
from httpx import ASGITransport, AsyncClient

from app.db import engine
from app.main import app, lifespan


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
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
