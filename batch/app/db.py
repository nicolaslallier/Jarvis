from collections.abc import AsyncGenerator

from jarvis_shared.db import Base, check_connection as _check_connection, make_engine, make_session_factory
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

settings = get_settings()

engine = make_engine(settings.sqlalchemy_url)
async_session = make_session_factory(engine)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def check_connection() -> None:
    await _check_connection(engine)


__all__ = ["Base", "engine", "async_session", "get_db", "check_connection"]
