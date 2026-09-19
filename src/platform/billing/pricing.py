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
    request_cost DOUBLE PRECISION NOT NULL DEFAULT 0,
    cost_kind VARCHAR(20) NOT NULL DEFAULT 'provider',
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
    ('cohere', 'rerank-v3.5', 0.0, 0.0, 0.00020),
    ('jev', 'jev-latest', 0.0, 0.0, 0.0),
    ('novita', 'default', 0.00015, 0.00060, 0.0),
    ('novita', 'small', 0.00010, 0.00040, 0.0),
    ('embeddings', 'default', 0.0, 0.0, 0.00002),
    ('reranker', 'default', 0.0, 0.0, 0.00020)
ON CONFLICT (provider, model) DO NOTHING
"""


@dataclass(kw_only=True, frozen=True)
class PriceRecord:
    provider: str
    model: str
    input_cost_per_1k: float
    output_cost_per_1k: float
    embedding_cost_per_1k: float
    request_cost: float = 0.0
    cost_kind: str = "provider"
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
        await session.execute(text(
            "ALTER TABLE pricing_models ADD COLUMN IF NOT EXISTS request_cost "
            "DOUBLE PRECISION NOT NULL DEFAULT 0"
        ))
        await session.execute(text(
            "ALTER TABLE pricing_models ADD COLUMN IF NOT EXISTS cost_kind "
            "VARCHAR(20) NOT NULL DEFAULT 'provider'"
        ))
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS provider_cost_history (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    provider VARCHAR(60) NOT NULL,
                    model VARCHAR(120) NOT NULL,
                    input_cost_per_1k DOUBLE PRECISION NOT NULL DEFAULT 0,
                    output_cost_per_1k DOUBLE PRECISION NOT NULL DEFAULT 0,
                    embedding_cost_per_1k DOUBLE PRECISION NOT NULL DEFAULT 0,
                    request_cost DOUBLE PRECISION NOT NULL DEFAULT 0,
                    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
                    cost_kind VARCHAR(20) NOT NULL DEFAULT 'provider',
                    effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    effective_to TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
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
                    "output_cost_per_1k, embedding_cost_per_1k, currency, "
                    "COALESCE(request_cost, 0) AS request_cost, "
                    "COALESCE(cost_kind, 'provider') AS cost_kind "
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
                        "output_cost_per_1k, embedding_cost_per_1k, currency, "
                        "COALESCE(request_cost, 0) AS request_cost, "
                        "COALESCE(cost_kind, 'provider') AS cost_kind "
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
                        "output_cost_per_1k, embedding_cost_per_1k, currency, "
                        "COALESCE(request_cost, 0) AS request_cost, "
                        "COALESCE(cost_kind, 'provider') AS cost_kind "
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
            request_cost=float(getattr(row, "request_cost", 0) or 0),
            cost_kind=str(getattr(row, "cost_kind", None) or "provider"),
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
    """Costo estimado = input + output + embeddings (por 1k tokens) + per-request."""
    return (
        prompt_tokens / 1000 * price.input_cost_per_1k
        + completion_tokens / 1000 * price.output_cost_per_1k
        + embedding_tokens / 1000 * price.embedding_cost_per_1k
        + float(price.request_cost or 0.0)
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
    request_cost: float = 0.0,
    cost_kind: str = "provider",
) -> None:
    """Actualiza un precio sin deploy (endpoint admin). Conserva historial."""
    await ensure_pricing_table()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                """
                INSERT INTO provider_cost_history (
                    provider, model, input_cost_per_1k, output_cost_per_1k,
                    embedding_cost_per_1k, request_cost, currency, cost_kind,
                    effective_from, effective_to
                )
                SELECT provider, model, input_cost_per_1k, output_cost_per_1k,
                       embedding_cost_per_1k, COALESCE(request_cost, 0),
                       currency, COALESCE(cost_kind, 'provider'),
                       updated_at, NOW()
                FROM pricing_models
                WHERE provider = :p AND model = :m
                """
            ),
            {"p": provider, "m": model},
        )
        await session.execute(
            text(
                "INSERT INTO pricing_models "
                "(provider, model, input_cost_per_1k, output_cost_per_1k, "
                "embedding_cost_per_1k, request_cost, cost_kind, currency) "
                "VALUES (:p, :m, :in_c, :out_c, :emb_c, :req_c, :kind, :cur) "
                "ON CONFLICT (provider, model) DO UPDATE SET "
                "input_cost_per_1k = EXCLUDED.input_cost_per_1k, "
                "output_cost_per_1k = EXCLUDED.output_cost_per_1k, "
                "embedding_cost_per_1k = EXCLUDED.embedding_cost_per_1k, "
                "request_cost = EXCLUDED.request_cost, "
                "cost_kind = EXCLUDED.cost_kind, "
                "currency = EXCLUDED.currency, updated_at = NOW()"
            ),
            {
                "p": provider,
                "m": model,
                "in_c": input_cost_per_1k,
                "out_c": output_cost_per_1k,
                "emb_c": embedding_cost_per_1k,
                "req_c": request_cost,
                "kind": cost_kind or "provider",
                "cur": currency,
            },
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
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
                    "output_cost_per_1k, embedding_cost_per_1k, "
                    "COALESCE(request_cost, 0) AS request_cost, "
                    "COALESCE(cost_kind, 'provider') AS cost_kind, "
                    "currency, updated_at FROM pricing_models "
                    "ORDER BY provider, model"
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
                "request_cost": float(r.request_cost or 0),
                "cost_kind": r.cost_kind,
                "currency": r.currency,
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ]
    finally:
        await session.close()


async def list_price_history(provider: str | None = None, model: str | None = None) -> list[dict]:
    session = await get_async_session()
    query = (
        "SELECT provider, model, input_cost_per_1k, output_cost_per_1k, "
        "embedding_cost_per_1k, request_cost, currency, cost_kind, "
        "effective_from, effective_to FROM provider_cost_history "
        "ORDER BY effective_from DESC LIMIT 200"
    )
    params: dict = {}
    if provider and model:
        query = (
            "SELECT provider, model, input_cost_per_1k, output_cost_per_1k, "
            "embedding_cost_per_1k, request_cost, currency, cost_kind, "
            "effective_from, effective_to FROM provider_cost_history "
            "WHERE provider = :p AND model = :m "
            "ORDER BY effective_from DESC LIMIT 200"
        )
        params = {"p": provider, "m": model}
    elif provider:
        query = (
            "SELECT provider, model, input_cost_per_1k, output_cost_per_1k, "
            "embedding_cost_per_1k, request_cost, currency, cost_kind, "
            "effective_from, effective_to FROM provider_cost_history "
            "WHERE provider = :p ORDER BY effective_from DESC LIMIT 200"
        )
        params = {"p": provider}
    try:
        rows = (await session.execute(text(query), params)).fetchall()
        return [
            {
                "provider": r.provider,
                "model": r.model,
                "input_cost_per_1k": r.input_cost_per_1k,
                "output_cost_per_1k": r.output_cost_per_1k,
                "embedding_cost_per_1k": r.embedding_cost_per_1k,
                "request_cost": float(r.request_cost or 0),
                "currency": r.currency,
                "cost_kind": r.cost_kind,
                "effective_from": r.effective_from.isoformat() if r.effective_from else None,
                "effective_to": r.effective_to.isoformat() if r.effective_to else None,
            }
            for r in rows
        ]
    except Exception:
        return []
    finally:
        await session.close()
