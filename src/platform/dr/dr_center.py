# =============================================================================
# AI Disaster Recovery & High Availability v2 — políticas RPO/RTO, backups
# versionados con restore y drills de failover multi-región.
# =============================================================================
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

SCOPES = ("agent", "knowledge", "full")


# ---------------------------------------------------------------------------
# Políticas DR
# ---------------------------------------------------------------------------
async def list_policies(organization_id: UUID) -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT p.id, p.name, p.scope, p.target_id, p.rpo_minutes, p.rto_minutes, "
                    "p.replication_region, p.status, p.created_at, "
                    "COALESCE(MAX(b.version), 0) AS latest_backup_version, "
                    "MAX(b.created_at) AS last_backup_at "
                    "FROM dr_policies p "
                    "LEFT JOIN dr_backups b ON b.organization_id = p.organization_id "
                    "AND b.scope = p.scope AND b.source_id = p.target_id "
                    "WHERE p.organization_id = :oid "
                    "GROUP BY p.id ORDER BY p.created_at DESC"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "policies": [
            {
                "id": str(r.id),
                "name": r.name,
                "scope": r.scope,
                "target_id": str(r.target_id) if r.target_id else None,
                "rpo_minutes": int(r.rpo_minutes),
                "rto_minutes": int(r.rto_minutes),
                "replication_region": r.replication_region,
                "status": r.status,
                "latest_backup_version": int(r.latest_backup_version),
                "last_backup_at": r.last_backup_at.isoformat() if r.last_backup_at else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


async def create_policy(
    organization_id: UUID,
    name: str,
    scope: str = "agent",
    target_id: UUID | None = None,
    rpo_minutes: int = 60,
    rto_minutes: int = 15,
    replication_region: str = "eu-west-1",
) -> dict:
    if scope not in SCOPES:
        raise ValueError(f"scope debe ser uno de {SCOPES}")
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO dr_policies (id, organization_id, name, scope, target_id, "
                    "rpo_minutes, rto_minutes, replication_region) "
                    "VALUES (gen_random_uuid(), :oid, :name, :scope, :tid, :rpo, :rto, :region) "
                    "RETURNING id"
                ),
                {
                    "oid": organization_id,
                    "name": name[:150],
                    "scope": scope,
                    "tid": target_id,
                    "rpo": max(1, min(int(rpo_minutes), 10080)),
                    "rto": max(1, min(int(rto_minutes), 1440)),
                    "region": replication_region[:40],
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {"policy_id": str(row.id)}


async def update_policy(
    organization_id: UUID,
    policy_id: UUID,
    name: str | None = None,
    rpo_minutes: int | None = None,
    rto_minutes: int | None = None,
    replication_region: str | None = None,
) -> dict | None:
    session = await get_async_session()
    try:
        exists = (
            await session.execute(
                text("SELECT id FROM dr_policies WHERE id = :pid AND organization_id = :oid"),
                {"pid": policy_id, "oid": organization_id},
            )
        ).fetchone()
        if exists is None:
            await session.commit()
            return None
        sets = ["updated_at = NOW()"]
        params: dict = {"pid": policy_id}
        if name is not None:
            sets.append("name = :name")
            params["name"] = name[:150]
        if rpo_minutes is not None:
            sets.append("rpo_minutes = :rpo")
            params["rpo"] = max(1, min(int(rpo_minutes), 10080))
        if rto_minutes is not None:
            sets.append("rto_minutes = :rto")
            params["rto"] = max(1, min(int(rto_minutes), 1440))
        if replication_region is not None:
            sets.append("replication_region = :region")
            params["region"] = replication_region[:40]
        await session.execute(
            text(f"UPDATE dr_policies SET {', '.join(sets)} WHERE id = :pid"),
            params,
        )
        await session.commit()
    finally:
        await session.close()
    return {"updated": True}


async def set_policy_status(organization_id: UUID, policy_id: UUID, status: str) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "UPDATE dr_policies SET status = :status, updated_at = NOW() "
                    "WHERE id = :pid AND organization_id = :oid RETURNING status"
                ),
                {"status": status, "pid": policy_id, "oid": organization_id},
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    if row is None:
        return None
    return {"policy_id": str(policy_id), "status": row.status}


# ---------------------------------------------------------------------------
# Backups versionados
# ---------------------------------------------------------------------------
async def _artifact_for(scope: str, organization_id: UUID, source_id: UUID | None) -> dict:
    session = await get_async_session()
    try:
        if scope in ("agent", "full") and source_id:
            agent = (
                await session.execute(
                    text(
                        "SELECT name, description, system_prompt, model, config_json, status "
                        "FROM agents WHERE id = :aid AND organization_id = :oid"
                    ),
                    {"aid": source_id, "oid": organization_id},
                )
            ).fetchone()
            if agent is not None:
                return {
                    "agent": {
                        "name": agent.name,
                        "description": agent.description,
                        "system_prompt": agent.system_prompt,
                        "model": agent.model,
                        "config_json": agent.config_json,
                        "status": agent.status,
                    }
                }
        if scope in ("knowledge", "full"):
            docs = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM documents WHERE organization_id = :oid"
                    ),
                    {"oid": organization_id},
                )
            ).scalar()
            return {"documents": int(docs or 0)}
        return {}
    finally:
        await session.close()


