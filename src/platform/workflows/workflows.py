# =============================================================================
# Workflows & Automation — definiciones, ejecutor de pasos, cron, aprobaciones
# =============================================================================
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

STEP_TYPES = ("ingest", "evaluate", "deploy", "notify", "webhook", "approval")

RUN_RUNNING = "running"
RUN_WAITING = "waiting_approval"
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"
RUN_CANCELED = "canceled"

STEP_PENDING = "pending"
STEP_RUNNING = "running"
STEP_COMPLETED = "completed"
STEP_FAILED = "failed"
STEP_WAITING = "waiting_approval"


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
async def create_definition(
    organization_id: UUID,
    name: str,
    description: str | None,
    trigger_type: str,
    cron_expr: str | None,
    steps: list[dict],
    created_by: UUID | None,
) -> dict:
    if trigger_type == "schedule" and not cron_expr:
        raise ValueError("cron_expr requerido para trigger schedule")
    for step in steps:
        if step.get("type") not in STEP_TYPES:
            raise ValueError(f"Tipo de paso inválido: {step.get('type')}")
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO workflow_definitions (id, organization_id, name, "
                    "description, trigger_type, cron_expr, steps, created_by) "
                    "VALUES (gen_random_uuid(), :oid, :name, :desc, :trigger, :cron, "
                    ":steps, :by) RETURNING id, name, trigger_type, enabled"
                ),
                {
                    "oid": organization_id,
                    "name": name,
                    "desc": description,
                    "trigger": trigger_type,
                    "cron": cron_expr,
                    "steps": json.dumps(steps),
                    "by": created_by,
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {"id": str(row.id), "name": row.name, "trigger_type": row.trigger_type, "enabled": bool(row.enabled)}


async def list_definitions(organization_id: UUID | None, limit: int = 100) -> list[dict]:
    session = await get_async_session()
    try:
        sql = (
            "SELECT id, organization_id, name, description, enabled, trigger_type, "
            "cron_expr, steps, created_at, updated_at, last_run_at "
            "FROM workflow_definitions WHERE 1=1 "
        )
        params: dict = {"limit": limit}
        if organization_id is not None:
            sql += " AND organization_id = :oid "
            params["oid"] = organization_id
        sql += " ORDER BY created_at DESC LIMIT :limit"
        rows = (await session.execute(text(sql), params)).fetchall()
    finally:
        await session.close()
    return [_definition_response(r) for r in rows]


def _definition_response(r) -> dict:
    return {
        "id": str(r.id),
        "organization_id": str(r.organization_id),
        "name": r.name,
        "description": r.description,
        "enabled": bool(r.enabled),
        "trigger_type": r.trigger_type,
        "cron_expr": r.cron_expr,
        "steps": r.steps or [],
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
        "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
    }


async def get_definition(organization_id: UUID, workflow_id: UUID) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, organization_id, name, description, enabled, trigger_type, "
                    "cron_expr, steps, created_at, updated_at, last_run_at "
                    "FROM workflow_definitions WHERE id = :wid AND organization_id = :oid"
                ),
                {"wid": workflow_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    return _definition_response(row)


async def update_definition(
    organization_id: UUID, workflow_id: UUID, **fields
) -> bool:
    allowed = {"name", "description", "enabled", "trigger_type", "cron_expr", "steps"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    session = await get_async_session()
    try:
        sets: list[str] = []
        params: dict = {"wid": workflow_id, "oid": organization_id}
        for key, value in updates.items():
            sets.append(f"{key} = :{key}")
            params[key] = json.dumps(value) if key == "steps" else value
        sets.append("updated_at = NOW()")
        result = await session.execute(
            text(
                f"UPDATE workflow_definitions SET {', '.join(sets)} "  # noqa: S608 (keys whitelisted)
                "WHERE id = :wid AND organization_id = :oid"
            ),
            params,
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def delete_definition(organization_id: UUID, workflow_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "DELETE FROM workflow_definitions "
                "WHERE id = :wid AND organization_id = :oid"
            ),
            {"wid": workflow_id, "oid": organization_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------
async def _create_run(
    organization_id: UUID, workflow_id: UUID, trigger: str, created_by: UUID | None
) -> UUID:
    session = await get_async_session()
    try:
        run_id = (
            await session.execute(
                text(
                    "INSERT INTO workflow_runs (id, workflow_id, organization_id, "
                    "trigger, created_by) VALUES (gen_random_uuid(), :wid, :oid, "
                    ":trigger, :by) RETURNING id"
                ),
                {"wid": workflow_id, "oid": organization_id, "trigger": trigger, "by": created_by},
            )
        ).scalar()
        await session.execute(
            text("UPDATE workflow_definitions SET last_run_at = NOW() WHERE id = :wid"),
            {"wid": workflow_id},
        )
        await session.commit()
        return run_id
    finally:
        await session.close()


async def _set_run(run_id: UUID, **fields) -> None:
    session = await get_async_session()
    try:
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        params = {"rid": run_id, **fields}
        await session.execute(text(f"UPDATE workflow_runs SET {sets} WHERE id = :rid"), params)  # noqa: S608 (keys fijas)
        await session.commit()
    finally:
        await session.close()


async def _upsert_step(
    run_id: UUID, step_index: int, step_type: str, status: str, details: dict | None = None
) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO workflow_run_steps (id, run_id, step_index, step_type, "
                "status, details, started_at, completed_at) "
                "VALUES (gen_random_uuid(), :rid, :idx, :type, :status, :details, "
                "CASE WHEN CAST(:status AS varchar) = 'pending' THEN NULL ELSE NOW() END, "
                "CASE WHEN CAST(:status AS varchar) IN ('completed','failed') "
                "THEN NOW() ELSE NULL END) "
                "ON CONFLICT (run_id, step_index) DO UPDATE SET status = EXCLUDED.status, "
                "details = EXCLUDED.details, completed_at = EXCLUDED.completed_at"
            ),
            {
                "rid": run_id,
                "idx": step_index,
                "type": step_type,
                "status": status,
                "details": json.dumps(details or {}),
            },
        )
        await session.commit()
    finally:
        await session.close()


async def _step_ingest(organization_id: UUID, params: dict) -> dict:
    kb_id = params.get("knowledge_base_id")
    if not kb_id:
        raise ValueError("knowledge_base_id requerido")
    session = await get_async_session()
    try:
        exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM knowledge_bases WHERE id = :kid AND organization_id = :oid"
                ),
                {"kid": UUID(kb_id), "oid": organization_id},
            )
        ).fetchone()
        if exists is None:
            raise ValueError("knowledge_base no existe en esta org")
        job_id = (
            await session.execute(
                text(
                    "INSERT INTO ingestion_jobs (id, organization_id, knowledge_base_id, "
                    "job_type, status, attempts, max_attempts) "
                    "VALUES (gen_random_uuid(), :oid, :kid, 'workflow', 'pending', 0, 3) "
                    "RETURNING id"
                ),
                {"oid": organization_id, "kid": UUID(kb_id)},
            )
        ).scalar()
        await session.commit()
    finally:
        await session.close()
    return {"ingestion_job_id": str(job_id), "knowledge_base_id": kb_id}


