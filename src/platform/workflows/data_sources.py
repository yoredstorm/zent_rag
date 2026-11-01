# =============================================================================
# P19-02 — Catálogo seguro de conexiones, recursos y preview.
#
# No crea un registro paralelo: las conexiones salen de managed_databases y
# los recursos publicados salen de los bindings con plan canónico
# zent.data.query.binding/v1. La introspección reutiliza schema_discovery y la
# sesión read-only de Managed DB.
# =============================================================================
from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.core.domain.pii import is_sensitive_column, pii_flags_for_column
from src.infrastructure.postgres.session import get_async_session
from src.platform.workflows.bindings import (
    BindingError,
    _execute_managed_select,
    get_binding,
    list_bindings,
    parse_data_query_plan,
)

_CACHE_TTL_SECONDS = 30.0
_CACHE: dict[str, tuple[float, Any]] = {}
_MAX_LIMIT = 100


class DataSourceError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _cache_key(*parts: Any) -> str:
    return ":".join(str(part) for part in parts)


def invalidate_data_catalog(organization_id: UUID | str, workspace_id: UUID | str | None = None) -> None:
    prefix = f"{organization_id}:"
    if workspace_id is not None:
        prefix = f"{organization_id}:{workspace_id}:"
    for key in list(_CACHE):
        if key.startswith(prefix):
            _CACHE.pop(key, None)


def _get_cached(key: str) -> Any | None:
    item = _CACHE.get(key)
    if item is None:
        return None
    expires, value = item
    if expires < time.monotonic():
        _CACHE.pop(key, None)
        return None
    return value


def _set_cached(key: str, value: Any) -> None:
    _CACHE[key] = (time.monotonic() + _CACHE_TTL_SECONDS, value)


def _source_ref(database_id: Any) -> str:
    return f"managed_db:{database_id}"


def _parse_source_ref(source_ref: str) -> UUID:
    prefix = "managed_db:"
    if not source_ref.startswith(prefix):
        raise DataSourceError(404, "RESOURCE_NOT_EXPOSED", "fuente no expuesta")
    try:
        return UUID(source_ref[len(prefix) :])
    except (TypeError, ValueError) as exc:
        raise DataSourceError(404, "RESOURCE_NOT_EXPOSED", "fuente no expuesta") from exc


async def _managed_source(organization_id: UUID, workspace_id: UUID, source_id: UUID) -> Any:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, provider, status, connector_id FROM managed_databases "
                    "WHERE id = :did AND organization_id = :oid AND workspace_id = :wid"
                ),
                {"did": str(source_id), "oid": str(organization_id), "wid": str(workspace_id)},
            )
        ).fetchone()
    finally:
        await session.close()
    return row


async def list_data_sources(
    organization_id: UUID,
    workspace_id: UUID,
    *,
    permissions: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
    key = _cache_key(organization_id, workspace_id, "sources", tuple(sorted(permissions or ())))
    cached = _get_cached(key)
    if cached is not None:
        return cached
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT m.id, m.provider, m.status, m.connector_id, "
                    "c.status AS connector_status "
                    "FROM managed_databases m "
                    "LEFT JOIN connectors c ON c.id = m.connector_id "
                    "AND c.organization_id = m.organization_id "
                    "WHERE m.organization_id = :oid AND m.workspace_id = :wid "
                    "ORDER BY m.created_at DESC"
                ),
                {"oid": str(organization_id), "wid": str(workspace_id)},
            )
        ).fetchall()
    finally:
        await session.close()
    sources = []
    for row in rows:
        connector_status = str(row.connector_status or "").lower()
        if not row.connector_id or not connector_status:
            status = "NEEDS_CREDENTIALS"
        elif connector_status in ("disabled", "error", "revoked"):
            status = "DEGRADED"
        elif connector_status == "active":
            status = "CONNECTED"
        else:
            status = "DEGRADED"
        sources.append(
            {
                "ref": _source_ref(row.id),
                "label": "Base de datos gestionada",
                "provider_kind": "managed_db",
                "status": status,
                "read_only": True,
                "capabilities": ["select", "count"],
                "provider": str(row.provider or "managed"),
            }
        )
    payload = {"sources": sources}
    _set_cached(key, payload)
    return payload


