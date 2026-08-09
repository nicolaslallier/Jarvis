from unittest.mock import AsyncMock, patch

import pytest
from botocore.exceptions import ClientError


@pytest.fixture(autouse=True)
def _mock_ingest_publish():
    """upload_file() now fires an auto-ingest publish_message() call on every
    upload (see test_files_ingest.py for dedicated coverage of that
    behavior). Stub it out by default here so these MinIO/folder-focused
    tests don't depend on a live RabbitMQ; a test can still override this
    with its own ``patch(...)`` for the duration of its own ``with`` block.
    """
    with patch("app.routers.files.publish_message", new_callable=AsyncMock) as mock_publish:
        yield mock_publish


class _FakeS3Client:
    """Stand-in for the boto3 S3 client the files router opens to talk to MinIO."""

    def __init__(self, error=None):
        self._error = error
        self.objects: dict[str, bytes] = {}

    def head_bucket(self, Bucket):
        pass

    def create_bucket(self, Bucket):
        pass

    def put_object(self, Bucket, Key, Body, ContentType=None):
        if self._error is not None:
            raise self._error
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        if self._error is not None:
            raise self._error
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "GetObject")
        return {"Body": _FakeBody(self.objects[Key])}

    def delete_object(self, Bucket, Key):
        if self._error is not None:
            raise self._error
        self.objects.pop(Key, None)


class _FakeBody:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


@pytest.mark.asyncio
async def test_upload_and_list_files(client):
    fake_client = _FakeS3Client()
    with patch("jarvis_shared.storage.boto3.client", return_value=fake_client):
        response = await client.post(
            "/files", files={"file": ("hello.txt", b"hello world", "text/plain")}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "hello.txt"
    assert body["content_type"] == "text/plain"
    assert body["size"] == len(b"hello world")
    assert "id" in body

    list_response = await client.get("/files")
    assert list_response.status_code == 200
    assert [f["filename"] for f in list_response.json()] == ["hello.txt"]


@pytest.mark.asyncio
async def test_download_file(client):
    fake_client = _FakeS3Client()
    with patch("jarvis_shared.storage.boto3.client", return_value=fake_client):
        upload_response = await client.post(
            "/files", files={"file": ("hello.txt", b"hello world", "text/plain")}
        )
        file_id = upload_response.json()["id"]

        response = await client.get(f"/files/{file_id}/download")

    assert response.status_code == 200
    assert response.content == b"hello world"
    assert response.headers["content-type"].startswith("text/plain")
    assert 'filename="hello.txt"' in response.headers["content-disposition"]


@pytest.mark.asyncio
async def test_download_file_not_found(client):
    response = await client.get("/files/999999/download")
    assert response.status_code == 404
    assert response.json()["detail"] == "file not found"


@pytest.mark.asyncio
async def test_delete_file(client):
    fake_client = _FakeS3Client()
    with patch("jarvis_shared.storage.boto3.client", return_value=fake_client):
        upload_response = await client.post(
            "/files", files={"file": ("hello.txt", b"hello world", "text/plain")}
        )
        file_id = upload_response.json()["id"]

        response = await client.delete(f"/files/{file_id}")
        assert response.status_code == 204

        list_response = await client.get("/files")
    assert list_response.json() == []


@pytest.mark.asyncio
async def test_delete_file_not_found(client):
    response = await client.delete("/files/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "file not found"


@pytest.mark.asyncio
async def test_upload_file_minio_unreachable(client):
    fake_client = _FakeS3Client(error=ClientError({"Error": {"Code": "500", "Message": "boom"}}, "PutObject"))
    with patch("jarvis_shared.storage.boto3.client", return_value=fake_client):
        response = await client.post(
            "/files", files={"file": ("hello.txt", b"hello world", "text/plain")}
        )

    assert response.status_code == 502
    assert "Could not reach MinIO" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_and_list_folders(client):
    root_response = await client.post("/folders", json={"name": "Documents"})
    assert root_response.status_code == 200
    root = root_response.json()
    assert root["name"] == "Documents"
    assert root["parent_id"] is None

    child_response = await client.post(
        "/folders", json={"name": "Invoices", "parent_id": root["id"]}
    )
    assert child_response.status_code == 200
    child = child_response.json()
    assert child["parent_id"] == root["id"]

    root_list = await client.get("/folders")
    assert [f["name"] for f in root_list.json()] == ["Documents"]

    child_list = await client.get(f"/folders?parent_id={root['id']}")
    assert [f["name"] for f in child_list.json()] == ["Invoices"]


@pytest.mark.asyncio
async def test_create_folder_with_missing_parent(client):
    response = await client.post("/folders", json={"name": "Orphan", "parent_id": 999999})
    assert response.status_code == 404
    assert response.json()["detail"] == "folder not found"


@pytest.mark.asyncio
async def test_upload_and_list_file_in_folder(client):
    fake_client = _FakeS3Client()
    folder_response = await client.post("/folders", json={"name": "Documents"})
    folder_id = folder_response.json()["id"]

    with patch("jarvis_shared.storage.boto3.client", return_value=fake_client):
        upload_response = await client.post(
            "/files",
            data={"folder_id": str(folder_id)},
            files={"file": ("hello.txt", b"hello world", "text/plain")},
        )
    assert upload_response.status_code == 200
    assert upload_response.json()["folder_id"] == folder_id

    root_files = await client.get("/files")
    assert root_files.json() == []

    folder_files = await client.get(f"/files?folder_id={folder_id}")
    assert [f["filename"] for f in folder_files.json()] == ["hello.txt"]


@pytest.mark.asyncio
async def test_upload_file_with_missing_folder(client):
    response = await client.post(
        "/files",
        data={"folder_id": "999999"},
        files={"file": ("hello.txt", b"hello world", "text/plain")},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "folder not found"


@pytest.mark.asyncio
async def test_delete_folder_removes_nested_files_and_subfolders(client):
    fake_client = _FakeS3Client()

    parent_response = await client.post("/folders", json={"name": "Documents"})
    parent_id = parent_response.json()["id"]
    child_response = await client.post(
        "/folders", json={"name": "Invoices", "parent_id": parent_id}
    )
    child_id = child_response.json()["id"]

    with patch("jarvis_shared.storage.boto3.client", return_value=fake_client):
        await client.post(
            "/files",
            data={"folder_id": str(parent_id)},
            files={"file": ("a.txt", b"a", "text/plain")},
        )
        await client.post(
            "/files",
            data={"folder_id": str(child_id)},
            files={"file": ("b.txt", b"b", "text/plain")},
        )

        delete_response = await client.delete(f"/folders/{parent_id}")
    assert delete_response.status_code == 204
    assert fake_client.objects == {}

    folders = await client.get("/folders")
    assert folders.json() == []

    child_folders = await client.get(f"/folders?parent_id={parent_id}")
    assert child_folders.json() == []


@pytest.mark.asyncio
async def test_delete_folder_not_found(client):
    response = await client.delete("/folders/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "folder not found"
