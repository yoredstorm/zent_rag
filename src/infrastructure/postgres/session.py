# =============================================================================
# PostgreSQL Session Factory — Engine asíncrono y factory de sesiones
# =============================================================================
# Fábrica de sesión lazy per-event-loop (SQLAlchemy async + asyncpg).
# Las capas superiores acceden SOLO a esta fábrica; los repositorios
# concretos viven en relational_db.py.
# =============================================================================
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

# -----------------------------------------------------------------------------
# Engine y Session Factory — Inicialización lazy, per-event-loop
# -----------------------------------------------------------------------------
_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_engine_loop_id: int | None = None


async def get_async_session() -> AsyncSession:
    """Retorna una sesión asíncrona de SQLAlchemy desde el pool.

    Re-crea el engine si el event loop cambia (útil en tests con ASGITransport).
    """
    global _engine, _session_factory, _engine_loop_id

    engine = await _ensure_engine()
    assert _session_factory is not None
    return _session_factory()


async def _ensure_engine():
    """Crea (o devuelve) el engine asíncrono del event loop actual."""
    global _engine, _session_factory, _engine_loop_id

    import asyncio as _asyncio
    current_loop_id = id(_asyncio.get_running_loop())
    if _engine is None or _engine_loop_id != current_loop_id:
        if _engine is not None:
            await _engine.dispose()
        settings = get_settings()
        _engine = create_async_engine(
            settings.POSTGRES_DSN,
            pool_size=settings.POSTGRES_MIN_CONNECTIONS,
            max_overflow=settings.POSTGRES_MAX_CONNECTIONS - settings.POSTGRES_MIN_CONNECTIONS,
            pool_pre_ping=True,
            echo=False,
        )
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
        _engine_loop_id = current_loop_id
    return _engine


async def get_engine():
    """Engine asíncrono del loop actual (para conexiones raw/AUTOCOMMIT)."""
    return await _ensure_engine()


async def close_db_connections() -> None:
    """Cierra el pool de conexiones (útil en graceful shutdown)."""
    global _engine, _engine_loop_id
    if _engine:
        await _engine.dispose()
        _engine = None
        _engine_loop_id = None
