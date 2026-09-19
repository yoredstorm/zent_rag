# =============================================================================
# Control Center AI Runtime dashboard — aggregates existing traces + usage.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.core.config import get_settings
from src.decision.capabilities import InMemoryCapabilityRegistry
from src.decision.traces import DecisionTraceStore
from src.infrastructure.postgres.session import get_async_session
from src.runtime.efficiency import (
    DEFAULT_WEIGHTS,
    composite_score,
    from_dashboard,
    normalize_weights,
)


async def runtime_dashboard() -> dict:
    store = DecisionTraceStore()
    decision = await store.dashboard()
    usage = await _usage_today()
    weights = await load_efficiency_weights()
    cost_index = 1.0
    avg_cost = float(usage.get("average_cost") or 0.0)
    if avg_cost > 0:
        cost_index = max(0.0, min(1.0, 0.02 / avg_cost))
    components, _, _ = from_dashboard(
        average_confidence=float(decision.get("average_confidence") or 0.0),
        fallback_rate=float(decision.get("fallback_rate") or 0.0),
        average_latency_ms=float(decision.get("average_latency_ms") or 0.0),
        cost_index=cost_index,
    )
    score = composite_score(components, weights)
    jev_pct = float(decision.get("jev_pct") or 0.0)
    rules_pct = float(decision.get("rules_pct") or 0.0)
    today = int(decision.get("decisions_today") or 0)
    avoided = int(round(today * (rules_pct + jev_pct) / 100.0))
    settings = get_settings()
    return {
        "decisions": decision,
        "usage": usage,
        "efficiency": {
            "score": score,
            "components": {
                "quality": components.quality,
                "cost": components.cost,
                "latency": components.latency,
                "fallback": components.fallback,
            },
            "weights": weights,
            "formula": "weighted sum of quality, cost, latency, fallback (0-1, higher better)",
        },
        "llm_calls_avoided_estimate": avoided,
        "tokens_saved_estimate": int(usage.get("tokens_saved_estimate") or 0),
        "flags": {
            "decision_mode": settings.DECISION_ROUTING_MODE,
            "adaptive_mode": settings.ADAPTIVE_RAG_MODE,
            "tool_routing": settings.RUNTIME_TOOL_ROUTING_MODE,
            "termination_gate": settings.RUNTIME_TERMINATION_GATE,
            "shadow_sample_rate": settings.RUNTIME_SHADOW_SAMPLE_RATE,
        },
    }


async def _usage_today() -> dict:
    session = await get_async_session()
    empty = {
        "requests": 0,
        "tokens": 0,
        "cost": 0.0,
        "average_cost": 0.0,
        "weighted_average_cost": 0.0,
        "by_event_type": [],
        "by_provider": [],
        "tokens_saved_estimate": 0,
    }
    try:
        row = (
            await session.execute(
                text(
                    """
                    SELECT COUNT(*)::int AS requests,
                           COALESCE(SUM(total_tokens), 0)::bigint AS tokens,
                           COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost
                    FROM usage_events
                    WHERE created_at >= CURRENT_DATE
                    """
                )
            )
        ).mappings().first()
        data = dict(row) if row else {}
        requests = int(data.get("requests") or 0)
        cost = float(data.get("cost") or 0.0)
        by_type = (
            await session.execute(
                text(
                    """
                    SELECT event_type,
                           COUNT(*)::int AS requests,
                           COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost
                    FROM usage_events
                    WHERE created_at >= CURRENT_DATE
                    GROUP BY event_type
                    ORDER BY requests DESC
                    LIMIT 12
                    """
                )
            )
        ).mappings().all()
        by_provider = (
            await session.execute(
                text(
                    """
                    SELECT COALESCE(provider, 'unknown') AS provider,
                           COUNT(*)::int AS requests,
                           COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost
                    FROM usage_events
                    WHERE created_at >= CURRENT_DATE
                    GROUP BY COALESCE(provider, 'unknown')
                    ORDER BY requests DESC
                    LIMIT 12
                    """
                )
            )
        ).mappings().all()
        weighted = cost / requests if requests else 0.0
        return {
            "requests": requests,
            "tokens": int(data.get("tokens") or 0),
            "cost": round(cost, 6),
            "average_cost": round(weighted, 6),
            "weighted_average_cost": round(weighted, 6),
            "by_event_type": [dict(r) for r in by_type],
            "by_provider": [dict(r) for r in by_provider],
            "tokens_saved_estimate": 0,
        }
    except Exception:  # noqa: BLE001
        return empty
    finally:
        await session.close()


async def load_efficiency_weights() -> dict[str, float]:
    settings = get_settings()
    fallback = normalize_weights(
        {
            "quality": settings.RUNTIME_EFFICIENCY_QUALITY_WEIGHT,
            "cost": settings.RUNTIME_EFFICIENCY_COST_WEIGHT,
            "latency": settings.RUNTIME_EFFICIENCY_LATENCY_WEIGHT,
            "fallback": settings.RUNTIME_EFFICIENCY_FALLBACK_WEIGHT,
        }
    )
    try:
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT quality, cost, latency, fallback FROM efficiency_score_weights WHERE id = 1"
                    )
                )
            ).fetchone()
        finally:
            await session.close()
        if row is None:
            return fallback
        return normalize_weights(
            {
                "quality": row.quality,
                "cost": row.cost,
                "latency": row.latency,
                "fallback": row.fallback,
            }
        )
    except Exception:  # noqa: BLE001
        return fallback or dict(DEFAULT_WEIGHTS)


