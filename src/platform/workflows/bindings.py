# =============================================================================
# Capability Bindings — un workflow portable depende de capacidades lógicas
# (catalog.products.search, payments.checkout.create); el tenant resuelve cada
# capacidad contra un provider concreto: managed db, connected db, acción de
# marketplace, semantic query, REST o ERP.
#
# El runtime de ejecución NO se duplica:
#   - marketplace_action → execute_action (marketplace/runtime.py)
#   - semantic_query     → RAG orchestrator (semantic compiler + text-to-SQL)
#   - managed_db / connected_db → SELECT declarativo validado contra el
#     managed database del tenant (sin SQL arbitrario en plantillas)
#   - rest_api           → httpx con allowlist y SSRF check del runtime
# =============================================================================
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.platform.workflows.values import jsonable

logger = get_logger(__name__)

PROVIDER_KINDS: tuple[str, ...] = (
    "managed_db",
    "connected_db",
    "marketplace_action",
    "semantic_query",
    "rest_api",
    "erp",
    "custom",
    # Datos de negocio de Zent (catálogo, inventario, ventas) y pago
    # desacoplado del proveedor (Stripe / IZIPAY / sandbox).
    "commerce",
    "payment_provider",
    # Mensajería al cliente resuelta por binding (in_app/email/webhook).
    "conversation",
    # P19: acción de inventario gobernada (no SQL libre).
    "inventory",
)

_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)?$")
_SIMPLE_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_MAX_ROWS = 500
_DATA_QUERY_SCHEMA = "zent.data.query.binding/v1"
_QUERY_OPERATORS = ("eq", "ne", "gt", "gte", "lt", "lte", "like", "ilike", "in", "is_null", "is_not_null")
_SQL_OPERATORS = {
    "eq": "=",
    "ne": "<>",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "like": "LIKE",
    "ilike": "ILIKE",
    "in": "IN",
}
_AUTHORITY_KEYS = frozenset(
    {
        "table",
        "schema",
        "columns",
        "projection",
        "filters",
        "where",
        "order_by",
        "limit",
        "offset",
        "sql",
        "query_sql",
        "connection_ref",
        "workspace_id",
        "organization_id",
        "operation",
        "resource",
        "policy",
        "required_predicates",
        "parameters",
        "joins",
    }
)


def _valid_simple_ident(name: str) -> bool:
    return bool(_SIMPLE_IDENT_RE.match(name or ""))


def _plan_hash(config: dict[str, Any]) -> str:
    blob = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _binding_hash(binding: dict[str, Any], plan_hash: str) -> str:
    blob = json.dumps(
        {
            "binding_id": str(binding.get("id") or ""),
            "capability_ref": str(binding.get("capability_ref") or ""),
            "provider_kind": str(binding.get("provider_kind") or ""),
            "plan_hash": plan_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class _PlanBase(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class QueryResource(_PlanBase):
    schema_name: str | None = Field(default=None, alias="schema")
    name: str
    kind: Literal["table", "view"] = "view"

    @field_validator("schema_name", "name")
    @classmethod
    def _ident(cls, value: str | None) -> str | None:
        if value is not None and not _valid_simple_ident(value):
            raise ValueError(f"identificador inválido: {value!r}")
        return value


class QueryPredicate(_PlanBase):
    field: str
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "like", "ilike", "in", "is_null", "is_not_null"] = Field(
        default="eq", alias="op"
    )
    source: Literal["binding"] = "binding"
    value: Any = None

    @field_validator("field")
    @classmethod
    def _field(cls, value: str) -> str:
        if not _valid_simple_ident(value):
            raise ValueError(f"columna inválida: {value!r}")
        return value


class QueryParameter(_PlanBase):
    name: str
    field: str
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "like", "ilike", "in"] = "eq"
    type: Literal["string", "integer", "number", "boolean", "date", "datetime"] = "string"
    required: bool = True

    @field_validator("name", "field")
    @classmethod
    def _ident(cls, value: str) -> str:
        if not _valid_simple_ident(value):
            raise ValueError(f"identificador inválido: {value!r}")
        return value


class QuerySort(_PlanBase):
    field: str
    direction: Literal["asc", "desc"] = "asc"

    @field_validator("field")
    @classmethod
    def _field(cls, value: str) -> str:
        if not _valid_simple_ident(value):
            raise ValueError(f"columna inválida: {value!r}")
        return value


class QueryPolicy(_PlanBase):
    max_rows: int = Field(default=50, ge=1, le=_MAX_ROWS)
    timeout_ms: int = Field(default=3000, ge=100, le=30_000)
    read_only: Literal[True] = True
    pii_class: Literal["public", "internal", "personal", "sensitive"] = "internal"
    max_bytes: int = Field(default=262_144, ge=1024, le=5_242_880)


class QueryOwnership(_PlanBase):
    field: str
    principal_claim: str
    required: bool = True

    @field_validator("field", "principal_claim")
    @classmethod
    def _ident(cls, value: str) -> str:
        if not _valid_simple_ident(value):
            raise ValueError(f"identificador inválido: {value!r}")
        return value


class DataQueryPlan(_PlanBase):
    plan_schema: Literal["zent.data.query.binding/v1"] = Field(alias="schema")
    scope: Literal["workspace", "organization"] = "workspace"
    allowed_workspace_ids: list[UUID] = Field(default_factory=list)
    connection_ref: UUID | None = None
    resource: QueryResource
    operation: Literal["get_one", "list", "count"] = "list"
    projection: list[str] = Field(min_length=1)
    allowed_columns: list[str] = Field(default_factory=list)
    required_predicates: list[QueryPredicate] = Field(default_factory=list)
    parameters: list[QueryParameter] = Field(default_factory=list)
    order_by: list[QuerySort] = Field(default_factory=list)
    policy: QueryPolicy = Field(default_factory=QueryPolicy)
    ownership: QueryOwnership | None = None
    resource_ref: str | None = None
    column_types: dict[str, str] = Field(default_factory=dict)

    @field_validator("projection", "allowed_columns")
    @classmethod
    def _columns(cls, value: list[str]) -> list[str]:
        if "*" in value:
            raise ValueError("SELECT * no está permitido")
        for column in value:
            if not _valid_simple_ident(column):
                raise ValueError(f"columna inválida: {column!r}")
        return value

    @field_validator("parameters")
    @classmethod
    def _unique_parameters(cls, value: list[QueryParameter]) -> list[QueryParameter]:
        names = [item.name for item in value]
        if len(names) != len(set(names)):
            raise ValueError("parámetros duplicados")
        return value

    @field_validator("column_types")
    @classmethod
    def _column_types(cls, value: dict[str, str]) -> dict[str, str]:
        for column in value:
            if not _valid_simple_ident(column):
                raise ValueError(f"columna inválida: {column!r}")
        return value


def parse_data_query_plan(config: dict[str, Any] | None) -> DataQueryPlan | None:
    """Devuelve el plan canónico o None para bindings legacy."""
    if not isinstance(config, dict) or config.get("schema") != _DATA_QUERY_SCHEMA:
        return None
    try:
        return DataQueryPlan.model_validate(config)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in exc.errors()[:5]
        )
        raise BindingError("NEEDS_CONFIGURATION", f"plan inválido: {details}") from exc