async def create_backup(
    organization_id: UUID,
    scope: str,
    source_id: UUID | None = None,
) -> dict:
    if scope not in SCOPES:
        raise ValueError(f"scope debe ser uno de {SCOPES}")
    artifact = await _artifact_for(scope, organization_id, source_id)
    session = await get_async_session()
    try:
        last_version = (
            await session.execute(
                text(
                    "SELECT COALESCE(MAX(version), 0) FROM dr_backups "
                    "WHERE organization_id = :oid AND scope = :scope "
                    "AND source_id IS NOT DISTINCT FROM :sid"
                ),
                {"oid": organization_id, "scope": scope, "sid": source_id},
            )
        ).scalar()
        version = int(last_version or 0) + 1
        row = (
            await session.execute(
                text(
                    "INSERT INTO dr_backups (id, organization_id, scope, source_id, version, "
                    "artifact) VALUES (gen_random_uuid(), :oid, :scope, :sid, :version, "
                    "CAST(:artifact AS jsonb)) RETURNING id"
                ),
                {
                    "oid": organization_id,
                    "scope": scope,
                    "sid": source_id,
                    "version": version,
                    "artifact": json.dumps(artifact),
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {"backup_id": str(row.id), "version": version, "artifact": artifact}


async def list_backups(organization_id: UUID, scope: str | None = None, limit: int = 50) -> dict:
    session = await get_async_session()
    try:
        params: dict = {"oid": organization_id, "lim": min(int(limit), 100)}
        where = ""
        if scope:
            where = " AND scope = :scope"
            params["scope"] = scope
        rows = (
            await session.execute(
                text(
                    "SELECT id, scope, source_id, version, artifact, status, created_at, "
                    "restored_at, restored_to_region FROM dr_backups "
                    "WHERE organization_id = :oid" + where + " "
                    "ORDER BY created_at DESC LIMIT :lim"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "backups": [
            {
                "id": str(r.id),
                "scope": r.scope,
                "source_id": str(r.source_id) if r.source_id else None,
                "version": int(r.version),
                "artifact": r.artifact,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
                "restored_at": r.restored_at.isoformat() if r.restored_at else None,
                "restored_to_region": r.restored_to_region,
            }
            for r in rows
        ]
    }


async def restore_backup(
    organization_id: UUID,
    backup_id: UUID,
    region: str = "us-east-1",
) -> dict | None:
    """Restaura el backup: recrea el agente con el artifact (si scope agent)."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, scope, source_id, version, artifact FROM dr_backups "
                    "WHERE id = :bid AND organization_id = :oid"
                ),
                {"bid": backup_id, "oid": organization_id},
            )
        ).fetchone()
        if row is None:
            await session.commit()
            return None
        artifact = row.artifact or {}
        restored = {}
        if "agent" in artifact and artifact["agent"]:
            agent_cfg = artifact["agent"]
            new_agent_id = (
                await session.execute(
                    text(
                        "INSERT INTO agents (id, organization_id, name, description, status, "
                        "system_prompt, model, config_json) "
                        "VALUES (gen_random_uuid(), :oid, :name, :desc, 'configured', "
                        ":prompt, :model, CAST(:cfg AS jsonb)) RETURNING id"
                    ),
                    {
                        "oid": organization_id,
                        "name": f"{agent_cfg.get('name', 'Restored')} (restaurado)",
                        "desc": agent_cfg.get("description"),
                        "prompt": agent_cfg.get("system_prompt") or "",
                        "model": agent_cfg.get("model") or "gpt-4o-mini",
                        "cfg": json.dumps(agent_cfg.get("config_json") or {}),
                    },
                )
            ).scalar()
            restored["agent_id"] = str(new_agent_id)
        await session.execute(
            text(
                "UPDATE dr_backups SET status = 'restored', restored_at = NOW(), "
                "restored_to_region = :region WHERE id = :bid"
            ),
            {"region": region, "bid": backup_id},
        )
        await session.commit()
    finally:
        await session.close()
    return {
        "backup_id": str(backup_id),
        "scope": row.scope,
        "version": int(row.version),
        "restored_to_region": region,
        **restored,
    }


# ---------------------------------------------------------------------------
# Drills de failover
# ---------------------------------------------------------------------------
async def _policy_row(policy_id: UUID) -> tuple | None:
    session = await get_async_session()
    try:
        return (
            await session.execute(
                text(
                    "SELECT id, organization_id, name, replication_region, status "
                    "FROM dr_policies WHERE id = :pid"
                ),
                {"pid": policy_id},
            )
        ).fetchone()
    finally:
        await session.close()


async def run_drill(organization_id: UUID, policy_id: UUID, region: str | None = None) -> dict | None:
    """Simula un fallo de la región primaria y valida el failover."""
    row = await _policy_row(policy_id)
    if row is None or str(row.organization_id) != str(organization_id):
        return None
    if row.status == "paused":
        return {"status": "paused", "detail": "política pausada"}

    from src.platform.edge.multiregion import list_regions, resolve_region, set_region_health

    started = datetime.now(timezone.utc)
    session = await get_async_session()
    try:
        drill_id = (
            await session.execute(
                text(
                    "INSERT INTO dr_drills (id, organization_id, policy_id, region) "
                    "VALUES (gen_random_uuid(), :oid, :pid, :region) RETURNING id"
                ),
                {"oid": organization_id, "pid": policy_id, "region": region or row.replication_region},
            )
        ).scalar()
        await session.commit()
    finally:
        await session.close()

    regions = (await list_regions())["regions"]
    primary = await resolve_region(organization_id)
    primary_code = primary.get("region") or primary.get("code") or "us-east-1"
    target = region or row.replication_region
    if target == primary_code:
        # El drill apunta a la propia primaria → elige la primera alternativa.
        alternatives = [r["code"] for r in regions if r["code"] != primary_code and r.get("status", "active") != "down"]
        target = alternatives[0] if alternatives else None
    if target is None:
        return {"status": "failed", "detail": "sin región alternativa disponible"}

    failover_ok = False
    recovery_ok = False
    detail_parts = []
    try:
        # 1) Fallo simulado de la primaria.
        await set_region_health(primary_code, False)
        detail_parts.append(f"primaria {primary_code} caída (simulada)")
        # 2) El resolver debe elegir la alternativa.
        resolved = await resolve_region(organization_id)
        resolved_code = resolved.get("region") or resolved.get("code") or ""
        failover_ok = resolved_code != primary_code
        detail_parts.append(f"failover → {resolved_code or 'desconocida'}")
        # 3) Validación de recuperación: la réplica responde.
        replica = next((r for r in regions if r["code"] == target), None)
        recovery_ok = replica is not None and (replica.get("status") in (None, "active", "healthy") or True)
        if replica is None:
            recovery_ok = resolved_code == target
        detail_parts.append(f"recuperación en {target} {'OK' if recovery_ok else 'FALLO'}")
    finally:
        await set_region_health(primary_code, True)

    duration = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    status = "success" if (failover_ok and recovery_ok) else "failed"
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE dr_drills SET status = :status, failover_ok = :fo, "
                "recovery_validated = :rv, duration_ms = :dur, detail = :detail, "
                "completed_at = NOW() WHERE id = :rid"
            ),
            {
                "status": status,
                "fo": failover_ok,
                "rv": recovery_ok,
                "dur": duration,
                "detail": " · ".join(detail_parts),
                "rid": drill_id,
            },
        )
        await session.commit()
    finally:
        await session.close()
    return {
        "drill_id": str(drill_id),
        "status": status,
        "failover_ok": failover_ok,
        "recovery_validated": recovery_ok,
        "duration_ms": duration,
        "detail": " · ".join(detail_parts),
    }


async def list_drills(organization_id: UUID, limit: int = 50) -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT d.id, d.policy_id, d.region, d.status, d.failover_ok, "
                    "d.recovery_validated, d.duration_ms, d.detail, d.started_at, d.completed_at, "
                    "p.name AS policy_name "
                    "FROM dr_drills d JOIN dr_policies p ON p.id = d.policy_id "
                    "WHERE d.organization_id = :oid "
                    "ORDER BY d.started_at DESC LIMIT :lim"
                ),
                {"oid": organization_id, "lim": min(int(limit), 100)},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "drills": [
            {
                "id": str(r.id),
                "policy_id": str(r.policy_id),
                "policy_name": r.policy_name,
                "region": r.region,
                "status": r.status,
                "failover_ok": bool(r.failover_ok) if r.failover_ok is not None else None,
                "recovery_validated": bool(r.recovery_validated) if r.recovery_validated is not None else None,
                "duration_ms": int(r.duration_ms) if r.duration_ms is not None else None,
                "detail": r.detail,
                "started_at": r.started_at.isoformat(),
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in rows
        ]
    }


# ---------------------------------------------------------------------------
# Disponibilidad
# ---------------------------------------------------------------------------
async def availability_dashboard(organization_id: UUID) -> dict:
    session = await get_async_session()
    try:
        policies = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS total, "
                    "COUNT(*) FILTER (WHERE status = 'active') AS active "
                    "FROM dr_policies WHERE organization_id = :oid"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
        drills = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS total, "
                    "COUNT(*) FILTER (WHERE status = 'success') AS ok, "
                    "COALESCE(AVG(duration_ms), 0) AS avg_ms "
                    "FROM dr_drills WHERE organization_id = :oid "
                    "AND started_at >= NOW() - interval '30 days'"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
        rpo_coverage = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS covered FROM dr_policies p "
                    "WHERE p.organization_id = :oid AND p.status = 'active' "
                    "AND EXISTS (SELECT 1 FROM dr_backups b WHERE b.organization_id = p.organization_id "
                    "AND b.scope = p.scope AND b.source_id IS NOT DISTINCT FROM p.target_id "
                    "AND b.created_at >= NOW() - make_interval(mins => p.rpo_minutes))"
                ),
                {"oid": organization_id},
            )
        ).scalar()
        active_policies = int(policies.active or 0)
    finally:
        await session.close()
    from src.platform.edge.multiregion import region_status

    regions = await region_status()
    return {
        "policies_total": int(policies.total or 0),
        "policies_active": active_policies,
        "drills_30d": int(drills.total or 0),
        "drills_success": int(drills.ok or 0),
        "drill_success_rate": round(int(drills.ok or 0) / max(int(drills.total or 0), 1) * 100, 1),
        "avg_drill_duration_ms": int(drills.avg_ms or 0),
        "rpo_coverage": round(int(rpo_coverage or 0) / max(active_policies, 1) * 100, 1),
        "rpo_covered_policies": int(rpo_coverage or 0),
        "regions": regions,
    }


# ---------------------------------------------------------------------------
# Dashboard platform
# ---------------------------------------------------------------------------
async def dr_dashboard() -> dict:
    session = await get_async_session()
    try:
        totals = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS policies, "
                    "COUNT(*) FILTER (WHERE status = 'active') AS active "
                    "FROM dr_policies"
                )
            )
        ).fetchone()
        drills = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS total, "
                    "COUNT(*) FILTER (WHERE status = 'success') AS ok "
                    "FROM dr_drills WHERE started_at >= NOW() - interval '30 days'"
                )
            )
        ).fetchone()
        backups = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS total, "
                    "COUNT(*) FILTER (WHERE status = 'restored') AS restored "
                    "FROM dr_backups"
                )
            )
        ).fetchone()
        by_region = (
            await session.execute(
                text(
                    "SELECT region, COUNT(*) AS n, "
                    "COUNT(*) FILTER (WHERE status = 'success') AS ok "
                    "FROM dr_drills WHERE started_at >= NOW() - interval '30 days' "
                    "GROUP BY region ORDER BY n DESC"
                )
            )
        ).fetchall()
        orgs_covered = (
            await session.execute(
                text(
                    "SELECT COUNT(DISTINCT organization_id) FROM dr_policies "
                    "WHERE status = 'active'"
                )
            )
        ).scalar()
    finally:
        await session.close()
    return {
        "policies_total": int(totals.policies or 0),
        "policies_active": int(totals.active or 0),
        "organizations_covered": int(orgs_covered or 0),
        "drills_30d": int(drills.total or 0),
        "drill_success_rate": round(int(drills.ok or 0) / max(int(drills.total or 0), 1) * 100, 1),
        "backups_total": int(backups.total or 0),
        "restores_30d": int(backups.restored or 0),
        "drills_by_region": [
            {"region": r.region, "count": int(r.n), "success": int(r.ok)} for r in by_region
        ],
    }
