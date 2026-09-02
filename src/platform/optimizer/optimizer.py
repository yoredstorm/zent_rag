# =============================================================================
# Performance & Cost Optimization Advisor
# Perfiles por agente/deployment + recomendaciones accionables con apply.
# =============================================================================
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Perfiles
# ---------------------------------------------------------------------------
async def agent_profiles(organization_id: UUID) -> list[dict]:
    """Latencia (p50/p95), error rate, tokens y costo por agente (30d)."""
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT ue.agent_id, COALESCE(a.name, 'sin agente') AS agent_name, "
                    "COUNT(*)::int AS requests, "
                    "COUNT(*) FILTER (WHERE ue.status IN ('error','failed'))::int AS errors, "
                    "COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY ue.latency_ms), 0)::float AS p50, "
                    "COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY ue.latency_ms), 0)::float AS p95, "
                    "COALESCE(SUM(ue.total_tokens)::float / NULLIF(COUNT(*), 0), 0)::float AS tokens_per_request, "
                    "COALESCE(SUM(COALESCE(ue.actual_cost, ue.estimated_cost)) "  # noqa: E501
                    "/ NULLIF(COUNT(*), 0), 0)::float AS cost_per_request, "
                    "COALESCE(SUM(ue.embedding_tokens)::float "  # noqa: E501
                    "/ NULLIF(SUM(ue.total_tokens), 0), 0)::float AS embedding_share, "
                    "COALESCE(SUM(ue.retrieval_count)::float / NULLIF(COUNT(*), 0), 0)::float AS sources_per_request "
                    "FROM usage_events ue LEFT JOIN agents a ON a.id = ue.agent_id "
                    "WHERE ue.organization_id = :oid AND ue.event_type = 'agent_run' "
                    "AND ue.created_at > NOW() - INTERVAL '30 days' "
                    "GROUP BY 1, 2 ORDER BY requests DESC"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "agent_id": str(r.agent_id) if r.agent_id else None,
            "agent_name": r.agent_name,
            "requests": int(r.requests),
            "error_rate_pct": round(float(r.errors) / r.requests * 100, 2) if r.requests else 0.0,
            "p50_ms": round(float(r.p50), 1),
            "p95_ms": round(float(r.p95), 1),
            "tokens_per_request": round(float(r.tokens_per_request), 1),
            "cost_per_request": round(float(r.cost_per_request), 6),
            "embedding_share_pct": round(float(r.embedding_share) * 100, 1) if r.embedding_share else 0.0,
            "sources_per_request": round(float(r.sources_per_request), 1),
        }
        for r in rows
    ]


async def deployment_profile(organization_id: UUID, deployment_id: UUID) -> dict | None:
    session = await get_async_session()
    try:
        dep = (
            await session.execute(
                text(
                    "SELECT d.id, d.slug, d.status, a.name AS agent_name, "
                    "a.model, a.config_json "
                    "FROM deployments d JOIN agents a ON a.id = d.agent_id "
                    "WHERE d.id = :did AND d.organization_id = :oid"
                ),
                {"did": deployment_id, "oid": organization_id},
            )
        ).fetchone()
        if dep is None:
            return None
        stats = (
            await session.execute(
                text(
                    "SELECT COUNT(*)::int AS requests, "
                    "COUNT(*) FILTER (WHERE status IN ('error','failed'))::int AS errors, "
                    "COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms), 0)::float AS p50, "
                    "COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms), 0)::float AS p95, "
                    "COALESCE(SUM(total_tokens)::float / NULLIF(COUNT(*), 0), 0)::float AS tokens_per_request, "
                    "COALESCE(SUM(COALESCE(actual_cost, estimated_cost)) / "  # noqa: E501
                    "NULLIF(COUNT(*), 0), 0)::float AS cost_per_request "
                    "FROM usage_events WHERE organization_id = :oid "
                    "AND deployment_id = :did AND event_type = 'agent_run' "
                    "AND created_at > NOW() - INTERVAL '30 days'"
                ),
                {"oid": organization_id, "did": deployment_id},
            )
        ).fetchone()
    finally:
        await session.close()
    return {
        "deployment_id": str(dep.id),
        "slug": dep.slug,
        "status": dep.status,
        "agent_name": dep.agent_name,
        "model": dep.model,
        "config": dep.config_json or {},
        "requests": int(stats.requests or 0),
        "error_rate_pct": round(float(stats.errors or 0) / max(int(stats.requests or 0), 1) * 100, 2),
        "p50_ms": round(float(stats.p50 or 0), 1),
        "p95_ms": round(float(stats.p95 or 0), 1),
        "tokens_per_request": round(float(stats.tokens_per_request or 0), 1),
        "cost_per_request": round(float(stats.cost_per_request or 0), 6),
    }


