# =============================================================================
# AI Risk & Compliance Center v2 — registro de riesgos con scoring
# automático, mitigaciones, heatmap y postura de cumplimiento.
# =============================================================================
from __future__ import annotations

import json
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

RISK_TYPES = ("bias", "hallucination", "pii_leak", "security", "safety")
SEVERITY_OF = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _severity_for(score: float) -> str:
    if score >= 75:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


async def _upsert_risk(
    organization_id: UUID,
    risk_type: str,
    likelihood: float,
    impact: float,
    evidence: dict,
    agent_id: UUID | None = None,
) -> dict:
    """Crea un riesgo automático (no duplica un riesgo abierto del mismo tipo)."""
    score = round(min(max(likelihood * impact / 100, 0), 100), 1)
    severity = _severity_for(score)
    session = await get_async_session()
    try:
        existing = (
            await session.execute(
                text(
                    "SELECT id FROM ai_risks WHERE organization_id = :oid "
                    "AND risk_type = :rtype AND status = 'open'"
                ),
                {"oid": organization_id, "rtype": risk_type},
            )
        ).fetchone()
        if existing is not None:
            await session.commit()
            return {"status": "existing_open"}
        row = (
            await session.execute(
                text(
                    "INSERT INTO ai_risks (id, organization_id, agent_id, risk_type, "
                    "severity, likelihood, impact, score, status, source, evidence) "
                    "VALUES (gen_random_uuid(), :oid, :aid, :rtype, :sev, :like, :impact, "
                    ":score, 'open', 'auto', CAST(:ev AS jsonb)) "
                    "RETURNING id, severity, score"
                ),
                {
                    "oid": organization_id,
                    "aid": agent_id,
                    "rtype": risk_type,
                    "sev": severity,
                    "like": likelihood,
                    "impact": impact,
                    "score": score,
                    "ev": json.dumps(evidence),
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    if row is None:
        return {"status": "existing_open"}
    return {"risk_id": str(row.id), "severity": row.severity, "score": float(row.score)}


async def assess_organization_risks(organization_id: UUID) -> dict:
    """Scoring automático desde evals, moderación, incidentes y API logs."""
    session = await get_async_session()
    try:
        eval_stats = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS runs, "
                    "COALESCE(AVG(hallucination_rate), 0) AS halluc, "
                    "COALESCE(AVG(score_overall), 0) AS score "
                    "FROM eval_v2_runs WHERE organization_id = :oid "
                    "AND status = 'completed' AND completed_at >= NOW() - interval '7 days'"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
        pii_incidents = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM safety_incidents WHERE organization_id = :oid "
                    "AND created_at >= NOW() - interval '7 days' AND action = 'block'"
                ),
                {"oid": organization_id},
            )
        ).scalar()
        blocked_msgs = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM safety_incidents WHERE organization_id = :oid "
                    "AND created_at >= NOW() - interval '7 days'"
                ),
                {"oid": organization_id},
            )
        ).scalar()
        api_errors = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM api_logs WHERE organization_id = :oid "
                    "AND created_at >= NOW() - interval '7 days' AND status >= 400"
                ),
                {"oid": organization_id},
            )
        ).scalar()
        api_total = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM api_logs WHERE organization_id = :oid "
                    "AND created_at >= NOW() - interval '7 days'"
                ),
                {"oid": organization_id},
            )
        ).scalar()
        feedback_down = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM feedback WHERE organization_id = :oid "
                    "AND rating = 'down' AND created_at >= NOW() - interval '7 days'"
                ),
                {"oid": organization_id},
            )
        ).scalar()
        feedback_total = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM feedback WHERE organization_id = :oid "
                    "AND created_at >= NOW() - interval '7 days'"
                ),
                {"oid": organization_id},
            )
        ).scalar()
    finally:
        await session.close()

    runs = int(eval_stats.runs or 0)
    halluc = float(eval_stats.halluc or 0)
    eval_score = float(eval_stats.score or 0)
    assessments: list[dict] = []

    async def _assess(risk_type: str, likelihood: float, impact: float, evidence: dict) -> dict:
        if likelihood <= 0:
            return {"risk_type": risk_type, "created": False}
        result = await _upsert_risk(organization_id, risk_type, likelihood, impact, evidence)
        created = result.get("status") != "existing_open"
        return {"risk_type": risk_type, "created": created, **result}

    # Alucinación: tasa media de alucinación en evals (0-1) x impacto.
    if runs:
        assessments.append(
            await _assess("hallucination", min(halluc * 100, 100), 90 if halluc > 0.3 else 50, {
                "runs_7d": runs, "avg_hallucination_rate": round(halluc, 3), "avg_score": round(eval_score, 1)
            })
        )
    # PII: incidentes bloqueados por moderación (PII suele ser block).
    if int(pii_incidents or 0):
        likelihood = min(int(pii_incidents) * 20, 100)
        assessments.append(
            await _assess("pii_leak", likelihood, 95, {"blocked_incidents_7d": int(pii_incidents)})
        )
    # Seguridad: errores API + ratio.
    if int(api_total or 0):
        error_rate = int(api_errors or 0) / int(api_total)
        if error_rate > 0.05:
            assessments.append(
                await _assess("security", min(error_rate * 100, 100), 85, {
                    "api_errors_7d": int(api_errors), "api_total_7d": int(api_total),
                    "error_rate": round(error_rate, 3)
                })
            )
    # Seguridad/safety: mensajes bloqueados por moderación.
    if int(blocked_msgs or 0) and int(api_total or 0) > 0:
        block_rate = min(int(blocked_msgs) / int(api_total) * 100, 100)
        if block_rate > 2:
            assessments.append(
                await _assess("safety", block_rate, 80, {"blocked_messages_7d": int(blocked_msgs)})
            )
    # Sesgo: feedback negativo alto.
    if int(feedback_total or 0) >= 5:
        down_rate = int(feedback_down or 0) / int(feedback_total) * 100
        if down_rate > 30:
            assessments.append(
                await _assess("bias", min(down_rate, 100), 70, {
                    "down_7d": int(feedback_down), "total_7d": int(feedback_total),
                    "down_rate": round(down_rate, 1)
                })
            )
    return {"assessed": True, "assessments": assessments}


