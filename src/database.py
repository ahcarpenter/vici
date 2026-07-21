from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import get_settings

POSTGRES_INDEXES_NAMING_CONVENTION = {
    "ix": "%(column_0_label)s_idx",
    "uq": "%(table_name)s_%(column_0_name)s_key",
    "ck": "%(table_name)s_%(constraint_name)s_check",
    "fk": "%(table_name)s_%(column_0_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}

# SQLAlchemy defaults (pool_size=5, max_overflow=10, no pre_ping) are too small
# for concurrent Temporal activity execution + gauge updater + webhook handlers,
# and stale connections fail silently without pre_ping.
_POOL_SIZE: int = 10
_POOL_MAX_OVERFLOW: int = 20
_POOL_TIMEOUT_SECONDS: int = 30

metadata = MetaData(naming_convention=POSTGRES_INDEXES_NAMING_CONVENTION)


@lru_cache(maxsize=1)
def get_engine():
    settings = get_settings()
    url = settings.database_url
    kwargs: dict = {"echo": False}
    # Pool sizing applies only to server-based dialects; sqlite uses StaticPool
    # and ignores/rejects these arguments.
    if url.startswith("postgres") or url.startswith("mysql"):
        kwargs.update(
            pool_size=_POOL_SIZE,
            max_overflow=_POOL_MAX_OVERFLOW,
            pool_timeout=_POOL_TIMEOUT_SECONDS,
            pool_pre_ping=True,
        )
    return create_async_engine(url, **kwargs)


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with get_sessionmaker()() as session:
        yield session