_BINDING_DDL = """
CREATE TABLE IF NOT EXISTS workflow_capability_bindings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    workspace_id UUID,
    capability_ref VARCHAR(120) NOT NULL,
    provider_kind VARCHAR(40) NOT NULL,
    config JSONB NOT NULL DEFAULT '{}',
    credential_ref VARCHAR(160),
    contract_input_schema JSONB NOT NULL DEFAULT '{}',
    contract_output_schema JSONB NOT NULL DEFAULT '{}',
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


async def ensure_binding_tables() -> None:
    session = await get_async_session()
    try:
        await session.execute(text(_BINDING_DDL))
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        logger.warning("ensure_binding_tables failed", error=str(exc)[:200])
    finally:
        await session.close()


def _row(r: Any) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "organization_id": str(r.organization_id),
        "workspace_id": str(r.workspace_id) if r.workspace_id else None,
        "capability_ref": str(r.capability_ref),
        "provider_kind": str(r.provider_kind),
        "config": dict(r.config or {}),
        "credential_ref": r.credential_ref,
        "contract_input_schema": dict(r.contract_input_schema or {}),
        "contract_output_schema": dict(r.contract_output_schema or {}),
        "status": str(r.status),
    }


_BINDING_COLS = (
    "id, organization_id, workspace_id, capability_ref, provider_kind, config, "
    "credential_ref, contract_input_schema, contract_output_schema, status"
)


async def upsert_binding(
    organization_id: UUID,
    capability_ref: str,
    provider_kind: str,
    *,
    config: dict[str, Any] | None = None,
    workspace_id: UUID | None = None,
    credential_ref: str | None = None,
    contract_input_schema: dict[str, Any] | None = None,
    contract_output_schema: dict[str, Any] | None = None,
    created_by: UUID | None = None,
) -> dict[str, Any]:
    """Crea o actualiza el binding de una capacidad (por workspace u org-level)."""
    if provider_kind not in PROVIDER_KINDS:
        raise ValueError(f"provider_kind inválido: {provider_kind}")
    ref = str(capability_ref).strip()
    if not ref or len(ref) > 120:
        raise ValueError("capability_ref inválido")
    await ensure_binding_tables()
    session = await get_async_session()
    try:
        if workspace_id is not None:
            conflict = "(organization_id, workspace_id, capability_ref) WHERE workspace_id IS NOT NULL"
        else:
            conflict = "(organization_id, capability_ref) WHERE workspace_id IS NULL"
        row = (
            await session.execute(
                text(
                    "INSERT INTO workflow_capability_bindings "
                    "(organization_id, workspace_id, capability_ref, provider_kind, config, "
                    "credential_ref, contract_input_schema, contract_output_schema, created_by) "
                    "VALUES (:oid, :ws, :ref, :kind, CAST(:cfg AS jsonb), :cred, "
                    "CAST(:is AS jsonb), CAST(:os AS jsonb), :uid) "
                    f"ON CONFLICT {conflict} DO UPDATE SET "
                    "provider_kind = EXCLUDED.provider_kind, config = EXCLUDED.config, "
                    "credential_ref = EXCLUDED.credential_ref, "
                    "contract_input_schema = EXCLUDED.contract_input_schema, "
                    "contract_output_schema = EXCLUDED.contract_output_schema, "
                    "status = 'active', updated_at = NOW() "
                    f"RETURNING {_BINDING_COLS}"
                ),
                {
                    "oid": str(organization_id),
                    "ws": str(workspace_id) if workspace_id else None,
                    "ref": ref,
                    "kind": provider_kind,
                    "cfg": json.dumps(config or {}, ensure_ascii=False, default=str),
                    "cred": credential_ref,
                    "is": json.dumps(contract_input_schema or {}, ensure_ascii=False),
                    "os": json.dumps(contract_output_schema or {}, ensure_ascii=False),
                    "uid": str(created_by) if created_by else None,
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    try:
        from src.platform.workflows.data_sources import invalidate_data_catalog

        invalidate_data_catalog(organization_id, workspace_id)
    except Exception:  # noqa: BLE001 — la cache no rompe el guardado
        pass
    return _row(row)


async def list_bindings(organization_id: UUID, workspace_id: UUID | None = None) -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    f"SELECT {_BINDING_COLS} FROM workflow_capability_bindings "
                    "WHERE organization_id = :oid AND status = 'active' "
                    "AND (workspace_id IS NULL OR workspace_id = :ws) "
                    "ORDER BY capability_ref"
                ),
                {"oid": str(organization_id), "ws": str(workspace_id) if workspace_id else None},
            )
        ).fetchall()
    finally:
        await session.close()
    return {"bindings": [_row(r) for r in rows]}


async def delete_binding(organization_id: UUID, binding_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "UPDATE workflow_capability_bindings SET status = 'disabled', updated_at = NOW() "
                "WHERE id = :bid AND organization_id = :oid AND status = 'active'"
            ),
            {"bid": str(binding_id), "oid": str(organization_id)},
        )
        await session.commit()
        changed = result.rowcount > 0
    finally:
        await session.close()
    if changed:
        try:
            from src.platform.workflows.data_sources import invalidate_data_catalog

            invalidate_data_catalog(organization_id)
        except Exception:  # noqa: BLE001 — la cache no rompe el borrado
            pass
    return changed


async def resolve_binding(
    organization_id: UUID, capability_ref: str, workspace_id: UUID | None = None
) -> dict[str, Any] | None:
    """Binding exacto del workspace → binding org-level. None si no existe."""
    await ensure_binding_tables()
    session = await get_async_session()
    try:
        row = None
        if workspace_id is not None:
            row = (
                await session.execute(
                    text(
                        f"SELECT {_BINDING_COLS} FROM workflow_capability_bindings "
                        "WHERE organization_id = :oid AND workspace_id = :ws "
                        "AND capability_ref = :ref AND status = 'active' LIMIT 1"
                    ),
                    {"oid": str(organization_id), "ws": str(workspace_id), "ref": capability_ref},
                )
            ).fetchone()
        if row is None:
            row = (
                await session.execute(
                    text(
                        f"SELECT {_BINDING_COLS} FROM workflow_capability_bindings "
                        "WHERE organization_id = :oid AND workspace_id IS NULL "
                        "AND capability_ref = :ref AND status = 'active' LIMIT 1"
                    ),
                    {"oid": str(organization_id), "ref": capability_ref},
                )
            ).fetchone()
    finally:
        await session.close()
    return _row(row) if row else None


async def get_binding(
    organization_id: UUID,
    binding_id: UUID,
    *,
    workspace_id: UUID | None = None,
) -> dict[str, Any] | None:
    """Binding exacto por id, acotado a organización y workspace."""
    await ensure_binding_tables()
    session = await get_async_session()
    try:
        sql = (
            f"SELECT {_BINDING_COLS} FROM workflow_capability_bindings "
            "WHERE id = :bid AND organization_id = :oid AND status = 'active'"
        )
        params: dict[str, Any] = {"bid": str(binding_id), "oid": str(organization_id)}
        if workspace_id is not None:
            sql += " AND (workspace_id IS NULL OR workspace_id = :ws)"
            params["ws"] = str(workspace_id)
        sql += " LIMIT 1"
        row = (await session.execute(text(sql), params)).fetchone()
    finally:
        await session.close()
    return _row(row) if row else None


# ---------------------------------------------------------------------------
# Contratos (validación input/output declarativa)
# ---------------------------------------------------------------------------
def _type_ok(value: Any, want: str) -> bool:
    if want == "string":
        return isinstance(value, str)
    if want == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if want == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if want == "boolean":
        return isinstance(value, bool)
    if want == "object":
        return isinstance(value, dict)
    if want == "array":
        return isinstance(value, list)
    return True


def _coerce_structured(value: Any, want: str) -> Any:
    """Las referencias del grafo serializan listas/objetos como JSON.

    Un `items: "{{instance.state.cart.items}}"` llega como string JSON; el
    contrato debe validar la ESTRUCTURA, no su representación textual."""
    if want not in ("array", "object") or not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped[:1] not in ("[", "{"):
        return value
    try:
        return json.loads(stripped)
    except ValueError:
        return value


def validate_contract(payload: dict[str, Any], schema: dict[str, Any] | None) -> list[str]:
    """Errores de contrato (required + tipos básicos). Vacío = OK."""
    schema = schema or {}
    errors: list[str] = []
    for key in schema.get("required") or []:
        if key not in payload or payload.get(key) is None:
            errors.append(f"falta requerido: {key}")
    props = schema.get("properties") or {}
    for key, spec in props.items():
        if key not in payload or payload.get(key) is None:
            continue
        want = str((spec or {}).get("type") or "")
        value = _coerce_structured(payload.get(key), want)
        if want and not _type_ok(value, want):
            errors.append(f"tipo inválido en {key}: esperado {want}")
    return errors


# ---------------------------------------------------------------------------
# Ejecución
# ---------------------------------------------------------------------------
class BindingError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def execute_binding(
    organization_id: UUID,
    capability_ref: str,
    inputs: dict[str, Any] | None = None,
    *,
    workspace_id: UUID | None = None,
    source: str = "workflow",
    actor_id: UUID | None = None,
    workflow_id: UUID | None = None,
    run_id: UUID | None = None,
    instance_id: UUID | None = None,
    node_id: str | None = None,
) -> dict[str, Any]:
    """Ejecuta una capacidad resuelta por el binding del tenant.

    `instance_id` + `node_id` forman, junto al `business_operation_id`, la
    identidad lógica estable de una operación financiera: un retry repite la
    MISMA operación y nunca duplica un cobro.

    Lanza BindingError(code) para estados accionables: NEEDS_CONFIGURATION,
    NEEDS_CREDENTIALS, DISABLED, PROVIDER_NOT_IMPLEMENTED, CONTRACT_INVALID."""
    binding = await resolve_binding(organization_id, capability_ref, workspace_id)
    if binding is None:
        raise BindingError(
            "NEEDS_CONFIGURATION",
            f"la capacidad {capability_ref} no tiene binding configurado",
        )
    payload = dict(inputs or {})
    errors = validate_contract(payload, binding.get("contract_input_schema"))
    if errors:
        raise BindingError("CONTRACT_INVALID", "; ".join(errors[:5]))

    kind = binding["provider_kind"]
    ledger_eid: str | None = None
    if kind in ("rest_api", "marketplace_action", "inventory") and workflow_id and node_id:
        from src.platform.workflows.effect_ledger import begin_effect

        ledger_eid, confirmed = await begin_effect(
            organization_id=organization_id,
            workspace_id=workspace_id,
            workflow_id=workflow_id,
            instance_id=instance_id,
            run_id=run_id,
            node_id=node_id,
            capability_ref=capability_ref,
            inputs=payload,
        )
        if confirmed is not None:
            return {
                "capability": capability_ref,
                "provider_kind": kind,
                "output": confirmed,
                "effect_replayed": True,
            }
    try:
        out = await _dispatch_binding(
            organization_id,
            capability_ref,
            binding,
            payload,
            kind=kind,
            workspace_id=workspace_id,
            source=source,
            actor_id=actor_id,
            workflow_id=workflow_id,
            run_id=run_id,
            instance_id=instance_id,
            node_id=node_id,
        )
        if ledger_eid is not None:
            from src.platform.workflows.effect_ledger import confirm_effect

            await confirm_effect(
                organization_id=organization_id,
                eid=ledger_eid,
                response=dict(out or {}),
                external_id=str((out or {}).get("id") or (out or {}).get("reference") or ""),
            )
    except Exception as exc:
        if ledger_eid is not None:
            from src.platform.workflows.effect_ledger import fail_effect

            await fail_effect(
                organization_id=organization_id,
                eid=ledger_eid,
                error=str(exc)[:400],
            )
        raise
    output_errors = validate_contract(dict(out or {}), binding.get("contract_output_schema"))
    if output_errors:
        raise BindingError("CONTRACT_INVALID", "salida: " + "; ".join(output_errors[:5]))
    return {"capability": capability_ref, "provider_kind": kind, "output": out}


async def _dispatch_binding(
    organization_id: UUID,
    capability_ref: str,
    binding: dict[str, Any],
    payload: dict[str, Any],
    *,
    kind: str,
    workspace_id: UUID | None,
    source: str,
    actor_id: UUID | None,
    workflow_id: UUID | None,
    run_id: UUID | None,
    instance_id: UUID | None,
    node_id: str | None,
) -> dict[str, Any]:
    if kind == "marketplace_action":
        out = await _execute_marketplace_action(
            organization_id,
            binding,
            payload,
            workspace_id=workspace_id,
            source=source,
            actor_id=actor_id,
            workflow_id=workflow_id,
            run_id=run_id,
        )
    elif kind == "semantic_query":
        out = await _execute_semantic_query(organization_id, binding, payload, workspace_id=workspace_id)
    elif kind == "managed_db":
        out = await _execute_managed_select(organization_id, binding, payload, workspace_id=workspace_id)
    elif kind == "connected_db":
        out = await _execute_connected_select(
            organization_id, binding, payload, workspace_id=workspace_id
        )
    elif kind == "rest_api":
        out = await _execute_rest(organization_id, binding, payload)
    elif kind == "commerce":
        out = await _execute_commerce(
            organization_id,
            binding,
            payload,
            workspace_id=workspace_id,
            instance_id=instance_id,
            node_id=node_id,
            workflow_id=workflow_id,
            run_id=run_id,
        )
    elif kind == "payment_provider":
        out = await _execute_payment(
            organization_id,
            binding,
            payload,
            workspace_id=workspace_id,
            instance_id=instance_id,
            node_id=node_id,
            workflow_id=workflow_id,
            run_id=run_id,
        )
    elif kind == "conversation":
        from src.platform.workflows.conversation_capability import (
            execute_conversation_capability,
        )

        try:
            out = await execute_conversation_capability(
                organization_id,
                binding["capability_ref"],
                payload,
                workspace_id=workspace_id,
                instance_id=instance_id,
                node_id=node_id,
                workflow_id=workflow_id,
                run_id=run_id,
                binding=binding,
            )
        except BindingError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BindingError("PROVIDER_ERROR", f"mensajería falló: {str(exc)[:200]}") from exc
    elif kind == "inventory":
        out = await _execute_inventory_action(
            organization_id, binding, payload, workspace_id=workspace_id
        )
    else:
        raise BindingError(
            "PROVIDER_NOT_IMPLEMENTED",
            f"provider_kind {kind} registrado sin executor en esta versión",
        )
    return out


def _business_error(exc: Exception) -> BindingError:
    """Traduce errores de negocio a códigos accionables del binder."""
    code = str(getattr(exc, "code", "") or "PROVIDER_ERROR")
    message = str(getattr(exc, "message", "") or str(exc))[:300]
    aliases = {
        "NEEDS_CREDENTIALS": "NEEDS_CREDENTIALS",
        "PROVIDER_UNKNOWN": "NEEDS_CONFIGURATION",
        "ORDER_NOT_FOUND": "NOT_FOUND",
        "CHECKOUT_NOT_FOUND": "NOT_FOUND",
        "PRODUCT_NOT_FOUND": "NOT_FOUND",
        "INVALID_ORDER_TRANSITION": "CONFLICT",
        "ORDER_CONFLICT": "CONFLICT",
        "CHECKOUT_CONFLICT": "CONFLICT",
        "ALREADY_PAID": "CONFLICT",
        "NOT_PAID": "CONFLICT",
        "ORDER_CLOSED": "CONFLICT",
        "INSUFFICIENT_STOCK": "CONFLICT",
    }
    return BindingError(aliases.get(code, code), message)


async def _execute_commerce(
    organization_id: UUID,
    binding: dict[str, Any],
    payload: dict[str, Any],
    *,
    workspace_id: UUID | None,
    instance_id: UUID | None,
    node_id: str | None,
    workflow_id: UUID | None,
    run_id: UUID | None,
) -> dict[str, Any]:
    from src.platform.commerce.capabilities import execute_commerce_capability
    from src.platform.commerce.store import CommerceError

    try:
        return await execute_commerce_capability(
            organization_id,
            binding["capability_ref"],
            payload,
            workspace_id=workspace_id,
            instance_id=instance_id,
            node_id=node_id,
            workflow_id=workflow_id,
            run_id=run_id,
            binding=binding,
        )
    except CommerceError as exc:
        raise _business_error(exc) from exc
    except BindingError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BindingError("PROVIDER_ERROR", f"commerce falló: {str(exc)[:200]}") from exc


async def _execute_payment(
    organization_id: UUID,
    binding: dict[str, Any],
    payload: dict[str, Any],
    *,
    workspace_id: UUID | None,
    instance_id: UUID | None,
    node_id: str | None,
    workflow_id: UUID | None,
    run_id: UUID | None,
) -> dict[str, Any]:
    from src.platform.commerce.capabilities import execute_payment_capability
    from src.platform.commerce.payments.base import PaymentProviderError

    # El tenant elige el proveedor en el binding; el payload puede forzarlo
    # (multi-proveedor) sin que el workflow nombre a ninguno.
    config_provider = str((binding.get("config") or {}).get("provider") or "")
    if config_provider and not payload.get("provider"):
        payload = {**payload, "provider": config_provider}
    try:
        return await execute_payment_capability(
            organization_id,
            binding["capability_ref"],
            payload,
            workspace_id=workspace_id,
            instance_id=instance_id,
            node_id=node_id,
            workflow_id=workflow_id,
            run_id=run_id,
            binding=binding,
        )
    except PaymentProviderError as exc:
        raise _business_error(exc) from exc
    except BindingError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BindingError("PROVIDER_ERROR", f"pago falló: {str(exc)[:200]}") from exc


async def _execute_marketplace_action(
    organization_id: UUID,
    binding: dict[str, Any],
    payload: dict[str, Any],
    *,
    workspace_id: UUID | None,
    source: str,
    actor_id: UUID | None,
    workflow_id: UUID | None,
    run_id: UUID | None,
) -> dict[str, Any]:
    from src.platform.marketplace.resolver import resolve_capability
    from src.platform.marketplace.runtime import execute_action

    config = binding.get("config") or {}
    action_id = str(config.get("action_id") or "")
    if not action_id:
        raise BindingError("NEEDS_CONFIGURATION", "marketplace_action requiere config.action_id")
    install_id = config.get("install_id")
    if not install_id:
        resolved = await resolve_capability(organization_id, binding["capability_ref"], workspace_id=workspace_id)
        install_id = resolved.get("install_id")
        if not install_id:
            raise BindingError(
                "NEEDS_CREDENTIALS",
                f"el proveedor {resolved.get('provider_name') or config.get('action_id')} no está instalado",
            )
    outcome = await execute_action(
        organization_id,
        UUID(str(install_id)),
        action_id,
        payload,
        workspace_id=workspace_id,
        workflow_id=workflow_id,
        run_id=run_id,
        actor_id=actor_id,
        actor_type="workflow" if source == "workflow" else source,
        source=source,
    )
    if not outcome.ok:
        code = str(getattr(outcome, "error_code", "") or "PROVIDER_ERROR")
        if code in ("NOT_INSTALLED", "CREDENTIALS_MISSING"):
            code = "NEEDS_CREDENTIALS"
        if code == "APPROVAL_REQUIRED":
            raise BindingError("DISABLED", getattr(outcome, "error_message", "") or code)
        raise BindingError(code, str(getattr(outcome, "error_message", "") or "provider error"))
    data = dict(getattr(outcome, "data", {}) or {})
    return data


async def _execute_semantic_query(
    organization_id: UUID,
    binding: dict[str, Any],
    payload: dict[str, Any],
    *,
    workspace_id: UUID | None,
) -> dict[str, Any]:
    """Pregunta de negocio → pipeline semántico (compiler + text-to-SQL)."""
    config = binding.get("config") or {}
    question = str(payload.get("question") or payload.get("ask") or config.get("question") or "")
    if not question:
        raise BindingError("CONTRACT_INVALID", "semantic_query requiere question")
    try:
        from src.api.deps import get_rag_orchestrator

        orchestrator = get_rag_orchestrator()
        meta = {"workspace_id": str(workspace_id)} if workspace_id else None
        result = await orchestrator.execute(
            organization_id=organization_id,
            user_id=None,
            query=question,
            role="admin",
            language="es",
            metadata_filters=meta,
            trace_id=f"binding:{binding['capability_ref']}",
        )
    except Exception as exc:  # noqa: BLE001
        raise BindingError("PROVIDER_ERROR", f"semantic query falló: {str(exc)[:200]}") from exc
    structured = getattr(result, "structured_output", None) or {}
    return {
        "answer": (result.llm_response.content if getattr(result, "llm_response", None) is not None else None),
        "rows": list(structured.get("rows") or []),
        "columns": list(structured.get("columns") or []),
        "row_count": int(structured.get("row_count") or 0),
        "sql_query": getattr(result, "sql_query", None),
        "method": getattr(result, "method", None),
    }


def _q(ident: str) -> str:
    if not _IDENT_RE.match(ident or ""):
        raise BindingError("CONTRACT_INVALID", f"identificador inválido: {ident}")
    return ident


def _param_type_ok(value: Any, want: str) -> bool:
    if want == "string":
        return isinstance(value, str) and len(value) <= 500
    if want == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if want == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if want == "boolean":
        return isinstance(value, bool)
    if want in ("date", "datetime"):
        return isinstance(value, str) and 4 <= len(value) <= 64
    return False


def _like_pattern_ok(value: str) -> bool:
    if len(value) > 64:
        return False
    if value.startswith("%"):
        return False
    return value.count("%") <= 2 and value.count("_") <= 4


def _build_where(
    predicates: list[tuple[str, str, Any]],
) -> tuple[list[str], dict[str, Any]]:
    parts: list[str] = []
    params: dict[str, Any] = {}
    counter = 0
    for field, operator, value in predicates:
        if not _valid_simple_ident(field):
            raise BindingError("INVALID_PARAMS", f"columna inválida: {field}")
        if operator not in _QUERY_OPERATORS:
            raise BindingError("INVALID_PARAMS", f"operador no permitido: {operator}")
        col = _q(field)
        if operator == "is_null":
            parts.append(f"{col} IS NULL")
            continue
        if operator == "is_not_null":
            parts.append(f"{col} IS NOT NULL")
            continue
        if operator == "in":
            if not isinstance(value, (list, tuple)) or not value or len(value) > 50:
                raise BindingError("INVALID_PARAMS", f"{field}: lista inválida")
            names = []
            for item in value:
                if isinstance(item, (dict, list, tuple)):
                    raise BindingError("INVALID_PARAMS", f"{field}: valor de lista inválido")
                name = f"p{counter}"
                counter += 1
                names.append(f":{name}")
                params[name] = item
            parts.append(f"{col} IN ({', '.join(names)})")
            continue
        if value is None:
            raise BindingError("INVALID_PARAMS", f"{field}: valor requerido")
        if operator in ("like", "ilike"):
            if not isinstance(value, str) or not _like_pattern_ok(value):
                raise BindingError("INVALID_PARAMS", f"{field}: patrón no permitido")
        name = f"p{counter}"
        counter += 1
        parts.append(f"{col} {_SQL_OPERATORS[operator]} :{name}")
        params[name] = value
    return parts, params


async def _execute_sql(
    session: Any,
    sql: str,
    params: dict[str, Any],
    *,
    timeout_ms: int,
):
    try:
        await session.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
        return await asyncio.wait_for(
            session.execute(text(sql), params),
            timeout=(timeout_ms / 1000.0) + 0.5,
        )
    except (asyncio.TimeoutError, TimeoutError) as exc:
        raise BindingError("TIMEOUT", "la consulta excedió el tiempo autorizado") from exc


def _query_failure(exc: Exception) -> BindingError:
    message = str(exc).lower()
    if "statement timeout" in message or "canceling statement" in message:
        return BindingError("TIMEOUT", "la consulta excedió el tiempo autorizado")
    if "permission denied" in message or "insufficient privilege" in message:
        return BindingError("PERMISSION_DENIED", "la fuente denegó el acceso de lectura")
    if "does not exist" in message or "undefinedtable" in message or "undefined column" in message:
        return BindingError("RESOURCE_NOT_EXPOSED", "el recurso no está expuesto para esta consulta")
    if "connect" in message or "connection" in message or "server closed" in message:
        return BindingError("CONNECTION_FAILED", "no se pudo conectar a la fuente")
    if "getaddrinfo" in message or "name or service" in message:
        return BindingError("CONNECTION_FAILED", "no se pudo resolver el host de la fuente")
    return BindingError("PROVIDER_ERROR", f"la consulta falló ({type(exc).__name__})")


def _output_columns(plan: DataQueryPlan) -> list[dict[str, Any]]:
    return [
        {
            "name": column,
            "type": plan.column_types.get(column, "unknown"),
            "label": column.replace("_", " "),
        }
        for column in plan.projection
    ]


def _record_size(data: Any) -> int:
    return len(json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"))


async def _execute_data_query_plan(
    organization_id: UUID,
    binding: dict[str, Any],
    plan: DataQueryPlan,
    payload: dict[str, Any],
    *,
    workspace_id: UUID | None,
    principal: dict[str, Any] | None = None,
    session_factory: Any | None = None,
) -> dict[str, Any]:
    from src.platform.managed_db.service import open_managed_query_session

    if set(payload or {}) - {"params"}:
        raise BindingError(
            "UNEXPECTED_PARAMETER",
            "el payload solo puede enviar params; los recursos se resuelven en el servidor",
        )
    raw_params = (payload or {}).get("params")
    params_input = raw_params if isinstance(raw_params, dict) else {}
    if raw_params is not None and not isinstance(raw_params, dict):
        raise BindingError("INVALID_PARAMS", "params debe ser un objeto")

    if plan.scope == "organization":
        if workspace_id is None:
            raise BindingError("NEEDS_CONFIGURATION", "la consulta org-level requiere workspace")
        if workspace_id not in plan.allowed_workspace_ids:
            raise BindingError("PERMISSION_DENIED", "el workspace no tiene el binding autorizado")
    else:
        if not binding.get("workspace_id"):
            raise BindingError(
                "NEEDS_CONFIGURATION",
                "el plan workspace debe estar guardado en un binding de workspace",
            )
        if str(binding["workspace_id"]) != str(workspace_id):
            raise BindingError("PERMISSION_DENIED", "el binding pertenece a otro workspace")

    allowed_fields = set(plan.projection) | set(plan.allowed_columns)
    allowed_fields |= {item.field for item in plan.required_predicates}
    allowed_fields |= {item.field for item in plan.parameters}
    allowed_fields |= {item.field for item in plan.order_by}
    if plan.ownership is not None:
        allowed_fields.add(plan.ownership.field)
    if plan.allowed_columns:
        declared_fields = set(allowed_fields)
        if not declared_fields.issubset(set(plan.allowed_columns)):
            raise BindingError(
                "NEEDS_CONFIGURATION",
                "el plan usa columnas fuera de allowed_columns",
            )
    for field in allowed_fields:
        if not _valid_simple_ident(field):
            raise BindingError("NEEDS_CONFIGURATION", f"columna inválida en el plan: {field}")

    declared = {item.name for item in plan.parameters}
    unknown = set(params_input) - declared
    if unknown:
        raise BindingError(
            "UNEXPECTED_PARAMETER",
            f"parámetros no declarados: {', '.join(sorted(unknown)[:5])}",
        )

    predicates: list[tuple[str, str, Any]] = []
    for item in plan.required_predicates:
        if item.operator not in ("is_null", "is_not_null") and item.value is None:
            raise BindingError("NEEDS_CONFIGURATION", f"predicado sin valor: {item.field}")
        predicates.append((item.field, item.operator, item.value))

    for item in plan.parameters:
        if item.name not in params_input:
            if item.required:
                raise BindingError("INVALID_PARAMS", f"falta el parámetro {item.name}")
            continue
        value = params_input[item.name]
        if not _param_type_ok(value, item.type):
            raise BindingError("INVALID_PARAMS", f"tipo inválido en {item.name}: esperado {item.type}")
        predicates.append((item.field, item.operator, value))

    if plan.ownership is not None and plan.ownership.required:
        resolved_principal = principal if isinstance(principal, dict) else {}
        owner_value = resolved_principal.get(plan.ownership.principal_claim)
        if owner_value is None or str(owner_value).strip() == "":
            raise BindingError("PERMISSION_DENIED", "identidad del titular no verificada")
        predicates.append((plan.ownership.field, "eq", owner_value))

    where_parts, params = _build_where(predicates)
    table = _q(plan.resource.name)
    if plan.resource.schema_name:
        table = f"{_q(plan.resource.schema_name)}.{table}"
    cols_sql = ", ".join(_q(column) for column in plan.projection)
    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
    order_sql = ""
    if plan.order_by and plan.operation != "count":
        order_sql = " ORDER BY " + ", ".join(f"{_q(item.field)} {item.direction.upper()}" for item in plan.order_by)

    if plan.operation == "count":
        sql = f"SELECT COUNT(*) AS row_count FROM {table}{where_sql}"
    else:
        row_limit = plan.policy.max_rows + (1 if plan.operation == "list" else 1)
        if plan.operation == "get_one":
            row_limit = 2
        sql = f"SELECT {cols_sql} FROM {table}{where_sql}{order_sql} LIMIT {row_limit}"

    started = datetime.now(timezone.utc)
    if session_factory is not None:
        session = session_factory()
    else:
        session = await open_managed_query_session(
            organization_id, workspace_id, database_id=plan.connection_ref
        )
    if session is None:
        raise BindingError("NEEDS_CONFIGURATION", "no hay managed database para el tenant")
    try:
        try:
            result = await _execute_sql(session, sql, params, timeout_ms=plan.policy.timeout_ms)
            rows = result.fetchall()
        except BindingError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _query_failure(exc) from exc
    finally:
        await session.close()

    duration_ms = max(0, int((datetime.now(timezone.utc) - started).total_seconds() * 1000))
    plan_hash = _plan_hash(binding.get("config") or {})
    binding_hash = _binding_hash(binding, plan_hash)
    source_ref = plan.resource_ref or f"{plan.resource.kind}:{table}"
    columns = _output_columns(plan)
    base: dict[str, Any] = {
        "status": "FOUND",
        "found": False,
        "record": None,
        "rows": [],
        "columns": columns,
        "row_count": 0,
        "truncated": False,
        "data_as_of": None,
        "source_ref": source_ref,
        "binding_ref": str(binding.get("id") or ""),
        "binding_hash": binding_hash,
        "duration_ms": duration_ms,
        "reason_code": None,
        "provenance": {
            "provider_kind": str(binding.get("provider_kind") or "managed_db"),
            "queried_at": started.isoformat(),
            "resource_kind": plan.resource.kind,
        },
    }

    if plan.operation == "count":
        count = int(rows[0]._mapping["row_count"]) if rows else 0
        return {**base, "status": "FOUND", "found": True, "row_count": count, "rows": []}

    if plan.operation == "get_one":
        if not rows:
            return {
                **base,
                "status": "NOT_FOUND",
                "reason_code": "NOT_FOUND",
            }
        if len(rows) > 1:
            return {
                **base,
                "status": "MULTIPLE_MATCHES",
                "row_count": len(rows),
                "reason_code": "MULTIPLE_MATCHES",
            }
        record = jsonable(dict(rows[0]._mapping))
        if _record_size(record) > plan.policy.max_bytes:
            raise BindingError("INVALID_PARAMS", "el registro excede el tamaño autorizado")
        return {
            **base,
            "status": "FOUND",
            "found": True,
            "record": record,
            "row_count": 1,
        }

    data = [jsonable(dict(row._mapping)) for row in rows]
    truncated = len(data) > plan.policy.max_rows
    data = data[: plan.policy.max_rows]
    while data and _record_size(data) > plan.policy.max_bytes:
        data.pop()
        truncated = True
    return {
        **base,
        "status": "FOUND",
        "found": bool(data),
        "rows": data,
        "row_count": len(data),
        "truncated": truncated,
    }


async def _execute_legacy_select(
    organization_id: UUID,
    binding: dict[str, Any],
    payload: dict[str, Any],
    *,
    workspace_id: UUID | None,
) -> dict[str, Any]:
    """Camino legacy seguro: la configuración manda, el payload no la sustituye."""
    from src.platform.managed_db.service import open_managed_query_session

    unexpected = set(payload or {}) & _AUTHORITY_KEYS
    if unexpected:
        raise BindingError(
            "UNEXPECTED_PARAMETER",
            f"parámetros de autoridad no permitidos: {', '.join(sorted(unexpected)[:5])}",
        )
    config = binding.get("config") or {}
    table = _q(str(config.get("table") or ""))
    if not table:
        raise BindingError("NEEDS_CONFIGURATION", "managed_db requiere config.table")
    columns = config.get("columns")
    if not isinstance(columns, list) or not columns:
        raise BindingError(
            "NEEDS_CONFIGURATION",
            "managed_db legacy requiere config.columns explícito; SELECT * no está permitido",
        )
    if "*" in columns:
        raise BindingError("NEEDS_CONFIGURATION", "SELECT * no está permitido")
    cols_sql = ", ".join(_q(str(column)) for column in columns)
    filters = config.get("filters") or {}
    if not isinstance(filters, dict):
        filters = {}
    predicates: list[tuple[str, str, Any]] = []
    for column, value in list(filters.items())[:20]:
        if isinstance(value, dict):
            predicates.append((str(column), str(value.get("op") or "eq"), value.get("value")))
        else:
            predicates.append((str(column), "eq", value))
    # Compatibilidad: inputs planos que coinciden con una columna proyectada o
    # filtrada se aceptan como parámetros eq. Nunca table/columns/limit/order_by.
    accepted = {str(column) for column in columns} | {item[0] for item in predicates}
    for key, value in list((payload or {}).items())[:20]:
        if key in accepted and not any(item[0] == key for item in predicates):
            predicates.append((str(key), "eq", value))
    where_parts, params = _build_where(predicates)
    order_by = config.get("order_by")
    order_sql = ""
    if order_by:
        direction = "ASC"
        if isinstance(order_by, dict):
            direction = "DESC" if str(order_by.get("dir") or "asc").lower() == "desc" else "ASC"
            order_by = order_by.get("column")
        if order_by:
            order_sql = f" ORDER BY {_q(str(order_by))} {direction}"
    try:
        limit = min(max(int(config.get("limit") or 50), 1), _MAX_ROWS)
    except (TypeError, ValueError):
        limit = 50
    sql = f"SELECT {cols_sql} FROM {table}"
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    sql += order_sql + f" LIMIT {limit}"
    database_id = config.get("database_id")
    try:
        database_uuid = UUID(str(database_id)) if database_id else None
    except (TypeError, ValueError) as exc:
        raise BindingError("NEEDS_CONFIGURATION", "config.database_id inválido") from exc
    session = await open_managed_query_session(organization_id, workspace_id, database_id=database_uuid)
    if session is None:
        raise BindingError("NEEDS_CONFIGURATION", "no hay managed database para el tenant")
    try:
        try:
            result = await _execute_sql(session, sql, params, timeout_ms=3000)
            rows = result.fetchall()
        except BindingError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _query_failure(exc) from exc
    finally:
        await session.close()
    data = [dict(row._mapping) for row in rows]
    return {"rows": data, "row_count": len(data), "table": table}


async def _execute_connected_select(
    organization_id: UUID,
    binding: dict[str, Any],
    payload: dict[str, Any],
    *,
    workspace_id: UUID | None,
) -> dict[str, Any]:
    """Ejecutor connected_db (PostgreSQL externo read-only) de P19-06."""
    from urllib.parse import quote_plus

    from src.infrastructure.postgres.relational_db import PostgresConnectorRepository
    from src.infrastructure.secrets.secret_store_resolver import get_secret_store

    plan = parse_data_query_plan(binding.get("config") or {})
    if plan is None:
        raise BindingError(
            "NEEDS_CONFIGURATION",
            "connected_db requiere un plan zent.data.query.binding/v1; legacy no soportado",
        )
    if plan.connection_ref is None:
        raise BindingError("NEEDS_CONFIGURATION", "connected_db requiere connection_ref")
    connector = await PostgresConnectorRepository().get_connector(
        organization_id, plan.connection_ref
    )
    if connector is None or str(connector.status or "").lower() != "active":
        raise BindingError("RESOURCE_NOT_EXPOSED", "conector no expuesto o inactivo")
    if connector.workspace_id and workspace_id and str(connector.workspace_id) != str(workspace_id):
        raise BindingError("PERMISSION_DENIED", "el conector pertenece a otro workspace")
    if str(connector.type or "").lower() not in ("postgres", "postgresql"):
        raise BindingError("PROVIDER_NOT_SUPPORTED", "solo PostgreSQL externo está certificado")
    config = connector.config_json if isinstance(connector.config_json, dict) else {}
    host = str(config.get("host") or "").strip()
    database = str(config.get("database") or "").strip()
    user = str(config.get("user") or "").strip()
    if not host or not database or not user:
        raise BindingError("NEEDS_CONFIGURATION", "conector PostgreSQL incompleto")
    try:
        port = int(config.get("port") or 5432)
    except (TypeError, ValueError) as exc:
        raise BindingError("NEEDS_CONFIGURATION", "puerto del conector inválido") from exc
    secret = await get_secret_store().get(organization_id, plan.connection_ref)
    password = secret.get("password") if isinstance(secret, dict) else None
    if not password:
        raise BindingError("NEEDS_CREDENTIALS", "el conector no tiene credencial de lectura")
    dsn = (
        f"postgresql+asyncpg://{quote_plus(user)}:{quote_plus(str(password))}"
        f"@{host}:{port}/{quote_plus(database)}"
    )
    connect_args: dict[str, Any] = {
        "server_settings": {"default_transaction_read_only": "on"}
    }
    if config.get("ssl"):
        connect_args["ssl"] = "require"
    engine = create_async_engine(
        dsn,
        pool_size=1,
        max_overflow=0,
        pool_pre_ping=True,
        connect_args=connect_args,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        return await _execute_data_query_plan(
            organization_id,
            binding,
            plan,
            payload,
            workspace_id=workspace_id,
            session_factory=factory,
        )
    except BindingError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _query_failure(exc) from exc
    finally:
        await engine.dispose()


async def _execute_managed_select(
    organization_id: UUID,
    binding: dict[str, Any],
    payload: dict[str, Any],
    *,
    workspace_id: UUID | None,
    principal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ejecuta un plan canónico o el camino legacy seguro."""
    plan = parse_data_query_plan(binding.get("config") or {})
    if plan is not None:
        return await _execute_data_query_plan(
            organization_id,
            binding,
            plan,
            payload,
            workspace_id=workspace_id,
            principal=principal,
        )
    return await _execute_legacy_select(organization_id, binding, payload, workspace_id=workspace_id)