async def save_efficiency_weights(weights: dict) -> dict[str, float]:
    normalized = normalize_weights(weights)
    session = await get_async_session()
    try:
        await session.execute(
            text(
                """
                INSERT INTO efficiency_score_weights (id, quality, cost, latency, fallback, updated_at)
                VALUES (1, :q, :c, :l, :f, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    quality = EXCLUDED.quality,
                    cost = EXCLUDED.cost,
                    latency = EXCLUDED.latency,
                    fallback = EXCLUDED.fallback,
                    updated_at = NOW()
                """
            ),
            {
                "q": normalized["quality"],
                "c": normalized["cost"],
                "l": normalized["latency"],
                "f": normalized["fallback"],
            },
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    return normalized


async def tenant_usage_breakdown(organization_id: UUID, days: int = 30) -> dict:
    days = max(1, min(days, 90))
    session = await get_async_session()
    empty = {"daily": [], "monthly": [], "by_capability": [], "by_provider": [], "forecast": None}
    try:
        daily = (
            await session.execute(
                text(
                    """
                    SELECT date_trunc('day', created_at)::date AS day,
                           COUNT(*)::int AS requests,
                           COALESCE(SUM(total_tokens), 0)::bigint AS tokens,
                           COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost
                    FROM usage_events
                    WHERE organization_id = :oid
                      AND created_at > NOW() - (:days * INTERVAL '1 day')
                    GROUP BY 1 ORDER BY 1
                    """
                ),
                {"oid": organization_id, "days": days},
            )
        ).mappings().all()
        monthly = (
            await session.execute(
                text(
                    """
                    SELECT date_trunc('month', created_at)::date AS month,
                           COUNT(*)::int AS requests,
                           COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost
                    FROM usage_events
                    WHERE organization_id = :oid
                      AND created_at > NOW() - INTERVAL '12 months'
                    GROUP BY 1 ORDER BY 1
                    """
                ),
                {"oid": organization_id},
            )
        ).mappings().all()
        by_cap = (
            await session.execute(
                text(
                    """
                    SELECT event_type AS capability,
                           COUNT(*)::int AS requests,
                           COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost
                    FROM usage_events
                    WHERE organization_id = :oid
                      AND created_at > NOW() - (:days * INTERVAL '1 day')
                    GROUP BY event_type ORDER BY requests DESC LIMIT 12
                    """
                ),
                {"oid": organization_id, "days": days},
            )
        ).mappings().all()
        by_provider = (
            await session.execute(
                text(
                    """
                    SELECT COALESCE(provider, 'unknown') AS provider,
                           COUNT(*)::int AS requests,
                           COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost
                    FROM usage_events
                    WHERE organization_id = :oid
                      AND created_at > NOW() - (:days * INTERVAL '1 day')
                    GROUP BY 1 ORDER BY requests DESC LIMIT 12
                    """
                ),
                {"oid": organization_id, "days": days},
            )
        ).mappings().all()
        forecast = None
        if len(daily) >= 7:
            last = [float(r["cost"] or 0) for r in daily[-7:]]
            avg = sum(last) / len(last)
            forecast = {
                "method": "7-day moving average of cost",
                "next_day_cost_estimate": round(avg, 6),
                "certainty": "none",
            }
        return {
            "daily": [
                {
                    "day": str(r["day"]),
                    "requests": int(r["requests"]),
                    "tokens": int(r["tokens"]),
                    "cost": float(r["cost"]),
                }
                for r in daily
            ],
            "monthly": [
                {"month": str(r["month"]), "requests": int(r["requests"]), "cost": float(r["cost"])}
                for r in monthly
            ],
            "by_capability": [dict(r) for r in by_cap],
            "by_provider": [dict(r) for r in by_provider],
            "forecast": forecast,
        }
    except Exception:  # noqa: BLE001
        return empty
    finally:
        await session.close()


async def profitability_snapshot() -> dict:
    session = await get_async_session()
    empty = {"organizations": [], "by_provider": [], "note": "internal only"}
    try:
        orgs = (
            await session.execute(
                text(
                    """
                    SELECT organization_id::text AS organization_id,
                           COUNT(*)::int AS requests,
                           COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS provider_cost
                    FROM usage_events
                    WHERE created_at >= date_trunc('month', NOW())
                    GROUP BY organization_id
                    ORDER BY provider_cost DESC
                    LIMIT 50
                    """
                )
            )
        ).mappings().all()
        providers = (
            await session.execute(
                text(
                    """
                    SELECT COALESCE(provider, 'unknown') AS provider,
                           COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS provider_cost
                    FROM usage_events
                    WHERE created_at >= date_trunc('month', NOW())
                    GROUP BY 1 ORDER BY provider_cost DESC LIMIT 20
                    """
                )
            )
        ).mappings().all()
        return {
            "period": "month_to_date",
            "organizations": [dict(r) for r in orgs],
            "by_provider": [dict(r) for r in providers],
            "infrastructure_estimated_cost": None,
            "note": "Revenue comes from billing invoices. Margin is Super Admin only. Never shown to tenants.",
        }
    except Exception:  # noqa: BLE001
        return empty
    finally:
        await session.close()


def list_capabilities() -> list[dict]:
    registry = InMemoryCapabilityRegistry()
    registry.sync_tools()
    out = []
    for spec in registry.list_available(permissions=frozenset({"*"})):
        out.append(
            {
                "id": spec.id,
                "name": spec.name,
                "description": spec.description,
                "risk": spec.risk_level.value if hasattr(spec.risk_level, "value") else str(spec.risk_level),
                "cost_class": spec.cost_class.value if hasattr(spec.cost_class, "value") else str(spec.cost_class),
                "permission": spec.required_permission,
                "timeout_seconds": spec.timeout_seconds,
                "handler": spec.handler,
                "availability": spec.availability,
                "tags": list(spec.tags),
            }
        )
    return out
