# =============================================================================
# AI Model Budgets & Guardrails v2 — budgets por modelo con throttling
# adaptativo, guardrails de salida (clasificadores configurables) y circuit
# breakers por modelo con auto-fallback.
# =============================================================================
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

GUARDRAIL_KINDS = ("toxicity", "pii", "banned_topics", "length_limit", "custom_pattern")
GUARDRAIL_ACTIONS = ("block", "mask", "warn")


# ---------------------------------------------------------------------------
# Guardrails de salida
# ---------------------------------------------------------------------------
async def list_guardrails(organization_id: UUID | None = None) -> dict:
    session = await get_async_session()
    try:
        params: dict = {}
        where = ""
        if organization_id:
            where = " WHERE organization_id = :oid"
            params["oid"] = organization_id
        rows = (
            await session.execute(
                text(
                    "SELECT id, organization_id, name, kind, config, action, enabled, "
                    "created_at FROM output_guardrails"
                    + where
                    + " ORDER BY created_at"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "guardrails": [
            {
                "id": str(r.id),
                "organization_id": str(r.organization_id),
                "name": r.name,
                "kind": r.kind,
                "config": r.config,
                "action": r.action,
                "enabled": bool(r.enabled),
            }
            for r in rows
        ]
    }


async def create_guardrail(
    organization_id: UUID,
    name: str,
    kind: str,
    config: dict,
    action: str = "mask",
) -> dict:
    if kind not in GUARDRAIL_KINDS:
        raise ValueError(f"kind must be one of {GUARDRAIL_KINDS}")
    if action not in GUARDRAIL_ACTIONS:
        raise ValueError(f"action must be one of {GUARDRAIL_ACTIONS}")
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO output_guardrails (id, organization_id, name, kind, "
                    "config, action) "
                    "VALUES (gen_random_uuid(), :oid, :name, :kind, :config, :action) "
                    "RETURNING id, name, kind, action"
                ),
                {
                    "oid": organization_id,
                    "name": name[:120],
                    "kind": kind,
                    "config": json.dumps(config or {}),
                    "action": action,
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {"id": str(row.id), "name": row.name, "kind": row.kind, "action": row.action}


async def delete_guardrail(guardrail_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text("DELETE FROM output_guardrails WHERE id = :gid"),
            {"gid": guardrail_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def toggle_guardrail(guardrail_id: UUID, enabled: bool) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text("UPDATE output_guardrails SET enabled = :e WHERE id = :gid"),
            {"e": enabled, "gid": guardrail_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


def _mask(text: str, matches: list[str]) -> str:
    masked = text
    for match in matches:
        masked = masked.replace(match, "[REDACTED]")
    return masked


async def _apply_one(guardrail: dict, answer: str) -> dict | None:
    """Devuelve violación o None. Nunca lanza."""
    kind = guardrail["kind"]
    config = guardrail["config"] or {}
    action = guardrail["action"]
    if kind == "length_limit":
        max_chars = int(config.get("max_chars", 2000))
        if len(answer) > max_chars:
            return {
                "kind": kind,
                "name": guardrail["name"],
                "action": action,
                "matched": f"len={len(answer)}>max={max_chars}",
            }
        return None
    if kind == "banned_topics":
        words = [str(w).lower() for w in config.get("words", []) if w]
        lowered = answer.lower()
        found = [w for w in words if w in lowered]
        return (
            {"kind": kind, "name": guardrail["name"], "action": action, "matched": found[:5]}
            if found
            else None
        )
    if kind == "custom_pattern":
        patterns = [str(p) for p in config.get("patterns", []) if p]
        found = []
        for pattern in patterns:
            try:
                if re.search(pattern, answer, re.IGNORECASE):
                    found.append(pattern)
            except re.error:
                continue
        return (
            {"kind": kind, "name": guardrail["name"], "action": action, "matched": found[:5]}
            if found
            else None
        )
    if kind == "toxicity":
        words = [str(w).lower() for w in config.get("words", []) if w]
        lowered = answer.lower()
        found = [w for w in words if w in lowered]
        return (
            {"kind": kind, "name": guardrail["name"], "action": action, "matched": found[:5]}
            if found
            else None
        )
    if kind == "pii":
        try:
            from src.platform.ai_governance.ai_governance import mask_pii

            masked, changed = mask_pii(answer)
            if changed:
                return {
                    "kind": kind,
                    "name": guardrail["name"],
                    "action": action,
                    "matched": ["pii"],
                    "masked_answer": masked,
                }
        except Exception as exc:  # noqa: BLE001
            logger.warning("PII guardrail failed", error=str(exc)[:150])
        return None
    return None


async def protect_answer(organization_id: UUID, answer: str) -> tuple[str, list[dict], bool]:
    """Aplica los guardrails habilitados de la org. Devuelve
    (answer_final, violations, blocked)."""
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, name, kind, config, action FROM output_guardrails "
                    "WHERE organization_id = :oid AND enabled ORDER BY created_at"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    guardrails = [
        {"name": r.name, "kind": r.kind, "config": r.config, "action": r.action}
        for r in rows
    ]
    violations: list[dict] = []
    blocked = False
    final = answer
    for guardrail in guardrails:
        try:
            violation = await _apply_one(guardrail, final)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Guardrail eval failed", error=str(exc)[:150])
            violation = None
        if violation is None:
            continue
        violations.append(violation)
        if violation.get("action") == "block":
            blocked = True
            final = ""
        elif violation.get("action") == "mask":
            if violation.get("masked_answer"):
                final = violation["masked_answer"]
            else:
                final = _mask(final, [str(m) for m in violation.get("matched", [])])
    return final, violations, blocked


# ---------------------------------------------------------------------------
# Budgets por modelo con throttling adaptativo
# ---------------------------------------------------------------------------
async def _model_cost_month(organization_id: UUID, model: str) -> float:
    session = await get_async_session()
    try:
        cost = (
            await session.execute(
                text(
                    "SELECT COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0.0) "
                    "FROM usage_events WHERE organization_id = :oid AND model = :model "
                    "AND created_at >= date_trunc('month', NOW())"
                ),
                {"oid": organization_id, "model": model},
            )
        ).scalar()
        return float(cost)
    finally:
        await session.close()


async def model_budget_status(organization_id: UUID, model: str) -> dict:
    session = await get_async_session()
    try:
        budget = (
            await session.execute(
                text(
                    "SELECT monthly_budget_cents FROM model_budgets "
                    "WHERE organization_id = :oid AND model = :model LIMIT 1"
                ),
                {"oid": organization_id, "model": model},
            )
        ).scalar()
    finally:
        await session.close()
    if budget is None:
        return {"model": model, "budget_cents": None, "allowed": True, "throttle_factor": 1.0, "usage_pct": 0.0}
    limit = float(budget) / 100
    used = await _model_cost_month(organization_id, model)
    usage_pct = used / limit * 100 if limit else 0.0
    if usage_pct >= 100:
        return {
            "model": model,
            "budget_cents": int(budget),
            "allowed": False,
            "throttle_factor": 0.0,
            "usage_pct": round(usage_pct, 1),
            "note": "budget agotado — bloqueado",
        }
    if usage_pct > 80:
        factor = round(max(0.2, 1 - (usage_pct - 80) / 20), 2)
        return {
            "model": model,
            "budget_cents": int(budget),
            "allowed": True,
            "throttle_factor": factor,
            "usage_pct": round(usage_pct, 1),
            "note": f"throttled ×{factor}",
        }
    return {
        "model": model,
        "budget_cents": int(budget),
        "allowed": True,
        "throttle_factor": 1.0,
        "usage_pct": round(usage_pct, 1),
    }


async def budgets_status(organization_id: UUID | None = None) -> dict:
    session = await get_async_session()
    try:
        params: dict = {}
        where = ""
        if organization_id:
            where = " WHERE organization_id = :oid"
            params["oid"] = organization_id
        rows = (
            await session.execute(
                text(
                    "SELECT DISTINCT ON (organization_id, model) organization_id, model, "
                    "monthly_budget_cents FROM model_budgets" + where + " "
                    "ORDER BY organization_id, model"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    statuses = []
    for row in rows:
        status = await model_budget_status(UUID(str(row.organization_id)), row.model)
        status["organization_id"] = str(row.organization_id)
        statuses.append(status)
    return {"budgets": statuses, "count": len(statuses)}


# ---------------------------------------------------------------------------
# Circuit breakers por modelo
# ---------------------------------------------------------------------------
async def check_circuit(model: str) -> dict:
    """closed | open (cooldown activo) | half_open (cooldown vencido)."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT state, failures, failure_threshold, window_seconds, "
                    "cooldown_seconds, last_failure_at, opened_at, opened_until "
                    "FROM model_circuit_breakers WHERE model_name = :model"
                ),
                {"model": model},
            )
        ).fetchone()
        if row is None:
            return {"model": model, "state": "closed", "failures": 0}
        state = row.state
        if state == "open" and row.opened_until and row.opened_until <= datetime.now(timezone.utc):
            state = "half_open"
    finally:
        await session.close()
    return {
        "model": model,
        "state": state,
        "failures": int(row.failures),
        "failure_threshold": int(row.failure_threshold),
        "opened_until": row.opened_until.isoformat() if row.opened_until else None,
    }


async def record_failure(model: str) -> dict:
    now = datetime.now(timezone.utc)
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, failures, failure_threshold, window_seconds, "
                    "cooldown_seconds, state, last_failure_at FROM model_circuit_breakers "
                    "WHERE model_name = :model"
                ),
                {"model": model},
            )
        ).fetchone()
        if row is None:
            await session.execute(
                text(
                    "INSERT INTO model_circuit_breakers (id, model_name, failures, "
                    "last_failure_at) VALUES (gen_random_uuid(), :model, 1, :now)"
                ),
                {"model": model, "now": now},
            )
            await session.commit()
            return {"model": model, "state": "closed", "failures": 1}
        failures = int(row.failures) + 1
        window_ok = (
            row.last_failure_at is None
            or (now - row.last_failure_at).total_seconds() <= int(row.window_seconds)
        )
        if not window_ok:
            failures = 1
        state = row.state
        if (
            failures >= int(row.failure_threshold)
            and state != "open"
        ):
            state = "open"
            await session.execute(
                text(
                    "UPDATE model_circuit_breakers SET failures = :f, state = 'open', "
                    "opened_at = :now, opened_until = :until, last_failure_at = :now "
                    "WHERE model_name = :model"
                ),
                {
                    "f": failures,
                    "now": now,
                    "until": now + timedelta(seconds=int(row.cooldown_seconds)),
                    "model": model,
                },
            )
        else:
            await session.execute(
                text(
                    "UPDATE model_circuit_breakers SET failures = :f, last_failure_at = :now "
                    "WHERE model_name = :model"
                ),
                {"f": failures, "now": now, "model": model},
            )
        await session.commit()
    finally:
        await session.close()
    return {"model": model, "state": state, "failures": failures}


async def record_success(model: str) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE model_circuit_breakers SET failures = 0, "
                "state = CASE WHEN state = 'open' THEN 'half_open' ELSE state END "
                "WHERE model_name = :model"
            ),
            {"model": model},
        )
        await session.commit()
    finally:
        await session.close()


async def reset_circuit(model: str) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "UPDATE model_circuit_breakers SET failures = 0, state = 'closed', "
                "opened_at = NULL, opened_until = NULL, last_failure_at = NULL "
                "WHERE model_name = :model"
            ),
            {"model": model},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def circuits_list() -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT model_name, state, failures, failure_threshold, "
                    "window_seconds, cooldown_seconds, opened_at, opened_until "
                    "FROM model_circuit_breakers ORDER BY model_name"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "circuits": [
            {
                "model": r.model_name,
                "state": r.state,
                "failures": int(r.failures),
                "failure_threshold": int(r.failure_threshold),
                "window_seconds": int(r.window_seconds),
                "cooldown_seconds": int(r.cooldown_seconds),
                "opened_at": r.opened_at.isoformat() if r.opened_at else None,
                "opened_until": r.opened_until.isoformat() if r.opened_until else None,
            }
            for r in rows
        ]
    }


# ---------------------------------------------------------------------------
# Dashboard de salud por modelo
# ---------------------------------------------------------------------------
async def model_health_dashboard(hours: int = 24) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT model, "
                    "COUNT(*) AS requests, "
                    "SUM(total_tokens) AS tokens, "
                    "SUM(cost) AS cost, "
                    "COUNT(*) FILTER (WHERE status <> 'completed') AS errors, "
                    "AVG(latency_ms) AS avg_latency_ms, "
                    "PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95 "
                    "FROM inference_logs WHERE created_at >= :since "
                    "GROUP BY model ORDER BY requests DESC"
                ),
                {"since": since},
            )
        ).fetchall()
    finally:
        await session.close()
    models = [
        {
            "model": r.model,
            "requests": int(r.requests),
            "tokens": int(r.tokens),
            "cost": round(float(r.cost), 4),
            "errors": int(r.errors),
            "error_rate": round(int(r.errors) / int(r.requests), 4) if int(r.requests) else 0.0,
            "avg_latency_ms": round(float(r.avg_latency_ms), 1),
            "p95_latency_ms": round(float(r.p95), 1),
        }
        for r in rows
    ]
    circuits = {c["model"]: c["state"] for c in (await circuits_list())["circuits"]}
    for item in models:
        item["circuit_state"] = circuits.get(item["model"], "closed")
    return {"window_hours": hours, "models": models, "count": len(models)}
