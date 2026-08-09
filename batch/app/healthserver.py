"""Minimal stdlib HTTP server exposing GET /health for Docker's healthcheck.

Runs on a daemon thread so it doesn't block the asyncio event loop the
scheduler and DB/S3 calls run on.
"""

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from app.health_state import state

logger = logging.getLogger(__name__)


class _HealthRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (stdlib method name)
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return

        healthy = state.last_status in ("ok", "starting")
        body = json.dumps(
            {
                "status": state.last_status,
                "last_run_at": state.last_run_at.isoformat() if state.last_run_at else None,
            }
        ).encode()

        self.send_response(200 if healthy else 503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        logger.debug("healthserver: " + format, *args)


def start_health_server(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", port), _HealthRequestHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("health server listening on :%d", server.server_address[1])
    return server
