"""Docker-py helpers for starting/awaiting the `jarvis-ingest` container.

Sync (docker-py) — every function here must be called via asyncio.to_thread.
Talks to the Docker daemon via the docker-socket-proxy sidecar (see
docker-compose.yml's `docker-socket-proxy`/`batch` services and CLAUDE.md's
security note on what that scopes batch down to). Shared by the periodic
poll job (ingest_trigger) and the RabbitMQ-triggered consumer
(ingest_consumer).
"""

import docker

from app.config import get_settings


def start_container(container_name: str) -> str:
    """Returns "started" or "already-running" so the caller can log without
    a second status check."""
    client = docker.DockerClient(base_url=get_settings().docker_proxy_url)
    try:
        container = client.containers.get(container_name)
        if container.status == "running":
            return "already-running"
        container.start()
        return "started"
    finally:
        client.close()


def wait_container(container_name: str) -> int:
    """Blocks until the container exits, returns its exit code."""
    client = docker.DockerClient(base_url=get_settings().docker_proxy_url)
    try:
        container = client.containers.get(container_name)
        result = container.wait()
        return result["StatusCode"]
    finally:
        client.close()
