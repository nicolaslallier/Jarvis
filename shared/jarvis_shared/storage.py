import boto3
from botocore.exceptions import ClientError

from jarvis_shared.config import SharedSettings


def get_s3_client(settings: SharedSettings):
    return boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
    )


def ensure_bucket(settings: SharedSettings) -> None:
    client = get_s3_client(settings)
    try:
        client.head_bucket(Bucket=settings.minio_bucket)
    except ClientError:
        client.create_bucket(Bucket=settings.minio_bucket)


def count_objects(settings: SharedSettings) -> int:
    """Sync — must be called via asyncio.to_thread from async job code."""
    client = get_s3_client(settings)
    paginator = client.get_paginator("list_objects_v2")
    count = 0
    for page in paginator.paginate(Bucket=settings.minio_bucket):
        count += len(page.get("Contents", []))
    return count


def put_object(settings: SharedSettings, key: str, body: bytes, content_type: str | None) -> None:
    """Sync — must be called via asyncio.to_thread from async job/route code."""
    client = get_s3_client(settings)
    ensure_bucket(settings)
    client.put_object(
        Bucket=settings.minio_bucket,
        Key=key,
        Body=body,
        ContentType=content_type or "application/octet-stream",
    )


def get_object(settings: SharedSettings, key: str) -> bytes:
    """Sync — must be called via asyncio.to_thread from async job/route code."""
    client = get_s3_client(settings)
    obj = client.get_object(Bucket=settings.minio_bucket, Key=key)
    return obj["Body"].read()


def delete_object(settings: SharedSettings, key: str) -> None:
    """Sync — must be called via asyncio.to_thread from async job/route code."""
    client = get_s3_client(settings)
    client.delete_object(Bucket=settings.minio_bucket, Key=key)
