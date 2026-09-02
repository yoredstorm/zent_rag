# =============================================================================
# Tenant Onboarding Experience v2 — checklist interactivo con sync desde
# acciones reales, guías contextuales y métricas de activación.
# =============================================================================
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

STEPS = ["create_kb", "add_documents", "create_agent", "deploy_agent", "first_query"]
STEP_LABELS = {
    "create_kb": "Crea tu primera base de conocimiento",
    "add_documents": "Añade documentos",
    "create_agent": "Crea un agente",
    "deploy_agent": "Despliega el agente",
    "first_query": "Ejecuta tu primera consulta",
}


def _default_steps() -> dict:
    return {step: {"done": False, "at": None} for step in STEPS}


async def get_progress(organization_id: UUID) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT steps, current_step, started_at, completed_at, "
                    "time_to_first_value_seconds FROM onboarding_progress "
                    "WHERE organization_id = :oid"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
        if row is None:
            await session.execute(
                text(
                    "INSERT INTO onboarding_progress (id, organization_id, steps) "
                    "VALUES (gen_random_uuid(), :oid, :steps) "
                    "ON CONFLICT (organization_id) DO NOTHING"
                ),
                {"oid": organization_id, "steps": json.dumps(_default_steps())},
            )
            await session.commit()
            row = (
                await session.execute(
                    text(
                        "SELECT steps, current_step, started_at, completed_at, "
                        "time_to_first_value_seconds FROM onboarding_progress "
                        "WHERE organization_id = :oid"
                    ),
                    {"oid": organization_id},
                )
            ).fetchone()
    finally:
        await session.close()
    return {
        "steps": row.steps or _default_steps(),
        "current_step": row.current_step,
        "started_at": row.started_at.isoformat(),
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "time_to_first_value_seconds": round(float(row.time_to_first_value_seconds), 1)
        if row.time_to_first_value_seconds is not None
        else None,
    }