# ---------------------------------------------------------------------------
# Motor de recomendaciones
# ---------------------------------------------------------------------------
async def _insert_recommendation(
    organization_id: UUID,
    recommendation_key: str,
    severity: str,
    message: str,
    expected_savings_pct: float | None,
    details: dict,
    agent_id: UUID | None,
    deployment_id: UUID | None,
) -> bool:
    session = await get_async_session()
    try:
        exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM optimizer_actions "
                    "WHERE organization_id = :oid AND recommendation_key = :key "
                    "AND status = 'suggested' "
                    "AND (agent_id IS NOT DISTINCT FROM :aid) "
                    "AND (deployment_id IS NOT DISTINCT FROM :did) "
                    "AND created_at > NOW() - INTERVAL '7 days' LIMIT 1"
                ),
                {"oid": organization_id, "key": recommendation_key, "aid": agent_id, "did": deployment_id},
            )
        ).fetchone()
        if exists:
            return False
        await session.execute(
            text(
                "INSERT INTO optimizer_actions (id, organization_id, agent_id, "
                "deployment_id, recommendation_key, severity, message, "
                "expected_savings_pct, details) "
                "VALUES (gen_random_uuid(), :oid, :aid, :did, :key, :sev, :msg, "
                ":savings, :details)"
            ),
            {
                "oid": organization_id,
                "aid": agent_id,
                "did": deployment_id,
                "key": recommendation_key,
                "sev": severity,
                "msg": message[:500],
                "savings": expected_savings_pct,
                "details": json.dumps(details),
            },
        )
        await session.commit()
        return True
    finally:
        await session.close()


