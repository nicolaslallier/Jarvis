"""Docker-py helpers for starting/awaiting the `jarvis-ingest` container.

Sync (docker-py) — every function here must be called via asyncio.to_thread.
Talks to the Docker daemon over the socket mounted into this container (see
docker-compose.yml's `batch` service and CLAUDE.md's security note on what
that mount grants). Shared by the periodic poll job (ingest_trigger) and the
RabbitMQ-triggered consumer (ingest_consumer).
"""

import docker


def start_container(container_name: str) -> str:
    """Returns "started" or "already-running" so the caller can log without
    a second status check."""
    client = docker.DockerClient(base_url="unix://var/run/docker.sock")
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
    client = docker.DockerClient(base_url="unix://var/run/docker.sock")
    try:
        container = client.containers.get(container_name)
        result = container.wait()
        return result["StatusCode"]
    finally:
        client.close()
