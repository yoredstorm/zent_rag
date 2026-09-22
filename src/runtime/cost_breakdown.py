# =============================================================================
# Cost breakdown — desglose por request/run y por tenant.
# =============================================================================
# Sólo lectura sobre `usage_events` (ya idempotente por (request_id, event_type)):
#   JEV Routing / Evidence / Grounding / Agent Step, LLM, Embeddings,
#   Reranker, Tools, Agents, Workflows.
#
# Cost per successful answer / agent run / workflow run / tenant se calculan
# con `status='completed'`. Nunca inventa costos: si un evento no tiene costo
# queda en 0.
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

# Categoría -> patrones de event_type (prefijo o igualdad).
CATEGORY_PATTERNS: dict[str, tuple[str, ...]] = {
    "jev_pre_retrieval": ("jev_judge:pre_retrieval", "jev_judge:routing"),
    "jev_evidence": ("jev_judge:evidence", "jev_judge:post_retrieval"),
    "jev_grounding": ("jev_judge:grounding", "jev_judge:post_generation"),
    "jev_agent_step": (
        "jev_judge:tool_routing",
        "jev_judge:agent_step",
        "jev_judge:termination",
        "jev_judge:answer_gate",
    ),
    "jev_other": ("jev_judge:",),
    "routing": ("decision",),
    "llm": ("llm", "rag_llm", "query", "knowledge_llm_analysis", "intelligence."),
    "embeddings": ("embedding", "embeddings", "embed"),
    "reranker": ("rerank", "reranker"),
    "tools": ("tool", "mcp_tool"),
    "agents": ("agent_run",),
    "workflows": ("workflow_run", "workflow.run"),
}

CATEGORY_ORDER: tuple[str, ...] = (
    "jev_pre_retrieval",
    "jev_evidence",
    "jev_grounding",
    "jev_agent_step",
    "jev_other",
    "routing",
    "llm",
    "embeddings",
    "reranker",
    "tools",
    "agents",
    "workflows",
    "other",
)


def categorize(event_type: str) -> str:
    value = str(event_type or "")
    for category in CATEGORY_ORDER:
        patterns = CATEGORY_PATTERNS.get(category)
        if not patterns:
            continue
        for pattern in patterns:
            if value == pattern or value.startswith(pattern):
                return category
    return "other"


async def _rows(query: str, params: dict[str, Any]) -> list[dict]:
    session = await get_async_session()
    try:
        result = await session.execute(text(query), params)
        return [dict(row) for row in result.mappings().all()]
    except Exception as exc:  # noqa: BLE001
        logger.warning("cost breakdown query failed", error=str(exc)[:200])
        return []
    finally:
        await session.close()


def _scope(organization_id: UUID | None, days: int) -> tuple[str, dict[str, Any]]:
    window = max(1, min(int(days or 30), 365))
    if organization_id is None:
        return "", {"days": window}
    return " AND organization_id = :oid", {"days": window, "oid": organization_id}


