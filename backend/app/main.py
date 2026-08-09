import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import Base, engine
from app.routers import chat, health, items, tasks

settings = get_settings()

STARTUP_DB_RETRIES = 5
STARTUP_DB_RETRY_DELAY_SECONDS = 1


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # On cold start, container DNS (e.g. resolving the `postgres` hostname on
    # an external Docker network) can briefly lag the app process being
    # ready to make its first connection. Retry a few times before failing.
    for attempt in range(1, STARTUP_DB_RETRIES + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            break
        except OSError:
            if attempt == STARTUP_DB_RETRIES:
                raise
            await asyncio.sleep(STARTUP_DB_RETRY_DELAY_SECONDS)
    yield


app = FastAPI(title="Jarvis API", lifespan=lifespan)

origins = settings.cors_origin_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(items.router)
app.include_router(tasks.router)
app.include_router(chat.router)
