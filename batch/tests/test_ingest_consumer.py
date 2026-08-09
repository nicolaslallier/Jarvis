from unittest.mock import AsyncMock, patch

import docker
import pytest

from app import ingest_consumer


class _FakeContainer:
    def __init__(self, status: str, exit_code: int = 0):
        self.status = status
        self.start_called = False
        self._exit_code = exit_code

    def start(self) -> None:
        self.start_called = True
        self.status = "running"

    def wait(self) -> dict:
        return {"StatusCode": self._exit_code}


class _FakeContainers:
    def __init__(self, container: _FakeContainer | None):
        self._container = container

    def get(self, name: str) -> _FakeContainer:
        if self._container is None:
            raise docker.errors.NotFound("no such container")
        return self._container


class _FakeDockerClient:
    def __init__(self, container: _FakeContainer | None):
        self.containers = _FakeContainers(container)

    def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_handle_ingest_requested_publishes_completion_on_success():
    fake_container = _FakeContainer(status="exited", exit_code=0)

    with (
        patch("docker.DockerClient", return_value=_FakeDockerClient(fake_container)),
        patch("app.ingest_consumer.publish_message", new_callable=AsyncMock) as mock_publish,
    ):
        await ingest_consumer.handle_ingest_requested({"file_id": 42})

    assert fake_container.start_called is True
    mock_publish.assert_awaited_once()
    args, _ = mock_publish.call_args
    _rabbitmq_url, queue_name, payload = args
    assert queue_name == "jarvis.ingest.completed"
    assert payload["file_id"] == 42
    assert payload["exit_code"] == 0
    assert "error" not in payload


@pytest.mark.asyncio
async def test_handle_ingest_requested_container_not_found_still_publishes():
    with (
        patch("docker.DockerClient", return_value=_FakeDockerClient(None)),
        patch("app.ingest_consumer.publish_message", new_callable=AsyncMock) as mock_publish,
    ):
        await ingest_consumer.handle_ingest_requested({"file_id": 7})

    mock_publish.assert_awaited_once()
    args, _ = mock_publish.call_args
    _rabbitmq_url, queue_name, payload = args
    assert queue_name == "jarvis.ingest.completed"
    assert payload["file_id"] == 7
    assert payload["exit_code"] is None
    assert payload["error"] == "container not found"