async def _published_plans(
    organization_id: UUID,
    workspace_id: UUID,
    permissions: frozenset[str] | set[str] | None = None,
) -> list[tuple[dict[str, Any], Any]]:
    key = _cache_key(
        organization_id,
        workspace_id,
        "plans",
        tuple(sorted(permissions or ())),
    )
    cached = _get_cached(key)
    if cached is not None:
        return cached
    bindings = (await list_bindings(organization_id, workspace_id)).get("bindings") or []
    published: list[tuple[dict[str, Any], Any]] = []
    for binding in bindings:
        if str(binding.get("provider_kind") or "") != "managed_db":
            continue
        try:
            plan = parse_data_query_plan(binding.get("config") or {})
        except BindingError:
            continue
        if plan is None:
            continue
        if plan.scope == "organization":
            if workspace_id not in plan.allowed_workspace_ids:
                continue
        elif str(binding.get("workspace_id") or "") != str(workspace_id):
            continue
        published.append((binding, plan))
    _set_cached(key, published)
    return published


def _plan_resource_ref(plan: Any) -> str:
    if plan.resource_ref:
        return str(plan.resource_ref)
    if plan.resource.schema_name:
        return f"{plan.resource.schema_name}.{plan.resource.name}"
    return str(plan.resource.name)


def _plan_columns(plan: Any) -> set[str]:
    fields = set(plan.allowed_columns) | set(plan.projection)
    fields |= {item.field for item in plan.required_predicates}
    fields |= {item.field for item in plan.parameters}
    fields |= {item.field for item in plan.order_by}
    if plan.ownership is not None:
        fields.add(plan.ownership.field)
    return fields


