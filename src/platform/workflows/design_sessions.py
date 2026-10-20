# =============================================================================
# Workflow Design Sessions (Prompt 07).
#
# Sesión persistente de DISEÑO, separada de WorkflowInstance y de las
# conversaciones de clientes finales. Guarda mensajes, plan/grafo, requisitos,
# validación, simulación y revisiones con control optimista.
# =============================================================================
from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

DESIGN_STATUSES = ("active", "closed", "draft_saved", "published")

_CREATE_SQL = (
    """
    CREATE TABLE IF NOT EXISTS workflow_design_sessions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        workspace_id UUID,
        user_id UUID,
        title VARCHAR(200) NOT NULL DEFAULT 'Diseño',
        original_prompt TEXT NOT NULL DEFAULT '',
        status VARCHAR(20) NOT NULL DEFAULT 'active',
        revision INT NOT NULL DEFAULT 0,
        plan JSONB,
        graph JSONB,
        plan_hash VARCHAR(64),
        capability_snapshot_hash VARCHAR(64),
        workflow_id UUID,
        state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        closed_at TIMESTAMPTZ
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_workflow_design_sessions_org
    ON workflow_design_sessions(organization_id, workspace_id, updated_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS workflow_design_revisions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        session_id UUID NOT NULL REFERENCES workflow_design_sessions(id) ON DELETE CASCADE,
        organization_id UUID NOT NULL,
        revision INT NOT NULL,
        user_id UUID,
        kind VARCHAR(30) NOT NULL DEFAULT 'patch',
        instruction TEXT,
        summary TEXT,
        diff JSONB NOT NULL DEFAULT '{}'::jsonb,
        plan JSONB,
        graph JSONB,
        plan_hash VARCHAR(64),
        validation JSONB NOT NULL DEFAULT '{}'::jsonb,
        simulation JSONB NOT NULL DEFAULT '{}'::jsonb,
        state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (session_id, revision)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_workflow_design_revisions_session
    ON workflow_design_revisions(session_id, revision DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS workflow_design_messages (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        session_id UUID NOT NULL REFERENCES workflow_design_sessions(id) ON DELETE CASCADE,
        organization_id UUID NOT NULL,
        role VARCHAR(20) NOT NULL,
        content TEXT NOT NULL,
        user_id UUID,
        revision INT NOT NULL DEFAULT 0,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_workflow_design_messages_session
    ON workflow_design_messages(session_id, created_at)
    """,
)


class DesignSessionNotFound(LookupError):
    pass


class DesignSessionConflict(RuntimeError):
    def __init__(self, current_revision: int, expected_revision: int) -> None:
        super().__init__(
            "La sesión cambió desde que la cargaste; recarga antes de editar."
        )
        self.current_revision = current_revision
        self.expected_revision = expected_revision


async def ensure_design_session_tables() -> None:
    session = await get_async_session()
    try:
        for statement in _CREATE_SQL:
            await session.execute(text(statement))
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def _json(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, default=str)


