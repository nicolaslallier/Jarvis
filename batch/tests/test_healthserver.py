import json
import urllib.error
import urllib.request

from app.health_state import state
from app.healthserver import start_health_server


def test_health_endpoint_ok_and_error():
    server = start_health_server(0)
    port = server.server_address[1]
    try:
        state.record("ok")
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health") as resp:
            assert resp.status == 200
            body = json.loads(resp.read())
            assert body["status"] == "ok"

        state.record("error")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health")
            assert False, "expected HTTPError for 503 response"
        except urllib.error.HTTPError as exc:
            assert exc.code == 503
    finally:
        server.shutdown()
