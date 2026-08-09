import asyncio
import uuid

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.models import StoredFile
from app.schemas import FileRead

router = APIRouter()


def _s3_client(settings: Settings):
    return boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
    )


def _put_object(settings: Settings, key: str, body: bytes, content_type: str | None) -> None:
    client = _s3_client(settings)
    try:
        client.head_bucket(Bucket=settings.minio_bucket)
    except ClientError:
        client.create_bucket(Bucket=settings.minio_bucket)
    client.put_object(
        Bucket=settings.minio_bucket,
        Key=key,
        Body=body,
        ContentType=content_type or "application/octet-stream",
    )


def _get_object(settings: Settings, key: str) -> bytes:
    client = _s3_client(settings)
    obj = client.get_object(Bucket=settings.minio_bucket, Key=key)
    return obj["Body"].read()


def _delete_object(settings: Settings, key: str) -> None:
    client = _s3_client(settings)
    client.delete_object(Bucket=settings.minio_bucket, Key=key)


@router.post("/files", response_model=FileRead)
async def upload_file(file: UploadFile, db: AsyncSession = Depends(get_db)) -> StoredFile:
    settings = get_settings()
    body = await file.read()
    object_key = f"{uuid.uuid4()}/{file.filename}"

    try:
        await asyncio.to_thread(_put_object, settings, object_key, body, file.content_type)
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(
            status_code=502, detail=f"Could not reach MinIO at {settings.minio_endpoint}: {exc}"
        ) from exc

    db_file = StoredFile(
        filename=file.filename,
        content_type=file.content_type,
        size=len(body),
        object_key=object_key,
    )
    db.add(db_file)
    await db.commit()
    await db.refresh(db_file)
    return db_file


@router.get("/files", response_model=list[FileRead])
async def list_files(db: AsyncSession = Depends(get_db)) -> list[StoredFile]:
    result = await db.execute(select(StoredFile).order_by(StoredFile.id))
    return list(result.scalars().all())


@router.get("/files/{file_id}/download")
async def download_file(file_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    db_file = await db.get(StoredFile, file_id)
    if db_file is None:
        raise HTTPException(status_code=404, detail="file not found")

    settings = get_settings()
    try:
        data = await asyncio.to_thread(_get_object, settings, db_file.object_key)
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(
            status_code=502, detail=f"Could not reach MinIO at {settings.minio_endpoint}: {exc}"
        ) from exc

    return Response(
        content=data,
        media_type=db_file.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{db_file.filename}"'},
    )


@router.delete("/files/{file_id}", status_code=204)
async def delete_file(file_id: int, db: AsyncSession = Depends(get_db)) -> None:
    db_file = await db.get(StoredFile, file_id)
    if db_file is None:
        raise HTTPException(status_code=404, detail="file not found")

    settings = get_settings()
    try:
        await asyncio.to_thread(_delete_object, settings, db_file.object_key)
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(
            status_code=502, detail=f"Could not reach MinIO at {settings.minio_endpoint}: {exc}"
        ) from exc

    await db.delete(db_file)
    await db.commit()