async def risk_register(organization_id: UUID, status: str = "open") -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT r.id, r.agent_id, r.risk_type, r.severity, r.likelihood, "
                    "r.impact, r.score, r.status, r.source, r.evidence, r.created_at, "
                    "r.mitigated_at, a.name AS agent_name, "
                    "(SELECT COUNT(*) FROM risk_mitigations m WHERE m.risk_id = r.id) AS mitigations "
                    "FROM ai_risks r LEFT JOIN agents a ON a.id = r.agent_id "
                    "WHERE r.organization_id = :oid AND r.status = :status "
                    "ORDER BY r.score DESC"
                ),
                {"oid": organization_id, "status": status},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "risks": [
            {
                "id": str(r.id),
                "agent_id": str(r.agent_id) if r.agent_id else None,
                "agent_name": r.agent_name,
                "risk_type": r.risk_type,
                "severity": r.severity,
                "likelihood": float(r.likelihood),
                "impact": float(r.impact),
                "score": float(r.score),
                "status": r.status,
                "source": r.source,
                "evidence": r.evidence,
                "mitigations": int(r.mitigations),
                "created_at": r.created_at.isoformat(),
                "mitigated_at": r.mitigated_at.isoformat() if r.mitigated_at else None,
            }
            for r in rows
        ]
    }


async def add_manual_risk(
    organization_id: UUID,
    risk_type: str,
    severity: str,
    notes: str | None = None,
    agent_id: UUID | None = None,
    created_by: UUID | None = None,
) -> dict:
    if risk_type not in RISK_TYPES:
        raise ValueError(f"risk_type debe ser uno de {RISK_TYPES}")
    if severity not in SEVERITY_OF:
        raise ValueError("severity debe ser low|medium|high|critical")
    severity_mult = {"low": 0.2, "medium": 0.5, "high": 0.8, "critical": 1.0}
    likelihood = severity_mult[severity] * 100
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO ai_risks (id, organization_id, agent_id, risk_type, "
                    "severity, likelihood, impact, score, status, source, evidence) "
                    "VALUES (gen_random_uuid(), :oid, :aid, :rtype, :sev, :like, :impact, "
                    ":score, 'open', 'manual', CAST(:ev AS jsonb)) RETURNING id"
                ),
                {
                    "oid": organization_id,
                    "aid": agent_id,
                    "rtype": risk_type,
                    "sev": severity,
                    "like": likelihood,
                    "impact": 1.0,
                    "score": likelihood,
                    "ev": json.dumps({"notes": notes or ""}),
                },
            )
        ).scalar()
        await session.commit()
    finally:
        await session.close()
    return {"risk_id": str(row), "source": "manual", "status": "open"}


