# =============================================================================
# Data Export & Compliance v2 — export ZIP del tenant (KB/agentes/usage/
# config) con anonimización, auditoría de exportaciones y retención granular
# con purga automática.
# =============================================================================
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

EXPORT_DIR = Path("data") / "exports"
RETENTION_TABLES = {
    "usage_events": "created_at",
    "inference_logs": "created_at",
    "api_logs": "created_at",
    "audit_logs": "created_at",
    "agent_versions": "created_at",
}


# ---------------------------------------------------------------------------
# Anonimización (pseudonimización + k-anonimity básico)
# ---------------------------------------------------------------------------
def _anon_email(email: str | None) -> str | None:
    if not email:
        return None
    digest = hashlib.sha256(email.encode()).hexdigest()[:12]
    domain = email.split("@")[-1] if "@" in email else "local"
    return f"{digest}@{domain}"


def _anon_owner(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def _anonymize_payload(payload: dict, *, round_days: bool) -> dict:
    """Pseudonimiza emails/ids y redondea fechas a día (k≈: cohortes con
    la misma (org, model, día) se agrupan)."""
    for section in ("kb", "agents", "usage", "config"):
        data = payload.get(section)
        if section == "config":
            if isinstance(data, dict):
                org_data = data.get("organization")
                if isinstance(org_data, dict) and org_data.get("owner"):
                    org_data["owner"] = _anon_owner(str(org_data["owner"]))
        elif isinstance(data, list):
            for row in data:
                if not isinstance(row, dict):
                    continue
                if section == "usage" and round_days and row.get("created_at"):
                    row["created_at"] = row["created_at"][:10]
                if section == "agents" and row.get("created_by"):
                    row["created_by"] = _anon_owner(str(row["created_by"]))
    return payload


# ---------------------------------------------------------------------------
# Export ZIP por scope
# ---------------------------------------------------------------------------
async def _collect_kb(organization_id: UUID) -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, name, description, status, embedding_model, "
                    "chunking_strategy, chunk_size, metadata_schema, created_at "
                    "FROM knowledge_bases WHERE organization_id = :oid ORDER BY name"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
        docs = (
            await session.execute(
                text(
                    "SELECT external_id, title, source_url, chunk_count, status, "
                    "created_at FROM documents WHERE organization_id = :oid "
                    "ORDER BY created_at DESC LIMIT 1000"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "description": r.description,
            "status": r.status,
            "embedding_model": r.embedding_model,
            "chunking_strategy": r.chunking_strategy,
            "chunk_size": r.chunk_size,
            "metadata_schema": r.metadata_schema,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ], [
        {
            "external_id": r.external_id,
            "title": r.title,
            "source_url": r.source_url,
            "chunk_count": int(r.chunk_count or 0),
            "status": r.status,
            "created_at": r.created_at.isoformat(),
        }
        for r in docs
    ]


async def _collect_agents(organization_id: UUID) -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, name, model, status, config_json, created_at, created_by "
                    "FROM agents WHERE organization_id = :oid ORDER BY created_at"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "model": r.model,
            "status": r.status,
            "config_json": r.config_json,
            "created_at": r.created_at.isoformat(),
            "created_by": str(r.created_by) if r.created_by else None,
        }
        for r in rows
    ]


async def _collect_usage(organization_id: UUID, days: int = 90) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT event_type, agent_id, model, total_tokens, latency_ms, "
                    "status, estimated_cost, created_at "
                    "FROM usage_events WHERE organization_id = :oid "
                    "AND created_at >= :since ORDER BY created_at DESC LIMIT 5000"
                ),
                {"oid": organization_id, "since": since},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "event_type": r.event_type,
            "agent_id": str(r.agent_id) if r.agent_id else None,
            "model": r.model,
            "total_tokens": int(r.total_tokens or 0),
            "latency_ms": round(float(r.latency_ms or 0), 1),
            "status": r.status,
            "cost": round(float(r.estimated_cost or 0), 6),
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