async def _step_evaluate(organization_id: UUID, params: dict) -> dict:
    from src.platform.observability.slos import org_slos

    agent_id = params.get("agent_id")
    slos = await org_slos(organization_id)
    agent_slo = None
    if agent_id:
        agent_slo = next(
            (d for d in slos["deployments"] if d.get("deployment_id") and d["agent_name"]),
            None,
        )
    aggregate = slos["aggregate_24h"]
    threshold = params.get("threshold_status")
    ok = True
    if threshold and aggregate["status"] != "no_traffic":
        ok = aggregate["status"] == threshold
    return {
        "aggregate_status": aggregate["status"],
        "availability_pct": aggregate["availability_pct"],
        "error_rate_pct": aggregate["error_rate_pct"],
        "passed_threshold": ok,
    }


async def _step_deploy(organization_id: UUID, params: dict) -> dict:
    from src.infrastructure.postgres.relational_db import (
        PostgresAgentRepository,
        PostgresAgentVersionRepository,
        PostgresDeploymentRepository,
        PostgresOrganizationRepository,
    )
    from src.platform.deployments.deployments import (
        deploy_to_environment,
        ensure_default_environments,
    )

    repo = PostgresDeploymentRepository()
    await ensure_default_environments(repo, organization_id)
    agent_id = params.get("agent_id")
    environment = params.get("environment") or "production"
    if not agent_id:
        raise ValueError("agent_id requerido")
    agent_repo = PostgresAgentRepository()
    agent = await agent_repo.get_agent(organization_id, UUID(agent_id))
    if agent is None:
        raise ValueError("agent no existe")
    session = await get_async_session()
    try:
        env_row = (
            await session.execute(
                text(
                    "SELECT id FROM environments WHERE slug = :slug AND organization_id = :oid"
                ),
                {"slug": environment, "oid": organization_id},
            )
        ).fetchone()
        version_row = (
            await session.execute(
                text(
                    "SELECT id FROM agent_versions WHERE agent_id = :aid "
                    "AND status = 'ready' ORDER BY created_at DESC LIMIT 1"
                ),
                {"aid": UUID(agent_id)},
            )
        ).fetchone()
    finally:
        await session.close()
    if env_row is None:
        raise ValueError(f"entorno '{environment}' no existe")
    if version_row is None:
        raise ValueError("no hay versión ready del agente")
    org = await PostgresOrganizationRepository().get_by_id(organization_id)
    version = await PostgresAgentVersionRepository().get_version(
        organization_id, UUID(agent_id), version_row.id
    )
    deployment = await deploy_to_environment(
        repo,
        organization_id,
        agent=agent,
        version=version,
        environment_id=env_row.id,
        slug=params.get("slug"),
        deployed_by=None,
    )
    return {"deployment_id": str(deployment.id), "slug": deployment.slug, "status": deployment.status.value}


