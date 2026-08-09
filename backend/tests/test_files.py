from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError


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
    with patch("app.routers.files.boto3.client", return_value=fake_client):
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
    with patch("app.routers.files.boto3.client", return_value=fake_client):
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
    with patch("app.routers.files.boto3.client", return_value=fake_client):
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
    with patch("app.routers.files.boto3.client", return_value=fake_client):
        response = await client.post(
            "/files", files={"file": ("hello.txt", b"hello world", "text/plain")}
        )

    assert response.status_code == 502
    assert "Could not reach MinIO" in response.json()["detail"]
