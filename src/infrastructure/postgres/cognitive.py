# =============================================================================
# Cognitive Repository — Postgres (Phase 3)
# =============================================================================
# Runs + tasks + agent_messages del supervisor cognitivo. Scoped estricto por
# organization_id; los mensajes son append-only.
# =============================================================================
from __future__ import annotations

import json
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import text

from src.core.domain.cognitive import (
    AgentMessage,
    AgentMessageType,
    CognitiveRun,
    CognitiveRunStatus,
    CognitiveTask,
    ComplexityLevel,
)
from src.core.ports.cognitive import CognitiveRepository
from src.infrastructure.postgres.session import get_async_session

_RUN_COLUMNS = (
    "id, organization_id, workspace_id, query, complexity, status, budget, "
    "scope, plan, created_by, created_at, updated_at"
)

_TASK_COLUMNS = (
    "id, run_id, organization_id, task_key, description, agent_id, status, "
    "depends_on, position, budget, input_scope, output_contract, result, error, "
    "created_at, updated_at"
)

_MESSAGE_COLUMNS = (
    "id, run_id, organization_id, message_type, from_agent, to_agent, task_key, "
    "text, claim_ids, evidence_ids, confidence, metadata, created_at"
)


class PostgresCognitiveRepository(CognitiveRepository):

    async def create_run(self, run: CognitiveRun) -> CognitiveRun:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"""
                    INSERT INTO cognitive_runs ({_RUN_COLUMNS})
                    VALUES (
                        :id, :organization_id, :workspace_id, :query, :complexity,
                        :status, CAST(:budget AS jsonb), CAST(:scope AS jsonb),
                        CAST(:plan AS jsonb), :created_by, now(), now()
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        status = EXCLUDED.status,
                        plan = EXCLUDED.plan,
                        budget = EXCLUDED.budget,
                        updated_at = now()
                    RETURNING {_RUN_COLUMNS}
                    """
                ),
                {
                    "id": str(run.id),
                    "organization_id": str(run.organization_id),
                    "workspace_id": _uuid_or_none(run.workspace_id),
                    "query": run.query,
                    "complexity": run.complexity.value,
                    "status": run.status.value,
                    "budget": json.dumps(run.budget.to_dict()),
                    "scope": json.dumps(run.scope, default=str),
                    "plan": json.dumps(run.plan, default=str),
                    "created_by": _uuid_or_none(run.created_by),
                },
            )
            row = result.fetchone()
            await session.commit()
            return _row_to_run(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def save_tasks(
        self, *, organization_id: UUID, tasks: Sequence[CognitiveTask]
    ) -> None:
        if not tasks:
            return
        session = await get_async_session()
        try:
            columns = (
                "id, run_id, organization_id, task_key, description, agent_id, "
                "status, depends_on, position, budget, input_scope, "
                "output_contract, result, error"
            )
            placeholders = _placeholder_sql(columns)
            rows = [
                {
                    "id": str(task.id),
                    "run_id": str(task.run_id),
                    "organization_id": str(organization_id),
                    "task_key": task.key,
                    "description": task.description,
                    "agent_id": task.agent_id,
                    "status": task.status.value,
                    "depends_on": json.dumps(list(task.depends_on)),
                    "position": task.position,
                    "budget": json.dumps(
                        task.budget.to_dict() if task.budget else {}
                    ),
                    "input_scope": json.dumps(task.input_scope, default=str),
                    "output_contract": json.dumps(
                        task.output_contract, default=str
                    ),
                    "result": (
                        json.dumps(task.result, default=str)
                        if task.result is not None
                        else None
                    ),
                    "error": task.error,
                }
                for task in tasks
            ]
            await session.execute(
                text(
                    f"INSERT INTO cognitive_tasks ({columns}) "
                    f"VALUES {placeholders} "
                    "ON CONFLICT (run_id, task_key) DO NOTHING"
                ),
                rows,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def get_run(
        self, organization_id: UUID, run_id: UUID
    ) -> dict | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_RUN_COLUMNS} FROM cognitive_runs "
                    "WHERE id = :id AND organization_id = :oid"
                ),
                {"id": str(run_id), "oid": str(organization_id)},
            )
            row = result.fetchone()
            return _row_to_dict(row) if row is not None else None
        finally:
            await session.close()

    async def list_tasks(
        self, organization_id: UUID, run_id: UUID
    ) -> list[dict]:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_TASK_COLUMNS} FROM cognitive_tasks "
                    "WHERE organization_id = :oid AND run_id = :rid "
                    "ORDER BY position, task_key"
                ),
                {"oid": str(organization_id), "rid": str(run_id)},
            )
            return [_row_to_dict(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def append_message(
        self, organization_id: UUID, message: AgentMessage
    ) -> AgentMessage:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"""
                    INSERT INTO agent_messages ({_MESSAGE_COLUMNS})
                    VALUES (
                        :id, :run_id, :organization_id, :message_type,
                        :from_agent, :to_agent, :task_key, :text,
                        CAST(:claim_ids AS uuid[]), CAST(:evidence_ids AS uuid[]),
                        :confidence, CAST(:metadata AS jsonb), now()
                    )
                    RETURNING {_MESSAGE_COLUMNS}
                    """
                ),
                {
                    "id": str(message.id),
                    "run_id": str(message.run_id),
                    "organization_id": str(organization_id),
                    "message_type": message.type.value,
                    "from_agent": message.from_agent,
                    "to_agent": message.to_agent,
                    "task_key": message.task_key,
                    "text": message.text,
                    "claim_ids": [str(c) for c in message.claim_ids],
                    "evidence_ids": [str(e) for e in message.evidence_ids],
                    "confidence": message.confidence,
                    "metadata": json.dumps(message.metadata, default=str),
                },
            )
            row = result.fetchone()
            await session.commit()
            return _row_to_message(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def list_messages(
        self, organization_id: UUID, run_id: UUID, limit: int = 200
    ) -> list[dict]:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_MESSAGE_COLUMNS} FROM agent_messages "
                    "WHERE organization_id = :oid AND run_id = :rid "
                    "ORDER BY created_at, id LIMIT :limit"
                ),
                {"oid": str(organization_id), "rid": str(run_id), "limit": limit},
            )
            return [_row_to_dict(row) for row in result.fetchall()]
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid_or_none(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def _placeholder_sql(columns: str) -> str:
    names = [c.strip() for c in columns.split(",")]
    return "(" + ", ".join(f":{name}" for name in names) + ")"


def _row_to_run(row) -> CognitiveRun:
    return CognitiveRun(
        id=row.id,
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        query=row.query,
        complexity=ComplexityLevel(row.complexity),
        status=CognitiveRunStatus(row.status),
        budget=_budget_from_dict(row.budget),
        scope=row.scope if isinstance(row.scope, dict) else {},
        plan=row.plan if isinstance(row.plan, dict) else {},
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_message(row) -> AgentMessage:
    return AgentMessage(
        id=row.id,
        run_id=row.run_id,
        type=AgentMessageType(row.message_type),
        from_agent=row.from_agent,
        to_agent=row.to_agent,
        task_key=row.task_key,
        text=row.text or "",
        claim_ids=tuple(row.claim_ids or ()),
        evidence_ids=tuple(row.evidence_ids or ()),
        confidence=row.confidence,
        metadata=row.metadata if isinstance(row.metadata, dict) else {},
        created_at=row.created_at,
    )


def _budget_from_dict(value) -> object:
    from src.core.domain.cognitive import CognitiveBudget

    data = value if isinstance(value, dict) else {}
    return CognitiveBudget(
        max_agents=int(data.get("max_agents", 4)),
        max_llm_calls=int(data.get("max_llm_calls", 12)),
        max_tokens=int(data.get("max_tokens", 24000)),
        max_cost_usd=float(data.get("max_cost_usd", 1.0)),
        max_seconds=float(data.get("max_seconds", 120.0)),
        max_tool_calls=int(data.get("max_tool_calls", 20)),
        max_debate_rounds=int(data.get("max_debate_rounds", 0)),
    )


def _row_to_dict(row) -> dict:
    data: dict = {}
    for column in row._mapping.keys():
        value = getattr(row, column)
        if isinstance(value, UUID):
            value = str(value)
        elif hasattr(value, "isoformat"):
            value = value.isoformat()
        data[column] = value
    return data