async def _step_notify(organization_id: UUID, params: dict) -> dict:
    from src.platform.customer_success.customer_success import send_email

    email = params.get("email")
    message = params.get("message") or "Workflow completado"
    if not email:
        raise ValueError("email requerido")
    ok = await send_email(email, f"Workflow: {message}", f"<p>{message}</p>")
    return {"sent": ok, "note": "SMTP no configurado" if not ok else "delivered"}


async def _step_webhook(organization_id: UUID, params: dict, run_id: UUID) -> dict:
    import httpx

    url = params.get("url")
    if not url:
        raise ValueError("url requerido")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            url,
            json={"event": "workflow.step", "run_id": str(run_id), "organization_id": str(organization_id)},
        )
    if not (200 <= resp.status_code < 300):
        raise ValueError(f"webhook responded {resp.status_code}")
    return {"status_code": resp.status_code}


async def _run_steps(
    organization_id: UUID,
    workflow_id: UUID,
    run_id: UUID,
    steps: list[dict],
    created_by: UUID | None,
    start_index: int = 0,
) -> None:
    for index, step in enumerate(steps):
        index = start_index + index
        step_type = step.get("type", "")
        params = step.get("params") or {}
        await _set_run(run_id, current_step=index, status=RUN_RUNNING)
        await _upsert_step(run_id, index, step_type, STEP_RUNNING)

        if step_type == "approval":
            await _upsert_step(
                run_id, index, step_type, STEP_WAITING,
                {"message": params.get("message", "Requiere aprobación")},
            )
            await _set_run(run_id, status=RUN_WAITING)
            return  # run queda en waiting_approval; approve() continúa

        try:
            if step_type == "ingest":
                details = await _step_ingest(organization_id, params)
            elif step_type == "evaluate":
                details = await _step_evaluate(organization_id, params)
                if not details.get("passed_threshold", True):
                    raise ValueError(
                        f"SLO no cumple threshold (status={details['aggregate_status']})"
                    )
            elif step_type == "deploy":
                details = await _step_deploy(organization_id, params)
            elif step_type == "notify":
                details = await _step_notify(organization_id, params)
            elif step_type == "webhook":
                details = await _step_webhook(organization_id, params, run_id)
            else:
                raise ValueError(f"Paso desconocido: {step_type}")
            await _upsert_step(run_id, index, step_type, STEP_COMPLETED, details)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)[:400]
            logger.warning("Workflow step failed", run_id=str(run_id), step=step_type, error=error)
            await _upsert_step(run_id, index, step_type, STEP_FAILED, {"error": error})
            await _set_run(run_id, status=RUN_FAILED, error=error, completed_at=datetime.now(timezone.utc))
            return

    await _set_run(run_id, status=RUN_COMPLETED, completed_at=datetime.now(timezone.utc))


async def trigger_workflow(
    organization_id: UUID, workflow_id: UUID, trigger: str = "manual", created_by: UUID | None = None
) -> dict:
    definition = await get_definition(organization_id, workflow_id)
    if definition is None:
        return {"status": "not_found"}
    if not definition["enabled"]:
        return {"status": "disabled"}
    run_id = await _create_run(organization_id, workflow_id, trigger, created_by)
    asyncio.get_running_loop().create_task(
        _run_steps(organization_id, workflow_id, run_id, definition["steps"], created_by)
    )
    return {"status": "started", "run_id": str(run_id)}


