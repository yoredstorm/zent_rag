# =============================================================================
# AI Governance Board & Audit Trail v2 — políticas, decisiones con firmas,
# auditoría encadenada con hash y reporte ejecutivo por pilares.
# =============================================================================
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

DECISION_TYPES = ("deploy_approval", "incident_review", "policy_change", "model_change")
CERTIFICATIONS = ("AI Ethics", "Prompt Safety", "Data Privacy", "Governance")


def _chain_hash(prev_hash: str, payload: str) -> str:
    return hashlib.sha256(f"{prev_hash}|{payload}".encode()).hexdigest()


async def _append_audit(
    organization_id: UUID,
    actor_id: UUID | None,
    actor_name: str,
    action: str,
    entity_type: str,
    entity_id: UUID | None,
    detail: str,
) -> str:
    """Registra una acción en la cadena de auditoría (hash encadenado por org)."""
    session = await get_async_session()
    try:
        last = (
            await session.execute(
                text(
                    "SELECT hash FROM governance_audit_log "
                    "WHERE organization_id = :oid ORDER BY created_at DESC, id DESC LIMIT 1"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
        prev_hash = last.hash if last else ""
        stamp = datetime.now(timezone.utc)
        payload = (
            f"{actor_id or 'system'}|{actor_name}|{action}|{entity_type}|"
            f"{entity_id or ''}|{detail}|{stamp.isoformat()}"
        )
        chain_hash = _chain_hash(prev_hash, payload)
        await session.execute(
            text(
                "INSERT INTO governance_audit_log (id, organization_id, actor_id, actor_name, "
                "action, entity_type, entity_id, detail, prev_hash, hash, created_at) "
                "VALUES (gen_random_uuid(), :oid, :actor, :name, :action, :etype, :eid, "
                ":detail, :prev, :hash, :stamp)"
            ),
            {
                "oid": organization_id,
                "actor": actor_id,
                "name": actor_name[:150],
                "action": action[:40],
                "etype": entity_type[:40],
                "eid": entity_id,
                "detail": detail,
                "prev": prev_hash,
                "hash": chain_hash,
                "stamp": stamp,
            },
        )
        await session.commit()
        return chain_hash
    finally:
        await session.close()


async def _user_name(user_id: UUID | None) -> str:
    if user_id is None:
        return "system"
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT email FROM users WHERE id = :uid"),
                {"uid": user_id},
            )
        ).fetchone()
    finally:
        await session.close()
    return (row.email or "system") if row else "system"


# ---------------------------------------------------------------------------
# Políticas
# ---------------------------------------------------------------------------
POLICY_SEEDS = [
    (
        "acceptable_use",
        "Uso Aceptable de IA",
        "Los agentes deben usarse solo para fines autorizados y respetar las políticas "
        "de privacidad. Está prohibido el uso para discriminar, acosar o engañar.",
    ),
    (
        "deployment",
        "Aprobación de Despliegues",
        "Todo despliegue en producción requiere una decisión de aprobación con al "
        "menos 2 aprobadores de la junta de gobierno.",
    ),
    (
        "incident_response",
        "Respuesta a Incidentes",
        "Los incidentes de seguridad deben revisarse por la junta en un plazo máximo "
        "de 7 días y documentar la mitigación.",
    ),
    (
        "data_handling",
        "Manejo de Datos",
        "Los datos personales deben anonimizarse en los conjuntos de entrenamiento "
        "y evaluaciones.",
    ),
]


async def _seed_policies(organization_id: UUID) -> None:
    session = await get_async_session()
    try:
        count = (
            await session.execute(
                text("SELECT COUNT(*) FROM governance_policies WHERE organization_id = :oid"),
                {"oid": organization_id},
            )
        ).scalar()
        if int(count) > 0:
            await session.commit()
            return
        for ptype, name, content in POLICY_SEEDS:
            await session.execute(
                text(
                    "INSERT INTO governance_policies (id, organization_id, policy_type, "
                    "name, content, version, status) "
                    "VALUES (gen_random_uuid(), :oid, :ptype, :name, :content, 1, 'active')"
                ),
                {"oid": organization_id, "ptype": ptype, "name": name, "content": content},
            )
        await session.commit()
    finally:
        await session.close()


async def list_policies(organization_id: UUID) -> dict:
    await _seed_policies(organization_id)
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, policy_type, name, content, version, status, created_at, "
                    "updated_at FROM governance_policies "
                    "WHERE organization_id = :oid ORDER BY policy_type"
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
                "policy_type": r.policy_type,
                "name": r.name,
                "content": r.content,
                "version": int(r.version),
                "status": r.status,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ]
    }


