from datetime import UTC, datetime
from unittest.mock import patch

import pytest

# 2026-08-09T16:00:00Z is 2026-08-09T12:00:00-04:00 in America/Toronto (EDT,
# UTC-4 in August), so local "today" runs from 2026-08-09T04:00:00Z
# (inclusive) to 2026-08-10T04:00:00Z (exclusive).
FROZEN_UTC_NOON = datetime(2026, 8, 9, 16, 0, 0, tzinfo=UTC)


class _FakeSummaryResponse:
    def __init__(self, status_code: int, content: str | None = None):
        self.status_code = status_code
        self._content = content

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self._content}}]}


class _FakeSummaryClient:
    """Stand-in for the httpx.AsyncClient app/briefing_service.py opens for
    its one-shot, non-streaming summary call."""

    def __init__(self, response: _FakeSummaryResponse | None = None, error: Exception | None = None):
        self._response = response
        self._error = error
        self.post_calls: list[tuple[str, dict]] = []

    async def __aenter__(self) -> "_FakeSummaryClient":
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs.get("json")))
        if self._error is not None:
            raise self._error
        return self._response


def _frozen_datetime(mock_datetime) -> None:
    mock_datetime.now.return_value = FROZEN_UTC_NOON


@pytest.mark.asyncio
async def test_appointments_today_included_tomorrow_excluded(client):
    await client.post(
        "/calendar/appointments",
        json={
            "title": "Today meeting",
            "start_time": "2026-08-09T15:00:00+00:00",
            "end_time": "2026-08-09T16:00:00+00:00",
        },
    )
    await client.post(
        "/calendar/appointments",
        json={
            "title": "Tomorrow meeting",
            "start_time": "2026-08-10T15:00:00+00:00",
            "end_time": "2026-08-10T16:00:00+00:00",
        },
    )

    fake_client = _FakeSummaryClient(response=_FakeSummaryResponse(200, "Bonjour Nicolas"))
    with (
        patch("app.briefing_service.datetime") as mock_datetime,
        patch("app.briefing_service.httpx.AsyncClient", return_value=fake_client),
    ):
        _frozen_datetime(mock_datetime)
        response = await client.get("/briefing")

    assert response.status_code == 200
    body = response.json()
    assert body["date"] == "2026-08-09"
    assert [a["title"] for a in body["appointments"]] == ["Today meeting"]


@pytest.mark.asyncio
async def test_tasks_bucketed_due_today_overdue_and_future(client):
    await client.post("/tasks", json={"title": "Due today", "due_at": "2026-08-09T20:00:00Z"})
    await client.post("/tasks", json={"title": "Overdue", "due_at": "2026-08-08T12:00:00Z"})
    await client.post("/tasks", json={"title": "Future", "due_at": "2026-08-15T12:00:00Z"})

    fake_client = _FakeSummaryClient(response=_FakeSummaryResponse(200, "Bonjour Nicolas"))
    with (
        patch("app.briefing_service.datetime") as mock_datetime,
        patch("app.briefing_service.httpx.AsyncClient", return_value=fake_client),
    ):
        _frozen_datetime(mock_datetime)
        response = await client.get("/briefing")

    assert response.status_code == 200
    body = response.json()
    assert [t["title"] for t in body["due_tasks"]] == ["Due today"]
    assert [t["title"] for t in body["overdue_tasks"]] == ["Overdue"]
    bucketed_titles = {t["title"] for t in body["due_tasks"] + body["overdue_tasks"]}
    assert "Future" not in bucketed_titles


@pytest.mark.asyncio
async def test_done_and_cancelled_tasks_excluded_even_if_overdue(client):
    done = await client.post("/tasks", json={"title": "Done overdue", "due_at": "2026-08-01T12:00:00Z"})
    await client.put(f"/tasks/{done.json()['id']}", json={"status": "done"})
    cancelled = await client.post(
        "/tasks", json={"title": "Cancelled overdue", "due_at": "2026-08-02T12:00:00Z"}
    )
    await client.put(f"/tasks/{cancelled.json()['id']}", json={"status": "cancelled"})

    with patch("app.briefing_service.datetime") as mock_datetime:
        _frozen_datetime(mock_datetime)
        response = await client.get("/briefing")

    assert response.status_code == 200
    body = response.json()
    assert body["due_tasks"] == []
    assert body["overdue_tasks"] == []


@pytest.mark.asyncio
async def test_llm_summary_failure_still_returns_200_with_null_summary(client):
    await client.post(
        "/calendar/appointments",
        json={
            "title": "Today meeting",
            "start_time": "2026-08-09T15:00:00+00:00",
            "end_time": "2026-08-09T16:00:00+00:00",
        },
    )

    fake_client = _FakeSummaryClient(response=_FakeSummaryResponse(500))
    with (
        patch("app.briefing_service.datetime") as mock_datetime,
        patch("app.briefing_service.httpx.AsyncClient", return_value=fake_client),
    ):
        _frozen_datetime(mock_datetime)
        response = await client.get("/briefing")

    assert response.status_code == 200
    assert response.json()["summary"] is None


@pytest.mark.asyncio
async def test_llm_summary_network_error_still_returns_200_with_null_summary(client):
    await client.post("/tasks", json={"title": "Due today", "due_at": "2026-08-09T20:00:00Z"})

    fake_client = _FakeSummaryClient(error=RuntimeError("connection refused"))
    with (
        patch("app.briefing_service.datetime") as mock_datetime,
        patch("app.briefing_service.httpx.AsyncClient", return_value=fake_client),
    ):
        _frozen_datetime(mock_datetime)
        response = await client.get("/briefing")

    assert response.status_code == 200
    assert response.json()["summary"] is None


@pytest.mark.asyncio
async def test_empty_day_skips_llm_call(client):
    fake_client = _FakeSummaryClient(response=_FakeSummaryResponse(200, "should not be used"))
    with (
        patch("app.briefing_service.datetime") as mock_datetime,
        patch("app.briefing_service.httpx.AsyncClient", return_value=fake_client) as mock_async_client,
    ):
        _frozen_datetime(mock_datetime)
        response = await client.get("/briefing")

    assert response.status_code == 200
    body = response.json()
    assert body["appointments"] == []
    assert body["due_tasks"] == []
    assert body["overdue_tasks"] == []
    assert body["summary"] is not None
    mock_async_client.assert_not_called()
