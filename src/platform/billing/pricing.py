# =============================================================================
# Pricing Registry — precios por provider/model actualizables sin deploy
# =============================================================================
# Tabla pricing_models + caché en memoria con TTL. Fallback:
# exacto (provider, model) → (default, model) → (default, default).
# =============================================================================
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS pricing_models (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider VARCHAR(60) NOT NULL,
    model VARCHAR(120) NOT NULL,
    input_cost_per_1k DOUBLE PRECISION NOT NULL DEFAULT 0,
    output_cost_per_1k DOUBLE PRECISION NOT NULL DEFAULT 0,
    embedding_cost_per_1k DOUBLE PRECISION NOT NULL DEFAULT 0,
    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (provider, model)
)
"""

_SEED_SQL = """
INSERT INTO pricing_models (provider, model, input_cost_per_1k, output_cost_per_1k, embedding_cost_per_1k)
VALUES
    ('default', 'default', 0.00015, 0.00060, 0.00002),
    ('openai', 'gpt-4o-mini', 0.00015, 0.00060, 0.00002),
    ('openai', 'gpt-4o', 0.00250, 0.01000, 0.00002),
    ('openai', 'gpt-4.1-mini', 0.00040, 0.00160, 0.00002),
    ('openai', 'baai/bge-m3', 0.0, 0.0, 0.00002),
    ('cohere', 'rerank-v3.5', 0.0, 0.0, 0.00020)
