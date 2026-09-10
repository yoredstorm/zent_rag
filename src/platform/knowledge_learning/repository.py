# =============================================================================
# Knowledge Learning Repository — persistencia del Learning Engine (FASE 33)
# =============================================================================
# Raw-SQL fail-soft (convención del repo), org-scoped estricto.
# Tablas creadas por la migración 094 (ensure_tables es idempotente para dev).
#
# Aislamiento multi-tenant: TODA lectura/escritura filtra organization_id.
# =============================================================================
from __future__ import annotations

import json
import re
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.domain.knowledge_learning import QuestionStatus
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_RUN_COLS = (
    "id, organization_id, workspace_id, catalog_source_id, kb_source_id, "
    "training_run_id, trigger, status, current_stage, overall_progress, "
    "stage_progress, gate, tables_analyzed, entities_detected, fields_detected, "
    "relationships_detected, metrics, error_summary, created_by, created_at, "
    "started_at, finished_at, updated_at"
)

_STEP_COLS = (
    "id, organization_id, run_id, stage, sequence, status, progress, metrics, "
    "error, started_at, finished_at, duration_ms, created_at"
)

_EVENT_COLS = (
    "id, seq, organization_id, run_id, source_id, event_type, stage, category, "
    "severity, message, payload, created_at"
)

_LLM_ANALYSIS_COLS = (
    "id, organization_id, source_id, run_id, table_id, schema_fingerprint, "
    "prompt_version, model, status, context_digest, context_meta, result, "
    "reasoning_summary, confidence, tokens_input, tokens_output, latency_ms, "
    "estimated_cost, error, created_at, updated_at"
)

_RULE_COLS = (
    "id, organization_id, rule_key, name, definition, applies_to, provenance, "
    "confidence, source, suggestion_id, created_by, approved_by, "
    "last_learned_at, learned_run_id, created_at, updated_at"
)

_QUESTION_COLS = (
    "id, organization_id, source_id, run_id, catalog_table_id, entity_id, "
    "field_id, column_id, relationship_id, question_key, question_type, title, "
    "body, evidence, options, answer_schema, priority, priority_score, impact, "
    "status, answer, structured_answer, answered_by, answered_at, "
    "confidence_before, confidence_after, created_at, updated_at"
)

_FEEDBACK_COLS = (
    "id, organization_id, question_id, run_id, source_id, knowledge_type, "
    "knowledge_id, question, answer, structured_answer, source, applied, "
    "applied_to, created_by, created_at"
)


