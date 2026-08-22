# =============================================================================
# Read-only Session Factory — pool dedicado para el SQL Expert
# =============================================================================
# El motor Text-to-SQL ejecuta SOLO con un rol PostgreSQL read-only
# (POSTGRES_READONLY_USER). Si el rol no está configurado, cae a la sesión
# principal con un warning único (no rompe desarrollo local).
# =============================================================================
from __future__ import annotations

from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_engine_loop_id: int | None = None
_warned_once = False


async def _ensure_readonly_engine() -> AsyncSession:
    global _engine, _session_factory, _engine_loop_id, _warned_once

    settings = get_settings()
    dsn = settings.POSTGRES_READONLY_DSN
    if dsn is None:
        if not _warned_once:
            logger.warning(
                "POSTGRES_READONLY_USER not configured; "
                "SQL Expert falling back to main credentials. "
                "Create the read-only role for production."
            )
            _warned_once = True
        from src.infrastructure.postgres.session import get_async_session

        return cast(AsyncSession, await get_async_session())

    import asyncio as _asyncio

    current_loop_id = id(_asyncio.get_running_loop())
    if _engine is None or _engine_loop_id != current_loop_id:
        if _engine is not None:
            await _engine.dispose()
        _engine = create_async_engine(
            dsn,
            pool_size=max(1, settings.POSTGRES_MIN_CONNECTIONS // 2),
            max_overflow=4,
            pool_pre_ping=True,
            echo=False,
        )
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
        _engine_loop_id = current_loop_id
    assert _session_factory is not None
    return _session_factory()


async def get_readonly_session() -> AsyncSession:
    """Sesión con credenciales read-only (fallback: sesión principal)."""
    return await _ensure_readonly_engine()


async def close_readonly_connections() -> None:
    """Cierra el pool read-only (graceful shutdown)."""
    global _engine, _engine_loop_id
    if _engine:
        await _engine.dispose()
        _engine = None
        _engine_loop_id = None