async def _risk_row(organization_id: UUID, risk_id: UUID) -> tuple | None:
    session = await get_async_session()
    try:
        return (
            await session.execute(
                text(
                    "SELECT id, agent_id FROM ai_risks "
                    "WHERE id = :rid AND organization_id = :oid"
                ),
                {"rid": risk_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()


async def mitigate_risk(
    organization_id: UUID,
    risk_id: UUID,
    description: str,
    performed_by: UUID | None = None,
) -> dict | None:
    row = await _risk_row(organization_id, risk_id)
    if row is None:
        return None
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO risk_mitigations (id, risk_id, action_type, description, performed_by) "
                "VALUES (gen_random_uuid(), :rid, 'mitigation', :desc, :by)"
            ),
            {"rid": risk_id, "desc": description[:500], "by": performed_by},
        )
        await session.execute(
            text(
                "UPDATE ai_risks SET status = 'mitigated', mitigated_at = NOW(), "
                "updated_at = NOW() WHERE id = :rid"
            ),
            {"rid": risk_id},
        )
        await session.commit()
    finally:
        await session.close()
    return {"risk_id": str(risk_id), "status": "mitigated"}


async def accept_risk(organization_id: UUID, risk_id: UUID, reason: str | None = None) -> dict | None:
    row = await _risk_row(organization_id, risk_id)
    if row is None:
        return None
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO risk_mitigations (id, risk_id, action_type, description) "
                "VALUES (gen_random_uuid(), :rid, 'accepted', :desc)"
            ),
            {"rid": risk_id, "desc": reason or "Riesgo aceptado"},
        )
        await session.execute(
            text(
                "UPDATE ai_risks SET status = 'accepted', updated_at = NOW() WHERE id = :rid"
            ),
            {"rid": risk_id},
        )
        await session.commit()
    finally:
        await session.close()
    return {"risk_id": str(risk_id), "status": "accepted"}


async def risk_heatmap(organization_id: UUID) -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT a.name AS agent_name, a.id AS agent_id, "
                    "r.risk_type, r.severity, MAX(r.score) AS score, r.status "
                    "FROM ai_risks r LEFT JOIN agents a ON a.id = r.agent_id "
                    "WHERE r.organization_id = :oid AND r.status = 'open' "
                    "GROUP BY a.id, a.name, r.risk_type, r.severity, r.status "
                    "ORDER BY score DESC"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    agents: dict[str, dict] = {}
    for r in rows:
        key = str(r.agent_id) if r.agent_id else "general"
        entry = agents.setdefault(key, {"agent_id": key, "agent_name": r.agent_name or "General", "risks": {}})
        entry["risks"][r.risk_type] = {
            "severity": r.severity,
            "score": round(float(r.score), 1),
        }
    return {"heatmap": list(agents.values())}


async def mitigations_list(organization_id: UUID, limit: int = 50) -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT m.id, m.risk_id, m.action_type, m.description, m.performed_by, "
                    "m.created_at, r.risk_type, r.severity, r.status AS risk_status "
                    "FROM risk_mitigations m JOIN ai_risks r ON r.id = m.risk_id "
                    "WHERE r.organization_id = :oid "
                    "ORDER BY m.created_at DESC LIMIT :lim"
                ),
                {"oid": organization_id, "lim": min(int(limit), 100)},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "mitigations": [
            {
                "id": str(m.id),
                "risk_id": str(m.risk_id),
                "action_type": m.action_type,
                "description": m.description,
                "created_at": m.created_at.isoformat(),
                "risk_type": m.risk_type,
                "severity": m.severity,
                "risk_status": m.risk_status,
            }
            for m in rows
        ]
    }