def _rule_key(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return (slug or "rule")[:200]

_ACTIVE_STATUSES = ("queued", "running", "awaiting_validation")

_CREATE_TABLES = [
    # Espejo idempotente de la migración 094 (dev/test sin alembic).
    """CREATE TABLE IF NOT EXISTS knowledge_learning_runs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        workspace_id UUID,
        catalog_source_id UUID,
        kb_source_id UUID,
        training_run_id UUID,
        trigger VARCHAR(20) NOT NULL DEFAULT 'manual',
        status VARCHAR(24) NOT NULL DEFAULT 'queued',
        current_stage VARCHAR(30) NOT NULL DEFAULT 'connecting',
        overall_progress INT NOT NULL DEFAULT 0,
        stage_progress INT NOT NULL DEFAULT 0,
        gate VARCHAR(16),
        tables_analyzed INT NOT NULL DEFAULT 0,
        entities_detected INT NOT NULL DEFAULT 0,
        fields_detected INT NOT NULL DEFAULT 0,
        relationships_detected INT NOT NULL DEFAULT 0,
        metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
        error_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_by UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        started_at TIMESTAMPTZ,
        finished_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS knowledge_learning_steps (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        run_id UUID NOT NULL,
        stage VARCHAR(30) NOT NULL,
        sequence INT NOT NULL DEFAULT 0,
        status VARCHAR(12) NOT NULL DEFAULT 'pending',
        progress INT NOT NULL DEFAULT 0,
        metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
        error TEXT,
        started_at TIMESTAMPTZ,
        finished_at TIMESTAMPTZ,
        duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (run_id, stage)
    )""",
    """CREATE TABLE IF NOT EXISTS knowledge_events (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        seq BIGSERIAL NOT NULL,
        organization_id UUID NOT NULL,
        run_id UUID,
        source_id UUID,
        event_type VARCHAR(60) NOT NULL,
        stage VARCHAR(30),
        category VARCHAR(20) NOT NULL DEFAULT 'system',
        severity VARCHAR(10) NOT NULL DEFAULT 'info',
        message TEXT NOT NULL DEFAULT '',
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS knowledge_scores (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        scope_key VARCHAR(80) NOT NULL DEFAULT 'organization',
        source_id UUID,
        run_id UUID,
        overall DOUBLE PRECISION NOT NULL DEFAULT 0,
        gate VARCHAR(16) NOT NULL DEFAULT 'NOT_READY',
        dimensions JSONB NOT NULL DEFAULT '[]'::jsonb,
        reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
        weights JSONB NOT NULL DEFAULT '{}'::jsonb,
        computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (organization_id, scope_key)
    )""",
    """CREATE TABLE IF NOT EXISTS knowledge_learning_settings (
        organization_id UUID PRIMARY KEY,
        weights JSONB NOT NULL DEFAULT '{}'::jsonb,
        thresholds JSONB NOT NULL DEFAULT '{}'::jsonb,
        updated_by UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS knowledge_business_rules (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        rule_key VARCHAR(200) NOT NULL,
        name VARCHAR(200) NOT NULL,
        definition TEXT NOT NULL,
        applies_to JSONB NOT NULL DEFAULT '[]'::jsonb,
        provenance VARCHAR(20) NOT NULL DEFAULT 'INFERRED',
        confidence VARCHAR(10) NOT NULL DEFAULT 'medium',
        source VARCHAR(40) NOT NULL DEFAULT 'llm',
        suggestion_id UUID,
        created_by UUID,
        approved_by UUID,
        last_learned_at TIMESTAMPTZ,
        learned_run_id UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (organization_id, rule_key)
    )""",
    """CREATE TABLE IF NOT EXISTS knowledge_llm_analyses (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        source_id UUID,
        run_id UUID,
        table_id UUID,
        schema_fingerprint VARCHAR(64) NOT NULL,
        prompt_version VARCHAR(20) NOT NULL DEFAULT 'kl-v1',
        model VARCHAR(120) NOT NULL DEFAULT '',
        status VARCHAR(12) NOT NULL DEFAULT 'completed',
        context_digest VARCHAR(64) NOT NULL DEFAULT '',
        context_meta JSONB NOT NULL DEFAULT '{}'::jsonb,
        result JSONB NOT NULL DEFAULT '{}'::jsonb,
        reasoning_summary TEXT,
        confidence DOUBLE PRECISION,
        tokens_input INT NOT NULL DEFAULT 0,
        tokens_output INT NOT NULL DEFAULT 0,
        latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
        estimated_cost DOUBLE PRECISION NOT NULL DEFAULT 0,
        error TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (organization_id, table_id, schema_fingerprint, prompt_version, model)
    )""",
    """CREATE TABLE IF NOT EXISTS knowledge_questions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        source_id UUID,
        run_id UUID,
        catalog_table_id UUID,
        entity_id UUID,
        field_id UUID,
        column_id UUID,
        relationship_id UUID,
        question_key VARCHAR(200) NOT NULL,
        question_type VARCHAR(30) NOT NULL DEFAULT 'other',
        title TEXT NOT NULL,
        body TEXT NOT NULL DEFAULT '',
        evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
        options JSONB NOT NULL DEFAULT '[]'::jsonb,
        answer_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
        priority VARCHAR(10) NOT NULL DEFAULT 'medium',
        priority_score DOUBLE PRECISION NOT NULL DEFAULT 0,
        impact JSONB NOT NULL DEFAULT '{}'::jsonb,
        status VARCHAR(12) NOT NULL DEFAULT 'pending',
        answer JSONB NOT NULL DEFAULT '{}'::jsonb,
        structured_answer JSONB NOT NULL DEFAULT '{}'::jsonb,
        answered_by UUID,
        answered_at TIMESTAMPTZ,
        confidence_before DOUBLE PRECISION,
        confidence_after DOUBLE PRECISION,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (organization_id, question_key)
    )""",
    """CREATE TABLE IF NOT EXISTS knowledge_feedback (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        question_id UUID,
        run_id UUID,
        source_id UUID,
        knowledge_type VARCHAR(40) NOT NULL DEFAULT 'question',
        knowledge_id VARCHAR(80),
        question TEXT NOT NULL DEFAULT '',
        answer TEXT NOT NULL DEFAULT '',
        structured_answer JSONB NOT NULL DEFAULT '{}'::jsonb,
        source VARCHAR(40) NOT NULL DEFAULT 'question',
        applied BOOLEAN NOT NULL DEFAULT false,
        applied_to JSONB NOT NULL DEFAULT '[]'::jsonb,
        created_by UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
]

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_knowledge_learning_runs_org_created "
    "ON knowledge_learning_runs(organization_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_learning_runs_org_source_status "
    "ON knowledge_learning_runs(organization_id, catalog_source_id, status)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_learning_active_run "
    "ON knowledge_learning_runs(organization_id, catalog_source_id) "
    "WHERE status IN ('queued','running','awaiting_validation')",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_learning_steps_run "
    "ON knowledge_learning_steps(run_id, sequence)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_events_seq ON knowledge_events(seq)",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_events_org_created "
    "ON knowledge_events(organization_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_events_org_run_seq "
    "ON knowledge_events(organization_id, run_id, seq)",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_events_org_category "
    "ON knowledge_events(organization_id, category, seq DESC)",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_scores_org_source "
    "ON knowledge_scores(organization_id, source_id)",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_llm_analyses_org_run "
    "ON knowledge_llm_analyses(organization_id, run_id)",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_llm_analyses_org_source "
    "ON knowledge_llm_analyses(organization_id, source_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_llm_analyses_org_table "
    "ON knowledge_llm_analyses(organization_id, table_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_business_rules_org_status "
    "ON knowledge_business_rules(organization_id, provenance, confidence)",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_questions_org_status_priority "
    "ON knowledge_questions(organization_id, status, priority)",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_questions_org_run "
    "ON knowledge_questions(organization_id, run_id)",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_feedback_org_created "
    "ON knowledge_feedback(organization_id, created_at DESC)",
]


class ActiveRunExistsError(RuntimeError):
    """Ya existe un run activo para la misma organización/fuente."""


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class PostgresKnowledgeLearningRepository:
    """Persistencia del Learning Engine (org-scoped, fail-soft)."""

    # -------------------------------------------------------------- lifecycle
    async def ensure_tables(self) -> None:
        session: AsyncSession = await get_async_session()
        try:
            for stmt in _CREATE_TABLES:
                await session.execute(text(stmt))
            for stmt in _CREATE_INDEXES:
                try:
                    await session.execute(text(stmt))
                except Exception as exc:  # noqa: BLE001
                    await session.rollback()
                    logger.warning("Knowledge learning index skipped", error=str(exc)[:200])
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Knowledge learning ensure_tables failed", error=str(exc))
        finally:
            await session.close()

    # -------------------------------------------------------------------- runs
    async def create_run(
        self,
        organization_id: UUID,
        *,
        catalog_source_id: UUID | None = None,
        workspace_id: UUID | None = None,
        kb_source_id: UUID | None = None,
        training_run_id: UUID | None = None,
        trigger: str = "manual",
        created_by: UUID | None = None,
    ) -> dict:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        f"INSERT INTO knowledge_learning_runs (id, organization_id, "
                        f"workspace_id, catalog_source_id, kb_source_id, training_run_id, "
                        f"trigger, status, current_stage, created_by) "
                        f"VALUES (uuid_generate_v4(), :oid, :wid, :sid, :kid, :tid, "
                        f":trigger, 'queued', 'connecting', :by) "
                        f"RETURNING {_RUN_COLS}"  # noqa: S608 — cols constantes
                    ),
                    {
                        "oid": organization_id,
                        "wid": workspace_id,
                        "sid": catalog_source_id,
                        "kid": kb_source_id,
                        "tid": training_run_id,
                        "trigger": trigger,
                        "by": created_by,
                    },
                )
            ).fetchone()
            await session.commit()
            return self._run_row(row)
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            if "uq_knowledge_learning_active_run" in str(exc):
                raise ActiveRunExistsError(str(catalog_source_id)) from exc
            logger.warning("Knowledge learning run create failed", error=str(exc))
            raise
        finally:
            await session.close()

    async def get_run(self, organization_id: UUID, run_id: UUID) -> dict | None:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        f"SELECT {_RUN_COLS} FROM knowledge_learning_runs "
                        "WHERE organization_id = :oid AND id = :rid"  # noqa: S608
                    ),
                    {"oid": organization_id, "rid": run_id},
                )
            ).fetchone()
            return self._run_row(row) if row else None
        finally:
            await session.close()

    async def list_runs(
        self,
        organization_id: UUID,
        *,
        catalog_source_id: UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            query = (
                f"SELECT {_RUN_COLS} FROM knowledge_learning_runs "
                "WHERE organization_id = :oid"  # noqa: S608
            )
            params: dict = {"oid": organization_id, "limit": limit, "offset": offset}
            if catalog_source_id is not None:
                query += " AND catalog_source_id = :sid"
                params["sid"] = catalog_source_id
            if status:
                query += " AND status = :status"
                params["status"] = status
            query += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            rows = (await session.execute(text(query), params)).fetchall()
            return [self._run_row(r) for r in rows]
        finally:
            await session.close()

    async def list_active_runs(self, organization_id: UUID, limit: int = 20) -> list[dict]:
        """Runs activos de la organización (cualquier fuente)."""
        active_literal = ",".join(f"'{s}'" for s in _ACTIVE_STATUSES)
        session: AsyncSession = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        f"SELECT {_RUN_COLS} FROM knowledge_learning_runs "
                        f"WHERE organization_id = :oid AND status IN ({active_literal}) "
                        "ORDER BY created_at DESC LIMIT :limit"  # noqa: S608
                    ),
                    {"oid": organization_id, "limit": limit},
                )
            ).fetchall()
            return [self._run_row(r) for r in rows]
        finally:
            await session.close()

    async def find_active_run(
        self, organization_id: UUID, catalog_source_id: UUID | None = None
    ) -> dict | None:
        session: AsyncSession = await get_async_session()
        try:
            active_literal = ",".join(f"'{s}'" for s in _ACTIVE_STATUSES)
            query = (
                f"SELECT {_RUN_COLS} FROM knowledge_learning_runs "
                f"WHERE organization_id = :oid AND status IN ({active_literal})"  # noqa: S608
            )
            params: dict = {"oid": organization_id}
            if catalog_source_id is None:
                query += " AND catalog_source_id IS NULL"
            else:
                query += " AND catalog_source_id = :sid"
                params["sid"] = catalog_source_id
            query += " ORDER BY created_at DESC LIMIT 1"
            row = (await session.execute(text(query), params)).fetchone()
            return self._run_row(row) if row else None
        finally:
            await session.close()

    async def update_run(self, organization_id: UUID, run_id: UUID, **fields) -> bool:
        allowed = {
            "status",
            "current_stage",
            "overall_progress",
            "stage_progress",
            "gate",
            "tables_analyzed",
            "entities_detected",
            "fields_detected",
            "relationships_detected",
            "metrics",
            "error_summary",
            "started_at",
            "finished_at",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        session: AsyncSession = await get_async_session()
        try:
            set_parts: list[str] = []
            params: dict = {"oid": organization_id, "rid": run_id}
            for key, value in updates.items():
                set_parts.append(f"{key} = :{key}")
                if key in ("metrics", "error_summary"):
                    params[key] = json.dumps(value or {})
                else:
                    params[key] = value
            set_parts.append("updated_at = now()")
            result = await session.execute(
                text(
                    f"UPDATE knowledge_learning_runs SET {', '.join(set_parts)} "
                    "WHERE organization_id = :oid AND id = :rid"  # noqa: S608
                ),
                params,
            )
            await session.commit()
            return (result.rowcount or 0) > 0
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Knowledge learning run update failed", error=str(exc))
            raise
        finally:
            await session.close()

    # ------------------------------------------------------------------- steps
    async def create_steps(
        self, organization_id: UUID, run_id: UUID, stages: list[str]
    ) -> None:
        if not stages:
            return
        session: AsyncSession = await get_async_session()
        try:
            for sequence, stage in enumerate(stages):
                await session.execute(
                    text(
                        "INSERT INTO knowledge_learning_steps "
                        "(id, organization_id, run_id, stage, sequence, status) "
                        "VALUES (uuid_generate_v4(), :oid, :rid, :stage, :seq, 'pending') "
                        "ON CONFLICT (run_id, stage) DO NOTHING"
                    ),
                    {
                        "oid": organization_id,
                        "rid": run_id,
                        "stage": stage,
                        "seq": sequence,
                    },
                )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Knowledge learning steps create failed", error=str(exc))
            raise
        finally:
            await session.close()

    async def list_steps(self, organization_id: UUID, run_id: UUID) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        f"SELECT {_STEP_COLS} FROM knowledge_learning_steps "
                        "WHERE organization_id = :oid AND run_id = :rid "
                        "ORDER BY sequence"  # noqa: S608
                    ),
                    {"oid": organization_id, "rid": run_id},
                )
            ).fetchall()
            return [self._step_row(r) for r in rows]
        finally:
            await session.close()

    async def start_step(
        self,
        organization_id: UUID,
        run_id: UUID,
        stage: str,
        *,
        reset: bool = False,
    ) -> None:
        session: AsyncSession = await get_async_session()
        try:
            guard = "" if reset else " AND status <> 'completed'"
            await session.execute(
                text(
                    "UPDATE knowledge_learning_steps SET status = 'running', "
                    "started_at = COALESCE(started_at, now()), error = NULL "
                    "WHERE organization_id = :oid AND run_id = :rid AND stage = :stage "
                    f"{guard}"  # noqa: S608 — guard constante interna
                ),
                {"oid": organization_id, "rid": run_id, "stage": stage},
            )
            await session.commit()
        finally:
            await session.close()

    async def complete_step(
        self,
        organization_id: UUID,
        run_id: UUID,
        stage: str,
        *,
        metrics: dict | None = None,
        progress: int = 100,
    ) -> None:
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE knowledge_learning_steps SET status = 'completed', "
                    "progress = :progress, metrics = CAST(:metrics AS jsonb), "
                    "finished_at = now(), "
                    "duration_ms = EXTRACT(EPOCH FROM (now() - COALESCE(started_at, now()))) * 1000 "
                    "WHERE organization_id = :oid AND run_id = :rid AND stage = :stage"
                ),
                {
                    "oid": organization_id,
                    "rid": run_id,
                    "stage": stage,
                    "progress": max(0, min(100, progress)),
                    "metrics": json.dumps(metrics or {}),
                },
            )
            await session.commit()
        finally:
            await session.close()

    async def fail_step(
        self, organization_id: UUID, run_id: UUID, stage: str, error: str
    ) -> None:
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE knowledge_learning_steps SET status = 'failed', "
                    "error = :error, finished_at = now(), "
                    "duration_ms = EXTRACT(EPOCH FROM (now() - COALESCE(started_at, now()))) * 1000 "
                    "WHERE organization_id = :oid AND run_id = :rid AND stage = :stage"
                ),
                {
                    "oid": organization_id,
                    "rid": run_id,
                    "stage": stage,
                    "error": error[:2000],
                },
            )
            await session.commit()
        finally:
            await session.close()

    # ------------------------------------------------------------------ events
    async def append_event(
        self,
        organization_id: UUID,
        *,
        event_type: str,
        run_id: UUID | None = None,
        source_id: UUID | None = None,
        stage: str | None = None,
        category: str = "system",
        severity: str = "info",
        message: str = "",
        payload: dict | None = None,
    ) -> dict:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        f"INSERT INTO knowledge_events (id, organization_id, run_id, "
                        f"source_id, event_type, stage, category, severity, message, payload) "
                        f"VALUES (uuid_generate_v4(), :oid, :rid, :sid, :etype, :stage, "
                        f":category, :severity, :message, CAST(:payload AS jsonb)) "
                        f"RETURNING {_EVENT_COLS}"  # noqa: S608 — cols constantes
                    ),
                    {
                        "oid": organization_id,
                        "rid": run_id,
                        "sid": source_id,
                        "etype": event_type[:60],
                        "stage": stage[:30] if stage else None,
                        "category": category[:20],
                        "severity": severity[:10],
                        "message": (message or "")[:2000],
                        "payload": json.dumps(payload or {}, default=str),
                    },
                )
            ).fetchone()
            await session.commit()
            return self._event_row(row)
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Knowledge event append failed", error=str(exc))
            raise
        finally:
            await session.close()

    async def list_events(
        self,
        organization_id: UUID,
        *,
        run_id: UUID | None = None,
        source_id: UUID | None = None,
        category: str | None = None,
        since_seq: int = 0,
        limit: int = 200,
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            query = (
                f"SELECT {_EVENT_COLS} FROM knowledge_events "
                "WHERE organization_id = :oid AND seq > :since"  # noqa: S608
            )
            params: dict = {
                "oid": organization_id,
                "since": max(0, int(since_seq)),
                "limit": max(1, min(int(limit), 1000)),
            }
            if run_id is not None:
                query += " AND run_id = :rid"
                params["rid"] = run_id
            if source_id is not None:
                query += " AND source_id = :sid"
                params["sid"] = source_id
            if category:
                query += " AND category = :category"
                params["category"] = category
            query += " ORDER BY seq ASC LIMIT :limit"
            rows = (await session.execute(text(query), params)).fetchall()
            return [self._event_row(r) for r in rows]
        finally:
            await session.close()

    # ------------------------------------------------------------------ scores
    async def upsert_score(
        self,
        organization_id: UUID,
        *,
        overall: float,
        gate: str,
        dimensions: list[dict],
        reasons: list[str],
        weights: dict,
        source_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> dict:
        scope_key = f"source:{source_id}" if source_id else "organization"
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "INSERT INTO knowledge_scores (id, organization_id, scope_key, "
                        "source_id, run_id, overall, gate, dimensions, reasons, weights) "
                        "VALUES (uuid_generate_v4(), :oid, :scope, :sid, :rid, :overall, "
                        ":gate, CAST(:dims AS jsonb), CAST(:reasons AS jsonb), "
                        "CAST(:weights AS jsonb)) "
                        "ON CONFLICT (organization_id, scope_key) DO UPDATE SET "
                        "source_id = EXCLUDED.source_id, run_id = EXCLUDED.run_id, "
                        "overall = EXCLUDED.overall, gate = EXCLUDED.gate, "
                        "dimensions = EXCLUDED.dimensions, reasons = EXCLUDED.reasons, "
                        "weights = EXCLUDED.weights, computed_at = now() "
                        "RETURNING id, overall, gate, dimensions, reasons, weights, "
                        "source_id, run_id, computed_at"
                    ),
                    {
                        "oid": organization_id,
                        "scope": scope_key,
                        "sid": source_id,
                        "rid": run_id,
                        "overall": round(float(overall), 2),
                        "gate": gate,
                        "dims": json.dumps(dimensions),
                        "reasons": json.dumps(reasons),
                        "weights": json.dumps(weights),
                    },
                )
            ).fetchone()
            await session.commit()
            return {
                "id": str(row.id),
                "overall": round(float(row.overall), 2),
                "gate": row.gate,
                "dimensions": row.dimensions or [],
                "reasons": row.reasons or [],
                "weights": row.weights or {},
                "source_id": str(row.source_id) if row.source_id else None,
                "run_id": str(row.run_id) if row.run_id else None,
                "computed_at": _iso(row.computed_at),
            }
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Knowledge score upsert failed", error=str(exc))
            raise
        finally:
            await session.close()

    async def get_score(
        self, organization_id: UUID, source_id: UUID | None = None
    ) -> dict | None:
        scope_key = f"source:{source_id}" if source_id else "organization"
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT id, overall, gate, dimensions, reasons, weights, "
                        "source_id, run_id, computed_at FROM knowledge_scores "
                        "WHERE organization_id = :oid AND scope_key = :scope"
                    ),
                    {"oid": organization_id, "scope": scope_key},
                )
            ).fetchone()
            if row is None:
                return None
            return {
                "id": str(row.id),
                "overall": round(float(row.overall), 2),
                "gate": row.gate,
                "dimensions": row.dimensions or [],
                "reasons": row.reasons or [],
                "weights": row.weights or {},
                "source_id": str(row.source_id) if row.source_id else None,
                "run_id": str(row.run_id) if row.run_id else None,
                "computed_at": _iso(row.computed_at),
            }
        finally:
            await session.close()

    async def list_scores(self, organization_id: UUID) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, overall, gate, dimensions, reasons, weights, "
                        "source_id, run_id, computed_at FROM knowledge_scores "
                        "WHERE organization_id = :oid AND source_id IS NOT NULL "
                        "ORDER BY computed_at DESC"
                    ),
                    {"oid": organization_id},
                )
            ).fetchall()
            return [
                {
                    "id": str(r.id),
                    "overall": round(float(r.overall), 2),
                    "gate": r.gate,
                    "dimensions": r.dimensions or [],
                    "reasons": r.reasons or [],
                    "weights": r.weights or {},
                    "source_id": str(r.source_id) if r.source_id else None,
                    "run_id": str(r.run_id) if r.run_id else None,
                    "computed_at": _iso(r.computed_at),
                }
                for r in rows
            ]
        finally:
            await session.close()

    # ----------------------------------------------------------- llm analyses
    async def get_llm_analysis(
        self,
        organization_id: UUID,
        *,
        table_id: UUID,
        schema_fingerprint: str,
        prompt_version: str,
        model: str,
    ) -> dict | None:
        """Cache durable: análisis vigente para fingerprint+prompt+modelo."""
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        f"SELECT {_LLM_ANALYSIS_COLS} FROM knowledge_llm_analyses "
                        "WHERE organization_id = :oid AND table_id = :tid "
                        "AND schema_fingerprint = :fp AND prompt_version = :pv "
                        "AND model = :model AND status = 'completed' "  # noqa: S608
                        "ORDER BY updated_at DESC LIMIT 1"
                    ),
                    {
                        "oid": organization_id,
                        "tid": table_id,
                        "fp": schema_fingerprint[:64],
                        "pv": prompt_version[:20],
                        "model": model[:120],
                    },
                )
            ).fetchone()
            return self._llm_analysis_row(row) if row else None
        finally:
            await session.close()

    async def upsert_llm_analysis(
        self,
        organization_id: UUID,
        *,
        schema_fingerprint: str,
        prompt_version: str,
        model: str,
        status: str,
        source_id: UUID | None = None,
        run_id: UUID | None = None,
        table_id: UUID | None = None,
        context_digest: str = "",
        context_meta: dict | None = None,
        result: dict | None = None,
        reasoning_summary: str | None = None,
        confidence: float | None = None,
        tokens_input: int = 0,
        tokens_output: int = 0,
        latency_ms: float = 0.0,
        estimated_cost: float = 0.0,
        error: str | None = None,
    ) -> dict:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "INSERT INTO knowledge_llm_analyses "
                        "(id, organization_id, source_id, run_id, table_id, "
                        "schema_fingerprint, prompt_version, model, status, "
                        "context_digest, context_meta, result, reasoning_summary, "
                        "confidence, tokens_input, tokens_output, latency_ms, "
                        "estimated_cost, error) "
                        "VALUES (uuid_generate_v4(), :oid, :sid, :rid, :tid, :fp, "
                        ":pv, :model, :status, :digest, CAST(:cm AS jsonb), "
                        "CAST(:result AS jsonb), :summary, :confidence, :tin, :tout, "
                        ":lat, :cost, :error) "
                        "ON CONFLICT (organization_id, table_id, schema_fingerprint, "
                        "prompt_version, model) DO UPDATE SET "
                        "source_id = EXCLUDED.source_id, run_id = EXCLUDED.run_id, "
                        "status = EXCLUDED.status, context_digest = EXCLUDED.context_digest, "
                        "context_meta = EXCLUDED.context_meta, result = EXCLUDED.result, "
                        "reasoning_summary = EXCLUDED.reasoning_summary, "
                        "confidence = EXCLUDED.confidence, "
                        "tokens_input = EXCLUDED.tokens_input, "
                        "tokens_output = EXCLUDED.tokens_output, "
                        "latency_ms = EXCLUDED.latency_ms, "
                        "estimated_cost = EXCLUDED.estimated_cost, "
                        "error = EXCLUDED.error, updated_at = now() "
                        f"RETURNING {_LLM_ANALYSIS_COLS}"
                    ),
                    {
                        "oid": organization_id,
                        "sid": source_id,
                        "rid": run_id,
                        "tid": table_id,
                        "fp": schema_fingerprint[:64],
                        "pv": prompt_version[:20],
                        "model": model[:120],
                        "status": status,
                        "digest": context_digest[:64],
                        "cm": json.dumps(context_meta or {}),
                        "result": json.dumps(result or {}),
                        "summary": (reasoning_summary or None),
                        "confidence": confidence,
                        "tin": max(0, int(tokens_input)),
                        "tout": max(0, int(tokens_output)),
                        "lat": round(float(latency_ms), 2),
                        "cost": round(float(estimated_cost), 8),
                        "error": (error or None),
                    },
                )
            ).fetchone()
            await session.commit()
            return self._llm_analysis_row(row)
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("LLM analysis upsert failed", error=str(exc)[:300])
            raise
        finally:
            await session.close()

    async def list_llm_analyses(
        self,
        organization_id: UUID,
        *,
        run_id: UUID | None = None,
        source_id: UUID | None = None,
        limit: int = 200,
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            query = (
                f"SELECT {_LLM_ANALYSIS_COLS} FROM knowledge_llm_analyses "
                "WHERE organization_id = :oid"  # noqa: S608
            )
            params: dict = {"oid": organization_id, "limit": max(1, min(int(limit), 1000))}
            if run_id is not None:
                query += " AND run_id = :rid"
                params["rid"] = run_id
            if source_id is not None:
                query += " AND source_id = :sid"
                params["sid"] = source_id
            query += " ORDER BY created_at DESC LIMIT :limit"
            rows = (await session.execute(text(query), params)).fetchall()
            return [self._llm_analysis_row(r) for r in rows]
        finally:
            await session.close()

    # --------------------------------------------------------- business rules
    async def upsert_business_rule(
        self,
        organization_id: UUID,
        *,
        name: str,
        definition: str,
        applies_to: list[str] | None = None,
        provenance: str = "INFERRED",
        confidence: str = "medium",
        source: str = "llm",
        suggestion_id: UUID | None = None,
        created_by: UUID | None = None,
        learned_run_id: UUID | None = None,
    ) -> dict:
        rule_key = _rule_key(name)
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "INSERT INTO knowledge_business_rules "
                        "(id, organization_id, rule_key, name, definition, applies_to, "
                        "provenance, confidence, source, suggestion_id, created_by, "
                        "learned_run_id, last_learned_at) "
                        "VALUES (uuid_generate_v4(), :oid, :key, :name, :definition, "
                        "CAST(:applies AS jsonb), :provenance, :confidence, :source, "
                        ":suggestion, :created_by, :run_id, now()) "
                        "ON CONFLICT (organization_id, rule_key) DO UPDATE SET "
                        "definition = EXCLUDED.definition, "
                        "applies_to = EXCLUDED.applies_to, "
                        "confidence = EXCLUDED.confidence, "
                        "source = EXCLUDED.source, "
                        "provenance = CASE "
                        "  WHEN knowledge_business_rules.provenance = 'APPROVED' "
                        "  THEN 'APPROVED' ELSE EXCLUDED.provenance END, "
                        "learned_run_id = COALESCE(EXCLUDED.learned_run_id, "
                        "knowledge_business_rules.learned_run_id), "
                        "last_learned_at = now(), updated_at = now() "
                        f"RETURNING {_RULE_COLS}"
                    ),
                    {
                        "oid": organization_id,
                        "key": rule_key,
                        "name": name[:200],
                        "definition": definition[:8000],
                        "applies": json.dumps(applies_to or []),
                        "provenance": provenance,
                        "confidence": confidence,
                        "source": source[:40],
                        "suggestion": suggestion_id,
                        "created_by": created_by,
                        "run_id": learned_run_id,
                    },
                )
            ).fetchone()
            await session.commit()
            return self._business_rule_row(row)
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Business rule upsert failed", error=str(exc)[:200])
            raise
        finally:
            await session.close()

    async def list_business_rules(
        self,
        organization_id: UUID,
        *,
        provenance: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            query = (
                f"SELECT {_RULE_COLS} FROM knowledge_business_rules "
                "WHERE organization_id = :oid"  # noqa: S608
            )
            params: dict = {
                "oid": organization_id,
                "limit": max(1, min(int(limit), 1000)),
                "offset": max(0, int(offset)),
            }
            if provenance:
                query += " AND provenance = :provenance"
                params["provenance"] = provenance
            query += " ORDER BY name LIMIT :limit OFFSET :offset"
            rows = (await session.execute(text(query), params)).fetchall()
            return [self._business_rule_row(r) for r in rows]
        finally:
            await session.close()

    async def get_business_rule(
        self, organization_id: UUID, rule_id: UUID
    ) -> dict | None:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        f"SELECT {_RULE_COLS} FROM knowledge_business_rules "
                        "WHERE organization_id = :oid AND id = :id"  # noqa: S608
                    ),
                    {"oid": organization_id, "id": rule_id},
                )
            ).fetchone()
            return self._business_rule_row(row) if row else None
        finally:
            await session.close()

    async def update_business_rule_status(
        self,
        organization_id: UUID,
        rule_id: UUID,
        *,
        provenance: str,
        approved_by: UUID | None = None,
    ) -> dict | None:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "UPDATE knowledge_business_rules SET provenance = :provenance, "
                        "approved_by = COALESCE(:approved_by, approved_by), "
                        "updated_at = now() "
                        "WHERE organization_id = :oid AND id = :id "
                        f"RETURNING {_RULE_COLS}"
                    ),
                    {
                        "provenance": provenance,
                        "approved_by": approved_by,
                        "oid": organization_id,
                        "id": rule_id,
                    },
                )
            ).fetchone()
            await session.commit()
            return self._business_rule_row(row) if row else None
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Business rule status update failed", error=str(exc)[:200])
            raise
        finally:
            await session.close()

    # ------------------------------------------------------------- questions
    async def upsert_question(
        self,
        organization_id: UUID,
        *,
        question_key: str,
        question_type: str,
        title: str,
        body: str = "",
        source_id: UUID | None = None,
        run_id: UUID | None = None,
        catalog_table_id: UUID | None = None,
        entity_id: UUID | None = None,
        field_id: UUID | None = None,
        column_id: UUID | None = None,
        relationship_id: UUID | None = None,
        evidence: list | None = None,
        options: list | None = None,
        answer_schema: dict | None = None,
        priority: str = "medium",
        priority_score: float = 0.0,
        impact: dict | None = None,
        confidence_before: float | None = None,
    ) -> dict:
        """Idempotente por (org, question_key); nunca revive respondidas."""
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "INSERT INTO knowledge_questions "
                        "(id, organization_id, source_id, run_id, catalog_table_id, "
                        "entity_id, field_id, column_id, relationship_id, question_key, "
                        "question_type, title, body, evidence, options, answer_schema, "
                        "priority, priority_score, impact, confidence_before) "
                        "VALUES (uuid_generate_v4(), :oid, :sid, :rid, :tid, :eid, "
                        ":fid, :cid, :relid, :key, :qtype, :title, :body, "
                        "CAST(:evidence AS jsonb), CAST(:options AS jsonb), "
                        "CAST(:schema AS jsonb), :priority, :score, CAST(:impact AS jsonb), "
                        ":confidence) "
                        "ON CONFLICT (organization_id, question_key) DO UPDATE SET "
                        "source_id = EXCLUDED.source_id, run_id = EXCLUDED.run_id, "
                        "evidence = EXCLUDED.evidence, options = EXCLUDED.options, "
                        "answer_schema = EXCLUDED.answer_schema, "
                        "priority = EXCLUDED.priority, "
                        "priority_score = EXCLUDED.priority_score, "
                        "impact = EXCLUDED.impact, updated_at = now() "
                        "WHERE knowledge_questions.status = 'pending' "
                        f"RETURNING {_QUESTION_COLS}"
                    ),
                    {
                        "oid": organization_id,
                        "sid": source_id,
                        "rid": run_id,
                        "tid": catalog_table_id,
                        "eid": entity_id,
                        "fid": field_id,
                        "cid": column_id,
                        "relid": relationship_id,
                        "key": question_key[:200],
                        "qtype": question_type,
                        "title": title[:2000],
                        "body": body[:4000],
                        "evidence": json.dumps(evidence or []),
                        "options": json.dumps(options or []),
                        "schema": json.dumps(answer_schema or {}),
                        "priority": priority,
                        "score": round(float(priority_score), 4),
                        "impact": json.dumps(impact or {}),
                        "confidence": confidence_before,
                    },
                )
            ).fetchone()
            await session.commit()
            if row is not None:
                return self._question_row(row)
            existing = (
                await session.execute(
                    text(
                        f"SELECT {_QUESTION_COLS} FROM knowledge_questions "
                        "WHERE organization_id = :oid AND question_key = :key"
                    ),
                    {"oid": organization_id, "key": question_key[:200]},
                )
            ).fetchone()
            return self._question_row(existing) if existing else {}
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Question upsert failed", error=str(exc)[:300])
            raise
        finally:
            await session.close()

    async def get_question(
        self, organization_id: UUID, question_id: UUID
    ) -> dict | None:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        f"SELECT {_QUESTION_COLS} FROM knowledge_questions "
                        "WHERE organization_id = :oid AND id = :id"  # noqa: S608
                    ),
                    {"oid": organization_id, "id": question_id},
                )
            ).fetchone()
            return self._question_row(row) if row else None
        finally:
            await session.close()

    async def get_question_by_key(
        self, organization_id: UUID, question_key: str
    ) -> dict | None:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        f"SELECT {_QUESTION_COLS} FROM knowledge_questions "
                        "WHERE organization_id = :oid AND question_key = :key"  # noqa: S608
                    ),
                    {"oid": organization_id, "key": question_key[:200]},
                )
            ).fetchone()
            return self._question_row(row) if row else None
        finally:
            await session.close()

    async def list_questions(
        self,
        organization_id: UUID,
        *,
        status: str | None = None,
        statuses: list[str] | None = None,
        priority: str | None = None,
        source_id: UUID | None = None,
        run_id: UUID | None = None,
        entity_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            query = (
                f"SELECT {_QUESTION_COLS} FROM knowledge_questions "
                "WHERE organization_id = :oid"  # noqa: S608
            )
            params: dict = {
                "oid": organization_id,
                "limit": max(1, min(int(limit), 500)),
                "offset": max(0, int(offset)),
            }
            if status:
                query += " AND status = :status"
                params["status"] = status
            if statuses:
                placeholders = ", ".join(f":st{i}" for i in range(len(statuses)))
                query += f" AND status IN ({placeholders})"
                for index, value in enumerate(statuses):
                    params[f"st{index}"] = value
            if priority:
                query += " AND priority = :priority"
                params["priority"] = priority
            if source_id is not None:
                query += " AND source_id = :sid"
                params["sid"] = source_id
            if run_id is not None:
                query += " AND run_id = :rid"
                params["rid"] = run_id
            if entity_id is not None:
                query += " AND entity_id = :eid"
                params["eid"] = entity_id
            query += (
                " ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
                "WHEN 'medium' THEN 2 ELSE 3 END, priority_score DESC, "
                "created_at DESC LIMIT :limit OFFSET :offset"
            )
            rows = (await session.execute(text(query), params)).fetchall()
            return [self._question_row(r) for r in rows]
        finally:
            await session.close()

    async def count_pending_questions(
        self,
        organization_id: UUID,
        *,
        source_id: UUID | None = None,
        run_id: UUID | None = None,
        priorities: list[str] | None = None,
    ) -> int:
        session: AsyncSession = await get_async_session()
        try:
            query = (
                "SELECT COUNT(*)::int AS n FROM knowledge_questions "
                "WHERE organization_id = :oid AND status = 'pending'"  # noqa: S608
            )
            params: dict = {"oid": organization_id}
            if source_id is not None:
                query += " AND source_id = :sid"
                params["sid"] = source_id
            if run_id is not None:
                query += " AND run_id = :rid"
                params["rid"] = run_id
            if priorities:
                placeholders = ", ".join(f":p{i}" for i in range(len(priorities)))
                query += f" AND priority IN ({placeholders})"
                for index, value in enumerate(priorities):
                    params[f"p{index}"] = value
            row = (await session.execute(text(query), params)).fetchone()
            return int(row.n or 0) if row else 0
        finally:
            await session.close()

    async def count_pending_questions_by_entity(
        self, organization_id: UUID
    ) -> dict[str, int]:
        session: AsyncSession = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT entity_id, COUNT(*)::int AS n FROM knowledge_questions "
                        "WHERE organization_id = :oid AND status = 'pending' "
                        "AND entity_id IS NOT NULL GROUP BY entity_id"
                    ),
                    {"oid": organization_id},
                )
            ).fetchall()
            return {str(r.entity_id): int(r.n) for r in rows}
        finally:
            await session.close()

    async def update_question_status(
        self,
        organization_id: UUID,
        question_id: UUID,
        *,
        status: str,
        answer: dict | None = None,
        structured_answer: dict | None = None,
        answered_by: UUID | None = None,
        confidence_after: float | None = None,
    ) -> dict | None:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "UPDATE knowledge_questions SET "
                        "status = :status, "
                        "answer = CASE WHEN :has_answer THEN CAST(:answer AS jsonb) "
                        "ELSE answer END, "
                        "structured_answer = CASE WHEN :has_structured "
                        "THEN CAST(:structured AS jsonb) ELSE structured_answer END, "
                        "answered_by = COALESCE(:answered_by, answered_by), "
                        "answered_at = CASE WHEN :is_pending THEN answered_at "
                        "ELSE now() END, "
                        "confidence_after = COALESCE(:confidence_after, confidence_after), "
                        "updated_at = now() "
                        "WHERE organization_id = :oid AND id = :id "
                        f"RETURNING {_QUESTION_COLS}"
                    ),
                    {
                        "status": status,
                        "has_answer": answer is not None,
                        "answer": json.dumps(answer or {}),
                        "has_structured": structured_answer is not None,
                        "structured": json.dumps(structured_answer or {}),
                        "answered_by": answered_by,
                        "is_pending": status == QuestionStatus.PENDING.value,
                        "confidence_after": confidence_after,
                        "oid": organization_id,
                        "id": question_id,
                    },
                )
            ).fetchone()
            await session.commit()
            return self._question_row(row) if row else None
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Question status update failed", error=str(exc)[:300])
            raise
        finally:
            await session.close()

    # -------------------------------------------------------------- feedback
    async def insert_feedback(
        self,
        organization_id: UUID,
        *,
        question_id: UUID | None = None,
        run_id: UUID | None = None,
        source_id: UUID | None = None,
        knowledge_type: str = "question",
        knowledge_id: str | None = None,
        question: str = "",
        answer: str = "",
        structured_answer: dict | None = None,
        source: str = "question",
        applied: bool = False,
        applied_to: list | None = None,
        created_by: UUID | None = None,
    ) -> dict:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "INSERT INTO knowledge_feedback "
                        "(id, organization_id, question_id, run_id, source_id, "
                        "knowledge_type, knowledge_id, question, answer, "
                        "structured_answer, source, applied, applied_to, created_by) "
                        "VALUES (uuid_generate_v4(), :oid, :qid, :rid, :sid, :ktype, "
                        ":kid, :question, :answer, CAST(:structured AS jsonb), "
                        ":source, :applied, CAST(:applied_to AS jsonb), :by) "
                        f"RETURNING {_FEEDBACK_COLS}"
                    ),
                    {
                        "oid": organization_id,
                        "qid": question_id,
                        "rid": run_id,
                        "sid": source_id,
                        "ktype": knowledge_type[:40],
                        "kid": (knowledge_id or "")[:80] or None,
                        "question": (question or "")[:4000],
                        "answer": (answer or "")[:8000],
                        "structured": json.dumps(structured_answer or {}),
                        "source": source,
                        "applied": bool(applied),
                        "applied_to": json.dumps(applied_to or []),
                        "by": created_by,
                    },
                )
            ).fetchone()
            await session.commit()
            return self._feedback_row(row)
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Feedback insert failed", error=str(exc)[:300])
            raise
        finally:
            await session.close()

    async def list_feedback(
        self,
        organization_id: UUID,
        *,
        run_id: UUID | None = None,
        source_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            query = (
                f"SELECT {_FEEDBACK_COLS} FROM knowledge_feedback "
                "WHERE organization_id = :oid"  # noqa: S608
            )
            params: dict = {
                "oid": organization_id,
                "limit": max(1, min(int(limit), 500)),
                "offset": max(0, int(offset)),
            }
            if run_id is not None:
                query += " AND run_id = :rid"
                params["rid"] = run_id
            if source_id is not None:
                query += " AND source_id = :sid"
                params["sid"] = source_id
            query += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            rows = (await session.execute(text(query), params)).fetchall()
            return [self._feedback_row(r) for r in rows]
        finally:
            await session.close()

    # ---------------------------------------------------------------- settings
    async def get_settings(self, organization_id: UUID) -> dict | None:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT organization_id, weights, thresholds, updated_by, "
                        "updated_at FROM knowledge_learning_settings "
                        "WHERE organization_id = :oid"
                    ),
                    {"oid": organization_id},
                )
            ).fetchone()
            if row is None:
                return None
            return {
                "organization_id": str(row.organization_id),
                "weights": row.weights or {},
                "thresholds": row.thresholds or {},
                "updated_by": str(row.updated_by) if row.updated_by else None,
                "updated_at": _iso(row.updated_at),
            }
        finally:
            await session.close()

    async def upsert_settings(
        self,
        organization_id: UUID,
        *,
        weights: dict | None = None,
        thresholds: dict | None = None,
        updated_by: UUID | None = None,
    ) -> dict:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "INSERT INTO knowledge_learning_settings "
                        "(organization_id, weights, thresholds, updated_by) "
                        "VALUES (:oid, CAST(:weights AS jsonb), CAST(:thresholds AS jsonb), :by) "
                        "ON CONFLICT (organization_id) DO UPDATE SET "
                        "weights = EXCLUDED.weights, thresholds = EXCLUDED.thresholds, "
                        "updated_by = EXCLUDED.updated_by, updated_at = now() "
                        "RETURNING organization_id, weights, thresholds, updated_by, updated_at"
                    ),
                    {
                        "oid": organization_id,
                        "weights": json.dumps(weights or {}),
                        "thresholds": json.dumps(thresholds or {}),
                        "by": updated_by,
                    },
                )
            ).fetchone()
            await session.commit()
            return {
                "organization_id": str(row.organization_id),
                "weights": row.weights or {},
                "thresholds": row.thresholds or {},
                "updated_by": str(row.updated_by) if row.updated_by else None,
                "updated_at": _iso(row.updated_at),
            }
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Knowledge learning settings upsert failed", error=str(exc))
            raise
        finally:
            await session.close()

    # --------------------------------------------------------------- snapshots
    async def org_snapshot(self, organization_id: UUID) -> dict:
        """Conteos reales para el header de Learning y el score global."""
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT
                          (SELECT COUNT(*) FROM catalog_sources s
                             WHERE s.organization_id = :oid) AS sources_total,
                          (SELECT COUNT(*) FROM catalog_tables t
                             WHERE t.organization_id = :oid AND t.removed_at IS NULL)
                             AS tables_total,
                          (SELECT COUNT(*) FROM catalog_columns c
                             JOIN catalog_tables t ON c.table_id = t.id
                             WHERE c.organization_id = :oid AND t.removed_at IS NULL)
                             AS columns_total,
                          (SELECT COUNT(*) FROM catalog_entities e
                             WHERE e.organization_id = :oid) AS entities_total,
                          (SELECT COUNT(*) FROM catalog_entities e
                             WHERE e.organization_id = :oid AND EXISTS (
                               SELECT 1 FROM catalog_fields f
                               WHERE f.entity_id = e.id AND f.organization_id = :oid))
                             AS entities_understood,
                          (SELECT COUNT(*) FROM catalog_fields f
                             WHERE f.organization_id = :oid) AS fields_total,
                          (SELECT COUNT(*) FROM catalog_relationships r
                             WHERE r.organization_id = :oid) AS relationships_total,
                          (SELECT COUNT(*) FROM catalog_relationships r
                             WHERE r.organization_id = :oid AND r.status = 'confirmed')
                             AS relationships_confirmed,
                          (SELECT COUNT(*) FROM catalog_metrics m
                             WHERE m.organization_id = :oid AND m.status = 'approved')
                             AS metrics_approved,
                          (SELECT COUNT(*) FROM business_definitions d
                             WHERE d.organization_id = :oid AND d.status = 'approved')
                             AS definitions_approved,
                          (SELECT COUNT(*) FROM catalog_entities e
                             WHERE e.organization_id = :oid AND e.status = 'approved')
                             AS entities_approved,
                          (SELECT COUNT(*) FROM catalog_fields f
                             WHERE f.organization_id = :oid AND f.status = 'approved')
                             AS fields_approved,
                          (SELECT COUNT(*) FROM context_gaps g
                             WHERE g.organization_id = :oid AND g.status = 'open')
                             AS open_gaps
                        """
                    ),
                    {"oid": organization_id},
                )
            ).fetchone()
            if row is None:
                return {}
            return {key: int(value or 0) for key, value in dict(row._mapping).items()}
        finally:
            await session.close()

    async def source_snapshot(self, organization_id: UUID, source_id: UUID) -> dict:
        """Conteos reales por fuente (sección 25: Source Level Learning)."""
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT
                          (SELECT COUNT(*) FROM catalog_tables t
                             WHERE t.organization_id = :oid AND t.source_id = :sid
                             AND t.removed_at IS NULL) AS tables_total,
                          (SELECT COUNT(*) FROM catalog_tables t
                             WHERE t.organization_id = :oid AND t.source_id = :sid
                             AND t.removed_at IS NULL AND EXISTS (
                               SELECT 1 FROM catalog_columns c
                               WHERE c.table_id = t.id AND c.organization_id = :oid))
                             AS tables_analyzed,
                          (SELECT COUNT(*) FROM catalog_columns c
                             JOIN catalog_tables t ON c.table_id = t.id
                             WHERE c.organization_id = :oid AND t.source_id = :sid
                             AND t.removed_at IS NULL) AS columns_total,
                          (SELECT COUNT(*) FROM catalog_columns c
                             JOIN catalog_tables t ON c.table_id = t.id
                             WHERE c.organization_id = :oid AND t.source_id = :sid
                             AND t.removed_at IS NULL AND c.column_comment IS NOT NULL)
                             AS columns_documented,
                          (SELECT COUNT(*) FROM catalog_relationships r
                             WHERE r.organization_id = :oid AND r.source_id = :sid)
                             AS relationships_total,
                          (SELECT COUNT(*) FROM catalog_relationships r
                             WHERE r.organization_id = :oid AND r.source_id = :sid
                             AND r.status = 'confirmed') AS relationships_confirmed,
                          (SELECT COUNT(*) FROM catalog_entities e
                             WHERE e.organization_id = :oid AND EXISTS (
                               SELECT 1 FROM catalog_tables t
                               WHERE t.id = e.mapped_table_id AND t.source_id = :sid))
                             AS entities_total,
                          (SELECT COUNT(*) FROM catalog_fields f
                             JOIN catalog_entities e ON f.entity_id = e.id
                             WHERE f.organization_id = :oid AND EXISTS (
                               SELECT 1 FROM catalog_tables t
                               WHERE t.id = e.mapped_table_id AND t.source_id = :sid))
                             AS fields_total
                        """
                    ),
                    {"oid": organization_id, "sid": source_id},
                )
            ).fetchone()
            if row is None:
                return {}
            return {key: int(value or 0) for key, value in dict(row._mapping).items()}
        finally:
            await session.close()

    # ------------------------------------------------------------------ row maps
    @staticmethod
    def _run_row(row) -> dict:
        return {
            "id": str(row.id),
            "organization_id": str(row.organization_id),
            "workspace_id": str(row.workspace_id) if row.workspace_id else None,
            "catalog_source_id": str(row.catalog_source_id)
            if row.catalog_source_id
            else None,
            "kb_source_id": str(row.kb_source_id) if row.kb_source_id else None,
            "training_run_id": str(row.training_run_id) if row.training_run_id else None,
            "trigger": row.trigger,
            "status": row.status,
            "current_stage": row.current_stage,
            "overall_progress": int(row.overall_progress or 0),
            "stage_progress": int(row.stage_progress or 0),
            "gate": row.gate,
            "tables_analyzed": int(row.tables_analyzed or 0),
            "entities_detected": int(row.entities_detected or 0),
            "fields_detected": int(row.fields_detected or 0),
            "relationships_detected": int(row.relationships_detected or 0),
            "metrics": row.metrics or {},
            "error_summary": row.error_summary or {},
            "created_by": str(row.created_by) if row.created_by else None,
            "created_at": _iso(row.created_at),
            "started_at": _iso(row.started_at),
            "finished_at": _iso(row.finished_at),
        }

    @staticmethod
    def _step_row(row) -> dict:
        return {
            "id": str(row.id),
            "organization_id": str(row.organization_id),
            "run_id": str(row.run_id),
            "stage": row.stage,
            "sequence": int(row.sequence or 0),
            "status": row.status,
            "progress": int(row.progress or 0),
            "metrics": row.metrics or {},
            "error": row.error,
            "started_at": _iso(row.started_at),
            "finished_at": _iso(row.finished_at),
            "duration_ms": round(float(row.duration_ms or 0), 2),
        }

    @staticmethod
    def _event_row(row) -> dict:
        return {
            "id": str(row.id),
            "seq": int(row.seq),
            "organization_id": str(row.organization_id),
            "run_id": str(row.run_id) if row.run_id else None,
            "source_id": str(row.source_id) if row.source_id else None,
            "event_type": row.event_type,
            "stage": row.stage,
            "category": row.category,
            "severity": row.severity,
            "message": row.message,
            "payload": row.payload or {},
            "created_at": _iso(row.created_at),
        }

    @staticmethod
    def _question_row(row) -> dict:
        def _json(value, default):
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except (TypeError, ValueError):
                    return default
            return value if value is not None else default

        return {
            "id": str(row.id),
            "organization_id": str(row.organization_id),
            "source_id": str(row.source_id) if row.source_id else None,
            "run_id": str(row.run_id) if row.run_id else None,
            "catalog_table_id": (
                str(row.catalog_table_id) if row.catalog_table_id else None
            ),
            "entity_id": str(row.entity_id) if row.entity_id else None,
            "field_id": str(row.field_id) if row.field_id else None,
            "column_id": str(row.column_id) if row.column_id else None,
            "relationship_id": (
                str(row.relationship_id) if row.relationship_id else None
            ),
            "question_key": row.question_key,
            "question_type": row.question_type,
            "title": row.title,
            "body": row.body,
            "evidence": _json(row.evidence, []),
            "options": _json(row.options, []),
            "answer_schema": _json(row.answer_schema, {}),
            "priority": row.priority,
            "priority_score": round(float(row.priority_score or 0), 4),
            "impact": _json(row.impact, {}),
            "status": row.status,
            "answer": _json(row.answer, {}),
            "structured_answer": _json(row.structured_answer, {}),
            "answered_by": str(row.answered_by) if row.answered_by else None,
            "answered_at": _iso(row.answered_at),
            "confidence_before": row.confidence_before,
            "confidence_after": row.confidence_after,
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }

    @staticmethod
    def _feedback_row(row) -> dict:
        structured = row.structured_answer or {}
        if isinstance(structured, str):
            try:
                structured = json.loads(structured)
            except (TypeError, ValueError):
                structured = {}
        applied_to = row.applied_to or []
        if isinstance(applied_to, str):
            try:
                applied_to = json.loads(applied_to)
            except (TypeError, ValueError):
                applied_to = []
        return {
            "id": str(row.id),
            "organization_id": str(row.organization_id),
            "question_id": str(row.question_id) if row.question_id else None,
            "run_id": str(row.run_id) if row.run_id else None,
            "source_id": str(row.source_id) if row.source_id else None,
            "knowledge_type": row.knowledge_type,
            "knowledge_id": row.knowledge_id,
            "question": row.question,
            "answer": row.answer,
            "structured_answer": structured,
            "source": row.source,
            "applied": bool(row.applied),
            "applied_to": applied_to,
            "created_by": str(row.created_by) if row.created_by else None,
            "created_at": _iso(row.created_at),
        }

    @staticmethod
    def _business_rule_row(row) -> dict:
        applies = row.applies_to or []
        if isinstance(applies, str):
            try:
                applies = json.loads(applies)
            except (TypeError, ValueError):
                applies = []
        return {
            "id": str(row.id),
            "organization_id": str(row.organization_id),
            "rule_key": row.rule_key,
            "name": row.name,
            "definition": row.definition,
            "applies_to": applies,
            "provenance": row.provenance,
            "confidence": row.confidence,
            "source": row.source,
            "suggestion_id": str(row.suggestion_id) if row.suggestion_id else None,
            "created_by": str(row.created_by) if row.created_by else None,
            "approved_by": str(row.approved_by) if row.approved_by else None,
            "last_learned_at": _iso(row.last_learned_at),
            "learned_run_id": (
                str(row.learned_run_id) if row.learned_run_id else None
            ),
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }

    @staticmethod
    def _llm_analysis_row(row) -> dict:
        result = row.result or {}
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (TypeError, ValueError):
                result = {}
        meta = row.context_meta or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (TypeError, ValueError):
                meta = {}
        return {
            "id": str(row.id),
            "organization_id": str(row.organization_id),
            "source_id": str(row.source_id) if row.source_id else None,
            "run_id": str(row.run_id) if row.run_id else None,
            "table_id": str(row.table_id) if row.table_id else None,
            "schema_fingerprint": row.schema_fingerprint,
            "prompt_version": row.prompt_version,
            "model": row.model,
            "status": row.status,
            "context_digest": row.context_digest,
            "context_meta": meta,
            "result": result,
            "reasoning_summary": row.reasoning_summary,
            "confidence": row.confidence,
            "tokens_input": int(row.tokens_input or 0),
            "tokens_output": int(row.tokens_output or 0),
            "latency_ms": round(float(row.latency_ms or 0), 2),
            "estimated_cost": round(float(row.estimated_cost or 0), 8),
            "error": row.error,
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }
