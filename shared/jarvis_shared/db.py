from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def make_engine(sqlalchemy_url: str, *, register_vector_codec: bool = False) -> AsyncEngine:
    """Create the async engine each container's db.py module owns.

    ``register_vector_codec`` registers pgvector's asyncpg codec on every new
    connection, which is required for asyncpg to bind/read ``vector`` columns.
    Only the `ingest` container (the only one reading/writing `file_chunks`)
    should pass this — turning it on unconditionally would make *every*
    container's DB connection depend on the `vector` Postgres extension
    existing, breaking backend/batch before that extension is provisioned.
    """
    engine = create_async_engine(sqlalchemy_url)

    if register_vector_codec and sqlalchemy_url.startswith("postgresql+asyncpg://"):
        from pgvector.asyncpg import register_vector

        # asyncpg.connect() has no `init` kwarg (that only exists on
        # asyncpg.create_pool()) — SQLAlchemy's async engine wraps each raw
        # asyncpg connection in an object exposing `run_async` for exactly
        # this kind of per-connection async setup.
        @event.listens_for(engine.sync_engine, "connect")
        def _register_vector_codec(dbapi_connection: object, connection_record: object) -> None:
            dbapi_connection.run_async(lambda conn: register_vector(conn))

    return engine


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def check_connection(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
