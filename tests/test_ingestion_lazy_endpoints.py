# =============================================================================
# Tests — lazy_rows_indexed en /sources y GET /ingestion/lazy-activity
# =============================================================================
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from src.domain.services import ColumnMeta, DataSource
from src.infrastructure.data_ingestion import PostgresIngestionService
from src.infrastructure.lazy_activity import (
    lazy_log_cache_key,
    lazy_rows_cache_key,
    parse_lazy_activity,
    preferred_tenant_id,
)

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
_HAS_LITELLM = importlib.util.find_spec("litellm") is not None


class _FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ttl_seconds: int = 300) -> None:
        self.store[key] = value

    async def exists(self, key: str) -> bool:
        return key in self.store

    async def append_to_list(self, key: str, value: str, ttl_seconds: int = 3600) -> None:
        self.lists.setdefault(key, []).append(value)

    async def get_list(self, key: str) -> list[str]:
        return list(self.lists.get(key, []))

    async def trim_list(self, key: str, max_items: int) -> None:
        self.lists[key] = self.lists.get(key, [])[-max_items:]

    async def incr(self, key: str, ttl_seconds: int | None = None, by: int = 1) -> int:
        current = int(self.store.get(key, 0))
        self.store[key] = str(current + by)
        return current + by


class _FakeEmbed:
    async def embed(self, text: str | list[str], model: str | None = None) -> list[float] | list[list[float]]:
        if isinstance(text, list):
            return [[0.1] * 8 for _ in text]
        return [0.1] * 8


