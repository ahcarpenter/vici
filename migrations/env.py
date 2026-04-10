import asyncio
import os

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlmodel import SQLModel

# CRITICAL: import all domain models so SQLModel.metadata is populated
from src.models import (  # noqa: F401
    AuditLog,
    Job,
    Match,
    Message,
    RateLimit,
    User,
    WorkGoal,
)

target_metadata = SQLModel.metadata


def _get_database_url() -> str:
    """Return the database URL from env var or application settings.

    In migration-only contexts (e.g., K8s Job with only DATABASE_URL mounted),
    reading the env var directly avoids instantiating the full Settings model
    which validates credentials the migration container does not need.
    """
    url = os.environ.get("DATABASE_URL", "")
    if url:
        return url
    from src.config import get_settings

    return get_settings().database_url


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    config = context.config
    config.set_main_option("sqlalchemy.url", _get_database_url())
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


asyncio.run(run_async_migrations())