def _row(row: Any, *, include_plan: bool = True) -> dict[str, Any]:
    if row is None:
        return {}
    data = {
        "id": str(row.id),
        "organization_id": str(row.organization_id),
        "workspace_id": str(row.workspace_id) if row.workspace_id else None,
        "user_id": str(row.user_id) if row.user_id else None,
        "title": row.title,
        "original_prompt": row.original_prompt,
        "status": row.status,
        "revision": int(row.revision or 0),
        "plan_hash": row.plan_hash,
        "capability_snapshot_hash": row.capability_snapshot_hash,
        "workflow_id": str(row.workflow_id) if row.workflow_id else None,
        "state": dict(row.state_json or {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
    }
    if include_plan:
        data["plan"] = dict(row.plan) if row.plan else None
        data["graph"] = dict(row.graph) if row.graph else None
    return data


def _message(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "role": row.role,
        "content": row.content,
        "user_id": str(row.user_id) if row.user_id else None,
        "revision": int(row.revision or 0),
        "metadata": dict(row.metadata or {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def create_design_session(
    organization_id: UUID,
    *,
    user_id: UUID | None = None,
    workspace_id: UUID | None = None,
    prompt: str,
    title: str | None = None,
) -> dict[str, Any]:
    await ensure_design_session_tables()
    session_id = uuid4()
    clean_title = (title or prompt or "Diseño").strip()[:200] or "Diseño"
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO workflow_design_sessions "
                "(id, organization_id, workspace_id, user_id, title, original_prompt, "
                "status, revision, state_json) "
                "VALUES (:id, :oid, :ws, :uid, :title, :prompt, 'active', 0, "
                "CAST(:state AS jsonb))"
            ),
            {
                "id": session_id,
                "oid": organization_id,
                "ws": workspace_id,
                "uid": user_id,
                "title": clean_title,
                "prompt": prompt[:12000],
                "state": _json({"original_prompt": prompt[:12000]}),
            },
        )
        await session.commit()
    finally:
        await session.close()
    await append_design_message(
        organization_id,
        session_id,
        role="user",
        content=prompt,
        user_id=user_id,
    )
    loaded = await get_design_session(organization_id, session_id, user_id=user_id)
    if loaded is None:
        raise DesignSessionNotFound("no pude crear la sesión de diseño")
    return loaded


async def get_design_session(
    organization_id: UUID,
    session_id: UUID,
    *,
    user_id: UUID | None = None,
    include_messages: bool = True,
    include_revisions: bool = False,
) -> dict[str, Any] | None:
    await ensure_design_session_tables()
    session = await get_async_session()
    try:
        sql = (
            "SELECT id, organization_id, workspace_id, user_id, title, original_prompt, "
            "status, revision, plan, graph, plan_hash, capability_snapshot_hash, "
            "workflow_id, state_json, created_at, updated_at, closed_at "
            "FROM workflow_design_sessions WHERE id = :sid AND organization_id = :oid"
        )
        params: dict[str, Any] = {"sid": session_id, "oid": organization_id}
        if user_id is not None:
            sql += " AND (user_id IS NULL OR user_id = :uid)"
            params["uid"] = user_id
        row = (await session.execute(text(sql), params)).fetchone()
        if row is None:
            return None
        data = _row(row)
        if include_revisions:
            revisions = (
                await session.execute(
                    text(
                        "SELECT revision, kind, instruction, summary, diff, plan_hash, "
                        "validation, simulation, created_at, user_id "
                        "FROM workflow_design_revisions WHERE session_id = :sid "
                        "AND organization_id = :oid ORDER BY revision DESC"
                    ),
                    {"sid": session_id, "oid": organization_id},
                )
            ).fetchall()
            data["revisions"] = [
                {
                    "revision": int(item.revision),
                    "kind": item.kind,
                    "instruction": item.instruction,
                    "summary": item.summary,
                    "diff": dict(item.diff or {}),
                    "plan_hash": item.plan_hash,
                    "validation": (
                        item.validation
                        if isinstance(item.validation, dict)
                        else {"value": item.validation}
                    ),
                    "simulation": (
                        item.simulation
                        if isinstance(item.simulation, dict)
                        else {"preview": item.simulation}
                    ),
                    "user_id": str(item.user_id) if item.user_id else None,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
                for item in revisions
            ]
        if include_messages:
            messages = (
                await session.execute(
                    text(
                        "SELECT id, role, content, user_id, revision, metadata, created_at "
                        "FROM workflow_design_messages WHERE session_id = :sid "
                        "AND organization_id = :oid ORDER BY created_at, id"
                    ),
                    {"sid": session_id, "oid": organization_id},
                )
            ).fetchall()
            data["messages"] = [_message(item) for item in messages]
        return data
    finally:
        await session.close()


async def list_design_sessions(
    organization_id: UUID,
    *,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    await ensure_design_session_tables()
    session = await get_async_session()
    try:
        sql = (
            "SELECT id, organization_id, workspace_id, user_id, title, original_prompt, "
            "status, revision, NULL::jsonb AS plan, NULL::jsonb AS graph, plan_hash, "
            "capability_snapshot_hash, workflow_id, state_json, created_at, updated_at, closed_at "
            "FROM workflow_design_sessions WHERE organization_id = :oid"
        )
        params: dict[str, Any] = {"oid": organization_id, "limit": max(1, min(limit, 100))}
        if workspace_id is not None:
            sql += " AND (workspace_id IS NULL OR workspace_id = :ws)"
            params["ws"] = workspace_id
        if user_id is not None:
            sql += " AND (user_id IS NULL OR user_id = :uid)"
            params["uid"] = user_id
        sql += " ORDER BY updated_at DESC LIMIT :limit"
        rows = (await session.execute(text(sql), params)).fetchall()
        return {"sessions": [_row(item, include_plan=False) for item in rows]}
    finally:
        await session.close()


async def append_design_message(
    organization_id: UUID,
    session_id: UUID,
    *,
    role: str,
    content: str,
    user_id: UUID | None = None,
    revision: int = 0,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if role not in ("user", "assistant", "system"):
        raise ValueError("rol de mensaje inválido")
    await ensure_design_session_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO workflow_design_messages "
                    "(organization_id, session_id, role, content, user_id, revision, metadata) "
                    "VALUES (:oid, :sid, :role, :content, :uid, :rev, CAST(:meta AS jsonb)) "
                    "RETURNING id, role, content, user_id, revision, metadata, created_at"
                ),
                {
                    "oid": organization_id,
                    "sid": session_id,
                    "role": role,
                    "content": content[:12000],
                    "uid": user_id,
                    "rev": int(revision or 0),
                    "meta": _json(metadata or {}),
                },
            )
        ).fetchone()
        await session.execute(
            text(
                "UPDATE workflow_design_sessions SET updated_at = NOW() "
                "WHERE id = :sid AND organization_id = :oid"
            ),
            {"sid": session_id, "oid": organization_id},
        )
        await session.commit()
    finally:
        await session.close()
    return _message(row)


async def save_design_result(
    organization_id: UUID,
    session_id: UUID,
    result: dict[str, Any],
    *,
    expected_revision: int,
    user_id: UUID | None = None,
    kind: str = "patch",
    instruction: str | None = None,
    diff: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Guarda una revisión con bloqueo optimista. No toca workflows publicados."""
    await ensure_design_session_tables()
    session = await get_async_session()
    try:
        current = (
            await session.execute(
                text(
                    "SELECT revision, status, title, state_json FROM workflow_design_sessions "
                    "WHERE id = :sid AND organization_id = :oid FOR UPDATE"
                ),
                {"sid": session_id, "oid": organization_id},
            )
        ).fetchone()
        if current is None:
            raise DesignSessionNotFound("sesión de diseño inexistente")
        if int(current.revision or 0) != int(expected_revision):
            raise DesignSessionConflict(
                int(current.revision or 0), int(expected_revision)
            )
        revision = int(current.revision or 0) + 1
        plan = result.get("plan")
        graph = result.get("graph")
        preserved_keys = (
            "state",
            "specification",
            "intent",
            "issues",
            "requirements",
            "clarifications",
            "blockers",
            "assumptions",
            "questions",
            "preview",
            "matches",
            "resource_resolution",
            "readiness",
            "capability_snapshot",
            "cost",
            "requires_durable_instance",
            "publishable",
            "trace",
            "usage",
        )
        previous_state = dict(current.state_json or {})
        state_json = {
            key: previous_state.get(key)
            for key in preserved_keys
            if previous_state.get(key) is not None
        }
        state_json.update(
            {key: result.get(key) for key in preserved_keys if key in result}
        )
        decisions = (
            list(previous_state.get("decisions") or [])
            if isinstance(previous_state.get("decisions"), list)
            else []
        )
        if kind != "simulation" and (instruction or "").strip():
            decisions.append(
                {
                    "revision": revision,
                    "kind": kind,
                    "instruction": instruction.strip()[:400],
                }
            )
        state_json["decisions"] = decisions[-50:]
        previous_proposal = (
            previous_state.get("proposal")
            if isinstance(previous_state.get("proposal"), dict)
            else {}
        )
        state_json["proposal"] = {**previous_proposal, **result}
        validation = {
            "state": result.get("state"),
            "issues": result.get("issues") or [],
            "requirements": result.get("requirements") or [],
            "readiness": result.get("readiness"),
        }
        simulation = result.get("simulation_certification") or result.get("simulation")
        if not isinstance(simulation, dict):
            simulation = {"preview": simulation or None}
        title = str(
            (result.get("plan") or {}).get("goal")
            or getattr(current, "title", None)
            or "Diseño"
        )[:200]
        await session.execute(
            text(
                "INSERT INTO workflow_design_revisions "
                "(session_id, organization_id, revision, user_id, kind, instruction, summary, "
                "diff, plan, graph, plan_hash, validation, simulation, state_json) "
                "VALUES (:sid, :oid, :rev, :uid, :kind, :instruction, :summary, "
                "CAST(:diff AS jsonb), CAST(:plan AS jsonb), CAST(:graph AS jsonb), "
                ":plan_hash, CAST(:validation AS jsonb), CAST(:simulation AS jsonb), "
                "CAST(:state AS jsonb))"
            ),
            {
                "sid": session_id,
                "oid": organization_id,
                "rev": revision,
                "uid": user_id,
                "kind": kind[:30],
                "instruction": (instruction or "")[:2000] or None,
                "summary": str((diff or {}).get("summary") or result.get("state") or "")[:400],
                "diff": _json(diff or {}),
                "plan": _json(plan),
                "graph": _json(graph),
                "plan_hash": result.get("plan_hash"),
                "validation": _json(validation),
                "simulation": _json(simulation or {}),
                "state": _json(state_json),
            },
        )
        await session.execute(
            text(
                "UPDATE workflow_design_sessions SET revision = :rev, plan = CAST(:plan AS jsonb), "
                "graph = CAST(:graph AS jsonb), plan_hash = :plan_hash, "
                "capability_snapshot_hash = :snapshot_hash, state_json = CAST(:state AS jsonb), "
                "title = :title, updated_at = NOW() "
                "WHERE id = :sid AND organization_id = :oid"
            ),
            {
                "rev": revision,
                "plan": _json(plan),
                "graph": _json(graph),
                "plan_hash": result.get("plan_hash"),
                "snapshot_hash": (result.get("capability_snapshot") or {}).get(
                    "snapshot_hash"
                ),
                "state": _json(state_json),
                "title": title,
                "sid": session_id,
                "oid": organization_id,
            },
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    loaded = await get_design_session(
        organization_id, session_id, user_id=user_id, include_revisions=True
    )
    if loaded is None:
        raise DesignSessionNotFound("sesión de diseño inexistente")
    return loaded


async def save_design_simulation(
    organization_id: UUID,
    session_id: UUID,
    certification: dict[str, Any],
    *,
    expected_revision: int,
    user_id: UUID | None = None,
    instruction: str | None = None,
) -> dict[str, Any]:
    current = await get_design_session(
        organization_id, session_id, user_id=user_id, include_messages=False
    )
    if current is None:
        raise DesignSessionNotFound("sesión de diseño inexistente")
    proposal = dict((current.get("state") or {}).get("proposal") or {})
    proposal["simulation_certification"] = certification
    proposal["simulation"] = certification.get("scenarios")
    proposal["certification_state"] = certification.get("state")
    proposal["simulation_publishable"] = bool(certification.get("publishable"))
    return await save_design_result(
        organization_id,
        session_id,
        proposal,
        expected_revision=expected_revision,
        user_id=user_id,
        kind="simulation",
        instruction=instruction,
        diff={"summary": "Simulación y certificación"},
    )


async def restore_design_revision(
    organization_id: UUID,
    session_id: UUID,
    revision: int,
    *,
    expected_revision: int,
    user_id: UUID | None = None,
    instruction: str | None = None,
) -> dict[str, Any]:
    await ensure_design_session_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT plan, graph, plan_hash, state_json FROM workflow_design_revisions "
                    "WHERE session_id = :sid AND organization_id = :oid AND revision = :rev"
                ),
                {"sid": session_id, "oid": organization_id, "rev": revision},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        raise DesignSessionNotFound("revisión inexistente")
    state = dict(row.state_json or {})
    proposal = dict(state.get("proposal") or {})
    proposal["plan"] = dict(row.plan or {}) if row.plan else None
    proposal["graph"] = dict(row.graph or {}) if row.graph else None
    proposal["plan_hash"] = row.plan_hash
    return await save_design_result(
        organization_id,
        session_id,
        proposal,
        expected_revision=expected_revision,
        user_id=user_id,
        kind="restore",
        instruction=instruction or f"Restaurar revisión {revision}",
        diff={"summary": f"Restaurar revisión {revision}", "restored_from": revision},
    )


async def close_design_session(
    organization_id: UUID,
    session_id: UUID,
    *,
    expected_revision: int,
    user_id: UUID | None = None,
) -> dict[str, Any]:
    await ensure_design_session_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT revision FROM workflow_design_sessions "
                    "WHERE id = :sid AND organization_id = :oid FOR UPDATE"
                ),
                {"sid": session_id, "oid": organization_id},
            )
        ).fetchone()
        if row is None:
            raise DesignSessionNotFound("sesión de diseño inexistente")
        if int(row.revision or 0) != int(expected_revision):
            raise DesignSessionConflict(int(row.revision or 0), int(expected_revision))
        await session.execute(
            text(
                "UPDATE workflow_design_sessions SET status = 'closed', "
                "closed_at = NOW(), updated_at = NOW() "
                "WHERE id = :sid AND organization_id = :oid"
            ),
            {"sid": session_id, "oid": organization_id},
        )
        await session.commit()
    finally:
        await session.close()
    loaded = await get_design_session(organization_id, session_id, user_id=user_id)
    if loaded is None:
        raise DesignSessionNotFound("sesión de diseño inexistente")
    return loaded


async def reopen_design_session(
    organization_id: UUID,
    session_id: UUID,
    *,
    expected_revision: int,
    user_id: UUID | None = None,
) -> dict[str, Any]:
    await ensure_design_session_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT revision FROM workflow_design_sessions "
                    "WHERE id = :sid AND organization_id = :oid FOR UPDATE"
                ),
                {"sid": session_id, "oid": organization_id},
            )
        ).fetchone()
        if row is None:
            raise DesignSessionNotFound("sesión de diseño inexistente")
        if int(row.revision or 0) != int(expected_revision):
            raise DesignSessionConflict(int(row.revision or 0), int(expected_revision))
        await session.execute(
            text(
                "UPDATE workflow_design_sessions SET status = 'active', closed_at = NULL, "
                "updated_at = NOW() WHERE id = :sid AND organization_id = :oid"
            ),
            {"sid": session_id, "oid": organization_id},
        )
        await session.commit()
    finally:
        await session.close()
    loaded = await get_design_session(organization_id, session_id, user_id=user_id)
    if loaded is None:
        raise DesignSessionNotFound("sesión de diseño inexistente")
    return loaded


async def attach_workflow(
    organization_id: UUID,
    session_id: UUID,
    workflow_id: UUID,
    *,
    user_id: UUID | None = None,
) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE workflow_design_sessions SET workflow_id = :wid, "
                "status = CASE WHEN status = 'closed' THEN status ELSE 'draft_saved' END, "
                "updated_at = NOW() WHERE id = :sid AND organization_id = :oid"
            ),
            {"wid": workflow_id, "sid": session_id, "oid": organization_id},
        )
        await session.commit()
    finally:
        await session.close()


__all__ = [
    "DESIGN_STATUSES",
    "DesignSessionConflict",
    "DesignSessionNotFound",
    "append_design_message",
    "attach_workflow",
    "close_design_session",
    "create_design_session",
    "ensure_design_session_tables",
    "get_design_session",
    "list_design_sessions",
    "reopen_design_session",
    "restore_design_revision",
    "save_design_result",
    "save_design_simulation",
]
