from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.ws_manager import manager

router = APIRouter()


@router.websocket("/ws/ingest-status")
async def ingest_status(websocket: WebSocket) -> None:
    await websocket.accept()
    manager.connect(websocket)
    try:
        while True:
            # No inbound messages are expected; this just blocks until the
            # client disconnects so we can deregister it.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)
