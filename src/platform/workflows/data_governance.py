# =============================================================================
# P19.1-01 - Gobierno de publicacion de consultas.
#
# Autoridad separada de la edicion de workflows:
#   - descubrir no autoriza publicar;
#   - publicar exige permiso propio y una politica explicita por conector;
#   - las columnas sensibles exigen permiso y proposito;
#   - politicas y eventos son versionados/append-only.
#
# Este modulo no ejecuta SQL de negocio ni descubre por si mismo: recibe el
# recurso ya descubierto y decide si puede publicarse.
# =============================================================================
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import text

from src.core.domain.pii import is_sensitive_column, pii_flags_for_column
from src.infrastructure.postgres.session import get_async_session

POLICY_SCHEMA = "zent.data.publication.policy/v1"
SYSTEM_SCHEMAS = frozenset({"information_schema", "pg_catalog", "pg_toast", "pg_temp"})
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_OPERATIONS = ("get_one", "list", "count")


class DataPolicyError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class ResourceAllowlist(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_name: str = Field(alias="schema")
    table: str
    columns: list[str] = Field(min_length=1, max_length=100)
    sensitive_columns: list[str] = Field(default_factory=list, max_length=100)
    operations: list[Literal["get_one", "list", "count"]] = Field(
        default_factory=lambda: ["get_one", "list", "count"], min_length=1
    )
    max_rows: int = Field(default=50, ge=1, le=500)

    @field_validator("schema_name", "table", "columns", "sensitive_columns")
    @classmethod
    def _identifiers(cls, value: Any) -> Any:
        values = value if isinstance(value, list) else [value]
        for item in values:
            if not _IDENT.match(str(item)):
                raise ValueError(f"identificador invalido: {item!r}")
        return value


class PublicationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    policy_schema: Literal["zent.data.publication.policy/v1"] = Field(
        default=POLICY_SCHEMA, alias="schema"
    )
    resources: list[ResourceAllowlist] = Field(min_length=1, max_length=100)
    requires_purpose_for_sensitive: Literal[True] = True
    deny_by_default: Literal[True] = True

    @field_validator("resources")
    @classmethod
    def _unique_resources(cls, value: list[ResourceAllowlist]) -> list[ResourceAllowlist]:
        keys = [(item.schema_name, item.table) for item in value]
        if len(keys) != len(set(keys)):
            raise ValueError("recurso duplicado en la politica")
        return value


def policy_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _has_permission(permissions: frozenset[str] | set[str] | None, code: str) -> bool:
    values = set(permissions or ())
    return code in values or "*" in values or "admin:*" in values


def require_permission(permissions: frozenset[str] | set[str] | None, code: str) -> None:
    if not _has_permission(permissions, code):
        raise DataPolicyError(403, "PERMISSION_DENIED", f"falta el permiso {code}")


def validate_policy(body: dict[str, Any]) -> PublicationPolicy:
    try:
        parsed = PublicationPolicy.model_validate(body)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in exc.errors()[:5]
        )
        raise DataPolicyError(400, "INVALID_POLICY", f"politica invalida: {details}") from exc
    for resource in parsed.resources:
        if resource.schema_name in SYSTEM_SCHEMAS:
            raise DataPolicyError(403, "SYSTEM_SCHEMA_DENIED", "schema de sistema no publicable")
        if not set(resource.sensitive_columns).issubset(set(resource.columns)):
            raise DataPolicyError(
                400, "INVALID_POLICY", "sensitive_columns debe ser subconjunto de columns"
            )
    return parsed


