# =============================================================================
# Phase 32B — Instalaciones, credenciales (SecretStore), presupuestos,
# circuit breaker, evidencia y providers — núcleo del marketplace.
# =============================================================================
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)


class MarketplaceError(Exception):
    """Error base de marketplace."""

    code = "MARKETPLACE_ERROR"


class BudgetExceededError(MarketplaceError):
    code = "BUDGET_EXCEEDED"


class CircuitOpenError(MarketplaceError):
    code = "CIRCUIT_OPEN"


class ActionNotEnabledError(MarketplaceError):
    code = "ACTION_NOT_ENABLED"


class PolicyDeniedError(MarketplaceError):
    code = "POLICY_DENIED"


class PurposeRequiredError(MarketplaceError):
    code = "PURPOSE_REQUIRED"


class CredentialsMissingError(MarketplaceError):
    code = "CREDENTIALS_MISSING"


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


# ---------------------------------------------------------------------------
# Instalaciones
# ---------------------------------------------------------------------------
async def install_integration(
    organization_id: UUID,
    manifest_slug: str,
    *,
    workspace_id: UUID | None = None,
    created_by: UUID | None = None,
    purpose: str | None = None,
    legal_basis_reference: str | None = None,
) -> dict:
    session = await get_async_session()
    try:
        m = (
            await session.execute(
                text(
                    "SELECT id, slug, name, status FROM integration_manifests "
                    "WHERE slug = :slug AND status IN ('PUBLISHED', 'DEPRECATED')"
                ),
                {"slug": manifest_slug},
            )
        ).fetchone()
        if m is None:
            raise MarketplaceError("integración no publicada o inexistente")
        existing = (
            await session.execute(
                text(
                    "SELECT id FROM installed_integrations "
                    "WHERE organization_id = :oid AND workspace_id IS NOT DISTINCT FROM :ws "
                    "AND integration_id = :iid ORDER BY created_at DESC LIMIT 1"
                ),
                {"oid": organization_id, "ws": workspace_id, "iid": m.id},
            )
        ).fetchone()
        if existing is not None:
            await session.commit()
            return {"install_id": str(existing.id), "reused": True, "integration_slug": m.slug}
        install_id = uuid4()
        data_policy = (
            await session.execute(
                text("SELECT data_policy FROM integration_manifests WHERE id = :iid"),
                {"iid": m.id},
            )
        ).fetchone()
        dp = data_policy.data_policy if data_policy else {}
        if dp.get("purpose_required") and not purpose:
            await session.rollback()
            raise PurposeRequiredError("integración requiere purpose (datos personales)")
        await session.execute(
            text(
                "INSERT INTO installed_integrations "
                "(id, organization_id, workspace_id, integration_id, version, purpose, "
                "legal_basis_reference, created_by, enabled_actions, auto_use_policy) "
                "VALUES (:id, :oid, :ws, :iid, 1, :purpose, :lbr, :by, '[]', '{}')"
            ),
            {
                "id": install_id,
                "oid": organization_id,
                "ws": workspace_id,
                "iid": m.id,
                "purpose": purpose,
                "lbr": legal_basis_reference,
                "by": created_by,
            },
        )
        await session.commit()
    finally:
        await session.close()
    return {"install_id": str(install_id), "reused": False, "integration_slug": m.slug}


_INSTALL_SELECT = (
    "SELECT i.id, i.organization_id, i.workspace_id, i.status, i.purpose, "
    "i.legal_basis_reference, i.enabled_actions, i.auto_use_policy, i.spend_limit, "
    "i.version, i.created_at, i.updated_at, "
    "m.slug AS integration_slug, m.name AS integration_name, m.provider, m.category, "
    "m.pricing, m.rate_limits, m.data_policy, "
    "(SELECT jsonb_agg(jsonb_build_object('id', c.id, 'auth_mode', c.auth_mode, "
    "'cred_type', c.cred_type, 'status', c.status, 'refreshed_at', c.refreshed_at)) "
    "FROM integration_credentials c WHERE c.install_id = i.id) AS credentials "
    "FROM installed_integrations i "
    "JOIN integration_manifests m ON m.id = i.integration_id "
)


async def list_installs(organization_id: UUID, workspace_id: UUID | None = None) -> dict:
    session = await get_async_session()
    try:
        params: dict[str, Any] = {"oid": organization_id}
        # noqa: S608 — concatenación solo de literales constantes del módulo
        sql = _INSTALL_SELECT + "WHERE i.organization_id = :oid"
        if workspace_id is not None:
            sql += " AND (i.workspace_id = :ws OR i.workspace_id IS NULL)"
            params["ws"] = workspace_id
        rows = (await session.execute(text(sql + " ORDER BY i.created_at DESC"), params)).fetchall()
    finally:
        await session.close()
    return {"installs": [_install_row(r) for r in rows]}


