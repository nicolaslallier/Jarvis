from unittest.mock import patch

import pytest

from app.health_state import state
from app.jobs import heartbeat


class _FakePaginator:
    def __init__(self, pages):
        self._pages = pages

    def paginate(self, Bucket):
        return self._pages


class _FakeS3Client:
    def __init__(self, object_keys):
        self._object_keys = object_keys

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        contents = [{"Key": key} for key in self._object_keys]
        return _FakePaginator([{"Contents": contents}])


@pytest.mark.asyncio
async def test_heartbeat_ok():
    with (
        patch("app.jobs.heartbeat.check_connection", return_value=None),
        patch("app.storage.boto3.client", return_value=_FakeS3Client(["a", "b", "c"])),
    ):
        await heartbeat.run()

    assert state.last_status == "ok"
    assert state.last_run_at is not None


@pytest.mark.asyncio
async def test_heartbeat_db_failure():
    async def _raise():
        raise RuntimeError("db down")

    with patch("app.jobs.heartbeat.check_connection", side_effect=_raise):
        await heartbeat.run()

    assert state.last_status == "error"


@pytest.mark.asyncio
async def test_heartbeat_minio_failure():
    from botocore.exceptions import ClientError

    class _BrokenS3Client:
        def get_paginator(self, name):
            raise ClientError({"Error": {"Code": "500", "Message": "boom"}}, "ListObjectsV2")

    with (
        patch("app.jobs.heartbeat.check_connection", return_value=None),
        patch("app.storage.boto3.client", return_value=_BrokenS3Client()),
    ):
        await heartbeat.run()

    assert state.last_status == "error"
