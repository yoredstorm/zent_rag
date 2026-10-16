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

import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

PROVIDER_KINDS: tuple[str, ...] = (
    "managed_db",
    "connected_db",
    "marketplace_action",
    "semantic_query",
    "rest_api",
    "erp",
    "custom",
)

_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)?$")
_MAX_ROWS = 500

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
        return result.rowcount > 0
    finally:
        await session.close()


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
        if want and not _type_ok(payload.get(key), want):
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
) -> dict[str, Any]:
    """Ejecuta una capacidad resuelta por el binding del tenant.

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
    if kind == "marketplace_action":
        out = await _execute_marketplace_action(
            organization_id, binding, payload, workspace_id=workspace_id, source=source,
            actor_id=actor_id, workflow_id=workflow_id, run_id=run_id,
        )
    elif kind == "semantic_query":
        out = await _execute_semantic_query(organization_id, binding, payload, workspace_id=workspace_id)
    elif kind in ("managed_db", "connected_db"):
        out = await _execute_managed_select(organization_id, binding, payload, workspace_id=workspace_id)
    elif kind == "rest_api":
        out = await _execute_rest(organization_id, binding, payload)
    else:
        raise BindingError(
            "PROVIDER_NOT_IMPLEMENTED",
            f"provider_kind {kind} registrado sin executor en esta versión",
        )
    output_errors = validate_contract(dict(out or {}), binding.get("contract_output_schema"))
    if output_errors:
        raise BindingError("CONTRACT_INVALID", "salida: " + "; ".join(output_errors[:5]))
    return {"capability": capability_ref, "provider_kind": kind, "output": out}


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
        "answer": (
            result.llm_response.content
            if getattr(result, "llm_response", None) is not None
            else None
        ),
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


async def _execute_managed_select(
    organization_id: UUID,
    binding: dict[str, Any],
    payload: dict[str, Any],
    *,
    workspace_id: UUID | None,
) -> dict[str, Any]:
    """SELECT declarativo validado (sin SQL arbitrario en plantillas)."""
    from src.platform.managed_db.service import open_managed_query_session

    config = {**(binding.get("config") or {}), **payload}
    table = _q(str(config.get("table") or ""))
    if not table:
        raise BindingError("NEEDS_CONFIGURATION", "managed_db requiere config.table")
    columns = config.get("columns") or ["*"]
    if not isinstance(columns, list):
        columns = [columns]
    cols_sql = ", ".join("*" if c == "*" else _q(str(c)) for c in columns)
    filters = config.get("filters") or {}
    if not isinstance(filters, dict):
        filters = {}
    where_parts: list[str] = []
    params: dict[str, Any] = {}
    for idx, (column, value) in enumerate(list(filters.items())[:20]):
        col = _q(str(column))
        op = "="
        if isinstance(value, dict):
            op = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "like": "ILIKE"}.get(
                str(value.get("op") or "eq"), "="
            )
            value = value.get("value")
        pname = f"f{idx}"
        where_parts.append(f"{col} {op} :{pname}")
        params[pname] = value
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
    session = await open_managed_query_session(organization_id, workspace_id)
    if session is None:
        raise BindingError("NEEDS_CONFIGURATION", "no hay managed database para el tenant")
    try:
        rows = (await session.execute(text(sql), params)).fetchall()
        keys = list(rows[0]._mapping.keys()) if rows else []
    except BindingError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BindingError("PROVIDER_ERROR", f"consulta falló: {str(exc)[:200]}") from exc
    finally:
        await session.close()
    data = [dict(zip(keys, row)) for row in rows] if keys else [dict(row._mapping) for row in rows]
    return {"rows": data, "row_count": len(data), "table": table}


async def _execute_rest(
    organization_id: UUID, binding: dict[str, Any], payload: dict[str, Any]
) -> dict[str, Any]:
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
            store = get_secret_store()
            secret = await store.get(credential_ref) if store else None
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