async def get_install(organization_id: UUID, install_id: UUID) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    _INSTALL_SELECT
                    + "WHERE i.id = :iid AND i.organization_id = :oid"
                ),
                {"iid": install_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    return _install_row(row)


def _install_row(r) -> dict:
    return {
        "id": str(r.id),
        "organization_id": str(r.organization_id),
        "workspace_id": str(r.workspace_id) if r.workspace_id else None,
        "status": r.status,
        "purpose": r.purpose,
        "legal_basis_reference": r.legal_basis_reference,
        "enabled_actions": r.enabled_actions or [],
        "auto_use_policy": r.auto_use_policy or {},
        "spend_limit": r.spend_limit or {},
        "integration": {
            "slug": r.integration_slug,
            "name": r.integration_name,
            "provider": r.provider,
            "category": r.category,
            "pricing": r.pricing,
            "rate_limits": r.rate_limits,
            "data_policy": r.data_policy,
        },
        "credentials": [
            {
                "id": c["id"],
                "auth_mode": c["auth_mode"],
                "cred_type": c["cred_type"],
                "status": c["status"],
                "refreshed_at": c["refreshed_at"],
            }
            for c in (r.credentials or [])
        ]
        if isinstance(r.credentials, list)
        else [],
        "version": int(r.version or 1),
        "created_at": _iso(r.created_at),
        "updated_at": _iso(r.updated_at),
    }


async def update_install(
    organization_id: UUID,
    install_id: UUID,
    *,
    enabled_actions: list[str] | None = None,
    auto_use_policy: dict[str, str] | None = None,
    spend_limit: dict[str, Any] | None = None,
    purpose: str | None = None,
    legal_basis_reference: str | None = None,
    status: str | None = None,
) -> dict | None:
    from src.platform.marketplace.models import AUTO_USE_POLICY

    session = await get_async_session()
    try:
        exists = (
            await session.execute(
                text("SELECT id FROM installed_integrations WHERE id = :iid AND organization_id = :oid"),
                {"iid": install_id, "oid": organization_id},
            )
        ).fetchone()
        if exists is None:
            await session.commit()
            return None
        sets = ["updated_at = NOW()"]
        params: dict[str, Any] = {"iid": install_id}
        if enabled_actions is not None:
            sets.append("enabled_actions = CAST(:actions AS jsonb)")
            params["actions"] = json.dumps(enabled_actions)
        if auto_use_policy is not None:
            bad = {k: v for k, v in auto_use_policy.items() if v not in AUTO_USE_POLICY}
            if bad:
                raise MarketplaceError(f"auto_use_policy inválida: {bad}")
            sets.append("auto_use_policy = CAST(:policy AS jsonb)")
            params["policy"] = json.dumps(auto_use_policy)
        if spend_limit is not None:
            sets.append("spend_limit = CAST(:limit AS jsonb)")
            params["limit"] = json.dumps(spend_limit)
        if purpose is not None:
            sets.append("purpose = :purpose")
            params["purpose"] = purpose[:80]
        if legal_basis_reference is not None:
            sets.append("legal_basis_reference = :lbr")
            params["lbr"] = legal_basis_reference[:200]
        if status is not None:
            if status not in ("installed", "connected", "paused", "error", "suspended"):
                raise MarketplaceError("status de instalación inválido")
            sets.append("status = :status")
            params["status"] = status
        await session.execute(
            text(
                f"UPDATE installed_integrations SET {', '.join(sets)} WHERE id = :iid"  # noqa: S608
            ),
            params,
        )
        await session.commit()
    finally:
        await session.close()
    return {"updated": True}


async def delete_install(organization_id: UUID, install_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "DELETE FROM installed_integrations "
                "WHERE id = :iid AND organization_id = :oid"
            ),
            {"iid": install_id, "oid": organization_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Credenciales → SecretStore (nunca plaintext en DB)
# ---------------------------------------------------------------------------
async def set_credentials(
    organization_id: UUID,
    install_id: UUID,
    auth_mode: str,
    cred_type: str,
    secrets: dict[str, Any],
    *,
    workspace_id: UUID | None = None,
    provider_account_id: str | None = None,
) -> dict:
    from src.infrastructure.secrets.secret_store_resolver import get_secret_store

    session = await get_async_session()
    try:
        install = (
            await session.execute(
                text(
                    "SELECT id, integration_id FROM installed_integrations "
                    "WHERE id = :iid AND organization_id = :oid"
                ),
                {"iid": install_id, "oid": organization_id},
            )
        ).fetchone()
        if install is None:
            await session.commit()
            raise MarketplaceError("instalación no encontrada")
        cred_id = uuid4()
        await session.execute(
            text(
                "INSERT INTO integration_credentials "
                "(id, organization_id, workspace_id, integration_id, install_id, auth_mode, "
                "cred_type, status, provider_account_id, refreshed_at) "
                "VALUES (:id, :oid, :ws, :iid, :inst, :auth, :ctype, 'configured', :acc, NOW())"
            ),
            {
                "id": cred_id,
                "oid": organization_id,
                "ws": workspace_id,
                "iid": install.integration_id,
                "inst": install_id,
                "auth": auth_mode[:30],
                "ctype": cred_type[:30],
                "acc": (provider_account_id or "")[:160],
            },
        )
        await session.execute(
            text(
                "UPDATE installed_integrations SET status = 'connected', credential_ref = :ref "
                "WHERE id = :iid"
            ),
            {"ref": str(cred_id), "iid": install_id},
        )
        await session.commit()
    finally:
        await session.close()
    # Secretos SIEMPRE al SecretStore (Vault primario, Postgres cifrado fallback).
    blob = {k: v for k, v in (secrets or {}).items()}
    blob["_meta"] = {"auth_mode": auth_mode, "cred_type": cred_type}
    store = get_secret_store()
    await store.put(organization_id, cred_id, blob)
    return {"credential_id": str(cred_id), "status": "configured"}


async def read_credentials(organization_id: UUID, install_id: UUID) -> dict[str, Any]:
    """Lee secretos del SecretStore (solo uso interno del runtime)."""
    from src.infrastructure.secrets.secret_store_resolver import get_secret_store

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT credential_ref FROM installed_integrations "
                    "WHERE id = :iid AND organization_id = :oid"
                ),
                {"iid": install_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None or not row.credential_ref:
        return {}
    try:
        cred_id = UUID(str(row.credential_ref))
    except ValueError:
        return {}
    return dict(await get_secret_store().get(organization_id, cred_id))


# ---------------------------------------------------------------------------
# Presupuestos
# ---------------------------------------------------------------------------
def _bucket_scope(period: str, now: datetime) -> tuple[str, str]:
    if period == "daily":
        return "day", now.strftime("%Y-%m-%d")
    if period == "monthly":
        return "month", now.strftime("%Y-%m")
    return "day", now.strftime("%Y-%m-%d")


async def _check_spend_limits(
    organization_id: UUID,
    install_id: UUID,
    action_id: str,
    estimated_cost: float,
    *,
    workflow_id: UUID | None = None,
    workspace_id: UUID | None = None,
) -> None:
    """Valida spend_limit (daily/monthly/per_action/per_workflow) antes de ejecutar."""
    session = await get_async_session()
    try:
        install = (
            await session.execute(
                text("SELECT spend_limit FROM installed_integrations WHERE id = :iid AND organization_id = :oid"),
                {"iid": install_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if install is None or not install.spend_limit:
        return
    limit = install.spend_limit
    now = datetime.now(timezone.utc)
    for period, key in (("daily", "daily"), ("monthly", "monthly")):
        entry = limit.get(key)
        if not isinstance(entry, dict) or "amount" not in entry:
            continue
        scope, bucket = _bucket_scope(period, now)
        used = await _counter_sum(organization_id, workspace_id, install_id, action_id, scope, bucket)
        if float(entry["amount"]) <= 0 or float(used or 0) + float(estimated_cost or 0) >= float(entry["amount"]):
            raise BudgetExceededError(
                f"presupuesto {key} excedido (límite {entry['amount']} {entry.get('currency', '')})"
            )
    per_action = limit.get("per_action") or {}
    if isinstance(per_action, dict) and "amount" in per_action:
        scope, bucket = _bucket_scope("daily", now)
        used = await _counter_sum(organization_id, workspace_id, install_id, action_id, scope, bucket)
        if float(used or 0) + float(estimated_cost or 0) > float(per_action["amount"]):
            raise BudgetExceededError(f"presupuesto por acción excedido ({per_action['amount']})")
    per_workflow = limit.get("per_workflow") or {}
    if isinstance(per_workflow, dict) and "amount" in per_workflow and workflow_id:
        scope, bucket = _bucket_scope("daily", now)
        used = await _counter_sum(
            organization_id, workspace_id, install_id, None, scope, f"{bucket}:{workflow_id}"
        )
        if float(used or 0) + float(estimated_cost or 0) > float(per_workflow["amount"]):
            raise BudgetExceededError(f"presupuesto por workflow excedido ({per_workflow['amount']})")


async def _counter_sum(
    organization_id: UUID,
    workspace_id: UUID | None,
    install_id: UUID,
    action_id: str | None,
    scope: str,
    bucket: str,
) -> float:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT cost FROM integration_budget_counters "
                    "WHERE organization_id = :oid AND workspace_id IS NOT DISTINCT FROM :ws "
                    "AND install_id = :iid AND action_id IS NOT DISTINCT FROM :aid "
                    "AND scope = :scope AND bucket = :bucket"
                ),
                {"oid": organization_id, "ws": workspace_id, "iid": install_id, "aid": action_id,
                 "scope": scope, "bucket": bucket},
            )
        ).fetchone()
    finally:
        await session.close()
    return float(row.cost) if row else 0.0


async def _consume_budget(
    organization_id: UUID,
    workspace_id: UUID | None,
    install_id: UUID,
    action_id: str,
    cost: float,
    *,
    workflow_id: UUID | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    session = await get_async_session()
    try:
        buckets: list[tuple[str, str]] = []
        for period, _label in (("daily", "day"), ("monthly", "month")):
            scope, bucket = _bucket_scope(period, now)
            buckets.append((scope, bucket))
        if workflow_id:
            scope, bucket = _bucket_scope("daily", now)
            buckets.append((scope, f"{bucket}:{workflow_id}"))
        for scope, bucket in buckets:
            await session.execute(
                text(
                    "INSERT INTO integration_budget_counters "
                    "(id, organization_id, workspace_id, install_id, action_id, scope, bucket, cost) "
                    "VALUES (gen_random_uuid(), :oid, :ws, :iid, :aid, :scope, :bucket, :cost) "
                    "ON CONFLICT (organization_id, workspace_id, install_id, action_id, scope, bucket) "
                    "DO UPDATE SET cost = integration_budget_counters.cost + EXCLUDED.cost, "
                    "updated_at = NOW()"
                ),
                {"oid": organization_id, "ws": workspace_id, "iid": install_id,
                 "aid": action_id, "scope": scope, "bucket": bucket, "cost": round(cost, 4)},
            )
        await session.commit()
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Circuit breaker (Redis) — nunca golpear un provider caído
# ---------------------------------------------------------------------------
async def circuit_state(organization_id: UUID, action_id: str) -> bool:
    """True si el circuito está ABIERTO (bloqueando llamadas)."""
    try:
        from src.infrastructure.redis.cache import _get_redis

        client = await _get_redis()
        key = f"mkt:circuit:{organization_id.hex}:{action_id}"
        raw = await client.get(key)
        if not raw:
            return False
        state = json.loads(raw)
        if state.get("open_until", 0) > time.time():
            return True
        if state.get("failures", 0) >= 5 and state.get("window_start", 0) > time.time() - 60:
            # Umbral alcanzado dentro de la ventana → abrir durante 60s.
            await client.set(key, json.dumps({"open_until": time.time() + 60, "failures": state["failures"]}), ex=65)
            return True
        return False
    except Exception:  # noqa: BLE001
        return False


async def circuit_report(organization_id: UUID, action_id: str, ok: bool, status_code: int | None = None) -> None:
    try:
        from src.infrastructure.redis.cache import _get_redis

        client = await _get_redis()
        key = f"mkt:circuit:{organization_id.hex}:{action_id}"
        raw = await client.get(key)
        state = json.loads(raw) if raw else {"failures": 0, "window_start": time.time()}
        if not ok or (status_code and status_code >= 500) or status_code == 429:
            state["failures"] = state.get("failures", 0) + 1
        else:
            state["failures"] = 0
        if state["failures"] >= 5:
            state["open_until"] = time.time() + 60
        await client.set(key, json.dumps(state), ex=300)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Evidencia externa + cache de lookups
# ---------------------------------------------------------------------------
def _input_hash(inputs: dict[str, Any]) -> str:
    raw = json.dumps(inputs, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def find_cached_evidence(
    organization_id: UUID,
    workspace_id: UUID | None,
    install_id: UUID,
    action_id: str,
    inputs: dict[str, Any],
    purpose: str | None,
) -> dict | None:
    """Cache de lookup respetando tenant/workspace/purpose/TTL."""
    h = _input_hash(inputs)
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, output, retrieved_at, freshness_ttl_seconds, status FROM external_evidence "
                    "WHERE organization_id = :oid AND workspace_id IS NOT DISTINCT FROM :ws "
                    "AND install_id = :iid AND action_id = :aid AND input_hash = :h "
                    "AND purpose IS NOT DISTINCT FROM :purpose "
                    "AND status = 'fresh' AND retrieved_at > NOW() - make_interval(secs => :ttl) "
                    "ORDER BY retrieved_at DESC LIMIT 1"
                ),
                {"oid": organization_id, "ws": workspace_id, "iid": install_id, "aid": action_id,
                 "h": h, "purpose": purpose, "ttl": 3600},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    return {"evidence_id": str(row.id), "output": row.output, "cached": True}


async def record_evidence(
    *,
    organization_id: UUID,
    workspace_id: UUID | None,
    integration_id: UUID,
    install_id: UUID,
    action_id: str,
    entity_type: str,
    entity_id: str,
    provider: str,
    output: dict[str, Any],
    inputs: dict[str, Any],
    purpose: str | None,
    workflow_id: UUID | None,
    run_id: UUID | None,
    agent_run_id: UUID | None,
    cost: float,
    ttl_seconds: int = 3600,
    retention_days: int = 30,
) -> UUID:
    ev_id = uuid4()
    now = datetime.now(timezone.utc)
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO external_evidence "
                "(id, organization_id, workspace_id, integration_id, install_id, action_id, "
                "entity_type, entity_id, provider, purpose, retrieved_at, freshness_ttl_seconds, "
                "input_hash, output, provenance, workflow_id, run_id, agent_run_id, cost, retention_until) "
                "VALUES (:id, :oid, :ws, :iid, :inst, :aid, :etype, :eid, :prov, :purpose, NOW(), :ttl, "
                ":h, CAST(:output AS jsonb), CAST(:provenance AS jsonb), :wid, :rid, :arid, :cost, :ret)"
            ),
            {
                "id": ev_id,
                "oid": organization_id,
                "ws": workspace_id,
                "iid": integration_id,
                "inst": install_id,
                "aid": action_id,
                "etype": entity_type[:60],
                "eid": str(entity_id)[:120],
                "prov": provider[:150],
                "purpose": purpose,
                "ttl": int(ttl_seconds),
                "h": _input_hash(inputs),
                "output": json.dumps(output),
                "provenance": json.dumps({
                    "source": provider,
                    "integration": action_id.split(".")[0] if "." in action_id else action_id,
                    "action": action_id,
                    "inputs": inputs,
                }),
                "wid": workflow_id,
                "rid": run_id,
                "arid": agent_run_id,
                "cost": round(cost, 4),
                "ret": now + timedelta(days=max(1, int(retention_days))),
            },
        )
        await session.commit()
    finally:
        await session.close()
    return ev_id


async def list_evidence(
    organization_id: UUID,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    workspace_id: UUID | None = None,
    limit: int = 20,
) -> dict:
    session = await get_async_session()
    try:
        sql = (
            "SELECT id, action_id, entity_type, entity_id, provider, purpose, retrieved_at, "
            "freshness_ttl_seconds, status, cost, workflow_id, run_id, agent_run_id, output "
            "FROM external_evidence WHERE organization_id = :oid"
        )
        params: dict[str, Any] = {"oid": organization_id, "lim": min(int(limit), 100)}
        if entity_type:
            sql += " AND entity_type = :etype"
            params["etype"] = entity_type
        if entity_id:
            sql += " AND entity_id = :eid"
            params["eid"] = entity_id
        if workspace_id is not None:
            sql += " AND (workspace_id = :ws OR workspace_id IS NULL)"
            params["ws"] = workspace_id
        rows = (
            await session.execute(
                text(sql + " ORDER BY retrieved_at DESC LIMIT :lim"), params
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "evidence": [
            {
                "id": str(r.id),
                "action_id": r.action_id,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "provider": r.provider,
                "purpose": r.purpose,
                "retrieved_at": _iso(r.retrieved_at),
                "freshness_ttl_seconds": int(r.freshness_ttl_seconds or 0),
                "status": r.status,
                "cost": float(r.cost or 0),
                "workflow_id": str(r.workflow_id) if r.workflow_id else None,
                "run_id": str(r.run_id) if r.run_id else None,
                "agent_run_id": str(r.agent_run_id) if r.agent_run_id else None,
                "output": r.output,
            }
            for r in rows
        ]
    }


# ---------------------------------------------------------------------------
# Providers (adapter seguro — sin ejecución de código arbitrario)
# ---------------------------------------------------------------------------
async def _execute_rest(
    action: dict, credentials: dict[str, Any], inputs: dict[str, Any], organization_id: UUID
) -> dict:
    from urllib.parse import urlparse

    import httpx

    from src.agents.tools.base import ToolError
    from src.agents.tools.tools_builtin import CallApiTool
    from src.platform.workflows.engine import _org_config

    cfg = action.get("provider_config") or {}
    base_url = str(credentials.get("endpoint_base_url") or credentials.get("base_url") or "")
    if not base_url:
        raise CredentialsMissingError("endpoint_base_url no configurado en credenciales")
    parsed = urlparse(base_url)
    if parsed.scheme not in ("https", "http"):
        raise CredentialsMissingError("scheme inválido")
    if not parsed.hostname:
        raise CredentialsMissingError("URL sin host")
    # SSRF: bloquear localhost/metadata; allowlist del tenant (si configurada).
    org_cfg = await _org_config(organization_id)
    allowlist = ((org_cfg.get("agent") or {}).get("api_allowlist") or [])
    if allowlist and parsed.hostname not in allowlist:
        raise CredentialsMissingError(f"host '{parsed.hostname}' no está en la api_allowlist del tenant")
    try:
        CallApiTool._ssrf_check(parsed.hostname)
    except ToolError as exc:
        raise CredentialsMissingError(str(exc)) from exc

    path = str(cfg.get("path_template") or "/")
    for key, value in (inputs or {}).items():
        path = path.replace("{" + key + "}", str(value))
    url = base_url.rstrip("/") + path
    method = str(cfg.get("method") or "GET").upper()
    headers = dict(credentials.get("headers") or {})
    api_key = credentials.get("api_key")
    if api_key and "Authorization" not in headers and "X-API-Key" not in headers:
        headers["X-API-Key"] = str(api_key)
    if credentials.get("oauth_token"):
        headers["Authorization"] = f"Bearer {credentials['oauth_token']}"
    timeout = min(float(action.get("timeout_ms") or 5000) / 1000.0, 30.0)
    async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
        if method == "POST":
            resp = await client.post(url, json=inputs, headers=headers)
        elif method == "PUT":
            resp = await client.put(url, json=inputs, headers=headers)
        else:
            query = {k: v for k, v in (inputs or {}).items() if k not in path}
            resp = await client.get(url, params=query, headers=headers)
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        data = {"raw": resp.text[:2000], "status_code": resp.status_code}
    # Mapeo declarativo output_map (nunca fabricar campos).
    output_map = cfg.get("output_map") or {}
    if isinstance(data, dict) and output_map:
        normalized: dict[str, Any] = {}
        for field, source_path in output_map.items():
            cur = data
            for part in str(source_path).split("."):
                if isinstance(cur, dict):
                    cur = cur.get(part)
                else:
                    cur = None
                    break
            if cur is not None:
                normalized[field] = cur
    else:
        normalized = dict(data) if isinstance(data, dict) else {"raw": data}
    normalized.setdefault("source", credentials.get("provider_label") or parsed.hostname)
    normalized.setdefault("retrieved_at", _iso(datetime.now(timezone.utc)))
    if resp.status_code >= 400:
        return {"_http_error": True, "_status_code": resp.status_code, "_body": str(data)[:500]}
    return {"status_code": resp.status_code, "ok": True, "data": normalized, "_raw": data}


async def _execute_demo_echo(
    action: dict, credentials: dict[str, Any], inputs: dict[str, Any], organization_id: UUID
) -> dict:
    text = str(inputs.get("text", ""))
    return {
        "status_code": 200,
        "ok": True,
        "data": {"echo": text, "source": "demo.echo", "retrieved_at": _iso(datetime.now(timezone.utc))},
    }


PROVIDER_EXECUTORS = {
    "rest": _execute_rest,
    "demo_echo": _execute_demo_echo,
}


# ---------------------------------------------------------------------------
# Orquestación: execute_action (workflow / agente / manual / API = mismo runtime)
# ---------------------------------------------------------------------------
@dataclass
class ExecutionOutcome:
    ok: bool = True
    error_code: str | None = None
    error_message: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    evidence_id: UUID | None = None
    cached: bool = False
    provider_cost: float = 0.0
    customer_cost: float = 0.0
    currency: str = "PEN"
    units: int = 0
    latency_ms: float = 0.0
    status_code: int | None = None
    entity_type: str | None = None
    entity_id: str | None = None


def _estimate_cost(action: dict) -> float:
    model = (action.get("cost_model") or {}).get("model")
    if model in ("PER_CALL", "USAGE_PLUS_BASE"):
        return float((action.get("cost_model") or {}).get("price_per_call", 0.0) or 0.0)
    return 0.0


async def execute_action(
    organization_id: UUID,
    install_id: UUID,
    action_id: str,
    inputs: dict[str, Any],
    *,
    workspace_id: UUID | None = None,
    purpose: str | None = None,
    workflow_id: UUID | None = None,
    run_id: UUID | None = None,
    agent_run_id: UUID | None = None,
    actor_id: UUID | None = None,
    actor_type: str = "user",
    force_refresh: bool = False,
    source: str = "manual",
) -> ExecutionOutcome:
    """Ejecuta una acción instalada. Un solo runtime para workflow/agente/manual."""
    from src.platform.marketplace import catalog

    started = time.perf_counter()

    install = await _load_install(organization_id, install_id)
    if install is None:
        return ExecutionOutcome(ok=False, error_code="NOT_INSTALLED", error_message="instalación no encontrada")
    if install["status"] in ("paused", "suspended"):
        return ExecutionOutcome(
            ok=False,
            error_code="INSTALL_PAUSED",
            error_message="instalación " + str(install["status"]),
        )

    action = await catalog.get_action(action_id)
    if action is None or action.get("status") == "END_OF_LIFE":
        return ExecutionOutcome(ok=False, error_code="ACTION_NOT_FOUND", error_message="acción no encontrada")
    enabled = install["enabled_actions"] or []
    if enabled and action_id not in enabled:
        return ExecutionOutcome(
            ok=False,
            error_code="ACTION_NOT_ENABLED",
            error_message="acción no habilitada en la instalación",
        )
    if action.get("requires_approval") and source in ("agent", "auto"):
        return ExecutionOutcome(
            ok=False,
            error_code="APPROVAL_REQUIRED",
            error_message="acción requiere aprobación humana (no auto)",
        )

    # Purpose binding (datos personales).
    if action.get("contains_personal_data"):
        dp = install["data_policy"] or {}
        if dp.get("purpose_required"):
            effective_purpose = purpose or install["purpose"]
            if not effective_purpose:
                return ExecutionOutcome(
                ok=False,
                error_code="PURPOSE_REQUIRED",
                error_message="purpose requerido para datos personales",
            )
            if not install["purpose"] and dp.get("legal_basis_required") and install["legal_basis_reference"] is None:
                return ExecutionOutcome(
                ok=False,
                error_code="LEGAL_BASIS_REQUIRED",
                error_message="base legal requerida",
            )

    # Validación de inputs contra input_schema (mínimo: required + tipos).
    schema = action.get("input_schema") or {}
    required = schema.get("required") or []
    missing = [k for k in required if inputs.get(k) in (None, "")]
    if missing:
        return ExecutionOutcome(ok=False, error_code="INPUT_VALIDATION", error_message=f"faltan inputs: {missing}")

    # Cache de lookup (respeta tenant/workspace/purpose/TTL).
    cache_policy = action.get("cache_policy") or {}
    if cache_policy.get("allow") and not force_refresh:
        cached = await find_cached_evidence(
            organization_id, workspace_id, install_id, action_id, inputs, purpose or install["purpose"]
        )
        if cached:
            return ExecutionOutcome(
                ok=True,
                data=dict(cached["output"]),
                evidence_id=UUID(str(cached["evidence_id"])) if isinstance(cached["evidence_id"], str) else None,
                cached=True,
                latency_ms=(time.perf_counter() - started) * 1000.0,
            )

    # Presupuesto (estimado) + circuito.
    est = _estimate_cost(action)
    try:
        await _check_spend_limits(
            organization_id, install_id, action_id, est,
            workflow_id=workflow_id, workspace_id=workspace_id,
        )
    except BudgetExceededError as exc:
        await _audit(organization_id, install_id, action_id, actor_id, "marketplace.budget_exceeded", str(exc))
        return ExecutionOutcome(ok=False, error_code="BUDGET_EXCEEDED", error_message=str(exc))

    if await circuit_state(organization_id, action_id):
        return ExecutionOutcome(
            ok=False,
            error_code="CIRCUIT_OPEN",
            error_message="proveedor en circuito abierto (recuperación)",
        )

    # Credenciales desde SecretStore (nunca plaintext).
    credentials = await read_credentials(organization_id, install_id)
    kind = (action.get("provider_config") or {}).get("kind") or "rest"
    executor = PROVIDER_EXECUTORS.get(kind)
    if executor is None:
        return ExecutionOutcome(
            ok=False,
            error_code="PROVIDER_NOT_SUPPORTED",
            error_message=f"provider {kind} no soportado",
        )

    if kind == "rest" and not credentials:
        await _audit(organization_id, install_id, action_id, actor_id, "marketplace.credentials_missing")
        return ExecutionOutcome(
            ok=False,
            error_code="CREDENTIALS_MISSING",
            error_message="conecta credenciales antes de ejecutar",
        )

    # Ejecución del provider (con retry limitado declarado en la acción).
    max_attempts = max(1, int((action.get("retry_policy") or {}).get("max_attempts", 1) or 1))
    raw: dict[str, Any] | None = None
    last_error: str | None = None
    for attempt in range(max_attempts):
        try:
            raw = await executor(action, credentials, inputs, organization_id)
            break
        except MarketplaceError as exc:
            await circuit_report(organization_id, action_id, False, None)
            if attempt + 1 >= max_attempts:
                return ExecutionOutcome(ok=False, error_code=exc.code, error_message=str(exc))
            await asyncio.sleep(0.25 * (attempt + 1))
        except Exception as exc:  # noqa: BLE001
            await circuit_report(organization_id, action_id, False, 500)
            last_error = f"provider error: {str(exc)[:200]}"
            break
    if raw is None:
        await circuit_report(organization_id, action_id, False, 500)
        return ExecutionOutcome(
            ok=False,
            error_code="PROVIDER_ERROR",
            error_message=last_error or "error del proveedor",
        )

    status_code = raw.get("status_code")
    if raw.get("_http_error") or (status_code and status_code >= 400):
        await circuit_report(organization_id, action_id, False, status_code)
        return ExecutionOutcome(
            ok=False, error_code="PROVIDER_HTTP_ERROR",
            error_message=f"proveedor respondió {status_code}: {str(raw.get('_body') or '')[:200]}",
            status_code=status_code,
        )

    await circuit_report(organization_id, action_id, True, status_code)
    data = raw.get("data") or {}
    cost = float((action.get("cost_model") or {}).get("price_per_call", 0.0) or 0.0)
    units = int((action.get("cost_model") or {}).get("units", 1) or 1)
    currency = str((action.get("cost_model") or {}).get("currency") or "PEN")

    # Ledger (uso) + presupuesto real + métricas.
    await _record_ledger(
        organization_id=organization_id,
        workspace_id=workspace_id,
        install_id=install_id,
        action_id=action_id,
        units=units,
        provider_cost=cost,
        customer_cost=cost,
        currency=currency,
        workflow_id=workflow_id,
        run_id=run_id,
        agent_run_id=agent_run_id,
        purpose=purpose or install["purpose"],
        status="ok",
    )
    await _consume_budget(organization_id, workspace_id, install_id, action_id, cost, workflow_id=workflow_id)
    _emit_metrics(organization_id, action_id, "ok")

    # Evidencia externa (nunca confundir con verdad interna).
    entity_type, entity_id = _guess_entity(action_id, inputs)
    ttl = int((action.get("cache_policy") or {}).get("ttl_seconds", 3600) or 3600)
    retention_days = int((action.get("retention_policy") or {}).get("ttl_days", 30) or 30)
    evidence_id = await record_evidence(
        organization_id=organization_id,
        workspace_id=workspace_id,
        integration_id=UUID(str(action["integration_id"])),
        install_id=install_id,
        action_id=action_id,
        entity_type=entity_type,
        entity_id=entity_id,
        provider=str(action.get("integration_name") or action_id),
        output=data,
        inputs=inputs,
        purpose=purpose or install["purpose"],
        workflow_id=workflow_id,
        run_id=run_id,
        agent_run_id=agent_run_id,
        cost=cost,
        ttl_seconds=ttl,
        retention_days=retention_days,
    )

    await _audit(organization_id, install_id, action_id, actor_id, "marketplace.execute", None, entity_id=entity_id)
    result = ExecutionOutcome(
        ok=True,
        data=data,
        evidence_id=evidence_id,
        provider_cost=cost,
        customer_cost=cost,
        currency=currency,
        units=units,
        latency_ms=(time.perf_counter() - started) * 1000.0,
        status_code=status_code,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    return result


async def _load_install(organization_id: UUID, install_id: UUID) -> dict | None:
    from src.platform.marketplace import catalog as _c

    install = await get_install(organization_id, install_id)
    if install is None:
        return None
    manifest = await _c.get_manifest(install["integration"]["slug"])
    install["data_policy"] = (manifest or {}).get("data_policy") or {}
    return install


def _guess_entity(action_id: str, inputs: dict[str, Any]) -> tuple[str, str]:
    """Heurística declarativa: qué entidad representa el input de la acción."""
    for key, entity in (
        ("ruc", "company"),
        ("dni", "person"),
        ("base", "currency_pair"),
        ("customer_id", "customer"),
    ):
        if key in inputs and inputs[key] not in (None, ""):
            return entity, str(inputs[key])
    digest = hashlib.sha256(
            json.dumps(inputs, sort_keys=True, default=str).encode()
        ).hexdigest()[:12]
    return "external", f"{action_id}:{digest}"


async def _record_ledger(**kwargs: Any) -> None:
    from uuid import uuid4 as _u4

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO integration_usage_ledger "
                "(id, organization_id, workspace_id, integration_id, install_id, action_id, "
                "units, provider_cost, customer_cost, currency, workflow_id, run_id, agent_run_id, purpose, status) "
                "SELECT :id, :oid, :ws, m.integration_id, :inst, :aid, :units, :pc, :cc, :cur, "
                ":wid, :rid, :arid, :purpose, :status "
                "FROM installed_integrations m WHERE m.id = :inst"
            ),
            {
                "id": _u4(),
                "oid": kwargs["organization_id"],
                "ws": kwargs.get("workspace_id"),
                "inst": kwargs["install_id"],
                "aid": kwargs["action_id"],
                "units": int(kwargs.get("units", 0)),
                "pc": round(float(kwargs.get("provider_cost", 0)), 4),
                "cc": round(float(kwargs.get("customer_cost", 0)), 4),
                "cur": kwargs.get("currency", "PEN")[:3],
                "wid": kwargs.get("workflow_id"),
                "rid": kwargs.get("run_id"),
                "arid": kwargs.get("agent_run_id"),
                "purpose": kwargs.get("purpose"),
                "status": kwargs.get("status", "ok")[:20],
            },
        )
        await session.commit()
    except Exception:  # noqa: BLE001
        await session.rollback()
    finally:
        await session.close()


async def _audit(
    organization_id: UUID,
    install_id: UUID,
    action_id: str,
    actor_id: UUID | None,
    action: str,
    error: str | None = None,
    entity_id: str | None = None,
) -> None:
    try:
        from src.core.domain.entities import TenantContext
        from src.infrastructure.postgres.relational_db import PostgresAuditLogRepository
        from src.platform.audit.service import AuditLogService

        ctx = TenantContext(
            tenant_id=organization_id,
            user_id=None,
            roles=frozenset(),
            permissions=frozenset(),
            scopes=frozenset(),
            auth_type="marketplace_runtime",
        )
        metadata: dict[str, Any] = {"install_id": str(install_id), "action_id": action_id}
        if error:
            metadata["error"] = error
        if entity_id:
            metadata["entity_id"] = entity_id
        await AuditLogService(PostgresAuditLogRepository()).write(
            ctx, action, "integration", install_id, metadata=metadata
        )
    except Exception:  # noqa: BLE001
        pass


def _emit_metrics(organization_id: UUID, action_id: str, status: str) -> None:
    try:

        _market_calls.labels(action_id=action_id, status=status).inc()
    except Exception:  # noqa: BLE001
        pass


try:
    from prometheus_client import Counter

    _market_calls = Counter(
        "marketplace_calls_total", "Llamadas de marketplace", ["action_id", "status"]
    )
except Exception:  # noqa: BLE001
    _market_calls = None
