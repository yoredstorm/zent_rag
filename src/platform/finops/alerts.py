# =============================================================================
# FinOps Alerts — budget excedido, margen negativo, spikes de uso/provider
# =============================================================================
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

ALERT_BUDGET_EXCEEDED = "budget_exceeded"
ALERT_NEGATIVE_MARGIN = "negative_margin"
ALERT_USAGE_SPIKE = "usage_spike"
ALERT_PROVIDER_SPIKE = "provider_spike"


async def _insert_alert(
    organization_id: UUID,
    alert_type: str,
    message: str,
    threshold_value: float | None,
    actual_value: float | None,
) -> bool:
    """Inserta la alerta si no existe una idéntica no-ack en las últimas 24h."""
    session = await get_async_session()
    try:
        exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM finops_alerts "
                    "WHERE organization_id = :oid AND alert_type = :atype "
                    "AND acknowledged = false "
                    "AND created_at > NOW() - INTERVAL '24 hours' LIMIT 1"
                ),
                {"oid": organization_id, "atype": alert_type},
            )
        ).fetchone()
        if exists:
            return False
        await session.execute(
            text(
                "INSERT INTO finops_alerts (id, organization_id, alert_type, message, "
                "threshold_value, actual_value) "
                "VALUES (gen_random_uuid(), :oid, :atype, :msg, :thr, :act)"
            ),
            {
                "oid": organization_id,
                "atype": alert_type,
                "msg": message[:500],
                "thr": threshold_value,
                "act": actual_value,
            },
        )
        await session.commit()
        return True
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def check_organization(organization_id: UUID) -> list[dict]:
    """Ejecuta las 4 checks FinOps para una organización."""
    from datetime import datetime, timezone


    created: list[dict] = []
    now = datetime.now(timezone.utc)

    session = await get_async_session()
    try:
        org = (
            await session.execute(
                text(
                    "SELECT finops_budget_cents FROM organizations WHERE id = :oid"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
        budget_cents = int(org.finops_budget_cents) if org and org.finops_budget_cents else None

        # Uso actual (30d) y ventana previa (30d antes).
        current = (
            await session.execute(
                text(
                    "SELECT COUNT(*)::int AS requests, "
                    "COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost "
                    "FROM usage_events WHERE organization_id = :oid "
                    "AND created_at > NOW() - INTERVAL '30 days'"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
        prev = (
            await session.execute(
                text(
                    "SELECT COUNT(*)::int AS requests, "
                    "COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost "
                    "FROM usage_events WHERE organization_id = :oid "
                    "AND created_at > NOW() - INTERVAL '60 days' "
                    "AND created_at <= NOW() - INTERVAL '30 days'"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
        provider_prev = (
            await session.execute(
                text(
                    "SELECT provider, COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost "
                    "FROM usage_events WHERE organization_id = :oid "
                    "AND created_at > NOW() - INTERVAL '30 days' "
                    "GROUP BY provider"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()

    cost = float(current.cost or 0.0)
    requests = int(current.requests or 0)
    prev_cost = float(prev.cost or 0.0)
    prev_requests = int(prev.requests or 0)

    # 1) Budget excedido.
    if budget_cents is not None:
        budget = budget_cents / 100
        if cost > budget:
            ok = await _insert_alert(
                organization_id,
                ALERT_BUDGET_EXCEEDED,
                f"Costo AI 30d ${cost:,.2f} excede el budget ${budget:,.2f}",
                threshold_value=budget,
                actual_value=cost,
            )
            if ok:
                created.append({"type": ALERT_BUDGET_EXCEEDED, "message": "Budget excedido"})

    # 2) Margen negativo: revenue (paid invoices 30d) < costo.
    session = await get_async_session()
    try:
        revenue = (
            await session.execute(
                text(
                    "SELECT COALESCE(SUM(total_cents), 0)::bigint AS cents "
                    "FROM invoices WHERE organization_id = :oid "
                    "AND status = 'paid' AND paid_at > NOW() - INTERVAL '30 days'"
                ),
                {"oid": organization_id},
            )
        ).scalar()
    finally:
        await session.close()
    revenue_usd = int(revenue or 0) / 100
    if revenue_usd > 0 and cost > revenue_usd:
        margin = revenue_usd - cost
        ok = await _insert_alert(
            organization_id,
            ALERT_NEGATIVE_MARGIN,
            f"Margen negativo: revenue ${revenue_usd:,.2f} < costo ${cost:,.2f}",
            threshold_value=0.0,
            actual_value=margin,
        )
        if ok:
            created.append({"type": ALERT_NEGATIVE_MARGIN, "message": "Margen negativo"})

    # 3) Usage spike: requests 30d > 2x requests de los 30d previos.
    if prev_requests > 0 and requests > prev_requests * 2:
        ok = await _insert_alert(
            organization_id,
            ALERT_USAGE_SPIKE,
            f"Requests 30d ({requests}) > 2x del período previo ({prev_requests})",
            threshold_value=prev_requests * 2,
            actual_value=requests,
        )
        if ok:
            created.append({"type": ALERT_USAGE_SPIKE, "message": "Uso 2x"})

    # 4) Provider spike: costo de un provider 30d > 2x su costo previo.
    if prev_cost > 0:
        for row in provider_prev:
            provider = row.provider or "unknown"
            session = await get_async_session()
            try:
                prev_provider = (
                    await session.execute(
                        text(
                            "SELECT COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float "
                            "FROM usage_events WHERE organization_id = :oid AND provider = :p "
                            "AND created_at > NOW() - INTERVAL '60 days' "
                            "AND created_at <= NOW() - INTERVAL '30 days'"
                        ),
                        {"oid": organization_id, "p": provider},
                    )
                ).scalar()
            finally:
                await session.close()
            if float(prev_provider or 0) > 0 and float(row.cost or 0) > float(prev_provider) * 2:
                ok = await _insert_alert(
                    organization_id,
                    ALERT_PROVIDER_SPIKE,
                    f"Costo del provider '{provider}' 30d (${float(row.cost):,.2f}) > 2x previo",
                    threshold_value=float(prev_provider) * 2,
                    actual_value=float(row.cost or 0),
                )
                if ok:
                    created.append({"type": ALERT_PROVIDER_SPIKE, "message": f"Spike {provider}"})
    return created


async def list_alerts(organization_id: UUID, limit: int = 50) -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, alert_type, message, threshold_value, actual_value, "
                    "acknowledged, created_at FROM finops_alerts "
                    "WHERE organization_id = :oid ORDER BY created_at DESC LIMIT :limit"
                ),
                {"oid": organization_id, "limit": limit},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "alert_type": r.alert_type,
            "message": r.message,
            "threshold_value": r.threshold_value,
            "actual_value": r.actual_value,
            "acknowledged": bool(r.acknowledged),
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


async def acknowledge_alert(organization_id: UUID, alert_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "UPDATE finops_alerts SET acknowledged = true "
                "WHERE id = :aid AND organization_id = :oid"
            ),
            {"aid": alert_id, "oid": organization_id},
        )
        await session.commit()
        return result.rowcount > 0
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
