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
from uuid import UUID, uuid4

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


def _parse_source_ref(source_ref: str) -> tuple[str, UUID]:
    for prefix, kind in (("managed_db:", "managed_db"), ("connector:", "connector")):
        if source_ref.startswith(prefix):
            try:
                return kind, UUID(source_ref[len(prefix) :])
            except (TypeError, ValueError) as exc:
                raise DataSourceError(404, "RESOURCE_NOT_EXPOSED", "fuente no expuesta") from exc
    raise DataSourceError(404, "RESOURCE_NOT_EXPOSED", "fuente no expuesta")


async def list_data_query_plans(
    organization_id: UUID,
    workspace_id: UUID,
    *,
    permissions: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
    """Planes publicados que el editor puede seleccionar (sin SQL)."""
    from src.platform.workflows.bindings import binding_plan_hash

    plans = []
    for binding, plan in await _published_plans(
        organization_id, workspace_id, permissions
    ):
        plans.append(
            {
                "binding_ref": str(binding.get("id") or ""),
                "capability_ref": str(binding.get("capability_ref") or ""),
                "binding_hash": binding_plan_hash(binding),
                "plan_version": int(binding.get("plan_version") or 1),
                "policy_hash": plan.policy_hash,
                "sensitive_columns": list(plan.sensitive_columns),
                "legacy_plan": not bool(plan.policy_hash),
                "resource_ref": _plan_resource_ref(plan),
                "resource_kind": plan.resource.kind,
                "operation": plan.operation,
                "projection": list(plan.projection),
                "max_rows": plan.policy.max_rows,
                "parameters": [
                    {
                        "name": item.name,
                        "field": item.field,
                        "operator": item.operator,
                        "type": item.type,
                        "required": item.required,
                        "label": item.field.replace("_", " "),
                    }
                    for item in plan.parameters
                ],
                "ownership_required": bool(plan.ownership and plan.ownership.required),
                "pii_class": plan.policy.pii_class,
            }
        )
    return {"plans": plans}


async def publish_data_query_plan(
    organization_id: UUID,
    workspace_id: UUID,
    body: dict[str, Any],
    *,
    permissions: frozenset[str] | set[str] | None = None,
    actor_id: UUID | None = None,
) -> dict[str, Any]:
    """Publica un plan canónico desde una tabla descubierta del conector."""
    from src.connectors.plugin import get_plugin
    from src.infrastructure.postgres.relational_db import PostgresConnectorRepository
    from src.infrastructure.secrets.secret_store_resolver import get_secret_store
    from src.platform.workflows.bindings import _plan_hash, upsert_binding
    from src.platform.workflows.data_governance import (
        DataPolicyError,
        authorize_publication,
        record_publication_event,
    )

    permissions = set(permissions or ())
    if "data_queries:publish" not in permissions and "*" not in permissions and "admin:*" not in permissions:
        raise DataSourceError(403, "PERMISSION_DENIED", "falta el permiso data_queries:publish")

    source_ref = str(body.get("connector_ref") or "")
    source_kind, connector_id = _parse_source_ref(source_ref)
    if source_kind != "connector":
        raise DataSourceError(400, "INVALID_PARAMS", "solo conectores externos por ahora")
    connector = await PostgresConnectorRepository().get_connector(
        organization_id, connector_id
    )
    if connector is None or str(connector.status or "").lower() != "active":
        raise DataSourceError(404, "RESOURCE_NOT_EXPOSED", "conector no expuesto")
    if connector.workspace_id and str(connector.workspace_id) != str(workspace_id):
        raise DataSourceError(403, "PERMISSION_DENIED", "conector de otro workspace")
    resource_ref = str(body.get("resource_ref") or "")
    if "." not in resource_ref:
        raise DataSourceError(400, "INVALID_PARAMS", "resource_ref debe ser schema.tabla")
    schema_name, table_name = resource_ref.split(".", 1)
    operation = str(body.get("operation") or "get_one")
    if operation not in ("get_one", "list", "count"):
        raise DataSourceError(400, "INVALID_PARAMS", "operación no permitida")
    projection = body.get("projection")
    if not isinstance(projection, list) or not projection:
        raise DataSourceError(400, "INVALID_PARAMS", "projection requerida")
    projection = [str(column) for column in projection][:50]
    if "*" in projection:
        raise DataSourceError(400, "INVALID_PARAMS", "SELECT * no está permitido")
    if len(set(projection)) != len(projection):
        raise DataSourceError(400, "INVALID_PARAMS", "proyección duplicada")

    config_json = connector.config_json if isinstance(connector.config_json, dict) else {}
    secrets = await get_secret_store().get(organization_id, connector_id)
    try:
        plugin = get_plugin(connector.type, config_json, secrets or {})
    except ValueError as exc:
        raise DataSourceError(400, "PROVIDER_NOT_SUPPORTED", str(exc)) from exc
    try:
        discovery = await plugin.discover()
    except Exception as exc:  # noqa: BLE001
        raise DataSourceError(409, "CONNECTION_FAILED", "no se pudo descubrir el schema") from exc
    finally:
        try:
            await plugin.close()
        except Exception:
            pass
    table = next(
        (
            item
            for item in discovery.tables
            if str(item.schema or "public") == schema_name and item.name == table_name
        ),
        None,
    )
    if table is None:
        raise DataSourceError(404, "RESOURCE_NOT_EXPOSED", "tabla no expuesta")
    columns = {str(column.name): column for column in table.columns}
    if not set(projection).issubset(columns):
        raise DataSourceError(400, "INVALID_PARAMS", "proyección con columnas inexistentes")
    parameter = body.get("parameter")
    parameters: list[dict[str, Any]] = []
    if parameter:
        if not isinstance(parameter, dict):
            raise DataSourceError(400, "INVALID_PARAMS", "parameter inválido")
        field = str(parameter.get("field") or "")
        name = str(parameter.get("name") or field)
        if field not in columns or not name:
            raise DataSourceError(400, "INVALID_PARAMS", "parámetro con columna inexistente")
        parameters.append(
            {
                "name": name,
                "field": field,
                "operator": str(parameter.get("operator") or "eq"),
                "type": str(parameter.get("type") or "string"),
                "required": bool(parameter.get("required", True)),
            }
        )
    predicates = body.get("required_predicates")
    required = []
    for item in predicates or []:
        if not isinstance(item, dict) or str(item.get("field") or "") not in columns:
            raise DataSourceError(400, "INVALID_PARAMS", "predicado inválido")
        required.append(
            {
                "field": str(item["field"]),
                "op": str(item.get("op") or "eq"),
                "source": "binding",
                "value": item.get("value"),
            }
        )
    allowed = set(projection) | {item["field"] for item in parameters}
    allowed |= {item["field"] for item in required}
    purpose = str(body.get("purpose") or "").strip()[:300]
    try:
        stored_policy, sensitive, policy_max_rows = await authorize_publication(
            organization_id,
            workspace_id,
            connector_id,
            schema_name=schema_name,
            table_name=table_name,
            operation=operation,
            fields=allowed,
            permissions=permissions,
            purpose=purpose,
        )
    except DataPolicyError as exc:
        raise DataSourceError(exc.status_code, exc.code, exc.message) from exc
    try:
        max_rows = int(body.get("max_rows") or (1 if operation == "get_one" else 50))
    except (TypeError, ValueError):
        max_rows = 50
    max_rows = min(max(max_rows, 1), min(500, policy_max_rows))
    suffix = uuid4().hex[:8]
    # La referencia la genera el servidor: el cliente no elige ni reutiliza
    # una capacidad publicada para sustituir su plan.
    capability_ref = f"data.{schema_name}.{table_name}.{operation}.{suffix}"[:120]
    plan = {
        "schema": "zent.data.query.binding/v1",
        "scope": "workspace",
        "connection_ref": str(connector_id),
        "resource": {
            "schema": schema_name,
            "name": table_name,
            "kind": "view" if table.is_view else "table",
        },
        "operation": operation,
        "projection": projection,
        "allowed_columns": sorted(allowed),
        "required_predicates": required,
        "parameters": parameters,
        "policy": {"max_rows": max_rows, "timeout_ms": 3000, "read_only": True},
        "resource_ref": str(body.get("label") or f"{schema_name}/{table_name}"),
        "column_types": {
            column: str(columns[column].data_type)
            for column in allowed
            if column in columns
        },
        "sensitive_columns": sorted(sensitive),
        "purpose": purpose or None,
        "policy_hash": str(stored_policy.get("policy_hash") or ""),
    }
    binding = await upsert_binding(
        organization_id,
        capability_ref,
        "connected_db",
        config=plan,
        workspace_id=workspace_id,
        created_by=actor_id,
    )
    await record_publication_event(
        organization_id,
        workspace_id,
        action="plan.published",
        actor_id=actor_id,
        connector_id=connector_id,
        binding_id=binding.get("id"),
        capability_ref=capability_ref,
        resource_ref=plan["resource_ref"],
        selected_columns=projection,
        sensitive_columns=sorted(sensitive),
        purpose=purpose or None,
        policy_digest=str(stored_policy.get("policy_hash") or ""),
        plan_digest=_plan_hash(plan),
        metadata={"operation": operation, "max_rows": max_rows},
    )
    invalidate_data_catalog(organization_id, workspace_id)
    return {
        "binding_ref": str(binding.get("id") or ""),
        "capability_ref": capability_ref,
        "resource_ref": plan["resource_ref"],
        "operation": operation,
        "projection": projection,
        "parameters": parameters,
        "max_rows": max_rows,
        "sensitive_columns": sorted(sensitive),
        "policy_hash": plan["policy_hash"],
    }


async def _managed_source(
    organization_id: UUID, workspace_id: UUID, source_id: UUID
) -> Any:
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


async def _source_exists(
    organization_id: UUID, workspace_id: UUID, kind: str, source_id: UUID
) -> bool:
    if kind == "managed_db":
        return await _managed_source(organization_id, workspace_id, source_id) is not None
    from src.infrastructure.postgres.relational_db import PostgresConnectorRepository

    connector = await PostgresConnectorRepository().get_connector(organization_id, source_id)
    if connector is None:
        return False
    if connector.workspace_id and str(connector.workspace_id) != str(workspace_id):
        return False
    return str(connector.status or "").lower() == "active"


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
    session = await get_async_session()
    try:
        connector_rows = (
            await session.execute(
                text(
                    "SELECT id, name, type, status FROM connectors "
                    "WHERE organization_id = :oid AND workspace_id = :wid "
                    "AND type IN ('postgres', 'postgresql') ORDER BY name"
                ),
                {"oid": str(organization_id), "wid": str(workspace_id)},
            )
        ).fetchall()
    finally:
        await session.close()
    for row in connector_rows:
        status = "CONNECTED" if str(row.status or "").lower() == "active" else "DEGRADED"
        sources.append(
            {
                "ref": f"connector:{row.id}",
                "label": str(row.name or "PostgreSQL externo"),
                "provider_kind": "connected_db",
                "status": status,
                "read_only": True,
                "capabilities": ["select", "count"],
                "provider": str(row.type or "postgres"),
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
        if str(binding.get("provider_kind") or "") not in ("managed_db", "connected_db"):
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
    source_kind: str | None = None
    source_id: UUID | None = None
    if source_ref:
        source_kind, source_id = _parse_source_ref(source_ref)
        if not await _source_exists(
            organization_id, workspace_id, source_kind, source_id
        ):
            raise DataSourceError(404, "RESOURCE_NOT_EXPOSED", "fuente no expuesta")

    safe_limit = max(1, min(int(limit or 50), _MAX_LIMIT))
    safe_cursor = max(0, int(cursor or 0))
    resources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for binding, plan in await _published_plans(organization_id, workspace_id, permissions):
        if source_id is not None and plan.connection_ref is not None:
            if plan.connection_ref != source_id:
                continue
        if source_id is not None and source_kind == "connector":
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
        source_kind, source_id = _parse_source_ref(source_ref)
        if not await _source_exists(
            organization_id, workspace_id, source_kind, source_id
        ):
            raise DataSourceError(404, "RESOURCE_NOT_EXPOSED", "fuente no expuesta")
        if plan.connection_ref is not None and plan.connection_ref != source_id:
            raise DataSourceError(404, "RESOURCE_NOT_EXPOSED", "recurso no expuesto")
        if source_kind == "connector":
            allowed = _plan_columns(plan)
            return {
                "resource_ref": resource_ref,
                "binding_ref": str(binding.get("id") or ""),
                "kind": plan.resource.kind,
                "introspected": False,
                "columns": [
                    {
                        "name": column,
                        "label": column,
                        "data_type": plan.column_types.get(column, "unknown"),
                        "nullable": True,
                        "primary_key": False,
                        "foreign_key": False,
                        "foreign_table": None,
                        "foreign_column": None,
                        "sensitive": is_sensitive_column(column),
                        "pii_flags": pii_flags_for_column(column),
                    }
                    for column in sorted(allowed)
                ],
            }
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
    principal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from src.platform.workflows.data_governance import (
        DataPolicyError,
        require_permission,
        validate_plan_against_policy,
    )

    require_permission(permissions, "data_queries:preview")
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

    legacy_plan = not bool(plan.policy_hash)
    if not legacy_plan and plan.connection_ref is not None:
        try:
            await validate_plan_against_policy(
                organization_id,
                workspace_id,
                plan.connection_ref,
                schema_name=plan.resource.schema_name or "public",
                table_name=plan.resource.name,
                fields=_plan_columns(plan),
                plan_policy_digest=plan.policy_hash,
            )
        except DataPolicyError as exc:
            raise DataSourceError(exc.status_code, exc.code, exc.message) from exc

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
        if str(binding.get("provider_kind") or "") == "connected_db":
            from src.platform.workflows.bindings import _execute_connected_select

            result = await _execute_connected_select(
                organization_id,
                preview_binding,
                {"params": dict(params or {})},
                workspace_id=workspace_id,
                principal=principal,
            )
        else:
            result = await _execute_managed_select(
                organization_id,
                preview_binding,
                {"params": dict(params or {})},
                workspace_id=workspace_id,
                principal=principal,
            )
    except BindingError as exc:
        raise DataSourceError(400, exc.code, exc.message) from exc

    sensitive = set(plan.sensitive_columns)
    sensitive |= {column for column in _plan_columns(plan) if is_sensitive_column(column)}
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
    return {
        "preview": True,
        "redacted_fields": redacted,
        "legacy_plan": legacy_plan,
        "policy_hash": plan.policy_hash,
        "result": result,
    }
