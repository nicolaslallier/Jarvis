from unittest.mock import patch

import docker
import pytest
from jarvis_shared.db import Base
from jarvis_shared.models import StoredFile

from app.db import async_session, engine
from app.health_state import state
from app.jobs import ingest_trigger


@pytest.fixture
async def db():
    await engine.dispose()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


async def _add_pending_file() -> None:
    async with async_session() as session:
        session.add(StoredFile(filename="a.txt", content_type="text/plain", size=1, object_key="k1"))
        await session.commit()


class _FakeContainer:
    def __init__(self, status: str):
        self.status = status
        self.start_called = False

    def start(self) -> None:
        self.start_called = True


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
async def test_no_pending_files_does_not_touch_docker(db):
    with patch("docker.DockerClient") as mock_docker_client:
        await ingest_trigger.run()

    mock_docker_client.assert_not_called()
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_pending_files_starts_a_stopped_container(db):
    await _add_pending_file()
    fake_container = _FakeContainer(status="exited")

    with patch("docker.DockerClient", return_value=_FakeDockerClient(fake_container)):
        await ingest_trigger.run()

    assert fake_container.start_called is True
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_pending_files_skips_an_already_running_container(db):
    await _add_pending_file()
    fake_container = _FakeContainer(status="running")

    with patch("docker.DockerClient", return_value=_FakeDockerClient(fake_container)):
        await ingest_trigger.run()

    assert fake_container.start_called is False
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_pending_files_container_not_found_records_error_without_crashing(db):
    await _add_pending_file()

    with patch("docker.DockerClient", return_value=_FakeDockerClient(None)):
        await ingest_trigger.run()

    assert state.last_status == "error"