# ---------------------------------------------------------------------------
# Postura de cumplimiento
# ---------------------------------------------------------------------------
async def compliance_posture(organization_id: UUID, framework: str = "eu_ai_act") -> dict:
    """Score 0-100: % de controles del framework en estado 'implemented'."""
    session = await get_async_session()
    try:
        controls = (
            await session.execute(
                text(
                    "SELECT c.control_id, c.title, c.risk_type, "
                    "COALESCE(cs.status, 'na') AS status "
                    "FROM compliance_controls c "
                    "LEFT JOIN compliance_status cs ON cs.control_id = c.control_id "
                    "AND cs.organization_id = :oid "
                    "WHERE c.framework = :fw"
                ),
                {"oid": organization_id, "fw": framework},
            )
        ).fetchall()
    finally:
        await session.close()
    total = len(controls)
    implemented = [c for c in controls if c.status == "pass"]
    in_review = [c for c in controls if c.status == "review"]
    score = round(len(implemented) / total * 100, 1) if total else 0.0
    by_risk: dict[str, dict] = {}
    for c in controls:
        group = by_risk.setdefault(c.risk_type or "general", {"total": 0, "implemented": 0})
        group["total"] += 1
        if c.status == "pass":
            group["implemented"] += 1
    today = date.today()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO compliance_posture_snapshots (id, organization_id, date, framework, score) "
                "VALUES (gen_random_uuid(), :oid, :day, :fw, :score) "
                "ON CONFLICT (organization_id, date, framework) DO UPDATE SET score = :score"
            ),
            {"oid": organization_id, "day": today, "fw": framework, "score": score},
        )
        await session.commit()
    finally:
        await session.close()
    return {
        "framework": framework,
        "total_controls": total,
        "implemented": len(implemented),
        "in_review": len(in_review),
        "not_implemented": total - len(implemented) - len(in_review),
        "score": score,
        "by_risk_type": {
            k: {"total": v["total"], "implemented": v["implemented"],
                "pct": round(v["implemented"] / v["total"] * 100, 1)}
            for k, v in by_risk.items()
        },
        "controls": [
            {
                "control_id": c.control_id,
                "title": c.title,
                "risk_type": c.risk_type,
                "status": c.status,
            }
            for c in controls
        ],
    }


async def posture_trend(organization_id: UUID, framework: str = "eu_ai_act", days: int = 30) -> dict:
    since = date.today() - timedelta(days=days)
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT date, score FROM compliance_posture_snapshots "
                    "WHERE organization_id = :oid AND framework = :fw AND date >= :since "
                    "ORDER BY date"
                ),
                {"oid": organization_id, "fw": framework, "since": since},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "framework": framework,
        "trend": [{"date": r.date.isoformat(), "score": float(r.score)} for r in rows],
    }


# ---------------------------------------------------------------------------
# Dashboard platform
# ---------------------------------------------------------------------------
async def risk_compliance_dashboard() -> dict:
    session = await get_async_session()
    try:
        by_type = (
            await session.execute(
                text(
                    "SELECT risk_type, COUNT(*) AS open_count, "
                    "COALESCE(AVG(score), 0) AS avg_score "
                    "FROM ai_risks WHERE status = 'open' "
                    "GROUP BY risk_type ORDER BY open_count DESC"
                )
            )
        ).fetchall()
        by_severity = (
            await session.execute(
                text(
                    "SELECT severity, COUNT(*) AS n FROM ai_risks "
                    "WHERE status = 'open' GROUP BY severity ORDER BY n DESC"
                )
            )
        ).fetchall()
        posture_avg = (
            await session.execute(
                text(
                    "SELECT framework, AVG(score) AS avg_score, COUNT(DISTINCT organization_id) AS orgs "
                    "FROM compliance_posture_snapshots "
                    "WHERE date = CURRENT_DATE GROUP BY framework"
                )
            )
        ).fetchall()
        mitigated_7d = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM ai_risks WHERE status = 'mitigated' "
                    "AND mitigated_at >= NOW() - interval '7 days'"
                )
            )
        ).scalar()
        top_orgs = (
            await session.execute(
                text(
                    "SELECT o.name AS org_name, COUNT(r.id) AS open_risks, "
                    "COALESCE(SUM(r.score), 0) AS total_score "
                    "FROM ai_risks r JOIN organizations o ON o.id = r.organization_id "
                    "WHERE r.status = 'open' "
                    "GROUP BY o.id ORDER BY total_score DESC LIMIT 10"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "open_risks": sum(int(r.open_count) for r in by_type),
        "mitigated_7d": int(mitigated_7d or 0),
        "by_risk_type": [
            {"risk_type": r.risk_type, "count": int(r.open_count), "avg_score": round(float(r.avg_score or 0), 1)}
            for r in by_type
        ],
        "by_severity": [{"severity": r.severity, "count": int(r.n)} for r in by_severity],
        "posture_by_framework": [
            {"framework": r.framework, "avg_score": round(float(r.avg_score or 0), 1), "organizations": int(r.orgs)}
            for r in posture_avg
        ],
        "top_organizations": [
            {"org": r.org_name, "open_risks": int(r.open_risks), "total_score": round(float(r.total_score or 0), 1)}
            for r in top_orgs
        ],
    }
