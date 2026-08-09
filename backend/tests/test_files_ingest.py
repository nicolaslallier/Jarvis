from unittest.mock import AsyncMock, patch

import pytest
from botocore.exceptions import ClientError


@pytest.fixture(autouse=True)
def _mock_ingest_publish():
    """upload_file() now also fires a publish_message() call (the auto-ingest
    trigger under test below). Stub it out by default so tests that only
    care about the manual POST /files/{id}/ingest endpoint aren't tripped up
    by the upload step's own publish call; a test can still override this
    with its own ``patch(...)`` for the duration of its own ``with`` block
    (e.g. to assert on the upload-time call specifically, or simulate a
    broker outage).
    """
    with patch("app.routers.files.publish_message", new_callable=AsyncMock) as mock_publish:
        yield mock_publish


class _FakeS3Client:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def head_bucket(self, Bucket):
        pass

    def create_bucket(self, Bucket):
        pass

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "GetObject")
        return {"Body": _FakeBody(self.objects[Key])}

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)


class _FakeBody:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


@pytest.mark.asyncio
async def test_request_ingest_publishes_and_returns_202(client):
    fake_client = _FakeS3Client()
    with patch("jarvis_shared.storage.boto3.client", return_value=fake_client):
        upload_response = await client.post(
            "/files", files={"file": ("hello.txt", b"hello world", "text/plain")}
        )
    file_id = upload_response.json()["id"]

    with patch("app.routers.files.publish_message", new_callable=AsyncMock) as mock_publish:
        response = await client.post(f"/files/{file_id}/ingest")

    assert response.status_code == 202
    assert response.json() == {"status": "queued", "file_id": file_id}
    mock_publish.assert_awaited_once()
    args, _ = mock_publish.call_args
    rabbitmq_url, queue_name, payload = args
    assert queue_name == "jarvis.ingest.requested"
    assert payload["file_id"] == file_id
    assert "requested_at" in payload


@pytest.mark.asyncio
async def test_request_ingest_rabbitmq_unreachable_returns_502(client):
    fake_client = _FakeS3Client()
    with patch("jarvis_shared.storage.boto3.client", return_value=fake_client):
        upload_response = await client.post(
            "/files", files={"file": ("hello.txt", b"hello world", "text/plain")}
        )
    file_id = upload_response.json()["id"]

    with patch(
        "app.routers.files.publish_message",
        new_callable=AsyncMock,
        side_effect=ConnectionRefusedError("refused"),
    ):
        response = await client.post(f"/files/{file_id}/ingest")

    assert response.status_code == 502
    assert "RabbitMQ" in response.json()["detail"]


@pytest.mark.asyncio
async def test_request_ingest_not_found(client):
    with patch("app.routers.files.publish_message", new_callable=AsyncMock) as mock_publish:
        response = await client.post("/files/999999/ingest")

    assert response.status_code == 404
    assert response.json()["detail"] == "file not found"
    mock_publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_file_auto_publishes_ingest_request(client, _mock_ingest_publish):
    """POST /files should trigger ingestion automatically, without the
    caller needing to separately hit POST /files/{id}/ingest."""
    fake_client = _FakeS3Client()
    with patch("jarvis_shared.storage.boto3.client", return_value=fake_client):
        upload_response = await client.post(
            "/files", files={"file": ("hello.txt", b"hello world", "text/plain")}
        )

    assert upload_response.status_code == 200
    file_id = upload_response.json()["id"]

    _mock_ingest_publish.assert_awaited_once()
    args, _ = _mock_ingest_publish.call_args
    rabbitmq_url, queue_name, payload = args
    assert queue_name == "jarvis.ingest.requested"
    assert payload["file_id"] == file_id
    assert "requested_at" in payload


@pytest.mark.asyncio
async def test_upload_file_still_succeeds_when_rabbitmq_unreachable(client):
    """The auto-ingest publish is best-effort: the file is already stored in
    MinIO and committed to Postgres by the time we try to publish, so a
    broker outage must not fail the upload — the user can still retrigger
    ingestion later via the manual "Ingérer" button/endpoint."""
    fake_client = _FakeS3Client()
    with (
        patch("jarvis_shared.storage.boto3.client", return_value=fake_client),
        patch(
            "app.routers.files.publish_message",
            new_callable=AsyncMock,
            side_effect=ConnectionRefusedError("refused"),
        ),
    ):
        upload_response = await client.post(
            "/files", files={"file": ("hello.txt", b"hello world", "text/plain")}
        )

    assert upload_response.status_code == 200
    body = upload_response.json()
    assert body["filename"] == "hello.txt"

    list_response = await client.get("/files")
    assert list_response.status_code == 200
    assert [f["filename"] for f in list_response.json()] == ["hello.txt"]
