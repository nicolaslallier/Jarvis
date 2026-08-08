import pytest
from unittest.mock import AsyncMock, patch

from app.routers.health import router


@pytest.mark.asyncio
async def test_health(client):
    """Health endpoint returns 200 when the database is reachable.

    The real check_connection() would require a live Postgres.  We mock it
    so the test runs in CI without a database.
    """
    with patch("app.routers.health.check_connection", new_callable=AsyncMock):
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