async def revise_policy(
    organization_id: UUID,
    policy_id: UUID,
    content: str,
    created_by: UUID | None = None,
) -> dict | None:
    """Nueva versión de la política + decisión de cambio pendiente."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, name, version FROM governance_policies "
                    "WHERE id = :pid AND organization_id = :oid"
                ),
                {"pid": policy_id, "oid": organization_id},
            )
        ).fetchone()
        if row is None:
            await session.commit()
            return None
        new_version = int(row.version) + 1
        await session.execute(
            text(
                "UPDATE governance_policies SET content = :content, version = :version, "
                "status = 'active', updated_at = NOW() WHERE id = :pid"
            ),
            {"content": content, "version": new_version, "pid": policy_id},
        )
        await session.execute(
            text(
                "INSERT INTO governance_decisions (id, organization_id, decision_type, "
                "target_id, title, rationale, status) "
                "VALUES (gen_random_uuid(), :oid, 'policy_change', :pid, :title, "
                ":rationale, 'pending')"
            ),
            {
                "oid": organization_id,
                "pid": policy_id,
                "title": f"Revisión v{new_version} de {row.name}",
                "rationale": "Cambio de contenido aprobado por la junta",
            },
        )
        await session.commit()
    finally:
        await session.close()
    actor = await _user_name(created_by)
    await _append_audit(organization_id, created_by, actor, "policy.revised",
                        "governance_policy", policy_id, f"v{new_version}")
    return {"policy_id": str(policy_id), "version": new_version}


# ---------------------------------------------------------------------------
# Decisiones
# ---------------------------------------------------------------------------
async def create_decision(
    organization_id: UUID,
    decision_type: str,
    title: str,
    rationale: str | None = None,
    target_id: UUID | None = None,
    created_by: UUID | None = None,
) -> dict:
    if decision_type not in DECISION_TYPES:
        raise ValueError(f"decision_type debe ser uno de {DECISION_TYPES}")
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO governance_decisions (id, organization_id, decision_type, "
                    "target_id, title, rationale) "
                    "VALUES (gen_random_uuid(), :oid, :dtype, :tid, :title, :rationale) "
                    "RETURNING id"
                ),
                {
                    "oid": organization_id,
                    "dtype": decision_type,
                    "tid": target_id,
                    "title": title[:200],
                    "rationale": rationale,
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    actor = await _user_name(created_by)
    await _append_audit(organization_id, created_by, actor, "decision.created",
                        "governance_decision", row.id, title)
    return {"decision_id": str(row.id), "status": "pending"}


async def decide(
    organization_id: UUID,
    decision_id: UUID,
    approve: bool,
    decided_by: UUID | None = None,
) -> dict | None:
    """Firma un aprobador; al alcanzar el mínimo requerido la decisión se cierra."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, title, status, approvers, required_approvals "
                    "FROM governance_decisions WHERE id = :did AND organization_id = :oid"
                ),
                {"did": decision_id, "oid": organization_id},
            )
        ).fetchone()
        if row is None:
            await session.commit()
            return None
        if row.status != "pending":
            return {"decision_id": str(decision_id), "status": row.status, "final": True}
        approvers = list(row.approvers or [])
        actor = await _user_name(decided_by)
        approvers.append({
            "user_id": str(decided_by) if decided_by else "system",
            "name": actor,
            "approved": approve,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "signature": hashlib.sha256(
                f"{decision_id}|{actor}|{approve}|{datetime.now(timezone.utc).isoformat()}".encode()
            ).hexdigest()[:32],
        })
        if approve and len(approvers) >= int(row.required_approvals):
            final_status = "approved"
        elif not approve:
            final_status = "rejected"
        else:
            final_status = "pending"
        decided_at = datetime.now(timezone.utc) if final_status != "pending" else None
        await session.execute(
            text(
                "UPDATE governance_decisions SET approvers = CAST(:approvers AS jsonb), "
                "status = :status, decided_by = :by, decided_at = :decided_at WHERE id = :did"
            ),
            {
                "approvers": json.dumps(approvers),
                "status": final_status,
                "by": decided_by,
                "decided_at": decided_at,
                "did": decision_id,
            },
        )
        await session.commit()
    finally:
        await session.close()
    await _append_audit(
        organization_id, decided_by, actor,
        "approved" if approve else "rejected",
        "governance_decision", decision_id,
        f"{row.title} (signature {approvers[-1]['signature'][:8]})",
    )
    return {"decision_id": str(decision_id), "status": final_status, "approvals": len(approvers)}