ON CONFLICT (provider, model) DO NOTHING
"""


@dataclass(kw_only=True, frozen=True)
class PriceRecord:
    provider: str
    model: str
    input_cost_per_1k: float
    output_cost_per_1k: float
    embedding_cost_per_1k: float
    currency: str = "USD"


_cache: dict[tuple[str, str], tuple[PriceRecord, float]] = {}
_cache_lock = threading.Lock()


def extract_provider(model: str) -> str:
    """'openai/baai/bge-m3' → 'openai'; sin slash → 'default'."""
    text_model = (model or "").strip()
    if "/" in text_model:
        return text_model.split("/", 1)[0].strip() or "default"
    return "default"


def extract_model(model: str) -> str:
    """'openai/baai/bge-m3' → 'baai/bge-m3'."""
    text_model = (model or "").strip()
    if "/" in text_model:
        return text_model.split("/", 1)[1].strip()
    return text_model


async def ensure_pricing_table() -> None:
    session = await get_async_session()
    try:
        await session.execute(text(_TABLE_SQL))
        await session.execute(text(_SEED_SQL))
        await session.commit()
    except Exception:
        await session.rollback()
    finally:
        await session.close()


def _cached(provider: str, model: str) -> PriceRecord | None:
    settings = get_settings()
    ttl = settings.PRICING_CACHE_TTL
    with _cache_lock:
        entry = _cache.get((provider, model))
        if entry is not None and time.monotonic() - entry[1] < ttl:
            return entry[0]
    return None


def _store_cache(provider: str, model: str, record: PriceRecord) -> None:
    with _cache_lock:
        _cache[(provider, model)] = (record, time.monotonic())


def invalidate_pricing_cache() -> None:
    with _cache_lock:
        _cache.clear()


async def get_price(model: str) -> PriceRecord:
    """Resuelve el precio de un modelo con fallback en cascada."""
    provider = extract_provider(model)
    bare_model = extract_model(model)

    candidates = [
        (provider, bare_model),
        ("default", bare_model),
        ("default", "default"),
    ]
    for p, m in candidates:
        cached = _cached(p, m)
        if cached is not None:
            return cached

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT provider, model, input_cost_per_1k, "
                    "output_cost_per_1k, embedding_cost_per_1k, currency "
                    "FROM pricing_models WHERE (provider = :p AND model = :m)"
                ),
                {"p": provider, "m": bare_model},
            )
        ).fetchone()
        if row is None:
            row = (
                await session.execute(
                    text(
                        "SELECT provider, model, input_cost_per_1k, "
                        "output_cost_per_1k, embedding_cost_per_1k, currency "
                        "FROM pricing_models WHERE provider = 'default' "
                        "AND model = :m"
                    ),
                    {"m": bare_model},
                )
            ).fetchone()
        if row is None:
            row = (
                await session.execute(
                    text(
                        "SELECT provider, model, input_cost_per_1k, "
                        "output_cost_per_1k, embedding_cost_per_1k, currency "
                        "FROM pricing_models WHERE provider = 'default' "
                        "AND model = 'default'"
                    )
                )
            ).fetchone()
    finally:
        await session.close()

    if row is None:
        record = PriceRecord(
            provider="default",
            model="default",
            input_cost_per_1k=0.00015,
            output_cost_per_1k=0.00060,
            embedding_cost_per_1k=0.00002,
        )
    else:
        record = PriceRecord(
            provider=str(row.provider),
            model=str(row.model),
            input_cost_per_1k=float(row.input_cost_per_1k),
            output_cost_per_1k=float(row.output_cost_per_1k),
            embedding_cost_per_1k=float(row.embedding_cost_per_1k),
            currency=str(row.currency),
        )
    _store_cache(record.provider, record.model, record)
    return record


def estimate_cost_from_price(
    price: PriceRecord,
    prompt_tokens: int,
    completion_tokens: int,
    embedding_tokens: int = 0,
) -> float:
    """Costo estimado = input + output + embeddings (por 1k tokens)."""
    return (
        prompt_tokens / 1000 * price.input_cost_per_1k
        + completion_tokens / 1000 * price.output_cost_per_1k
        + embedding_tokens / 1000 * price.embedding_cost_per_1k
    )


async def estimate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    embedding_tokens: int = 0,
) -> float:
    price = await get_price(model)
    return estimate_cost_from_price(
        price, prompt_tokens, completion_tokens, embedding_tokens
    )


async def upsert_price(
    *,
    provider: str,
    model: str,
    input_cost_per_1k: float,
    output_cost_per_1k: float,
    embedding_cost_per_1k: float,
    currency: str = "USD",
) -> None:
    """Actualiza un precio sin deploy (endpoint admin)."""
    await ensure_pricing_table()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO pricing_models "
                "(provider, model, input_cost_per_1k, output_cost_per_1k, "
                "embedding_cost_per_1k, currency) "
                "VALUES (:p, :m, :in_c, :out_c, :emb_c, :cur) "
                "ON CONFLICT (provider, model) DO UPDATE SET "
                "input_cost_per_1k = EXCLUDED.input_cost_per_1k, "
                "output_cost_per_1k = EXCLUDED.output_cost_per_1k, "
                "embedding_cost_per_1k = EXCLUDED.embedding_cost_per_1k, "
                "currency = EXCLUDED.currency, updated_at = NOW()"
            ),
            {
                "p": provider,
                "m": model,
                "in_c": input_cost_per_1k,
                "out_c": output_cost_per_1k,
                "emb_c": embedding_cost_per_1k,
                "cur": currency,
            },
        )
        await session.commit()
    finally:
        await session.close()
    invalidate_pricing_cache()


async def list_prices() -> list[dict]:
    await ensure_pricing_table()
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, provider, model, input_cost_per_1k, "
                    "output_cost_per_1k, embedding_cost_per_1k, currency, "
                    "updated_at FROM pricing_models ORDER BY provider, model"
                )
            )
        ).fetchall()
        return [
            {
                "id": str(r.id),
                "provider": r.provider,
                "model": r.model,
                "input_cost_per_1k": r.input_cost_per_1k,
                "output_cost_per_1k": r.output_cost_per_1k,
                "embedding_cost_per_1k": r.embedding_cost_per_1k,
                "currency": r.currency,
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ]
    finally:
        await session.close()