class _FakeVectorStore:
    async def search(self, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def upsert(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def upsert_batch(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def delete_by_tenant(self, tenant_id: UUID) -> None:
        return None


def _event(days_ago: float, tables: list[str], rows: int = 1, preview: str = "q") -> str:
    at = NOW - timedelta(days=days_ago)
    return json.dumps(
        {
            "tables": tables,
            "rows_indexed": rows,
            "query_preview": preview,
            "at": at.isoformat(),
        }
    )


def test_preferred_tenant_id_ignores_spoofed_header_when_auth_present() -> None:
    auth = str(uuid4())
    spoof = str(uuid4())
    assert preferred_tenant_id(auth, spoof) == auth
    assert preferred_tenant_id("", spoof) == spoof
    assert preferred_tenant_id(None, spoof) == spoof


def test_lazy_cache_keys_are_tenant_scoped() -> None:
    a = uuid4()
    b = uuid4()
    assert lazy_log_cache_key(a) != lazy_log_cache_key(b)
    assert a.hex in lazy_log_cache_key(a)
    assert b.hex not in lazy_log_cache_key(a)
    assert lazy_rows_cache_key(a, "farmacia", "products") != lazy_rows_cache_key(
        b, "farmacia", "products"
    )


def test_parse_lazy_activity_filters_days_and_limit() -> None:
    raw = [
        _event(1, ["productos"], 18, "¿tienen paracetamol?"),
        _event(10, ["ventas"], 5, "cuántas ventas"),
        _event(40, ["viejo"], 9, "fuera de ventana"),
        "not-json",
        json.dumps({"tables": ["x"], "rows_indexed": 1}),
    ]
    trigger_count, recent = parse_lazy_activity(raw, days=30, limit=1, now=NOW)
    assert trigger_count == 2
    assert len(recent) == 1
    assert recent[0]["tables"] == ["productos"]
    assert recent[0]["rows_indexed"] == 18
    assert recent[0]["query_preview"].startswith("¿tienen")


def test_parse_lazy_activity_newest_first() -> None:
    raw = [
        _event(5, ["old"], 1, "antigua"),
        _event(0.1, ["new"], 2, "nueva"),
    ]
    count, recent = parse_lazy_activity(raw, days=30, limit=20, now=NOW)
    assert count == 2
    assert [e["tables"][0] for e in recent] == ["new", "old"]


@pytest.mark.asyncio
async def test_get_lazy_rows_indexed_reads_own_tenant_key() -> None:
    cache = _FakeCache()
    tenant = uuid4()
    other = uuid4()
    cache.store[lazy_rows_cache_key(tenant, "farmacia", "products")] = "18"
    cache.store[lazy_rows_cache_key(other, "farmacia", "products")] = "99"
    svc = PostgresIngestionService(_FakeVectorStore(), _FakeEmbed(), cache)

    assert await svc.get_lazy_rows_indexed(tenant, "farmacia", "products") == 18
    assert await svc.get_lazy_rows_indexed(other, "farmacia", "products") == 99
    assert await svc.get_lazy_rows_indexed(tenant, "farmacia", "sales") == 0


@pytest.mark.asyncio
async def test_get_lazy_rows_indexed_without_cache_returns_zero() -> None:
    svc = PostgresIngestionService(_FakeVectorStore(), _FakeEmbed(), None)
    assert await svc.get_lazy_rows_indexed(uuid4(), "farmacia", "products") == 0


class _FakeIngestion:
    _skip_tables: set[str] = set()

    def __init__(self, lazy_rows: int = 18) -> None:
        self.lazy_rows = lazy_rows

    async def discover_sources(self, tenant_id: UUID) -> list[DataSource]:
        return [
            DataSource(
                schema_name="farmacia",
                table_name="products",
                columns=[
                    ColumnMeta(
                        name="id",
                        data_type="uuid",
                        is_nullable=False,
                        is_primary_key=True,
                    )
                ],
                row_count=100,
            )
        ]

    async def is_synced(self, tenant_id: UUID, schema: str, table: str) -> bool:
        return False

    async def get_table_progress(self, tenant_id: UUID, schema: str, table: str) -> dict | None:
        return None

    async def get_lazy_rows_indexed(self, tenant_id: UUID, schema: str, table: str) -> int:
        return self.lazy_rows


@pytest.mark.skipif(not _HAS_LITELLM, reason="API tests require litellm")
@pytest.mark.asyncio
async def test_sources_include_lazy_rows_indexed(
    async_client, trial_auth: dict[str, str]
) -> None:
    from src.api.main import app
    from src.api.routes.ingestion import get_ingestion_service

    app.dependency_overrides[get_ingestion_service] = lambda: _FakeIngestion(18)
    try:
        response = await async_client.get("/api/v1/ingestion/sources", headers=trial_auth)
        assert response.status_code == 200
        data = response.json()
        assert data["sources"]
        assert data["sources"][0]["lazy_rows_indexed"] == 18
        assert data["sources"][0]["table"] == "products"
    finally:
        app.dependency_overrides.pop(get_ingestion_service, None)


@pytest.mark.skipif(not _HAS_LITELLM, reason="API tests require litellm")
@pytest.mark.asyncio
async def test_lazy_activity_uses_authenticated_tenant_not_spoofed_header(
    async_client, trial_auth: dict[str, str]
) -> None:
    from src.api.deps import get_cache_provider
    from src.api.main import app

    tenant_id = UUID(trial_auth["X-Tenant-Id"])
    other = uuid4()
    cache = _FakeCache()
    at = datetime.now(timezone.utc).isoformat()
    await cache.append_to_list(
        lazy_log_cache_key(tenant_id),
        json.dumps(
            {
                "tables": ["productos"],
                "rows_indexed": 18,
                "query_preview": "¿tienen paracetamol?",
                "at": at,
            }
        ),
    )
    await cache.append_to_list(
        lazy_log_cache_key(other),
        json.dumps(
            {
                "tables": ["secret"],
                "rows_indexed": 1,
                "query_preview": "no debe filtrarse",
                "at": at,
            }
        ),
    )
    app.dependency_overrides[get_cache_provider] = lambda: cache
    try:
        spoofed = {**trial_auth, "X-Tenant-Id": str(other)}
        response = await async_client.get(
            "/api/v1/ingestion/lazy-activity?days=30&limit=20",
            headers=spoofed,
        )
        # Hardening: header que no coincide con el Bearer -> 403 (anti cross-tenant).
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_cache_provider, None)