async def get_publication_policy(
    organization_id: UUID,
    workspace_id: UUID,
    connector_id: UUID,
) -> dict[str, Any] | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT policy, policy_hash, version, status, updated_at "
                    "FROM data_query_publication_policies "
                    "WHERE organization_id = :oid AND workspace_id = :wid "
                    "AND connector_ref = :cid AND status = 'active'"
                ),
                {"oid": str(organization_id), "wid": str(workspace_id), "cid": str(connector_id)},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    return {
        "policy": dict(row.policy or {}),
        "policy_hash": str(row.policy_hash or ""),
        "version": int(row.version or 1),
        "status": str(row.status),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def save_publication_policy(
    organization_id: UUID,
    workspace_id: UUID,
    connector_id: UUID,
    body: dict[str, Any],
    *,
    actor_id: UUID | None,
) -> dict[str, Any]:
    parsed = validate_policy(body)
    payload = parsed.model_dump(mode="json", by_alias=True)
    digest = policy_hash(payload)
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO data_query_publication_policies "
                    "(organization_id, workspace_id, connector_ref, policy, policy_hash, version, "
                    "status, created_by) "
                    "VALUES (:oid, :wid, :cid, CAST(:policy AS jsonb), :hash, 1, 'active', :actor) "
                    "ON CONFLICT (organization_id, workspace_id, connector_ref) DO UPDATE SET "
                    "policy = EXCLUDED.policy, policy_hash = EXCLUDED.policy_hash, "
                    "version = data_query_publication_policies.version + 1, "
                    "status = 'active', updated_at = NOW() "
                    "RETURNING version, updated_at"
                ),
                {
                    "oid": str(organization_id),
                    "wid": str(workspace_id),
                    "cid": str(connector_id),
                    "policy": json.dumps(payload, ensure_ascii=False),
                    "hash": digest,
                    "actor": str(actor_id) if actor_id else None,
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    await record_publication_event(
        organization_id,
        workspace_id,
        action="policy.updated",
        actor_id=actor_id,
        connector_id=connector_id,
        policy_digest=digest,
        metadata={"version": int(row.version or 1)},
    )
    return {
        "policy": payload,
        "policy_hash": digest,
        "version": int(row.version or 1),
        "status": "active",
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def authorize_publication(
    organization_id: UUID,
    workspace_id: UUID,
    connector_id: UUID,
    *,
    schema_name: str,
    table_name: str,
    operation: str,
    fields: set[str],
    permissions: frozenset[str] | set[str] | None,
    purpose: str,
) -> tuple[dict[str, Any], set[str], int]:
    require_permission(permissions, "data_queries:publish")
    if schema_name in SYSTEM_SCHEMAS:
        raise DataPolicyError(403, "SYSTEM_SCHEMA_DENIED", "schema de sistema no publicable")
    if operation not in _OPERATIONS:
        raise DataPolicyError(400, "INVALID_PARAMS", "operacion no permitida")
    stored = await get_publication_policy(organization_id, workspace_id, connector_id)
    if stored is None:
        raise DataPolicyError(
            403,
            "POLICY_REQUIRED",
            "el conector no tiene politica de publicacion; un administrador debe crearla",
        )
    parsed = validate_policy(dict(stored["policy"]))
    resource = next(
        (
            item
            for item in parsed.resources
            if item.schema_name == schema_name and item.table == table_name
        ),
        None,
    )
    if resource is None:
        raise DataPolicyError(403, "RESOURCE_NOT_ALLOWED", "tabla fuera de la allowlist")
    if operation not in resource.operations:
        raise DataPolicyError(403, "OPERATION_NOT_ALLOWED", "operacion no autorizada para la tabla")
    unknown = sorted(fields - set(resource.columns))
    if unknown:
        raise DataPolicyError(
            403,
            "COLUMN_NOT_ALLOWED",
            f"columnas fuera de la allowlist: {', '.join(unknown[:5])}",
        )
    sensitive = {column for column in fields if is_sensitive_column(column)}
    sensitive |= {column for column in fields if column in set(resource.sensitive_columns)}
    if sensitive:
        if not _has_permission(permissions, "data_queries:publish_sensitive"):
            raise DataPolicyError(
                403,
                "SENSITIVE_COLUMN_DENIED",
                "columnas sensibles requieren data_queries:publish_sensitive",
            )
        if len(str(purpose or "").strip()) < 10:
            raise DataPolicyError(
                403,
                "PURPOSE_REQUIRED",
                "columnas sensibles requieren un proposito aprobado",
            )
    return stored, sensitive, resource.max_rows


async def validate_plan_against_policy(
    organization_id: UUID,
    workspace_id: UUID,
    connector_id: UUID,
    *,
    schema_name: str,
    table_name: str,
    fields: set[str],
    plan_policy_digest: str | None,
) -> dict[str, Any]:
    """Revalida un plan ya publicado contra la politica vigente."""
    stored = await get_publication_policy(organization_id, workspace_id, connector_id)
    if stored is None:
        raise DataPolicyError(403, "POLICY_REQUIRED", "el conector no tiene politica vigente")
    if plan_policy_digest and plan_policy_digest != stored["policy_hash"]:
        raise DataPolicyError(
            409,
            "POLICY_STALE",
            "la politica cambio desde la publicacion; revisar y republicar",
        )
    parsed = validate_policy(dict(stored["policy"]))
    resource = next(
        (
            item
            for item in parsed.resources
            if item.schema_name == schema_name and item.table == table_name
        ),
        None,
    )
    if resource is None:
        raise DataPolicyError(403, "RESOURCE_NOT_ALLOWED", "tabla fuera de la allowlist vigente")
    unknown = sorted(fields - set(resource.columns))
    if unknown:
        raise DataPolicyError(
            403,
            "COLUMN_NOT_ALLOWED",
            f"columnas fuera de la allowlist vigente: {', '.join(unknown[:5])}",
        )
    return stored


async def record_publication_event(
    organization_id: UUID,
    workspace_id: UUID,
    *,
    action: str,
    actor_id: UUID | None = None,
    connector_id: UUID | None = None,
    binding_id: UUID | str | None = None,
    capability_ref: str | None = None,
    resource_ref: str | None = None,
    selected_columns: list[str] | None = None,
    sensitive_columns: list[str] | None = None,
    purpose: str | None = None,
    policy_digest: str | None = None,
    plan_digest: str | None = None,
    previous_binding_id: UUID | str | None = None,
    approval_id: UUID | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO data_query_publication_events "
                "(organization_id, workspace_id, actor_id, action, connector_ref, binding_id, "
                "capability_ref, resource_ref, selected_columns, sensitive_columns, purpose, "
                "policy_hash, plan_hash, previous_binding_id, approval_id, metadata) "
                "VALUES (:oid, :wid, :actor, :action, :cid, :bid, :cap, :res, "
                "CAST(:cols AS jsonb), CAST(:sensitive AS jsonb), :purpose, :policy, :plan, "
                ":previous, :approval, CAST(:metadata AS jsonb))"
            ),
            {
                "oid": str(organization_id),
                "wid": str(workspace_id),
                "actor": str(actor_id) if actor_id else None,
                "action": action[:40],
                "cid": str(connector_id) if connector_id else None,
                "bid": str(binding_id) if binding_id else None,
                "cap": capability_ref[:120] if capability_ref else None,
                "res": resource_ref[:200] if resource_ref else None,
                "cols": json.dumps(selected_columns or []),
                "sensitive": json.dumps(sensitive_columns or []),
                "purpose": purpose[:300] if purpose else None,
                "policy": policy_digest,
                "plan": plan_digest,
                "previous": str(previous_binding_id) if previous_binding_id else None,
                "approval": str(approval_id) if approval_id else None,
                "metadata": json.dumps(metadata or {}, ensure_ascii=False),
            },
        )
        await session.commit()
    finally:
        await session.close()


async def list_publication_events(
    organization_id: UUID,
    workspace_id: UUID,
    *,
    limit: int = 50,
) -> dict[str, Any]:
    safe_limit = min(max(int(limit), 1), 100)
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT action, connector_ref, binding_id, capability_ref, resource_ref, "
                    "selected_columns, sensitive_columns, purpose, policy_hash, plan_hash, "
                    "created_at FROM data_query_publication_events "
                    "WHERE organization_id = :oid AND workspace_id = :wid "
                    "ORDER BY created_at DESC LIMIT :limit"
                ),
                {"oid": str(organization_id), "wid": str(workspace_id), "limit": safe_limit},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "events": [
            {
                "action": str(row.action),
                "connector_ref": str(row.connector_ref) if row.connector_ref else None,
                "binding_id": str(row.binding_id) if row.binding_id else None,
                "capability_ref": row.capability_ref,
                "resource_ref": row.resource_ref,
                "selected_columns": list(row.selected_columns or []),
                "sensitive_columns": list(row.sensitive_columns or []),
                "purpose": row.purpose,
                "policy_hash": row.policy_hash,
                "plan_hash": row.plan_hash,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


def column_pii_flags(column: str) -> list[str]:
    return pii_flags_for_column(column)


__all__ = [
    "DataPolicyError",
    "POLICY_SCHEMA",
    "PublicationPolicy",
    "ResourceAllowlist",
    "authorize_publication",
    "column_pii_flags",
    "get_publication_policy",
    "list_publication_events",
    "policy_hash",
    "record_publication_event",
    "require_permission",
    "save_publication_policy",
    "validate_plan_against_policy",
    "validate_policy",
]