async def list_published_resources(
    organization_id: UUID,
    workspace_id: UUID,
    *,
    source_ref: str | None = None,
    cursor: int = 0,
    limit: int = 50,
    permissions: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
    source_id = _parse_source_ref(source_ref) if source_ref else None
    if source_id is not None:
        row = await _managed_source(organization_id, workspace_id, source_id)
        if row is None:
            raise DataSourceError(404, "RESOURCE_NOT_EXPOSED", "fuente no expuesta")

    safe_limit = max(1, min(int(limit or 50), _MAX_LIMIT))
    safe_cursor = max(0, int(cursor or 0))
    resources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for binding, plan in await _published_plans(organization_id, workspace_id, permissions):
        if source_id is not None and plan.connection_ref is not None:
            if plan.connection_ref != source_id:
                continue
        resource_ref = _plan_resource_ref(plan)
        if resource_ref in seen:
            continue
        seen.add(resource_ref)
        columns = _plan_columns(plan)
        resources.append(
            {
                "resource_ref": resource_ref,
                "label": resource_ref,
                "kind": plan.resource.kind,
                "schema": plan.resource.schema_name,
                "name": plan.resource.name,
                "columns_count": len(columns),
                "sensitive": any(is_sensitive_column(column) for column in columns),
                "binding_ref": str(binding.get("id") or ""),
                "capability_ref": str(binding.get("capability_ref") or ""),
            }
        )
    total = len(resources)
    page = resources[safe_cursor : safe_cursor + safe_limit]
    next_cursor = safe_cursor + safe_limit if safe_cursor + safe_limit < total else None
    return {
        "resources": page,
        "total": total,
        "next_cursor": next_cursor,
        "source_ref": source_ref,
    }


async def _resource_plan(
    organization_id: UUID,
    workspace_id: UUID,
    resource_ref: str,
    permissions: frozenset[str] | set[str] | None = None,
) -> tuple[dict[str, Any], Any]:
    for binding, plan in await _published_plans(organization_id, workspace_id, permissions):
        if _plan_resource_ref(plan) == resource_ref:
            return binding, plan
    raise DataSourceError(404, "RESOURCE_NOT_EXPOSED", "recurso no expuesto")


async def get_resource_schema(
    organization_id: UUID,
    workspace_id: UUID,
    resource_ref: str,
    *,
    source_ref: str | None = None,
    permissions: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
    binding, plan = await _resource_plan(organization_id, workspace_id, resource_ref, permissions)
    if source_ref:
        source_id = _parse_source_ref(source_ref)
        row = await _managed_source(organization_id, workspace_id, source_id)
        if row is None:
            raise DataSourceError(404, "RESOURCE_NOT_EXPOSED", "fuente no expuesta")
        if plan.connection_ref is not None and plan.connection_ref != source_id:
            raise DataSourceError(404, "RESOURCE_NOT_EXPOSED", "recurso no expuesto")
    from src.connectors.sql.schema_discovery import discover_columns
    from src.platform.managed_db.service import open_managed_query_session

    session = await open_managed_query_session(organization_id, workspace_id, database_id=plan.connection_ref)
    if session is None:
        raise DataSourceError(409, "NEEDS_CONFIGURATION", "no hay Managed DB disponible")
    try:
        columns = await discover_columns(session, plan.resource.schema_name or "public", plan.resource.name)
    except Exception as exc:  # noqa: BLE001
        raise DataSourceError(409, "CONNECTION_FAILED", "no se pudo leer el esquema") from exc
    finally:
        await session.close()

    if not columns:
        raise DataSourceError(404, "RESOURCE_NOT_EXPOSED", "recurso no expuesto")

    allowed = _plan_columns(plan)
    payload_columns = []
    for column in columns:
        if column.name not in allowed:
            continue
        payload_columns.append(
            {
                "name": column.name,
                "label": column.name,
                "data_type": column.data_type,
                "nullable": column.is_nullable,
                "primary_key": column.is_primary_key,
                "foreign_key": column.is_foreign_key,
                "foreign_table": column.fk_table,
                "foreign_column": column.fk_column,
                "sensitive": is_sensitive_column(column.name),
                "pii_flags": pii_flags_for_column(column.name),
            }
        )
    return {
        "resource_ref": resource_ref,
        "binding_ref": str(binding.get("id") or ""),
        "kind": plan.resource.kind,
        "columns": payload_columns,
    }


async def _redact_record(record: dict[str, Any], sensitive_fields: set[str]) -> tuple[dict[str, Any], list[str]]:
    redacted: list[str] = []
    out: dict[str, Any] = {}
    for key, value in record.items():
        if key in sensitive_fields or is_sensitive_column(str(key)):
            out[key] = "***"
            redacted.append(str(key))
        else:
            out[key] = value
    return out, redacted


async def preview_data_query(
    organization_id: UUID,
    workspace_id: UUID,
    binding_id: UUID,
    params: dict[str, Any] | None,
    *,
    permissions: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
    binding = await get_binding(organization_id, binding_id, workspace_id=workspace_id)
    if binding is None:
        raise DataSourceError(404, "RESOURCE_NOT_EXPOSED", "binding no expuesto")
    try:
        plan = parse_data_query_plan(binding.get("config") or {})
    except BindingError as exc:
        raise DataSourceError(409, "NEEDS_CONFIGURATION", exc.message) from exc
    if plan is None:
        raise DataSourceError(409, "NEEDS_CONFIGURATION", "el binding no es una consulta declarativa")
    if plan.scope == "organization" and workspace_id not in plan.allowed_workspace_ids:
        raise DataSourceError(403, "PERMISSION_DENIED", "workspace no autorizado")
    if plan.scope == "workspace" and str(binding.get("workspace_id") or "") != str(workspace_id):
        raise DataSourceError(403, "PERMISSION_DENIED", "workspace no autorizado")

    preview_policy = plan.policy.model_copy(
        update={
            "max_rows": min(plan.policy.max_rows, 5),
            "timeout_ms": min(plan.policy.timeout_ms, 1500),
            "max_bytes": min(plan.policy.max_bytes, 32_768),
        }
    )
    preview_plan = plan.model_copy(update={"policy": preview_policy})
    preview_binding = {**binding, "config": preview_plan.model_dump(by_alias=True)}
    try:
        result = await _execute_managed_select(
            organization_id,
            preview_binding,
            {"params": dict(params or {})},
            workspace_id=workspace_id,
        )
    except BindingError as exc:
        raise DataSourceError(400, exc.code, exc.message) from exc

    sensitive = {column for column in _plan_columns(plan) if is_sensitive_column(column)}
    redacted: list[str] = []
    if isinstance(result.get("record"), dict):
        result["record"], redacted = await _redact_record(result["record"], sensitive)
    if isinstance(result.get("rows"), list):
        out_rows = []
        for row in result["rows"]:
            if isinstance(row, dict):
                clean, fields = await _redact_record(row, sensitive)
                redacted.extend(field for field in fields if field not in redacted)
                out_rows.append(clean)
        result["rows"] = out_rows
    return {"preview": True, "redacted_fields": redacted, "result": result}
