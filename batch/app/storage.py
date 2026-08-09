import boto3
from botocore.exceptions import ClientError

from app.config import Settings


def get_s3_client(settings: Settings):
    return boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
    )


def ensure_bucket(settings: Settings) -> None:
    client = get_s3_client(settings)
    try:
        client.head_bucket(Bucket=settings.minio_bucket)
    except ClientError:
        client.create_bucket(Bucket=settings.minio_bucket)


def count_objects(settings: Settings) -> int:
    """Sync — must be called via asyncio.to_thread from job code."""
    client = get_s3_client(settings)
    paginator = client.get_paginator("list_objects_v2")
    count = 0
    for page in paginator.paginate(Bucket=settings.minio_bucket):
        count += len(page.get("Contents", []))
    return count