async def list_decisions(organization_id: UUID, status: str | None = None) -> dict:
    session = await get_async_session()
    try:
        params: dict = {"oid": organization_id}
        where = ""
        if status:
            where = " AND status = :status"
            params["status"] = status
        rows = (
            await session.execute(
                text(
                    "SELECT id, decision_type, target_id, title, rationale, status, "
                    "approvers, required_approvals, decided_by, decided_at, created_at "
                    "FROM governance_decisions WHERE organization_id = :oid" + where + " "
                    "ORDER BY created_at DESC LIMIT 100"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "decisions": [
            {
                "id": str(r.id),
                "decision_type": r.decision_type,
                "target_id": str(r.target_id) if r.target_id else None,
                "title": r.title,
                "rationale": r.rationale,
                "status": r.status,
                "approvers": r.approvers,
                "required_approvals": int(r.required_approvals),
                "decided_by": str(r.decided_by) if r.decided_by else None,
                "decided_at": r.decided_at.isoformat() if r.decided_at else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


# ---------------------------------------------------------------------------
# Auditoría
# ---------------------------------------------------------------------------
async def audit_trail(organization_id: UUID, limit: int = 100) -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, actor_id, actor_name, action, entity_type, entity_id, "
                    "detail, prev_hash, hash, created_at FROM governance_audit_log "
                    "WHERE organization_id = :oid "
                    "ORDER BY created_at DESC LIMIT :lim"
                ),
                {"oid": organization_id, "lim": min(int(limit), 200)},
            )
        ).fetchall()
    finally:
        await session.close()
    entries = [
        {
            "id": str(r.id),
            "actor_name": r.actor_name,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": str(r.entity_id) if r.entity_id else None,
            "detail": r.detail,
            "prev_hash": r.prev_hash,
            "hash": r.hash,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
    return {"entries": entries, "count": len(entries)}


async def verify_audit(organization_id: UUID) -> dict:
    """Reconstruye la cadena y detecta cualquier modificación."""
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, actor_id, actor_name, action, entity_type, entity_id, "
                    "detail, prev_hash, hash, created_at FROM governance_audit_log "
                    "WHERE organization_id = :oid ORDER BY created_at ASC, id ASC"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    prev = ""
    tampered: list[str] = []
    verified = 0
    for r in rows:
        payload = (
            f"{r.actor_id or 'system'}|{r.actor_name}|{r.action}|{r.entity_type}|"
            f"{r.entity_id or ''}|{r.detail}|{r.created_at.isoformat()}"
        )
        expected = _chain_hash(r.prev_hash, payload)
        if r.prev_hash != prev or expected != r.hash:
            tampered.append(str(r.id))
        else:
            verified += 1
        prev = r.hash
    return {
        "verified": verified,
        "tampered": tampered,
        "intact": not tampered,
        "chain_length": len(rows),
    }


# ---------------------------------------------------------------------------
# Certificaciones
# ---------------------------------------------------------------------------
async def add_certification(
    organization_id: UUID,
    member_name: str,
    certification: str,
    expires_in_days: int = 365,
) -> dict:
    if certification not in CERTIFICATIONS:
        raise ValueError(f"certification debe ser uno de {CERTIFICATIONS}")
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO team_certifications (id, organization_id, member_name, "
                    "certification, expires_at) "
                    "VALUES (gen_random_uuid(), :oid, :name, :cert, "
                    "CURRENT_DATE + make_interval(days => :days)) RETURNING id"
                ),
                {
                    "oid": organization_id,
                    "name": member_name[:150],
                    "cert": certification,
                    "days": max(1, min(int(expires_in_days), 3650)),
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    await _append_audit(organization_id, None, "system", "certification.issued",
                        "team_certification", row.id, f"{member_name}: {certification}")
    return {"certification_id": str(row.id)}


async def list_certifications(organization_id: UUID, status: str = "valid") -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, member_name, certification, issued_at, expires_at, status "
                    "FROM team_certifications WHERE organization_id = :oid AND status = :status "
                    "ORDER BY expires_at"
                ),
                {"oid": organization_id, "status": status},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "certifications": [
            {
                "id": str(r.id),
                "member_name": r.member_name,
                "certification": r.certification,
                "issued_at": r.issued_at.isoformat(),
                "expires_at": r.expires_at.isoformat(),
                "status": r.status,
            }
            for r in rows
        ]
    }


# ---------------------------------------------------------------------------
# Reporte ejecutivo por pilares
# ---------------------------------------------------------------------------
async def executive_report(organization_id: UUID) -> dict:
    await _seed_policies(organization_id)
    session = await get_async_session()
    try:
        policies = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS total, "
                    "COUNT(*) FILTER (WHERE status = 'active') AS active, "
                    "COALESCE(MAX(version), 1) AS max_version "
                    "FROM governance_policies WHERE organization_id = :oid"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
        approved_decisions = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM governance_decisions "
                    "WHERE organization_id = :oid AND status = 'approved'"
                ),
                {"oid": organization_id},
            )
        ).scalar()
        docs_conf = (
            await session.execute(
                text(
                    "SELECT COALESCE(AVG(confidence_score), 0) FROM documents "
                    "WHERE organization_id = :oid"
                ),
                {"oid": organization_id},
            )
        ).scalar()
        open_gaps = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM knowledge_gaps "
                    "WHERE organization_id = :oid AND status = 'open'"
                ),
                {"oid": organization_id},
            )
        ).scalar()
        eval_score = (
            await session.execute(
                text(
                    "SELECT COALESCE(AVG(score_overall), 0) FROM eval_v2_runs "
                    "WHERE organization_id = :oid AND status = 'completed' "
                    "AND completed_at >= NOW() - interval '30 days'"
                ),
                {"oid": organization_id},
            )
        ).scalar()
        mitigated = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM ai_risks WHERE organization_id = :oid "
                    "AND status IN ('mitigated', 'accepted')"
                ),
                {"oid": organization_id},
            )
        ).scalar()
        total_risks = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM ai_risks WHERE organization_id = :oid"
                ),
                {"oid": organization_id},
            )
        ).scalar()
        healthy_deps = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM deployments WHERE organization_id = :oid "
                    "AND status = 'healthy'"
                ),
                {"oid": organization_id},
            )
        ).scalar()
        total_deps = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM deployments WHERE organization_id = :oid "
                    "AND status <> 'failed'"
                ),
                {"oid": organization_id},
            )
        ).scalar()
        threat = (
            await session.execute(
                text(
                    "SELECT COALESCE(AVG(threat_score), 0) FROM security_posture_snapshots "
                    "WHERE organization_id = :oid AND date >= CURRENT_DATE - 7"
                ),
                {"oid": organization_id},
            )
        ).scalar()
    finally:
        await session.close()

    gov = round(min(float(policies.active or 0) / max(int(policies.total or 0), 1) * 100, 100), 1)
    data = round(min(float(docs_conf or 0) * 0.7 + max(100 - int(open_gaps or 0) * 20, 0) * 0.3, 100), 1)
    model = round(min(float(eval_score or 0) * 0.5 + (
        int(mitigated or 0) / max(int(total_risks or 0), 1) * 100
    ) * 0.5, 100), 1)
    ops = round(min((
        int(healthy_deps or 0) / max(int(total_deps or 0), 1) * 100
    ) * 0.6 + max(100 - float(threat or 0), 0) * 0.4, 100), 1)
    total = round((gov + data + model + ops) / 4, 1)
    return {
        "pillars": {
            "governance": {
                "score": gov,
                "detail": (
                    f"{int(policies.active or 0)}/{int(policies.total or 0)} políticas activas "
                    f"· {int(approved_decisions or 0)} decisiones aprobadas"
                ),
            },
            "data": {
                "score": data,
                "detail": (
                    f"Confianza docs {round(float(docs_conf or 0), 1)} "
                    f"· {int(open_gaps or 0)} gaps abiertos"
                ),
            },
            "model": {
                "score": model,
                "detail": (
                    f"Evals {round(float(eval_score or 0), 1)} "
                    f"· {int(mitigated or 0)}/{int(total_risks or 0)} riesgos mitigados"
                ),
            },
            "operations": {
                "score": ops,
                "detail": (
                    f"{int(healthy_deps or 0)}/{int(total_deps or 0)} deploys healthy "
                    f"· threat {round(float(threat or 0), 1)}"
                ),
            },
        },
        "total_score": total,
    }


