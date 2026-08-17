# =============================================================================
# Lazy ingestion activity — Redis log keys and event parsing (UI feed)
# =============================================================================
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID


def lazy_log_cache_key(tenant_id: UUID) -> str:
    return f"rag:lazy:log:{tenant_id.hex}"


def lazy_rows_cache_key(tenant_id: UUID, schema: str, table: str) -> str:
    return f"rag:lazy_rows:{tenant_id.hex}:{schema}.{table}"


def preferred_tenant_id(auth_tenant_id: str | None, header_tenant_id: str | None) -> str:
    """El tenant del Bearer gana; el header solo se usa si no hay auth."""
    return (auth_tenant_id or "").strip() or (header_tenant_id or "").strip()


def parse_lazy_activity(
    raw_entries: list[str],
    *,
    days: int,
    limit: int,
    now: datetime | None = None,
) -> tuple[int, list[dict]]:
    """Filtra eventos JSON del log Redis por ventana `days` y recorta `recent`.

    `trigger_count` cuenta toda la ventana; `recent` son los más nuevos primero.
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    cutoff = current - timedelta(days=max(days, 0))
    events: list[dict] = []
    for raw in raw_entries:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        at_raw = payload.get("at")
        if not isinstance(at_raw, str) or not at_raw:
            continue
        try:
            at = datetime.fromisoformat(at_raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if at < cutoff:
            continue
        tables = payload.get("tables")
        if not isinstance(tables, list):
            tables = []
        try:
            rows_indexed = int(payload.get("rows_indexed") or 0)
        except (TypeError, ValueError):
            rows_indexed = 0
        preview = str(payload.get("query_preview") or "")[:80]
        events.append(
            {
                "tables": [str(t) for t in tables],
                "rows_indexed": rows_indexed,
                "query_preview": preview,
                "at": at.isoformat(),
            }
        )
    events.sort(key=lambda e: e["at"], reverse=True)
    return len(events), events[: max(limit, 0)]
