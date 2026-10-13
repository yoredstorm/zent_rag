# =============================================================================
# Regresión de lifecycle async: el engine no deja conexiones colgadas entre
# loops. Un cambio de loop recrea el engine; en development el pool es NullPool
# (sin conexiones idle), por lo que no hay SAWarning del GC ni intentos de
# cerrar conexiones de un loop ya cerrado.
# =============================================================================
from __future__ import annotations

import asyncio
import gc
import warnings


async def _ping() -> None:
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(text("SELECT 1"))
    finally:
        await session.close()


def test_engine_se_recrea_entre_loops_sin_warnings() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        asyncio.run(_ping())
        # Segundo loop: fuerza el cambio de loop y la recreación del engine.
        asyncio.run(_ping())
        gc.collect()

    mensajes = [str(w.message) for w in caught]
    leaks = [m for m in mensajes if "non-checked-in connection" in m]
    assert leaks == [], f"conexiones sin devolver al pool: {leaks[:3]}"
    loop_errors = [m for m in mensajes if "Event loop is closed" in m]
    assert loop_errors == [], f"errores de loop en lifecycle: {loop_errors[:3]}"


def test_engine_en_development_no_usa_pool_de_conexiones() -> None:
    from src.core.config import get_settings
    from src.infrastructure.postgres.session import _engine_options

    settings = get_settings()
    options = _engine_options(settings)
    assert str(getattr(settings, "ENVIRONMENT", "")).lower() == "development"
    assert "poolclass" in options
    assert "pool_size" not in options
