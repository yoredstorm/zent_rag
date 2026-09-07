# =============================================================================
# Learning Store — persistencia del ciclo gobernado (FASE 25)
# =============================================================================
# Raw-SQL fail-soft (convención del repo), org-scoped estricto, paginado.
# Tablas creadas por la migración 081 (ensure_tables idempotente).
# =============================================================================
from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.domain.learning import (
    ApprovalRecord,
    ImprovementItem,
    LearningReplay,
    SourceConflictRecord,
    SpiderPolicy,
    SpiderRun,
)
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_CREATE_TABLES = [
    "CREATE TABLE IF NOT EXISTS improvement_items (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), organization_id UUID NOT NULL, priority VARCHAR(12) NOT NULL DEFAULT 'medium', gap_type VARCHAR(40) NOT NULL, title VARCHAR(400) NOT NULL, description TEXT, evidence JSONB NOT NULL DEFAULT '[]'::jsonb, affected_queries INT NOT NULL DEFAULT 0, affected_users INT NOT NULL DEFAULT 0, affected_agents INT NOT NULL DEFAULT 0, affected_sources JSONB NOT NULL DEFAULT '[]'::jsonb, recommended_action TEXT, estimated_impact JSONB NOT NULL DEFAULT '{}'::jsonb, status VARCHAR(20) NOT NULL DEFAULT 'OPEN', owner VARCHAR(120), suggested_concept VARCHAR(160), cluster_key VARCHAR(64), created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), resolved_at TIMESTAMPTZ, UNIQUE (organization_id, gap_type, cluster_key))",
    "CREATE TABLE IF NOT EXISTS approval_records (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), organization_id UUID NOT NULL, knowledge_type VARCHAR(30) NOT NULL, knowledge_id VARCHAR(64) NOT NULL, action VARCHAR(20) NOT NULL, acted_by UUID, reason TEXT, source_evidence JSONB NOT NULL DEFAULT '[]'::jsonb, previous_version JSONB NOT NULL DEFAULT '{}'::jsonb, new_version JSONB NOT NULL DEFAULT '{}'::jsonb, replay_id UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT now())",
    "CREATE TABLE IF NOT EXISTS learning_replays (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), organization_id UUID NOT NULL, knowledge_type VARCHAR(30) NOT NULL, knowledge_id VARCHAR(64) NOT NULL, trigger VARCHAR(10) NOT NULL DEFAULT 'manual', eval_run_id UUID, baseline_run_id UUID, before JSONB NOT NULL DEFAULT '{}'::jsonb, after JSONB NOT NULL DEFAULT '{}'::jsonb, verdict VARCHAR(10) NOT NULL DEFAULT 'unknown', status VARCHAR(12) NOT NULL DEFAULT 'queued', error TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now())",
    "CREATE TABLE IF NOT EXISTS source_conflicts (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), organization_id UUID NOT NULL, concept VARCHAR(160) NOT NULL, question TEXT, source_a VARCHAR(200) NOT NULL, value_a JSONB, source_b VARCHAR(200) NOT NULL, value_b JSONB, resolved_by_authority BOOLEAN NOT NULL DEFAULT false, authority_source VARCHAR(200), status VARCHAR(12) NOT NULL DEFAULT 'recorded', created_at TIMESTAMPTZ NOT NULL DEFAULT now())",
    "CREATE TABLE IF NOT EXISTS spider_policies (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), organization_id UUID NOT NULL, name VARCHAR(150) NOT NULL, enabled BOOLEAN NOT NULL DEFAULT true, schedule_hours INT NOT NULL DEFAULT 24, allowed_source_ids JSONB NOT NULL DEFAULT '[]'::jsonb, allowed_schemas JSONB NOT NULL DEFAULT '[]'::jsonb, excluded_objects JSONB NOT NULL DEFAULT '[]'::jsonb, profiling_level VARCHAR(12) NOT NULL DEFAULT 'standard', max_cost INT NOT NULL DEFAULT 500, max_duration_min INT NOT NULL DEFAULT 60, sampling_policy VARCHAR(14) NOT NULL DEFAULT 'conservative', pii_policy VARCHAR(8) NOT NULL DEFAULT 'never', created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE (organization_id, name))",
    "CREATE TABLE IF NOT EXISTS spider_runs (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), organization_id UUID NOT NULL, policy_id UUID NOT NULL, status VARCHAR(12) NOT NULL DEFAULT 'running', findings JSONB NOT NULL DEFAULT '[]'::jsonb, duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0, error TEXT, started_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ)",
    "CREATE TABLE IF NOT EXISTS agent_readiness (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), organization_id UUID NOT NULL, agent_id UUID NOT NULL, overall VARCHAR(12) NOT NULL DEFAULT 'LOW', score DOUBLE PRECISION NOT NULL DEFAULT 0, dimensions JSONB NOT NULL DEFAULT '{}'::jsonb, computed_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE (organization_id, agent_id))",
]


