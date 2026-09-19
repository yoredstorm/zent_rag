# =============================================================================
# Decision traces — Postgres, tenant-isolated.
# =============================================================================
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text

from src.core.domain.decision import DecisionTrace
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)


class DecisionTraceStore:
    async def record(self, trace: DecisionTrace) -> None:
        if trace.organization_id is None:
            return
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    """
                    INSERT INTO decision_traces (
                        id, organization_id, request_id, user_id, provider,
                        selected_capability, confidence, fallback_used,
                        latency_ms, estimated_cost, routing_mode,
                        actual_capability, jev_capability, agreement,
                        shadow, canary, payload
                    ) VALUES (
                        :id, :organization_id, :request_id, :user_id, :provider,
                        :selected_capability, :confidence, :fallback_used,
                        :latency_ms, :estimated_cost, :routing_mode,
                        :actual_capability, :jev_capability, :agreement,
                        :shadow, :canary, CAST(:payload AS jsonb)
                    )
                    """
                ),
                {
                    "id": trace.decision_id,
                    "organization_id": trace.organization_id,
                    "request_id": trace.request_id,
                    "user_id": trace.user_id,
                    "provider": trace.provider[:40],
                    "selected_capability": (trace.selected_capability or "")[:80],
                    "confidence": float(trace.confidence or 0.0),
                    "fallback_used": bool(trace.fallback_used),
                    "latency_ms": float(trace.latency_ms or 0.0),
                    "estimated_cost": float(trace.estimated_cost or 0.0),
                    "routing_mode": (trace.routing_mode or "")[:20],
                    "actual_capability": trace.actual_capability,
                    "jev_capability": trace.jev_capability,
                    "agreement": trace.agreement,
                    "shadow": bool(trace.shadow),
                    "canary": bool(trace.canary),
                    "payload": json.dumps(trace.to_dict(), default=str),
                },
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("decision trace persist failed", error=str(exc)[:200])
        finally:
            await session.close()

    async def update_actual(
        self,
        trace_id: str,
        *,
        actual_capability: str,
        jev_capability: str | None = None,
    ) -> None:
        """Fill what actually executed so cutover decisions have ground truth."""
        try:
            from uuid import UUID as _UUID

            parsed = _UUID(str(trace_id))
        except (ValueError, TypeError):
            return
        session = await get_async_session()
        try:
            if jev_capability:
                agreement: bool | None = jev_capability == actual_capability
            else:
                agreement = None
            await session.execute(
                text(
                    """
                    UPDATE decision_traces
                    SET actual_capability = :actual,
                        agreement = COALESCE(
                            CAST(:agreement AS boolean),
                            selected_capability = :actual
                        )
                    WHERE id = :id
                    """
                ),
                {
                    "actual": (actual_capability or "")[:80],
                    "agreement": agreement,
                    "id": parsed,
                },
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("decision trace update failed", error=str(exc)[:200])
        finally:
            await session.close()

    async def list_recent(
        self,
        organization_id: UUID | None,
        *,
        limit: int = 50,
    ) -> list[dict]:
        session = await get_async_session()
        try:
            if organization_id is None:
                rows = (
                    await session.execute(
                        text(
                            """
                            SELECT id, organization_id, provider, selected_capability,
                                   confidence, fallback_used, latency_ms, estimated_cost,
                                   routing_mode, actual_capability, jev_capability,
                                   agreement, shadow, canary, created_at
                            FROM decision_traces
                            ORDER BY created_at DESC
                            LIMIT :limit
                            """
                        ),
                        {"limit": min(limit, 200)},
                    )
                ).mappings().all()
            else:
                rows = (
                    await session.execute(
                        text(
                            """
                            SELECT id, organization_id, provider, selected_capability,
                                   confidence, fallback_used, latency_ms, estimated_cost,
                                   routing_mode, actual_capability, jev_capability,
                                   agreement, shadow, canary, created_at
                            FROM decision_traces
                            WHERE organization_id = :oid
                            ORDER BY created_at DESC
                            LIMIT :limit
                            """
                        ),
                        {"oid": organization_id, "limit": min(limit, 200)},
                    )
                ).mappings().all()
            return [dict(row) for row in rows]
        except Exception as exc:  # noqa: BLE001
            logger.warning("decision trace list failed", error=str(exc)[:200])
            return []
        finally:
            await session.close()

    async def dashboard(self) -> dict:
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT
                          COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE) AS decisions_today,
                          COUNT(*) FILTER (
                            WHERE created_at >= CURRENT_DATE AND provider = 'rules'
                          ) AS rules_count,
                          COUNT(*) FILTER (
                            WHERE created_at >= CURRENT_DATE AND provider = 'jev'
                          ) AS jev_count,
                          COUNT(*) FILTER (
                            WHERE created_at >= CURRENT_DATE AND provider = 'llm'
                            AND COALESCE(payload->>'needs_reasoning','false') <> 'true'
                          ) AS small_llm_count,
                          COUNT(*) FILTER (
                            WHERE created_at >= CURRENT_DATE AND selected_capability = 'llm.reason'
                          ) AS reasoning_count,
                          AVG(confidence) FILTER (WHERE created_at >= CURRENT_DATE) AS avg_confidence,
                          AVG(CASE WHEN fallback_used THEN 1.0 ELSE 0.0 END)
                            FILTER (WHERE created_at >= CURRENT_DATE) AS fallback_rate,
                          AVG(latency_ms) FILTER (WHERE created_at >= CURRENT_DATE) AS avg_latency_ms,
                          COALESCE(SUM(estimated_cost) FILTER (WHERE created_at >= CURRENT_DATE), 0)
                            AS cost_today
                        FROM decision_traces
                        """
                    )
                )
            ).mappings().first()
            data = dict(row) if row else {}
            today = int(data.get("decisions_today") or 0) or 1
            return {
                "decisions_today": int(data.get("decisions_today") or 0),
                "rules_pct": round(100.0 * float(data.get("rules_count") or 0) / today, 1),
                "jev_pct": round(100.0 * float(data.get("jev_count") or 0) / today, 1),
                "small_llm_pct": round(100.0 * float(data.get("small_llm_count") or 0) / today, 1),
                "reasoning_llm_pct": round(
                    100.0 * float(data.get("reasoning_count") or 0) / today, 1
                ),
                "average_confidence": round(float(data.get("avg_confidence") or 0.0), 3),
                "fallback_rate": round(float(data.get("fallback_rate") or 0.0), 3),
                "average_latency_ms": round(float(data.get("avg_latency_ms") or 0.0), 1),
                "estimated_savings": round(float(data.get("cost_today") or 0.0), 6),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("decision dashboard failed", error=str(exc)[:200])
            return {
                "decisions_today": 0,
                "rules_pct": 0.0,
                "jev_pct": 0.0,
                "small_llm_pct": 0.0,
                "reasoning_llm_pct": 0.0,
                "average_confidence": 0.0,
                "fallback_rate": 0.0,
                "average_latency_ms": 0.0,
                "estimated_savings": 0.0,
            }
        finally:
            await session.close()
