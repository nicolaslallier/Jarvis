"""Broadcasts ingest-completion messages to connected browser clients.

Populated by the RabbitMQ consumer started in main.py's lifespan (consuming
jarvis.ingest.completed) and read by routers/ingest_status.py's WebSocket
route.
"""

import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    def connect(self, websocket: WebSocket) -> None:
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        for websocket in list(self._connections):
            try:
                await websocket.send_json(payload)
            except Exception:
                logger.exception("ws_manager: failed to send to a client, dropping it")
                self._connections.discard(websocket)


manager = ConnectionManager()