class PostgresLearningStore:
    """Persistencia del ciclo gobernado (org-scoped, fail-soft)."""

    async def ensure_tables(self) -> None:
        session: AsyncSession = await get_async_session()
        try:
            for stmt in _CREATE_TABLES:
                await session.execute(text(stmt))
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Learning ensure_tables failed", error=str(exc))
        finally:
            await session.close()

    # ------------------------------------------------------------- improvements
    async def upsert_improvement(
        self, item: ImprovementItem, *, dedupe_key: str | None = None
    ) -> UUID:
        """Upsert deduplicado por (org, gap_type, cluster_key)."""
        session: AsyncSession = await get_async_session()
        try:
            existing = None
            if item.cluster_key:
                existing = (
                    await session.execute(
                        text(
                            "SELECT id FROM improvement_items "
                            "WHERE organization_id = :oid AND gap_type = :gtype "
                            "AND cluster_key = :ckey"
                        ),
                        {
                            "oid": item.organization_id,
                            "gtype": item.gap_type,
                            "ckey": item.cluster_key,
                        },
                    )
                ).fetchone()
            if existing:
                await session.execute(
                    text(
                        "UPDATE improvement_items SET affected_queries = "
                        "affected_queries + 1, affected_users = GREATEST("
                        "affected_users, :users), affected_agents = GREATEST("
                        "affected_agents, :agents), evidence = CAST(:evidence AS jsonb), "
                        "estimated_impact = CAST(:impact AS jsonb), status = 'OPEN', "
                        "updated_at = now() WHERE id = :id"
                    ),
                    {
                        "id": existing[0],
                        "users": item.affected_users,
                        "agents": item.affected_agents,
                        "evidence": json.dumps(item.evidence),
                        "impact": json.dumps(item.estimated_impact),
                    },
                )
                await session.commit()
                return UUID(str(existing[0]))
            await session.execute(
                text(
                    "INSERT INTO improvement_items "
                    "(id, organization_id, priority, gap_type, title, description, "
                    "evidence, affected_queries, affected_users, affected_agents, "
                    "affected_sources, recommended_action, estimated_impact, status, "
                    "owner, suggested_concept, cluster_key, created_at, updated_at) "
                    "VALUES (:id, :oid, :priority, :gtype, :title, :description, "
                    "CAST(:evidence AS jsonb), :queries, :users, :agents, "
                    "CAST(:sources AS jsonb), :action, CAST(:impact AS jsonb), "
                    ":status, :owner, :concept, :ckey, now(), now())"
                ),
                {
                    "id": item.id,
                    "oid": item.organization_id,
                    "priority": item.priority.value,
                    "gtype": item.gap_type,
                    "title": item.title,
                    "description": item.description,
                    "evidence": json.dumps(item.evidence),
                    "queries": item.affected_queries,
                    "users": item.affected_users,
                    "agents": item.affected_agents,
                    "sources": json.dumps(item.affected_sources),
                    "action": item.recommended_action,
                    "impact": json.dumps(item.estimated_impact),
                    "status": item.status.value,
                    "owner": item.owner,
                    "concept": item.suggested_concept,
                    "ckey": item.cluster_key,
                },
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Improvement upsert failed", error=str(exc))
        finally:
            await session.close()
        return item.id

    async def list_improvements(
        self,
        organization_id: UUID,
        *,
        status: str | None = None,
        gap_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            query = (
                "SELECT id, priority, gap_type, title, description, evidence, "
                "affected_queries, affected_users, affected_agents, "
                "affected_sources, recommended_action, estimated_impact, status, "
                "owner, suggested_concept, cluster_key, created_at, updated_at, "
                "resolved_at FROM improvement_items WHERE organization_id = :oid "
            )
            params: dict = {"oid": organization_id, "limit": limit, "offset": offset}
            if status:
                query += "AND status = :status "
                params["status"] = status
            if gap_type:
                query += "AND gap_type = :gap_type "
                params["gap_type"] = gap_type
            query += "ORDER BY "
            query += "CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, "
            query += "affected_queries DESC LIMIT :limit OFFSET :offset"
            rows = (await session.execute(text(query), params)).fetchall()
            return [
                {
                    "id": str(r.id),
                    "priority": r.priority,
                    "gap_type": r.gap_type,
                    "title": r.title,
                    "description": r.description,
                    "evidence": r.evidence or [],
                    "affected_queries": r.affected_queries,
                    "affected_users": r.affected_users,
                    "affected_agents": r.affected_agents,
                    "affected_sources": r.affected_sources or [],
                    "recommended_action": r.recommended_action,
                    "estimated_impact": r.estimated_impact or {},
                    "status": r.status,
                    "owner": r.owner,
                    "suggested_concept": r.suggested_concept,
                    "cluster_key": r.cluster_key,
                    "created_at": r.created_at.isoformat(),
                    "updated_at": r.updated_at.isoformat(),
                    "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
                }
                for r in rows
            ]
        finally:
            await session.close()

    async def get_improvement(
        self, organization_id: UUID, item_id: UUID
    ) -> dict | None:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT id, priority, gap_type, title, description, evidence, "
                        "affected_queries, affected_users, affected_agents, "
                        "affected_sources, recommended_action, estimated_impact, status, "
                        "owner, suggested_concept, cluster_key, created_at, updated_at, "
                        "resolved_at FROM improvement_items "
                        "WHERE organization_id = :oid AND id = :id"
                    ),
                    {"oid": organization_id, "id": item_id},
                )
            ).fetchone()
            return self._improvement_row(row) if row else None
        finally:
            await session.close()

    @staticmethod
    def _improvement_row(row) -> dict:
        return {
            "id": str(row.id),
            "priority": row.priority,
            "gap_type": row.gap_type,
            "title": row.title,
            "description": row.description,
            "evidence": row.evidence or [],
            "affected_queries": row.affected_queries,
            "affected_users": row.affected_users,
            "affected_agents": row.affected_agents,
            "affected_sources": row.affected_sources or [],
            "recommended_action": row.recommended_action,
            "estimated_impact": row.estimated_impact or {},
            "status": row.status,
            "owner": row.owner,
            "suggested_concept": row.suggested_concept,
            "cluster_key": row.cluster_key,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
            "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        }

    async def update_improvement_status(
        self,
        organization_id: UUID,
        item_id: UUID,
        *,
        status: str,
        owner: str | None = None,
        priority: str | None = None,
        resolved_by: UUID | None = None,
    ) -> bool:
        session: AsyncSession = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "UPDATE improvement_items SET status = :status, "
                    "owner = COALESCE(:owner, owner), "
                    "priority = COALESCE(:priority, priority), "
                    "resolved_at = CASE WHEN :terminal THEN now() "
                    "ELSE resolved_at END, updated_at = now() "
                    "WHERE organization_id = :oid AND id = :id"
                ),
                {
                    "status": status,
                    "owner": owner,
                    "priority": priority,
                    "terminal": status == "RESOLVED",
                    "oid": organization_id,
                    "id": item_id,
                },
            )
            await session.commit()
            return (result.rowcount or 0) > 0
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Improvement status update failed", error=str(exc))
            return False
        finally:
            await session.close()

    # ----------------------------------------------------------- approval_records
    async def add_approval_record(self, record: ApprovalRecord) -> UUID:
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO approval_records "
                    "(id, organization_id, knowledge_type, knowledge_id, action, "
                    "acted_by, reason, source_evidence, previous_version, "
                    "new_version, replay_id, created_at) "
                    "VALUES (:id, :oid, :ktype, :kid, :action, :acted_by, :reason, "
                    "CAST(:evidence AS jsonb), CAST(:previous AS jsonb), "
                    "CAST(:new AS jsonb), :replay_id, now())"
                ),
                {
                    "id": record.id,
                    "oid": record.organization_id,
                    "ktype": record.knowledge_type,
                    "kid": str(record.knowledge_id),
                    "action": record.action.value,
                    "acted_by": record.acted_by,
                    "reason": record.reason,
                    "evidence": json.dumps(record.source_evidence),
                    "previous": json.dumps(record.previous_version),
                    "new": json.dumps(record.new_version),
                    "replay_id": record.replay_id,
                },
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Approval record add failed", error=str(exc))
        finally:
            await session.close()
        return record.id

    async def list_approval_records(
        self,
        organization_id: UUID,
        *,
        knowledge_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            query = (
                "SELECT id, knowledge_type, knowledge_id, action, acted_by, "
                "reason, source_evidence, previous_version, new_version, "
                "replay_id, created_at FROM approval_records "
                "WHERE organization_id = :oid "
            )
            params: dict = {"oid": organization_id, "limit": limit, "offset": offset}
            if knowledge_type:
                query += "AND knowledge_type = :ktype "
                params["ktype"] = knowledge_type
            query += "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            rows = (await session.execute(text(query), params)).fetchall()
            return [
                {
                    "id": str(r.id),
                    "knowledge_type": r.knowledge_type,
                    "knowledge_id": r.knowledge_id,
                    "action": r.action,
                    "acted_by": str(r.acted_by) if r.acted_by else None,
                    "reason": r.reason,
                    "source_evidence": r.source_evidence or [],
                    "previous_version": r.previous_version or {},
                    "new_version": r.new_version or {},
                    "replay_id": str(r.replay_id) if r.replay_id else None,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ]
        finally:
            await session.close()

    # --------------------------------------------------------------- replays
    async def create_replay(self, replay: LearningReplay) -> UUID:
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO learning_replays "
                    "(id, organization_id, knowledge_type, knowledge_id, trigger, "
                    "eval_run_id, baseline_run_id, before, after, verdict, status, "
                    "error, created_at) "
                    "VALUES (:id, :oid, :ktype, :kid, :trigger, :eval_run, "
                    ":baseline, CAST(:before AS jsonb), CAST(:after AS jsonb), "
                    ":verdict, :status, :error, now())"
                ),
                {
                    "id": replay.id,
                    "oid": replay.organization_id,
                    "ktype": replay.knowledge_type,
                    "kid": str(replay.knowledge_id),
                    "trigger": replay.trigger,
                    "eval_run": replay.eval_run_id,
                    "baseline": replay.baseline_run_id,
                    "before": json.dumps(replay.before),
                    "after": json.dumps(replay.after),
                    "verdict": replay.verdict.value,
                    "status": replay.status,
                    "error": replay.error,
                },
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Replay create failed", error=str(exc))
        finally:
            await session.close()
        return replay.id

    async def update_replay(
        self,
        replay_id: UUID,
        *,
        status: str,
        verdict: str | None = None,
        eval_run_id: UUID | None = None,
        before: dict | None = None,
        after: dict | None = None,
        error: str | None = None,
    ) -> None:
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE learning_replays SET status = :status, "
                    "verdict = COALESCE(:verdict, verdict), "
                    "eval_run_id = COALESCE(:eval_run, eval_run_id), "
                    "before = COALESCE(CAST(:before AS jsonb), before), "
                    "after = COALESCE(CAST(:after AS jsonb), after), "
                    "error = COALESCE(:error, error) WHERE id = :id"
                ),
                {
                    "status": status,
                    "verdict": verdict,
                    "eval_run": eval_run_id,
                    "before": json.dumps(before) if before else None,
                    "after": json.dumps(after) if after else None,
                    "error": error,
                    "id": replay_id,
                },
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Replay update failed", error=str(exc))
        finally:
            await session.close()

    async def list_replays(
        self,
        organization_id: UUID,
        *,
        knowledge_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            query = (
                "SELECT id, organization_id, knowledge_type, knowledge_id, trigger, "
                "eval_run_id, baseline_run_id, before, after, verdict, status, "
                "error, created_at FROM learning_replays WHERE organization_id = :oid "
            )
            params: dict = {"oid": organization_id, "limit": limit, "offset": offset}
            if knowledge_type:
                query += "AND knowledge_type = :ktype "
                params["ktype"] = knowledge_type
            query += "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            rows = (await session.execute(text(query), params)).fetchall()
            return [
                {
                    "id": str(r.id),
                    "knowledge_type": r.knowledge_type,
                    "knowledge_id": r.knowledge_id,
                    "trigger": r.trigger,
                    "eval_run_id": str(r.eval_run_id) if r.eval_run_id else None,
                    "baseline_run_id": str(r.baseline_run_id) if r.baseline_run_id else None,
                    "before": r.before or {},
                    "after": r.after or {},
                    "verdict": r.verdict,
                    "status": r.status,
                    "error": r.error,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ]
        finally:
            await session.close()

    async def get_replay(self, replay_id: UUID) -> dict | None:
        """Replay por id (worker: contexto de sistema, sin filtro de org)."""
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT id, organization_id, knowledge_type, knowledge_id, "
                        "trigger, eval_run_id, baseline_run_id, before, after, "
                        "verdict, status, error, created_at FROM learning_replays "
                        "WHERE id = :id"
                    ),
                    {"id": replay_id},
                )
            ).fetchone()
            if row is None:
                return None
            return {
                "id": str(row.id),
                "organization_id": str(row.organization_id),
                "knowledge_type": row.knowledge_type,
                "knowledge_id": row.knowledge_id,
                "trigger": row.trigger,
                "eval_run_id": str(row.eval_run_id) if row.eval_run_id else None,
                "baseline_run_id": str(row.baseline_run_id) if row.baseline_run_id else None,
                "before": row.before or {},
                "after": row.after or {},
                "verdict": row.verdict,
                "status": row.status,
                "error": row.error,
                "created_at": row.created_at.isoformat(),
            }
        finally:
            await session.close()

    # -------------------------------------------------------------- conflicts
    async def record_source_conflict(
        self, conflict: SourceConflictRecord
    ) -> UUID:
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO source_conflicts "
                    "(id, organization_id, concept, question, source_a, value_a, "
                    "source_b, value_b, resolved_by_authority, authority_source, "
                    "status, created_at) "
                    "VALUES (:id, :oid, :concept, :question, :source_a, "
                    "CAST(:value_a AS jsonb), :source_b, CAST(:value_b AS jsonb), "
                    ":resolved, :authority, :status, now())"
                ),
                {
                    "id": conflict.id,
                    "oid": conflict.organization_id,
                    "concept": conflict.concept,
                    "question": conflict.question,
                    "source_a": conflict.source_a,
                    "value_a": json.dumps(conflict.value_a) if conflict.value_a is not None else None,
                    "source_b": conflict.source_b,
                    "value_b": json.dumps(conflict.value_b) if conflict.value_b is not None else None,
                    "resolved": conflict.resolved_by_authority,
                    "authority": conflict.authority_source,
                    "status": conflict.status,
                },
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Source conflict record failed", error=str(exc))
        finally:
            await session.close()
        return conflict.id

    async def list_source_conflicts(
        self, organization_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, concept, question, source_a, value_a, source_b, "
                        "value_b, resolved_by_authority, authority_source, status, "
                        "created_at FROM source_conflicts "
                        "WHERE organization_id = :oid "
                        "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
                    ),
                    {"oid": organization_id, "limit": limit, "offset": offset},
                )
            ).fetchall()
            return [
                {
                    "id": str(r.id),
                    "concept": r.concept,
                    "question": r.question,
                    "source_a": r.source_a,
                    "value_a": r.value_a,
                    "source_b": r.source_b,
                    "value_b": r.value_b,
                    "resolved_by_authority": r.resolved_by_authority,
                    "authority_source": r.authority_source,
                    "status": r.status,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ]
        finally:
            await session.close()

    # ------------------------------------------------------------------ spider
    async def upsert_spider_policy(self, policy: SpiderPolicy) -> UUID:
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO spider_policies "
                    "(id, organization_id, name, enabled, schedule_hours, "
                    "allowed_source_ids, allowed_schemas, excluded_objects, "
                    "profiling_level, max_cost, max_duration_min, sampling_policy, "
                    "pii_policy, created_by, created_at, updated_at) "
                    "VALUES (:id, :oid, :name, :enabled, :hours, "
                    "CAST(:source_ids AS jsonb), CAST(:schemas AS jsonb), "
                    "CAST(:excluded AS jsonb), :profiling, :cost, :duration, "
                    ":sampling, :pii, :created_by, now(), now()) "
                    "ON CONFLICT (organization_id, name) DO UPDATE SET "
                    "enabled = EXCLUDED.enabled, "
                    "schedule_hours = EXCLUDED.schedule_hours, "
                    "allowed_source_ids = EXCLUDED.allowed_source_ids, "
                    "allowed_schemas = EXCLUDED.allowed_schemas, "
                    "excluded_objects = EXCLUDED.excluded_objects, "
                    "profiling_level = EXCLUDED.profiling_level, "
                    "max_cost = EXCLUDED.max_cost, "
                    "max_duration_min = EXCLUDED.max_duration_min, "
                    "sampling_policy = EXCLUDED.sampling_policy, "
                    "pii_policy = EXCLUDED.pii_policy, "
                    "updated_at = now()"
                ),
                {
                    "id": policy.id,
                    "oid": policy.organization_id,
                    "name": policy.name,
                    "enabled": policy.enabled,
                    "hours": policy.schedule_hours,
                    "source_ids": json.dumps(policy.allowed_source_ids),
                    "schemas": json.dumps(policy.allowed_schemas),
                    "excluded": json.dumps(policy.excluded_objects),
                    "profiling": policy.profiling_level,
                    "cost": policy.max_cost,
                    "duration": policy.max_duration_min,
                    "sampling": policy.sampling_policy,
                    "pii": policy.pii_policy,
                    "created_by": policy.created_by,
                },
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Spider policy upsert failed", error=str(exc))
        finally:
            await session.close()
        return policy.id

    async def list_spider_policies(
        self, organization_id: UUID
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, name, enabled, schedule_hours, "
                        "allowed_source_ids, allowed_schemas, excluded_objects, "
                        "profiling_level, max_cost, max_duration_min, sampling_policy, "
                        "pii_policy, created_by, created_at, updated_at "
                        "FROM spider_policies WHERE organization_id = :oid "
                        "ORDER BY name"
                    ),
                    {"oid": organization_id},
                )
            ).fetchall()
            return [
                {
                    "id": str(r.id),
                    "name": r.name,
                    "enabled": r.enabled,
                    "schedule_hours": r.schedule_hours,
                    "allowed_source_ids": r.allowed_source_ids or [],
                    "allowed_schemas": r.allowed_schemas or [],
                    "excluded_objects": r.excluded_objects or [],
                    "profiling_level": r.profiling_level,
                    "max_cost": r.max_cost,
                    "max_duration_min": r.max_duration_min,
                    "sampling_policy": r.sampling_policy,
                    "pii_policy": r.pii_policy,
                    "created_by": str(r.created_by) if r.created_by else None,
                    "created_at": r.created_at.isoformat(),
                    "updated_at": r.updated_at.isoformat(),
                }
                for r in rows
            ]
        finally:
            await session.close()

    async def list_due_spider_policies(
        self, now: datetime, limit: int = 10
    ) -> list[dict]:
        """Políticas habilitadas con última ejecución vencida (por schedule)."""
        session: AsyncSession = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT p.id, p.organization_id, p.schedule_hours, "
                        "COALESCE(MAX(r.started_at), 'epoch'::timestamptz) AS last_run "
                        "FROM spider_policies p "
                        "LEFT JOIN spider_runs r ON r.policy_id = p.id "
                        "WHERE p.enabled = true "
                        "GROUP BY p.id, p.organization_id, p.schedule_hours "
                        "HAVING COALESCE(MAX(r.started_at), 'epoch'::timestamptz) "
                        "<= now() - make_interval(hours => p.schedule_hours) "
                        "ORDER BY last_run LIMIT :limit"
                    ),
                    {"limit": limit},
                )
            ).fetchall()
            return [
                {
                    "id": str(r.id),
                    "organization_id": str(r.organization_id),
                    "schedule_hours": r.schedule_hours,
                }
                for r in rows
            ]
        finally:
            await session.close()

    async def create_spider_run(self, run: SpiderRun) -> UUID:
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO spider_runs "
                    "(id, organization_id, policy_id, status, findings, "
                    "duration_ms, error, started_at, finished_at) "
                    "VALUES (:id, :oid, :policy, :status, CAST(:findings AS jsonb), "
                    ":duration, :error, now(), :finished)"
                ),
                {
                    "id": run.id,
                    "oid": run.organization_id,
                    "policy": run.policy_id,
                    "status": run.status,
                    "findings": json.dumps(run.findings),
                    "duration": run.duration_ms,
                    "error": run.error,
                    "finished": run.finished_at,
                },
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Spider run create failed", error=str(exc))
        finally:
            await session.close()
        return run.id

    async def update_spider_run(
        self,
        run_id: UUID,
        *,
        status: str,
        findings: list[dict] | None = None,
        duration_ms: float | None = None,
        error: str | None = None,
    ) -> None:
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE spider_runs SET status = :status, "
                    "findings = COALESCE(CAST(:findings AS jsonb), findings), "
                    "duration_ms = COALESCE(:duration, duration_ms), "
                    "error = COALESCE(:error, error), "
                    "finished_at = CASE WHEN :status IN "
                    "('completed','failed','cancelled') THEN now() ELSE finished_at END "
                    "WHERE id = :id"
                ),
                {
                    "status": status,
                    "findings": json.dumps(findings or []),
                    "duration": duration_ms,
                    "error": error,
                    "id": run_id,
                },
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Spider run update failed", error=str(exc))
        finally:
            await session.close()

    async def list_spider_runs(
        self, organization_id: UUID, *, limit: int = 20, offset: int = 0
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, policy_id, status, findings, duration_ms, error, "
                        "started_at, finished_at FROM spider_runs "
                        "WHERE organization_id = :oid "
                        "ORDER BY started_at DESC LIMIT :limit OFFSET :offset"
                    ),
                    {"oid": organization_id, "limit": limit, "offset": offset},
                )
            ).fetchall()
            return [
                {
                    "id": str(r.id),
                    "policy_id": str(r.policy_id),
                    "status": r.status,
                    "findings": r.findings or [],
                    "duration_ms": r.duration_ms,
                    "error": r.error,
                    "started_at": r.started_at.isoformat(),
                    "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                }
                for r in rows
            ]
        finally:
            await session.close()

    # --------------------------------------------------------- agent readiness
    async def save_agent_readiness(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID,
        overall: str,
        score: float,
        dimensions: dict,
    ) -> None:
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO agent_readiness "
                    "(organization_id, agent_id, overall, score, dimensions, computed_at) "
                    "VALUES (:oid, :agent, :overall, :score, CAST(:dimensions AS jsonb), now()) "
                    "ON CONFLICT (organization_id, agent_id) DO UPDATE SET "
                    "overall = EXCLUDED.overall, score = EXCLUDED.score, "
                    "dimensions = EXCLUDED.dimensions, computed_at = now()"
                ),
                {
                    "oid": organization_id,
                    "agent": agent_id,
                    "overall": overall,
                    "score": score,
                    "dimensions": json.dumps(dimensions),
                },
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Agent readiness save failed", error=str(exc))
        finally:
            await session.close()

    async def get_agent_readiness(
        self, organization_id: UUID, agent_id: UUID
    ) -> dict | None:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT agent_id, overall, score, dimensions, computed_at "
                        "FROM agent_readiness "
                        "WHERE organization_id = :oid AND agent_id = :agent"
                    ),
                    {"oid": organization_id, "agent": agent_id},
                )
            ).fetchone()
            if row is None:
                return None
            return {
                "agent_id": str(row.agent_id),
                "overall": row.overall,
                "score": row.score,
                "dimensions": row.dimensions or {},
                "computed_at": row.computed_at.isoformat(),
            }
        finally:
            await session.close()