async def _mark_done(organization_id: UUID, step: str, now: datetime) -> dict:
    """Marca el paso done (fail-soft) y emite el evento."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT steps, current_step, started_at FROM onboarding_progress "
                    "WHERE organization_id = :oid"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
        steps = row.steps or _default_steps() if row else _default_steps()
        if row is None:
            await session.execute(
                text(
                    "INSERT INTO onboarding_progress (id, organization_id, steps) "
                    "VALUES (gen_random_uuid(), :oid, :steps)"
                ),
                {"oid": organization_id, "steps": json.dumps(_default_steps())},
            )
        entry = steps.get(step) or {}
        steps[step] = {"done": True, "at": entry.get("at") or now.isoformat()}
        all_done = all(s.get("done") for s in steps.values())
        next_step = next((s for s in STEPS if not steps[s].get("done")), None)
        completed_at = now if all_done else None
        ttfv = round((now - row.started_at).total_seconds(), 1) if all_done and row else None
        await session.execute(
            text(
                "UPDATE onboarding_progress SET steps = :steps, current_step = :cur, "
                "completed_at = :completed, time_to_first_value_seconds = :ttfv, "
                "updated_at = :now WHERE organization_id = :oid"
            ),
            {
                "steps": json.dumps(steps),
                "cur": next_step or "completed",
                "completed": completed_at,
                "ttfv": ttfv,
                "now": now,
                "oid": organization_id,
            },
        )
        await session.execute(
            text(
                "INSERT INTO onboarding_events (id, organization_id, step, event_type) "
                "VALUES (gen_random_uuid(), :oid, :step, "
                "CASE WHEN :all_done THEN 'completed' ELSE 'step_done' END)"
            ),
            {"oid": organization_id, "step": step, "all_done": all_done},
        )
        await session.commit()
    finally:
        await session.close()
    return {"step": step, "completed": all_done}


async def complete_step(organization_id: UUID, step: str) -> dict:
    if step not in STEPS:
        raise ValueError(f"step must be one of {STEPS}")
    return await _mark_done(organization_id, step, datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Sync automático desde el estado real de la org
# ---------------------------------------------------------------------------
async def sync_progress(organization_id: UUID) -> dict:
    """Reconcilia el checklist con la actividad real (KB, docs, agentes,
    deployments, queries)."""
    session = await get_async_session()
    try:
        counts = (
            await session.execute(
                text(
                    "SELECT "
                    "(SELECT COUNT(*) FROM knowledge_bases WHERE organization_id = :oid "
                    "AND status <> 'deleted') AS kbs, "
                    "(SELECT COUNT(*) FROM documents WHERE organization_id = :oid) AS docs, "
                    "(SELECT COUNT(*) FROM agents WHERE organization_id = :oid) AS agents, "
                    "(SELECT COUNT(*) FROM deployments d JOIN environments e ON e.id = d.environment_id "
                    " WHERE d.organization_id = :oid AND e.slug = 'production') AS deploys, "
                    "(SELECT COUNT(*) FROM usage_events WHERE organization_id = :oid) AS queries"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    now = datetime.now(timezone.utc)
    done_steps = []
    if int(counts.kbs) > 0:
        done_steps.append("create_kb")
    if int(counts.docs) > 0:
        done_steps.append("add_documents")
    if int(counts.agents) > 0:
        done_steps.append("create_agent")
    if int(counts.deploys) > 0:
        done_steps.append("deploy_agent")
    if int(counts.queries) > 0:
        done_steps.append("first_query")
    for step in STEPS:
        if step in done_steps:
            try:
                await _mark_done(organization_id, step, now)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Onboarding sync step failed", error=str(exc)[:150])
    return await get_progress(organization_id)


# ---------------------------------------------------------------------------
# Estado de la org + guías contextuales
# ---------------------------------------------------------------------------
GUIDES = {
    "create_kb": {
        "title": "Empieza con tu conocimiento",
        "body": "Crea una base de conocimiento (KB) donde vivirán tus documentos. Ve a Conocimiento → Crear.",
        "href": "/knowledge-bases",
    },
    "add_documents": {
        "title": "Alimenta tu KB",
        "body": "Sube documentos o conécta un origen. Más contexto = mejores respuestas.",
        "href": "/knowledge-bases",
    },
    "create_agent": {
        "title": "Crea tu primer agente",
        "body": "Un agente combina un modelo, un prompt y tus KBs. Ve a Agentes → Crear.",
        "href": "/agents",
    },
    "deploy_agent": {
        "title": "Despliega en producción",
        "body": "Crea un deployment en el entorno production para exponer tu agente por API.",
        "href": "/agents",
    },
    "first_query": {
        "title": "Ejecuta tu primera consulta",
        "body": "Prueba tu agente desde el chat o con una llamada API.",
        "href": "/chat",
    },
    "completed": {
        "title": "¡Todo listo!",
        "body": "Tu tenant está activado. Explora analytics, integraciones y más.",
        "href": "/dashboard",
    },
}


async def org_state(organization_id: UUID) -> dict:
    progress = await sync_progress(organization_id)
    steps = progress["steps"]
    done = [s for s in STEPS if steps[s]["done"]]
    next_step = next((s for s in STEPS if not steps[s]["done"]), "completed")
    completed = progress["completed_at"] is not None
    return {
        "done_steps": done,
        "pending_steps": [s for s in STEPS if not steps[s]["done"]],
        "next_step": next_step,
        "progress_pct": round(len(done) / len(STEPS) * 100),
        "completed": completed,
        "time_to_first_value_seconds": progress["time_to_first_value_seconds"],
        "guide": GUIDES[next_step],
        "steps_labels": STEP_LABELS,
    }


# ---------------------------------------------------------------------------
# Métricas de activación (platform)
# ---------------------------------------------------------------------------
async def activation_metrics() -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS total, "
                    "COUNT(*) FILTER (WHERE completed_at IS NOT NULL) AS completed, "
                    "AVG(time_to_first_value_seconds) FILTER (WHERE "
                    "time_to_first_value_seconds IS NOT NULL) AS avg_ttfv "
                    "FROM onboarding_progress"
                )
            )
        ).fetchone()
        funnel = (
            await session.execute(
                text(
                    "SELECT o.step, COUNT(*) AS orgs FROM onboarding_events o "
                    "WHERE o.event_type = 'step_done' OR o.event_type = 'completed' "
                    "GROUP BY o.step ORDER BY CASE o.step "
                    "WHEN 'create_kb' THEN 1 WHEN 'add_documents' THEN 2 "
                    "WHEN 'create_agent' THEN 3 WHEN 'deploy_agent' THEN 4 "
                    "WHEN 'first_query' THEN 5 ELSE 9 END"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    total = int(row.total)
    completed = int(row.completed)
    funnel_map = {r.step: int(r.orgs) for r in funnel}
    return {
        "total_orgs": total,
        "completed": completed,
        "activation_rate": round(completed / total, 4) if total else 0.0,
        "avg_time_to_first_value_seconds": round(float(row.avg_ttfv), 1)
        if row.avg_ttfv is not None
        else None,
        "funnel": [
            {"step": step, "orgs": funnel_map.get(step, 0)} for step in STEPS
        ],
    }


async def status_by_org() -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT organization_id, steps, current_step, started_at, "
                    "completed_at, time_to_first_value_seconds FROM onboarding_progress "
                    "ORDER BY started_at DESC LIMIT 200"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "organizations": [
            {
                "organization_id": str(r.organization_id),
                "done_steps": [s for s, v in (r.steps or {}).items() if v.get("done")],
                "current_step": r.current_step,
                "started_at": r.started_at.isoformat(),
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "time_to_first_value_seconds": round(float(r.time_to_first_value_seconds), 1)
                if r.time_to_first_value_seconds is not None
                else None,
            }
            for r in rows
        ]
    }
