from collections.abc import AsyncGenerator

from jarvis_shared.db import Base, check_connection as _check_connection, make_engine, make_session_factory
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

settings = get_settings()

# register_vector_codec=True: this is the one container that reads/writes
# the file_chunks.embedding column, so asyncpg needs pgvector's codec
# registered on every connection. backend/batch deliberately don't set this
# — see jarvis_shared.db.make_engine's docstring for why.
engine = make_engine(settings.sqlalchemy_url, register_vector_codec=True)
async_session = make_session_factory(engine)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def check_connection() -> None:
    await _check_connection(engine)


__all__ = ["Base", "engine", "async_session", "get_db", "check_connection"]