async def _agent_config(organization_id: UUID, agent_id: UUID) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT model, config_json FROM agents "
                    "WHERE id = :aid AND organization_id = :oid"
                ),
                {"aid": agent_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return {}
    return {"model": row.model, "config_json": row.config_json or {}}


def _is_cheap_model(model: str | None) -> bool:
    return (model or "").lower() in ("zent-cheap", "") or "mini" in (model or "").lower()


def _rule_engine(profile: dict, org_id: UUID, agent_id: UUID | None, deployment_id: UUID | None) -> list[dict]:
    settings = get_settings()
    rules: list[dict] = []

    if profile["requests"] < 5:
        return rules

    # 1) Modelo caro o lento → zent-cheap.
    latency_high = profile["p95_ms"] > settings.OBS_P95_LATENCY_MS * 0.7
    cost_high = profile["cost_per_request"] > 0.002
    if (latency_high or cost_high) and profile["requests"] >= 10:
        rules.append(
            {
                "key": "cheaper_model",
                "severity": "important" if cost_high else "optimization",
                "message": (
                    f"Agente '{profile['agent_name']}': p95 {profile['p95_ms']:.0f}ms y "
                    f"${profile['cost_per_request']:.5f}/req. Cambiar al alias zent-cheap "
                    "puede reducir el costo 20-40%."
                ),
                "savings": 30.0 if cost_high else 20.0,
                "details": {
                    "p95_ms": profile["p95_ms"],
                    "cost_per_request": profile["cost_per_request"],
                    "suggested_model": "zent-cheap",
                },
                "agent_id": agent_id,
                "deployment_id": deployment_id,
            }
        )

    # 2) Tokens altos por request → reducir top_k.
    if profile["tokens_per_request"] > 1500:
        rules.append(
            {
                "key": "reduce_top_k",
                "severity": "optimization",
                "message": (
                    f"Agente '{profile['agent_name']}': {profile['tokens_per_request']:.0f} "
                    "tokens/request. Reducir retrieval.top_k (a 3) baja tokens y latencia ~15%."
                ),
                "savings": 15.0,
                "details": {
                    "tokens_per_request": profile["tokens_per_request"],
                    "suggested_top_k": 3,
                },
                "agent_id": agent_id,
                "deployment_id": deployment_id,
            }
        )

    # 3) Error rate alto con temperature alta → bajar temperature.
    if profile["error_rate_pct"] > 10:
        rules.append(
            {
                "key": "reduce_temperature",
                "severity": "important",
                "message": (
                    f"Agente '{profile['agent_name']}': {profile['error_rate_pct']:.0f}% de "
                    "errores. Reducir temperature (a 0.3) estabiliza las respuestas."
                ),
                "savings": None,
                "details": {"error_rate_pct": profile["error_rate_pct"], "suggested_temperature": 0.3},
                "agent_id": agent_id,
                "deployment_id": deployment_id,
            }
        )

    # 4) Muchas fuentes por request → recortar.
    if profile["sources_per_request"] > 6:
        rules.append(
            {
                "key": "prune_sources",
                "severity": "info",
                "message": (
                    f"Agente '{profile['agent_name']}': {profile['sources_per_request']:.0f} "
                    "fuentes/request. Limitar las fuentes inyectadas mejora precisión y costo."
                ),
                "savings": 8.0,
                "details": {"sources_per_request": profile["sources_per_request"], "suggested_max": 4},
                "agent_id": agent_id,
                "deployment_id": deployment_id,
            }
        )

    # 5) Share alto de embeddings → cache.
    if profile["embedding_share_pct"] > 30:
        rules.append(
            {
                "key": "embedding_cache",
                "severity": "info",
                "message": (
                    f"Agente '{profile['agent_name']}': {profile['embedding_share_pct']:.0f}% de "
                    "tokens son de embeddings. Cachear embeddings reduce costo de ingesta."
                ),
                "savings": 10.0,
                "details": {"embedding_share_pct": profile["embedding_share_pct"]},
                "agent_id": agent_id,
                "deployment_id": deployment_id,
            }
        )

    return rules


async def scan(organization_id: UUID | None = None) -> list[dict]:
    """Computa perfiles y crea recomendaciones (dedupe 7d)."""
    session = await get_async_session()
    try:
        orgs = (
            await session.execute(
                text(
                    "SELECT id FROM organizations WHERE status <> 'deleted' "
                    "AND (CAST(:oid AS uuid) IS NULL OR id = :oid)"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()

    created: list[dict] = []
    for org in orgs:
        for profile in await agent_profiles(org.id):
            if not profile["agent_id"]:
                continue
            for rule in _rule_engine(profile, org.id, UUID(profile["agent_id"]), None):
                ok = await _insert_recommendation(
                    org.id,
                    rule["key"],
                    rule["severity"],
                    rule["message"],
                    rule["savings"],
                    rule["details"],
                    UUID(profile["agent_id"]) if profile["agent_id"] else None,
                    None,
                )
                if ok:
                    created.append(
                        {
                            "type": rule["key"],
                            "agent_id": profile["agent_id"],
                            "organization_id": str(org.id),
                        }
                    )
    return created


async def list_recommendations(
    organization_id: UUID | None, status: str | None = None, limit: int = 100
) -> list[dict]:
    session = await get_async_session()
    try:
        sql = (
            "SELECT id, organization_id, agent_id, deployment_id, recommendation_key, "
            "severity, message, expected_savings_pct, status, details, created_at, "
            "applied_at FROM optimizer_actions WHERE 1=1 "
        )
        params: dict = {"limit": limit}
        if organization_id is not None:
            sql += " AND organization_id = :oid "
            params["oid"] = organization_id
        if status:
            sql += " AND status = :status "
            params["status"] = status
        sql += " ORDER BY created_at DESC LIMIT :limit"
        rows = (await session.execute(text(sql), params)).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "organization_id": str(r.organization_id),
            "agent_id": str(r.agent_id) if r.agent_id else None,
            "deployment_id": str(r.deployment_id) if r.deployment_id else None,
            "recommendation_key": r.recommendation_key,
            "severity": r.severity,
            "message": r.message,
            "expected_savings_pct": r.expected_savings_pct,
            "status": r.status,
            "details": r.details or {},
            "created_at": r.created_at.isoformat(),
            "applied_at": r.applied_at.isoformat() if r.applied_at else None,
        }
        for r in rows
    ]


APPLYABLE = {"cheaper_model", "reduce_top_k", "reduce_temperature"}


async def apply_recommendation(recommendation_id: UUID) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, organization_id, agent_id, recommendation_key, "
                    "details, status FROM optimizer_actions WHERE id = :rid"
                ),
                {"rid": recommendation_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return {"status": "not_found"}
    if row.status != "suggested":
        return {"status": "already_" + row.status}
    if row.recommendation_key not in APPLYABLE or row.agent_id is None:
        return {"status": "not_applicable"}

    from src.infrastructure.postgres.relational_db import (
        PostgresAgentRepository,
    )

    agent_repo = PostgresAgentRepository()
    org_id = row.organization_id
    agent = await agent_repo.get_agent(org_id, row.agent_id)
    if agent is None:
        return {"status": "agent_not_found"}

    current_cfg = dict(agent.config_json or {})
    updated_cfg = dict(current_cfg)
    model = agent.model
    detail = dict(row.details or {})

    if row.recommendation_key == "cheaper_model":
        model = "zent-cheap"
        detail["applied_model"] = "zent-cheap"
    elif row.recommendation_key == "reduce_top_k":
        retrieval = dict(updated_cfg.get("retrieval") or {})
        retrieval["top_k"] = 3
        updated_cfg["retrieval"] = retrieval
        detail["applied_top_k"] = 3
    elif row.recommendation_key == "reduce_temperature":
        updated_cfg["temperature"] = 0.3
        detail["applied_temperature"] = 0.3

    await agent_repo.update_agent(
        org_id, agent.id, model=model, config_json=updated_cfg
    )
    now = datetime.now(timezone.utc)
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE optimizer_actions SET status = 'applied', applied_at = :now, "
                "details = :details WHERE id = :rid"
            ),
            {"now": now, "details": json.dumps(detail), "rid": recommendation_id},
        )
        await session.commit()
    finally:
        await session.close()
    return {
        "status": "applied",
        "model": model,
        "config_updated": True,
        "note": "Para deployments, crea una nueva versión y re-despliega.",
    }


async def ignore_recommendation(recommendation_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "UPDATE optimizer_actions SET status = 'ignored' "
                "WHERE id = :rid AND status = 'suggested'"
            ),
            {"rid": recommendation_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()
