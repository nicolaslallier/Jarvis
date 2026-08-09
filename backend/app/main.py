import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from jarvis_shared.queue import INGEST_COMPLETED_QUEUE, consume
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import get_settings
from app.db import Base, engine
from app.models import Appointment, FileChunk, Memory
from app.routers import briefing, calendar, chat, files, health, ingest_status, items, memory, tasks
from app.telemetry import setup_telemetry
from app.ws_manager import manager as ws_manager

settings = get_settings()

STARTUP_DB_RETRIES = 5
STARTUP_DB_RETRY_DELAY_SECONDS = 1

# Tables added after the original create_all baseline are managed by Alembic
# migrations instead, not this startup create_all — either because
# create_all can't express what they need (file_chunks/memories depend on
# the `vector` Postgres extension existing first) or simply to keep the
# convention consistent for everything added since. Including them here
# would make startup fail (or silently diverge from what Alembic thinks the
# schema is) on any database that hasn't run those migrations yet. See
# CLAUDE.md's "Database" section.
_ALEMBIC_MANAGED_TABLE_NAMES = {FileChunk.__tablename__, Memory.__tablename__, Appointment.__tablename__}
_CREATE_ALL_TABLES = [
    table for table in Base.metadata.tables.values() if table.name not in _ALEMBIC_MANAGED_TABLE_NAMES
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # On cold start, container DNS (e.g. resolving the `postgres` hostname on
    # an external Docker network) can briefly lag the app process being
    # ready to make its first connection. Retry a few times before failing.
    for attempt in range(1, STARTUP_DB_RETRIES + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all, tables=_CREATE_ALL_TABLES)
            break
        except OSError:
            if attempt == STARTUP_DB_RETRIES:
                raise
            await asyncio.sleep(STARTUP_DB_RETRY_DELAY_SECONDS)

    ingest_status_task = asyncio.create_task(
        consume(settings.rabbitmq_url, INGEST_COMPLETED_QUEUE, ws_manager.broadcast)
    )
    try:
        yield
    finally:
        ingest_status_task.cancel()
        try:
            await ingest_status_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Jarvis API", lifespan=lifespan)

origins = settings.cors_origin_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_telemetry(
    app,
    endpoint=settings.otel_exporter_otlp_endpoint or None,
    service_name=settings.otel_service_name,
)

Instrumentator(
    should_group_status_codes=False,
    excluded_handlers=["/metrics"],
).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

app.include_router(health.router)
app.include_router(items.router)
app.include_router(tasks.router)
app.include_router(calendar.router)
app.include_router(chat.router)
app.include_router(files.router)
app.include_router(ingest_status.router)
app.include_router(memory.router)
app.include_router(briefing.router)
