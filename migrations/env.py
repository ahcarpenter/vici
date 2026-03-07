import asyncio

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
    WorkRequest,
)

target_metadata = SQLModel.metadata


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    from src.config import get_settings

    config = context.config
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


asyncio.run(run_async_migrations())