async def _collect_config(organization_id: UUID) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT o.name, o.config_json, o.cost_team, o.cost_business_unit, "
                    "o.primary_region_id, u.email AS owner_email, p.name AS plan, "
                    "s.status AS sub_status "
                    "FROM organizations o "
                    "LEFT JOIN subscriptions s ON s.organization_id = o.id "
                    "LEFT JOIN plans p ON p.id = s.plan_id "
                    "LEFT JOIN users u ON u.organization_id = o.id AND u.external_id = 'default-admin' "
                    "WHERE o.id = :oid"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    return {
        "organization": {
            "id": str(organization_id),
            "name": row.name if row else None,
            "config_json": row.config_json if row else None,
            "cost_team": row.cost_team if row else None,
            "cost_business_unit": row.cost_business_unit if row else None,
            "primary_region": str(row.primary_region_id) if row and row.primary_region_id else None,
            "owner": row.owner_email if row else None,
            "plan": row.plan if row else None,
            "subscription_status": row.sub_status if row else None,
        }
    }


async def export_tenant(
    organization_id: UUID,
    *,
    scope: str = "all",
    anonymized: bool = False,
    requested_by: UUID | None = None,
) -> dict:
    """Genera el ZIP portátil (fail-soft por sección)."""
    payload: dict = {}
    row_counts: dict = {}
    if scope in ("all", "kb"):
        try:
            kbs, docs = await _collect_kb(organization_id)
            payload["kb"] = {"knowledge_bases": kbs, "documents": docs}
            row_counts["kb"] = len(kbs)
            row_counts["documents"] = len(docs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("KB export failed", error=str(exc)[:150])
    if scope in ("all", "agents"):
        try:
            agents = await _collect_agents(organization_id)
            payload["agents"] = agents
            row_counts["agents"] = len(agents)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Agents export failed", error=str(exc)[:150])
    if scope in ("all", "usage"):
        try:
            usage = await _collect_usage(organization_id)
            payload["usage"] = usage
            row_counts["usage"] = len(usage)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Usage export failed", error=str(exc)[:150])
    if scope in ("all", "config"):
        try:
            payload["config"] = await _collect_config(organization_id)
            row_counts["config"] = 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Config export failed", error=str(exc)[:150])

    if anonymized:
        payload = _anonymize_payload(payload, round_days=True)

    manifest = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "organization_id": str(organization_id),
        "scope": scope,
        "anonymized": anonymized,
        "row_counts": row_counts,
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, default=str))
        for section in ("kb", "agents", "usage", "config"):
            if section in payload:
                zf.writestr(f"{section}.json", json.dumps(payload[section], indent=2, default=str))
    size = buffer.tell()

    file_key = f"exports/{organization_id}/{UUID(int=0)}"
    from uuid import uuid4

    file_key = f"exports/{organization_id}/{uuid4().hex}.zip"
    out_path = EXPORT_DIR / file_key
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(buffer.getvalue())

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO data_exports (id, organization_id, export_type, scope, "
                    "anonymized, status, file_key, size_bytes, row_counts, requested_by, "
                    "completed_at) "
                    "VALUES (gen_random_uuid(), :oid, 'full', :scope, :anon, 'completed', "
                    ":fkey, :size, :rows, :by, NOW()) "
                    "RETURNING id, status, size_bytes"
                ),
                {
                    "oid": organization_id,
                    "scope": scope[:40],
                    "anon": anonymized,
                    "fkey": file_key,
                    "size": size,
                    "rows": json.dumps(row_counts),
                    "by": requested_by,
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {
        "id": str(row.id),
        "organization_id": str(organization_id),
        "scope": scope,
        "anonymized": anonymized,
        "status": row.status,
        "size_bytes": int(row.size_bytes),
        "row_counts": row_counts,
        "file_key": file_key,
    }


async def list_exports(organization_id: UUID | None = None, limit: int = 50) -> dict:
    session = await get_async_session()
    try:
        params: dict = {"limit": limit}
        where = ""
        if organization_id:
            where = " WHERE organization_id = :oid"
            params["oid"] = organization_id
        rows = (
            await session.execute(
                text(
                    "SELECT id, organization_id, scope, anonymized, status, size_bytes, "
                    "row_counts, requested_by, requested_at, completed_at "
                    "FROM data_exports" + where + " ORDER BY requested_at DESC LIMIT :limit"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "exports": [
            {
                "id": str(r.id),
                "organization_id": str(r.organization_id),
                "scope": r.scope,
                "anonymized": bool(r.anonymized),
                "status": r.status,
                "size_bytes": int(r.size_bytes),
                "row_counts": r.row_counts,
                "requested_by": str(r.requested_by) if r.requested_by else None,
                "requested_at": r.requested_at.isoformat(),
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in rows
        ],
        "count": len(rows),
    }


async def get_export_file(export_id: UUID) -> tuple[bytes, str] | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT file_key, scope FROM data_exports WHERE id = :eid"),
                {"eid": export_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None or not row.file_key:
        return None
    path = EXPORT_DIR / row.file_key
    if not path.exists():
        return None
    return path.read_bytes(), row.scope


# ---------------------------------------------------------------------------
# Retención granular con purga automática
# ---------------------------------------------------------------------------
async def list_policies(organization_id: UUID | None = None) -> dict:
    session = await get_async_session()
    try:
        params: dict = {}
        where = ""
        if organization_id:
            where = " WHERE organization_id = :oid OR organization_id IS NULL"
            params["oid"] = organization_id
        rows = (
            await session.execute(
                text(
                    "SELECT id, organization_id, data_type, retention_days, enabled, "
                    "created_at FROM retention_policies" + where + " "
                    "ORDER BY data_type, organization_id NULLS FIRST"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "policies": [
            {
                "id": str(r.id),
                "organization_id": str(r.organization_id) if r.organization_id else None,
                "data_type": r.data_type,
                "retention_days": int(r.retention_days),
                "enabled": bool(r.enabled),
            }
            for r in rows
        ]
    }


async def upsert_policy(
    data_type: str,
    retention_days: int,
    enabled: bool = True,
    organization_id: UUID | None = None,
) -> dict:
    if data_type not in RETENTION_TABLES:
        raise ValueError(f"data_type must be one of {sorted(RETENTION_TABLES)}")
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO retention_policies (id, organization_id, data_type, "
                    "retention_days, enabled) "
                    "VALUES (gen_random_uuid(), :oid, :dt, :days, :en) "
                    "ON CONFLICT (organization_id, data_type) DO UPDATE SET "
                    "retention_days = EXCLUDED.retention_days, enabled = EXCLUDED.enabled "
                    "RETURNING id, data_type, retention_days, enabled"
                ),
                {"oid": organization_id, "dt": data_type, "days": retention_days, "en": enabled},
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {
        "id": str(row.id),
        "data_type": row.data_type,
        "retention_days": int(row.retention_days),
        "enabled": bool(row.enabled),
    }


async def delete_policy(policy_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text("DELETE FROM retention_policies WHERE id = :pid"),
            {"pid": policy_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def run_retention_purges() -> dict:
    """Purga por política: tabla derivada de data_type (whitelist) y columna
    created_at. Registra cada purga en retention_purges."""
    session = await get_async_session()
    purged: list[dict] = []
    try:
        policies = (
            await session.execute(
                text("SELECT id, organization_id, data_type, retention_days FROM retention_policies WHERE enabled")
            )
        ).fetchall()
        for policy in policies:
            table = policy.data_type
            if table not in RETENTION_TABLES:
                continue
            column = RETENTION_TABLES[table]
            cutoff = datetime.now(timezone.utc) - timedelta(days=int(policy.retention_days))
            params: dict = {"cutoff": cutoff}
            where = f"{column} < :cutoff"
            if policy.organization_id:
                where += " AND organization_id = :oid"
                params["oid"] = policy.organization_id
            count = (
                await session.execute(
                    text(
                        f"DELETE FROM {table} WHERE {where}"  # noqa: S608 — tabla whitelist
                    ),
                    params,
                )
            ).rowcount
            if count:
                await session.execute(
                    text(
                        "INSERT INTO retention_purges (id, policy_id, organization_id, "
                        "data_type, purged_rows) "
                        "VALUES (gen_random_uuid(), :pid, :oid, :dt, :rows)"
                    ),
                    {
                        "pid": policy.id,
                        "oid": policy.organization_id,
                        "dt": table,
                        "rows": count,
                    },
                )
                purged.append(
                    {
                        "data_type": table,
                        "organization_id": str(policy.organization_id) if policy.organization_id else "global",
                        "purged_rows": int(count),
                    }
                )
        await session.commit()
    finally:
        await session.close()
    return {"purged": purged, "count": len(purged)}


async def list_purges(limit: int = 50) -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, policy_id, organization_id, data_type, purged_rows, ran_at "
                    "FROM retention_purges ORDER BY ran_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "purges": [
            {
                "id": str(r.id),
                "policy_id": str(r.policy_id) if r.policy_id else None,
                "organization_id": str(r.organization_id) if r.organization_id else None,
                "data_type": r.data_type,
                "purged_rows": int(r.purged_rows),
                "ran_at": r.ran_at.isoformat(),
            }
            for r in rows
        ]
    }
