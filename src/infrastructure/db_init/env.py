# =============================================================================
# Alembic env.py — Async Engine Configuration para PostgreSQL
# =============================================================================
# Configurado para trabajar con SQLAlchemy async + asyncpg.
# Las migraciones usan run_async() para ejecutarse dentro de un event loop.
# target_metadata = None porque el proyecto usa SQL raw (no ORM).
# =============================================================================
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from src.core.config import Settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None

settings = Settings()


def run_migrations_offline() -> None:
    url = settings.POSTGRES_DSN
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = create_async_engine(
        settings.POSTGRES_DSN,
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