async def approve_run(organization_id: UUID, run_id: UUID, approve: bool) -> dict:
    """Aprueba/rechaza el paso de aprobación pendiente y continúa o cancela."""
    session = await get_async_session()
    try:
        run = (
            await session.execute(
                text(
                    "SELECT workflow_id, status, current_step FROM workflow_runs "
                    "WHERE id = :rid AND organization_id = :oid"
                ),
                {"rid": run_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if run is None:
        return {"status": "not_found"}
    if run.status != RUN_WAITING:
        return {"status": "not_waiting"}
    definition = await get_definition(organization_id, run.workflow_id)
    if definition is None:
        return {"status": "not_found"}
    steps = definition["steps"]
    next_index = int(run.current_step) + 1
    if not approve:
        await _set_run(run_id, status=RUN_CANCELED, completed_at=datetime.now(timezone.utc))
        await _upsert_step(
            run_id, int(run.current_step), "approval", STEP_FAILED, {"error": "rechazado"}
        )
        return {"status": "rejected"}
    # Aprobado: marcar el paso de aprobación como completado y seguir.
    await _upsert_step(
        run_id, int(run.current_step), "approval", STEP_COMPLETED, {"approved": True}
    )
    asyncio.get_running_loop().create_task(
        _run_steps(
            organization_id, run.workflow_id, run_id, steps[next_index:], None,
            start_index=next_index,
        )
    )
    return {"status": "approved"}


async def list_runs(organization_id: UUID | None, status: str | None = None, limit: int = 50) -> list[dict]:
    session = await get_async_session()
    try:
        sql = (
            "SELECT id, workflow_id, organization_id, trigger, status, current_step, "
            "started_at, completed_at, error FROM workflow_runs WHERE 1=1 "
        )
        params: dict = {"limit": limit}
        if organization_id is not None:
            sql += " AND organization_id = :oid "
            params["oid"] = organization_id
        if status:
            sql += " AND status = :status "
            params["status"] = status
        sql += " ORDER BY started_at DESC LIMIT :limit"
        rows = (await session.execute(text(sql), params)).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "workflow_id": str(r.workflow_id),
            "organization_id": str(r.organization_id),
            "trigger": r.trigger,
            "status": r.status,
            "current_step": int(r.current_step),
            "started_at": r.started_at.isoformat(),
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "error": r.error,
        }
        for r in rows
    ]


async def get_run_steps(run_id: UUID) -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT step_index, step_type, status, details, started_at, "
                    "completed_at FROM workflow_run_steps WHERE run_id = :rid "
                    "ORDER BY step_index"
                ),
                {"rid": run_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "step_index": int(r.step_index),
            "step_type": r.step_type,
            "status": r.status,
            "details": r.details or {},
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Cron matcher (minuto/hora/día del mes/mes/día de semana, con * y */n)
# ---------------------------------------------------------------------------
def _match_field(value: str, current: int) -> bool:
    if value == "*":
        return True
    for part in value.split(","):
        part = part.strip()
        if "/" in part:
            base, step = part.split("/")
            base_val = 0 if base == "*" else int(base)
            if current >= base_val and (current - base_val) % int(step) == 0:
                return True
        elif part == str(current):
            return True
    return False


def cron_matches(expr: str, now: datetime) -> bool:
    parts = expr.split()
    if len(parts) != 5:
        return False
    minute, hour, dom, month, dow = parts
    return (
        _match_field(minute, now.minute)
        and _match_field(hour, now.hour)
        and _match_field(dom, now.day)
        and _match_field(month, now.month)
        and _match_field(dow, now.isoweekday())
    )


async def workflow_scheduler_loop() -> None:
    """Cada 60s: ejecuta workflows schedule cuyo cron coincide (máx 1/min)."""
    while True:
        try:
            now = datetime.now(timezone.utc)
            session = await get_async_session()
            try:
                rows = (
                    await session.execute(
                        text(
                            "SELECT id, organization_id, cron_expr, last_run_at "
                            "FROM workflow_definitions WHERE enabled = true "
                            "AND trigger_type = 'schedule'"
                        )
                    )
                ).fetchall()
            finally:
                await session.close()
            for row in rows:
                if not row.cron_expr:
                    continue
                if row.last_run_at and row.last_run_at >= now.replace(second=0, microsecond=0):
                    continue
                if cron_matches(row.cron_expr, now):
                    logger.info("Scheduler: workflow due", workflow_id=str(row.id))
                    await trigger_workflow(row.organization_id, row.id, trigger="schedule")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Workflow scheduler iteration failed", error=str(exc)[:200])
        await asyncio.sleep(60)
