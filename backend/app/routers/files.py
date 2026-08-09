import asyncio
import logging
import uuid
from datetime import UTC, datetime

from aio_pika.exceptions import CONNECTION_EXCEPTIONS as AMQP_CONNECTION_EXCEPTIONS
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import Response
from jarvis_shared import storage
from jarvis_shared.queue import INGEST_REQUESTED_QUEUE, publish_message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models import Folder, StoredFile
from app.schemas import FileRead, FolderCreate, FolderRead

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_folder_or_404(db: AsyncSession, folder_id: int) -> Folder:
    folder = await db.get(Folder, folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="folder not found")
    return folder


async def _folder_subtree_ids(db: AsyncSession, root_id: int) -> list[int]:
    """Root folder id plus every descendant folder id, gathered breadth-first."""
    ids = [root_id]
    frontier = [root_id]
    while frontier:
        result = await db.execute(select(Folder.id).where(Folder.parent_id.in_(frontier)))
        children = list(result.scalars().all())
        if not children:
            break
        ids.extend(children)
        frontier = children
    return ids


@router.post("/files", response_model=FileRead)
async def upload_file(
    file: UploadFile,
    folder_id: int | None = Form(None),
    db: AsyncSession = Depends(get_db),
) -> StoredFile:
    settings = get_settings()

    if folder_id is not None:
        await _get_folder_or_404(db, folder_id)

    body = await file.read()
    object_key = f"{uuid.uuid4()}/{file.filename}"

    try:
        await asyncio.to_thread(storage.put_object, settings, object_key, body, file.content_type)
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(
            status_code=502, detail=f"Could not reach MinIO at {settings.minio_endpoint}: {exc}"
        ) from exc

    db_file = StoredFile(
        filename=file.filename,
        content_type=file.content_type,
        size=len(body),
        object_key=object_key,
        folder_id=folder_id,
    )
    db.add(db_file)
    await db.commit()
    await db.refresh(db_file)

    try:
        await publish_message(
            settings.rabbitmq_url,
            INGEST_REQUESTED_QUEUE,
            {"file_id": db_file.id, "requested_at": datetime.now(UTC).isoformat()},
        )
    except AMQP_CONNECTION_EXCEPTIONS as exc:
        logger.warning(
            "Could not publish auto-ingest request for file %s at %s: %s",
            db_file.id,
            settings.rabbitmq_url,
            exc,
        )

    return db_file


@router.get("/files", response_model=list[FileRead])
async def list_files(
    folder_id: int | None = None, db: AsyncSession = Depends(get_db)
) -> list[StoredFile]:
    result = await db.execute(
        select(StoredFile).where(StoredFile.folder_id == folder_id).order_by(StoredFile.id)
    )
    return list(result.scalars().all())


@router.post("/folders", response_model=FolderRead)
async def create_folder(payload: FolderCreate, db: AsyncSession = Depends(get_db)) -> Folder:
    if payload.parent_id is not None:
        await _get_folder_or_404(db, payload.parent_id)

    folder = Folder(name=payload.name, parent_id=payload.parent_id)
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return folder


@router.get("/folders", response_model=list[FolderRead])
async def list_folders(
    parent_id: int | None = None, db: AsyncSession = Depends(get_db)
) -> list[Folder]:
    result = await db.execute(
        select(Folder).where(Folder.parent_id == parent_id).order_by(Folder.name)
    )
    return list(result.scalars().all())


@router.delete("/folders/{folder_id}", status_code=204)
async def delete_folder(folder_id: int, db: AsyncSession = Depends(get_db)) -> None:
    folder = await _get_folder_or_404(db, folder_id)

    settings = get_settings()
    subtree_ids = await _folder_subtree_ids(db, folder_id)
    result = await db.execute(select(StoredFile).where(StoredFile.folder_id.in_(subtree_ids)))
    files_to_remove = list(result.scalars().all())

    for db_file in files_to_remove:
        try:
            await asyncio.to_thread(storage.delete_object, settings, db_file.object_key)
        except (BotoCoreError, ClientError) as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Could not reach MinIO at {settings.minio_endpoint}: {exc}",
            ) from exc
        await db.delete(db_file)

    # Deepest descendants first so no folder is deleted while a child row
    # still references it.
    for descendant_id in reversed(subtree_ids[1:]):
        descendant = await db.get(Folder, descendant_id)
        if descendant is not None:
            await db.delete(descendant)

    await db.delete(folder)
    await db.commit()


@router.get("/files/{file_id}/download")
async def download_file(file_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    db_file = await db.get(StoredFile, file_id)
    if db_file is None:
        raise HTTPException(status_code=404, detail="file not found")

    settings = get_settings()
    try:
        data = await asyncio.to_thread(storage.get_object, settings, db_file.object_key)
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(
            status_code=502, detail=f"Could not reach MinIO at {settings.minio_endpoint}: {exc}"
        ) from exc

    return Response(
        content=data,
        media_type=db_file.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{db_file.filename}"'},
    )


@router.post("/files/{file_id}/ingest", status_code=202)
async def request_ingest(file_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    db_file = await db.get(StoredFile, file_id)
    if db_file is None:
        raise HTTPException(status_code=404, detail="file not found")

    settings = get_settings()
    try:
        await publish_message(
            settings.rabbitmq_url,
            INGEST_REQUESTED_QUEUE,
            {"file_id": file_id, "requested_at": datetime.now(UTC).isoformat()},
        )
    except AMQP_CONNECTION_EXCEPTIONS as exc:
        raise HTTPException(
            status_code=502, detail=f"Could not reach RabbitMQ at {settings.rabbitmq_url}: {exc}"
        ) from exc
    return {"status": "queued", "file_id": file_id}


@router.delete("/files/{file_id}", status_code=204)
async def delete_file(file_id: int, db: AsyncSession = Depends(get_db)) -> None:
    db_file = await db.get(StoredFile, file_id)
    if db_file is None:
        raise HTTPException(status_code=404, detail="file not found")

    settings = get_settings()
    try:
        await asyncio.to_thread(storage.delete_object, settings, db_file.object_key)
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(
            status_code=502, detail=f"Could not reach MinIO at {settings.minio_endpoint}: {exc}"
        ) from exc

    await db.delete(db_file)
    await db.commit()