async def cost_breakdown(
    *,
    organization_id: UUID | None = None,
    days: int = 30,
) -> dict[str, Any]:
    """Desglose agregado + ratios de costo por resultado."""
    where, params = _scope(organization_id, days)
    window = "created_at > NOW() - (:days * INTERVAL '1 day')"
    rows = await _rows(
        f"""
        SELECT event_type,
               COUNT(*)::int AS events,
               COUNT(DISTINCT request_id)::int AS requests,
               COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost,
               COALESCE(SUM(total_tokens), 0)::bigint AS tokens,
               AVG(latency_ms)::float AS avg_latency_ms,
               COUNT(*) FILTER (WHERE status = 'completed')::int AS completed
        FROM usage_events
        WHERE {window}{where}
        GROUP BY event_type
        ORDER BY cost DESC
        """,
        params,
    )
    buckets: dict[str, dict[str, Any]] = {
        category: {
            "category": category,
            "events": 0,
            "requests": 0,
            "cost": 0.0,
            "tokens": 0,
            "avg_latency_ms": 0.0,
            "event_types": [],
        }
        for category in CATEGORY_ORDER
    }
    for row in rows:
        category = categorize(str(row.get("event_type") or ""))
        bucket = buckets[category]
        bucket["events"] += int(row.get("events") or 0)
        bucket["requests"] += int(row.get("requests") or 0)
        bucket["cost"] += float(row.get("cost") or 0.0)
        bucket["tokens"] += int(row.get("tokens") or 0)
        bucket["event_types"].append(
            {
                "event_type": str(row.get("event_type") or "")[:60],
                "events": int(row.get("events") or 0),
                "cost": round(float(row.get("cost") or 0.0), 6),
            }
        )
    categories = [
        {**bucket, "cost": round(bucket["cost"], 6)}
        for bucket in buckets.values()
        if bucket["events"]
    ]
    total_cost = round(sum(bucket["cost"] for bucket in categories), 6)
    jev_cost = round(
        sum(
            bucket["cost"]
            for bucket in categories
            if str(bucket["category"]).startswith("jev_")
        ),
        6,
    )

    def _cost_for(event_types: tuple[str, ...]) -> float:
        return round(
            sum(
                float(row.get("cost") or 0.0)
                for row in rows
                if str(row.get("event_type") or "") in event_types
            ),
            6,
        )

    completed = {
        str(row.get("event_type") or ""): int(row.get("completed") or 0)
        for row in rows
    }
    answers = sum(
        count
        for event_type, count in completed.items()
        if categorize(event_type) == "llm"
    )
    agent_runs = completed.get("agent_run", 0)
    workflow_runs = sum(
        count
        for event_type, count in completed.items()
        if categorize(event_type) == "workflows"
    )
    tenants = await _rows(
        f"""
        SELECT organization_id::text AS organization_id,
               COUNT(DISTINCT request_id)::int AS requests,
               COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost
        FROM usage_events
        WHERE {window}{where}
        GROUP BY organization_id
        ORDER BY cost DESC
        LIMIT 20
        """,
        params,
    )
    return {
        "window_days": params["days"],
        "total_cost": total_cost,
        "jev_cost": jev_cost,
        "jev_share": round(jev_cost / total_cost, 4) if total_cost else None,
        "categories": categories,
        "per_result": {
            "cost_per_successful_answer": (
                round(_cost_for(("query", "llm", "rag_llm")) / answers, 6)
                if answers
                else None
            ),
            "cost_per_agent_run": (
                round(_cost_for(("agent_run",)) / agent_runs, 6) if agent_runs else None
            ),
            "cost_per_workflow_run": (
                round(
                    sum(
                        float(row.get("cost") or 0.0)
                        for row in rows
                        if categorize(str(row.get("event_type") or "")) == "workflows"
                    )
                    / workflow_runs,
                    6,
                )
                if workflow_runs
                else None
            ),
        },
        "by_tenant": tenants,
        "note": "costos estimados desde usage_events; infrastructure_estimate no instrumentado",
    }


async def request_cost_breakdown(
    *,
    organization_id: UUID,
    request_id: UUID,
) -> dict[str, Any]:
    """Desglose de un request/run puntual (tenant-scoped)."""
    rows = await _rows(
        """
        SELECT event_type,
               COUNT(*)::int AS events,
               COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost,
               COALESCE(SUM(total_tokens), 0)::bigint AS tokens,
               MAX(latency_ms)::float AS latency_ms
        FROM usage_events
        WHERE organization_id = :oid AND request_id = :rid
        GROUP BY event_type
        ORDER BY cost DESC
        """,
        {"oid": organization_id, "rid": request_id},
    )
    categories: dict[str, dict[str, Any]] = {}
    total = 0.0
    for row in rows:
        category = categorize(str(row.get("event_type") or ""))
        bucket = categories.setdefault(
            category, {"category": category, "cost": 0.0, "tokens": 0, "events": []}
        )
        cost = float(row.get("cost") or 0.0)
        bucket["cost"] = round(bucket["cost"] + cost, 6)
        bucket["tokens"] += int(row.get("tokens") or 0)
        bucket["events"].append(str(row.get("event_type") or "")[:60])
        total += cost
    return {
        "request_id": str(request_id),
        "total_cost": round(total, 6),
        "categories": sorted(categories.values(), key=lambda item: item["cost"], reverse=True),
    }