async def _execute_inventory_action(
    organization_id: UUID,
    binding: dict[str, Any],
    payload: dict[str, Any],
    *,
    workspace_id: UUID | None,
) -> dict[str, Any]:
    """Acción de inventario gobernada: commit de stock con idempotencia."""
    from urllib.parse import quote_plus

    from src.infrastructure.postgres.relational_db import PostgresConnectorRepository
    from src.infrastructure.secrets.secret_store_resolver import get_secret_store

    config = binding.get("config") or {}
    if str(config.get("action") or "") != "commit_stock":
        raise BindingError("PROVIDER_NOT_SUPPORTED", "acción de inventario no soportada")
    if config.get("write") is not True:
        raise BindingError("PERMISSION_DENIED", "el conector no está habilitado para escritura")
    try:
        connector_id = UUID(str(config.get("connector_id") or ""))
    except (TypeError, ValueError) as exc:
        raise BindingError("NEEDS_CONFIGURATION", "inventory requiere connector_id") from exc
    order_number = str(payload.get("order_number") or "").strip()
    sku = str(payload.get("sku") or "").strip()
    if not _valid_simple_ident(sku) or not re.match(r"^[A-Za-z0-9_-]{3,40}$", order_number):
        raise BindingError("INVALID_PARAMS", "order_number o sku inválido")
    try:
        quantity = int(payload.get("quantity") or 0)
    except (TypeError, ValueError) as exc:
        raise BindingError("INVALID_PARAMS", "quantity inválida") from exc
    if quantity < 1 or quantity > int(config.get("max_quantity") or 100):
        raise BindingError("INVALID_PARAMS", "quantity fuera de rango")
    idempotency_key = str(
        payload.get("idempotency_key") or f"commit:{order_number}:{sku}"
    )[:160]

    connector = await PostgresConnectorRepository().get_connector(
        organization_id, connector_id
    )
    if connector is None or str(connector.status or "").lower() != "active":
        raise BindingError("RESOURCE_NOT_EXPOSED", "conector de escritura no disponible")
    if connector.workspace_id and workspace_id and str(connector.workspace_id) != str(workspace_id):
        raise BindingError("PERMISSION_DENIED", "el conector pertenece a otro workspace")
    cfg = connector.config_json if isinstance(connector.config_json, dict) else {}
    if str(connector.type or "").lower() not in ("postgres", "postgresql"):
        raise BindingError("PROVIDER_NOT_SUPPORTED", "solo PostgreSQL")
    host = str(cfg.get("host") or "").strip()
    database = str(cfg.get("database") or "").strip()
    user = str(cfg.get("user") or "").strip()
    if not host or not database or not user:
        raise BindingError("NEEDS_CONFIGURATION", "conector de escritura incompleto")
    secret = await get_secret_store().get(organization_id, connector_id)
    password = secret.get("password") if isinstance(secret, dict) else None
    if not password:
        raise BindingError("NEEDS_CREDENTIALS", "sin credencial de escritura")
    dsn = (
        f"postgresql+asyncpg://{quote_plus(user)}:{quote_plus(str(password))}"
        f"@{host}:{int(cfg.get('port') or 5432)}/{quote_plus(database)}"
    )
    engine = create_async_engine(dsn, pool_size=1, max_overflow=0, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            order = (
                await conn.execute(
                    text(
                        "SELECT status, payment_status FROM bodega.orders "
                        "WHERE order_number = :on FOR UPDATE"
                    ),
                    {"on": order_number},
                )
            ).fetchone()
            if order is None:
                raise BindingError("NOT_FOUND", "pedido no encontrado")
            stock = (
                await conn.execute(
                    text(
                        "SELECT on_hand, reserved FROM bodega.stock "
                        "WHERE sku = :sku FOR UPDATE"
                    ),
                    {"sku": sku},
                )
            ).fetchone()
            if stock is None:
                raise BindingError("RESOURCE_NOT_EXPOSED", "SKU no expuesto")
            existing = (
                await conn.execute(
                    text(
                        "SELECT id, after_on_hand FROM bodega.stock_movements "
                        "WHERE idempotency_key = :key"
                    ),
                    {"key": idempotency_key},
                )
            ).fetchone()
            if existing is not None:
                return {
                    "status": "ALREADY_APPLIED",
                    "order_number": order_number,
                    "sku": sku,
                    "quantity": quantity,
                    "on_hand": int(existing.after_on_hand),
                    "movement_id": str(existing.id),
                }
            before = int(stock.on_hand)
            if before < quantity:
                raise BindingError("CONFLICT", "stock insuficiente")
            after = before - quantity
            movement = (
                await conn.execute(
                    text(
                        "INSERT INTO bodega.stock_movements "
                        "(order_number, sku, quantity, movement_type, idempotency_key, "
                        "before_on_hand, after_on_hand) "
                        "VALUES (:on, :sku, :qty, 'commit', :key, :before, :after) "
                        "RETURNING id"
                    ),
                    {
                        "on": order_number,
                        "sku": sku,
                        "qty": quantity,
                        "key": idempotency_key,
                        "before": before,
                        "after": after,
                    },
                )
            ).fetchone()
            await conn.execute(
                text(
                    "UPDATE bodega.stock SET on_hand = :after, "
                    "reserved = GREATEST(reserved - :qty, 0), version = version + 1 "
                    "WHERE sku = :sku"
                ),
                {"after": after, "qty": quantity, "sku": sku},
            )
            await conn.execute(
                text(
                    "UPDATE bodega.orders SET status = 'confirmed', "
                    "payment_status = 'approved_manual', updated_at = NOW() "
                    "WHERE order_number = :on"
                ),
                {"on": order_number},
            )
        return {
            "status": "COMMITTED",
            "order_number": order_number,
            "sku": sku,
            "quantity": quantity,
            "on_hand_before": before,
            "on_hand": after,
            "movement_id": str(movement.id) if movement else None,
        }
    except BindingError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _query_failure(exc) from exc
    finally:
        await engine.dispose()


async def _execute_rest(organization_id: UUID, binding: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    import httpx

    from src.infrastructure.secrets.secret_store_resolver import get_secret_store

    config = binding.get("config") or {}
    url = str(config.get("url") or "")
    method = str(config.get("method") or "post").upper()
    if not url.startswith("https://") and not url.startswith("http://"):
        raise BindingError("NEEDS_CONFIGURATION", "rest_api requiere config.url http(s)")
    from src.agents.tools.tools_builtin import CallApiTool

    try:
        CallApiTool._ssrf_check(url)
    except Exception as exc:  # noqa: BLE001
        raise BindingError("DISABLED", f"url rechazada: {str(exc)[:120]}") from exc
    headers = {"Content-Type": "application/json"}
    credential_ref = binding.get("credential_ref")
    if credential_ref:
        try:
            from uuid import UUID as _UUID

            store = get_secret_store()
            secret = await store.get(organization_id, _UUID(str(credential_ref))) if store else None
            if isinstance(secret, dict):
                headers.update({str(k): str(v) for k, v in secret.get("headers", {}).items()})
                if secret.get("api_key"):
                    headers[str(config.get("auth_header") or "Authorization")] = str(secret["api_key"])
            elif secret:
                headers[str(config.get("auth_header") or "Authorization")] = str(secret)
        except Exception as exc:  # noqa: BLE001
            raise BindingError("NEEDS_CREDENTIALS", f"credencial inaccesible: {str(exc)[:120]}") from exc
    try:
        async with httpx.AsyncClient(timeout=float(config.get("timeout_seconds") or 15)) as client:
            if method == "GET":
                response = await client.get(url, params=payload, headers=headers)
            else:
                response = await client.request(method, url, json=payload, headers=headers)
    except Exception as exc:  # noqa: BLE001
        raise BindingError("PROVIDER_ERROR", f"http falló: {str(exc)[:160]}") from exc
    if response.status_code >= 400:
        raise BindingError("PROVIDER_HTTP_ERROR", f"HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        body = {"text": response.text[:20_000]}
    return body if isinstance(body, dict) else {"data": body}