# ---------------------------------------------------------------------------
# Dashboard platform
# ---------------------------------------------------------------------------
async def governance_dashboard() -> dict:
    session = await get_async_session()
    try:
        decisions = (
            await session.execute(
                text(
                    "SELECT status, COUNT(*) AS n FROM governance_decisions "
                    "GROUP BY status"
                )
            )
        ).fetchall()
        audit_count = (
            await session.execute(text("SELECT COUNT(*) FROM governance_audit_log"))
        ).scalar()
        certs = (
            await session.execute(
                text(
                    "SELECT certification, COUNT(*) AS n FROM team_certifications "
                    "WHERE status = 'valid' GROUP BY certification"
                )
            )
        ).fetchall()
        orgs_governing = (
            await session.execute(
                text(
                    "SELECT COUNT(DISTINCT organization_id) FROM governance_policies "
                    "WHERE status = 'active'"
                )
            )
        ).scalar()
        recent_audit = (
            await session.execute(
                text(
                    "SELECT actor_name, action, detail, created_at FROM governance_audit_log "
                    "ORDER BY created_at DESC LIMIT 10"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "organizations_governing": int(orgs_governing or 0),
        "audit_entries": int(audit_count or 0),
        "decisions_by_status": [{"status": r.status, "count": int(r.n)} for r in decisions],
        "certifications": [{"certification": r.certification, "count": int(r.n)} for r in certs],
        "recent_audit": [
            {"actor": r.actor_name, "action": r.action, "detail": r.detail, "created_at": r.created_at.isoformat()}
            for r in recent_audit
        ],
    }
