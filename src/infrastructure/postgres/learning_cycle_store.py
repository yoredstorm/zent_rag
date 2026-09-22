# =============================================================================
# Postgres store del learning cycle. Tenant-scoped. Payload JSON.
# =============================================================================
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text

from src.core.domain.learning_cycle import (
    EvaluationRecord,
    ExperimentRequest,
    ExperimentStatus,
    Finding,
    Hypothesis,
    PromotionAudit,
    Recommendation,
    RunSignal,
    StrategyComparison,
    ToolStep,
)
from src.infrastructure.postgres.session import get_async_session
from src.learning_engine.store import merge_finding


def _default(value: Any) -> str:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"unsupported value {type(value)}")


def dump(obj: Any) -> str:
    return json.dumps(asdict(obj), default=_default)


def _load(payload: Any) -> dict:
    if isinstance(payload, str):
        return json.loads(payload)
    return dict(payload)


def _uuid(value: Any) -> UUID | None:
    if not value:
        return None
    return value if isinstance(value, UUID) else UUID(str(value))


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def load_signal(payload: Any, *, clustered: bool | None = None) -> RunSignal:
    data = _load(payload)
    data["id"] = _uuid(data["id"])
    data["organization_id"] = _uuid(data["organization_id"])
    data["occurred_at"] = _dt(data["occurred_at"])
    if clustered is not None:
        data["clustered"] = clustered
    return RunSignal(**data)


def load_finding(payload: Any) -> Finding:
    data = _load(payload)
    data["id"] = _uuid(data["id"])
    data["organization_id"] = _uuid(data["organization_id"])
    data["memory_id"] = _uuid(data.get("memory_id"))
    data["first_seen"] = _dt(data["first_seen"])
    data["last_seen"] = _dt(data["last_seen"])
    return Finding(**data)


def load_hypothesis(payload: Any) -> Hypothesis:
    data = _load(payload)
    data["id"] = _uuid(data["id"])
    data["organization_id"] = _uuid(data["organization_id"])
    data["finding_id"] = _uuid(data["finding_id"])
    return Hypothesis(**data)


def load_experiment(payload: Any) -> ExperimentRequest:
    data = _load(payload)
    data["id"] = _uuid(data["id"])
    data["organization_id"] = _uuid(data["organization_id"])
    data["hypothesis_id"] = _uuid(data["hypothesis_id"])
    data["finding_id"] = _uuid(data["finding_id"])
    data["memory_id"] = _uuid(data.get("memory_id"))
    data["created_at"] = _dt(data["created_at"])
    data["tool_plan"] = tuple(ToolStep(**step) for step in data.get("tool_plan") or [])
    return ExperimentRequest(**data)


def load_evaluation(payload: Any) -> EvaluationRecord:
    data = _load(payload)
    data["id"] = _uuid(data["id"])
    data["organization_id"] = _uuid(data["organization_id"])
    data["experiment_id"] = _uuid(data["experiment_id"])
    data["created_at"] = _dt(data["created_at"])
    return EvaluationRecord(**data)


def load_recommendation(payload: Any) -> Recommendation:
    data = _load(payload)
    data["id"] = _uuid(data["id"])
    data["organization_id"] = _uuid(data["organization_id"])
    data["experiment_id"] = _uuid(data["experiment_id"])
    data["evaluation_id"] = _uuid(data["evaluation_id"])
    data["finding_id"] = _uuid(data["finding_id"])
    data["hypothesis_id"] = _uuid(data["hypothesis_id"])
    data["memory_id"] = _uuid(data.get("memory_id"))
    data["created_at"] = _dt(data["created_at"])
    return Recommendation(**data)


def load_promotion(payload: Any) -> PromotionAudit:
    data = _load(payload)
    data["id"] = _uuid(data["id"])
    data["organization_id"] = _uuid(data["organization_id"])
    data["actor_id"] = _uuid(data["actor_id"])
    data["recommendation_id"] = _uuid(data["recommendation_id"])
    data["experiment_id"] = _uuid(data["experiment_id"])
    data["memory_id"] = _uuid(data.get("memory_id"))
    data["acted_at"] = _dt(data["acted_at"])
    data["rolled_back_at"] = _dt(data.get("rolled_back_at"))
    data["rolled_back_by"] = _uuid(data.get("rolled_back_by"))
    return PromotionAudit(**data)


def load_comparison(payload: Any) -> StrategyComparison:
    data = _load(payload)
    data["id"] = _uuid(data["id"])
    data["organization_id"] = _uuid(data["organization_id"])
    data["validated_memory_id"] = _uuid(data.get("validated_memory_id"))
    return StrategyComparison(**data)


def load_conflict(payload: Any):
    from src.learning_engine.conflicts import Conflict

    data = _load(payload)
    data["id"] = _uuid(data["id"])
    data["organization_id"] = _uuid(data["organization_id"])
    data["resolved_by"] = _uuid(data.get("resolved_by"))
    data["chosen_claim_id"] = _uuid(data.get("chosen_claim_id"))
    data["resolved_at"] = _dt(data.get("resolved_at"))
    return Conflict(**data)


class PostgresLearningCycleStore:
    async def append_signal(self, signal: RunSignal) -> RunSignal:
        await self._exec(
            """
            INSERT INTO learning_signals (id, organization_id, occurred_at, clustered, payload)
            VALUES (:id, :oid, :occurred, :clustered, CAST(:payload AS jsonb))
            ON CONFLICT (id) DO NOTHING
            """,
            {
                "id": signal.id,
                "oid": signal.organization_id,
                "occurred": signal.occurred_at,
                "clustered": signal.clustered,
                "payload": dump(signal),
            },
        )
        return signal

    async def signals_in_window(self, organization_id: UUID, start: datetime | None) -> list[RunSignal]:
        sql = """
            SELECT payload, clustered FROM learning_signals
            WHERE organization_id = :oid
        """
        params: dict[str, Any] = {"oid": organization_id}
        if start is not None:
            sql += " AND occurred_at >= :start"
            params["start"] = start
        sql += " ORDER BY occurred_at ASC LIMIT 5000"
        rows = await self._rows(sql, params)
        return [load_signal(row["payload"], clustered=row["clustered"]) for row in rows]

    async def unclustered_signals(self, organization_id: UUID) -> list[RunSignal]:
        rows = await self._rows(
            """
            SELECT payload, clustered FROM learning_signals
            WHERE organization_id = :oid AND clustered = FALSE
            ORDER BY occurred_at ASC
            LIMIT 5000
            """,
            {"oid": organization_id},
        )
        return [load_signal(row["payload"], clustered=False) for row in rows]

    async def mark_clustered(self, organization_id: UUID, signal_ids: list[UUID]) -> None:
        if not signal_ids:
            return
        session = await get_async_session()
        try:
            statement = text(
                """
                UPDATE learning_signals
                SET clustered = TRUE
                WHERE organization_id = :oid AND id IN :ids
                """
            ).bindparams(bindparam("ids", expanding=True))
            await session.execute(statement, {"oid": organization_id, "ids": list(signal_ids)})
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def upsert_finding(self, finding: Finding) -> Finding:
        row = await self._one(
            """
            SELECT id, payload FROM learning_artifacts
            WHERE organization_id = :oid AND kind = 'finding' AND dedupe_key = :key
            """,
            {"oid": finding.organization_id, "key": finding.dedupe_key},
        )
        if row is not None:
            current = merge_finding(load_finding(row["payload"]), finding)
            await self._write_artifact(current.id, current.organization_id, "finding", current.dedupe_key, current)
            return current
        await self._write_artifact(finding.id, finding.organization_id, "finding", finding.dedupe_key, finding)
        return finding

    async def list_findings(self, organization_id: UUID, *, limit: int = 50, offset: int = 0) -> list[Finding]:
        rows = await self._rows(
            """
            SELECT payload FROM learning_artifacts
            WHERE organization_id = :oid AND kind = 'finding'
            ORDER BY updated_at DESC
            LIMIT :limit OFFSET :offset
            """,
            {"oid": organization_id, "limit": limit, "offset": offset},
        )
        return [load_finding(row["payload"]) for row in rows]

    async def get_finding(self, organization_id: UUID, finding_id: UUID) -> Finding | None:
        return await self._get(organization_id, finding_id, "finding", load_finding)

    async def upsert_hypothesis(self, hypothesis: Hypothesis) -> Hypothesis:
        row = await self._one(
            """
            SELECT id, payload FROM learning_artifacts
            WHERE organization_id = :oid AND kind = 'hypothesis' AND dedupe_key = :key
            """,
            {"oid": hypothesis.organization_id, "key": str(hypothesis.finding_id)},
        )
        if row is not None:
            return load_hypothesis(row["payload"])
        await self._write_artifact(
            hypothesis.id, hypothesis.organization_id, "hypothesis", str(hypothesis.finding_id), hypothesis
        )
        return hypothesis

    async def list_hypotheses(self, organization_id: UUID) -> list[Hypothesis]:
        rows = await self._rows(
            """
            SELECT payload FROM learning_artifacts
            WHERE organization_id = :oid AND kind = 'hypothesis'
            ORDER BY updated_at DESC LIMIT 100
            """,
            {"oid": organization_id},
        )
        return [load_hypothesis(row["payload"]) for row in rows]

    async def get_hypothesis(self, organization_id: UUID, hypothesis_id: UUID) -> Hypothesis | None:
        return await self._get(organization_id, hypothesis_id, "hypothesis", load_hypothesis)

    async def save_experiment(self, experiment: ExperimentRequest) -> ExperimentRequest:
        current = await self.get_experiment(experiment.organization_id, experiment.id)
        if current is not None:
            await self._write_artifact(experiment.id, experiment.organization_id, "experiment", "", experiment)
            return experiment
        rows = await self._rows(
            """
            SELECT payload FROM learning_artifacts
            WHERE organization_id = :oid AND kind = 'experiment'
            ORDER BY updated_at DESC LIMIT 200
            """,
            {"oid": experiment.organization_id},
        )
        for row in rows:
            queued = load_experiment(row["payload"])
            if queued.hypothesis_id == experiment.hypothesis_id and queued.status == ExperimentStatus.QUEUED:
                return queued
        await self._write_artifact(experiment.id, experiment.organization_id, "experiment", "", experiment)
        return experiment

    async def get_experiment(self, organization_id: UUID, experiment_id: UUID) -> ExperimentRequest | None:
        return await self._get(organization_id, experiment_id, "experiment", load_experiment)

    async def save_evaluation(self, evaluation: EvaluationRecord) -> EvaluationRecord:
        await self._write_artifact(evaluation.id, evaluation.organization_id, "evaluation", "", evaluation)
        return evaluation

    async def save_recommendation(self, recommendation: Recommendation) -> Recommendation:
        await self._write_artifact(
            recommendation.id, recommendation.organization_id, "recommendation", "", recommendation
        )
        return recommendation

    async def list_recommendations(self, organization_id: UUID) -> list[Recommendation]:
        rows = await self._rows(
            """
            SELECT payload FROM learning_artifacts
            WHERE organization_id = :oid AND kind = 'recommendation'
            ORDER BY updated_at DESC LIMIT 100
            """,
            {"oid": organization_id},
        )
        return [load_recommendation(row["payload"]) for row in rows]

    async def get_recommendation(self, organization_id: UUID, recommendation_id: UUID) -> Recommendation | None:
        return await self._get(organization_id, recommendation_id, "recommendation", load_recommendation)

    async def save_promotion(self, promotion: PromotionAudit) -> PromotionAudit:
        await self._write_artifact(promotion.id, promotion.organization_id, "promotion", "", promotion)
        return promotion

    async def get_promotion(self, organization_id: UUID, promotion_id: UUID) -> PromotionAudit | None:
        return await self._get(organization_id, promotion_id, "promotion", load_promotion)

    async def list_promotions(self, organization_id: UUID) -> list[PromotionAudit]:
        rows = await self._rows(
            """
            SELECT payload FROM learning_artifacts
            WHERE organization_id = :oid AND kind = 'promotion'
            ORDER BY updated_at DESC LIMIT 100
            """,
            {"oid": organization_id},
        )
        return [load_promotion(row["payload"]) for row in rows]

    async def save_comparison(self, comparison: StrategyComparison) -> StrategyComparison:
        key = f"{comparison.kind}:{comparison.pattern_key}:{comparison.window}"
        row = await self._one(
            """
            SELECT id, payload FROM learning_artifacts
            WHERE organization_id = :oid AND kind = 'comparison' AND dedupe_key = :key
            """,
            {"oid": comparison.organization_id, "key": key},
        )
        if row is not None:
            current = load_comparison(row["payload"])
            current.rows = list(comparison.rows)
            current.sample_size = comparison.sample_size
            current.confidence = comparison.confidence
            current.validated_memory_id = comparison.validated_memory_id
            current.judgment_signal = comparison.judgment_signal
            await self._write_artifact(current.id, current.organization_id, "comparison", key, current)
            return current
        await self._write_artifact(comparison.id, comparison.organization_id, "comparison", key, comparison)
        return comparison

    async def list_comparisons(self, organization_id: UUID, *, kind: str | None = None) -> list[StrategyComparison]:
        rows = await self._rows(
            """
            SELECT payload FROM learning_artifacts
            WHERE organization_id = :oid AND kind = 'comparison'
            ORDER BY updated_at DESC LIMIT 100
            """,
            {"oid": organization_id},
        )
        items = [load_comparison(row["payload"]) for row in rows]
        if kind:
            items = [item for item in items if item.kind == kind]
        return items

    async def save_finding(self, finding: Finding) -> Finding:
        await self._write_artifact(finding.id, finding.organization_id, "finding", finding.dedupe_key, finding)
        return finding

    async def save_hypothesis(self, hypothesis: Hypothesis) -> Hypothesis:
        await self._write_artifact(
            hypothesis.id, hypothesis.organization_id, "hypothesis", str(hypothesis.finding_id), hypothesis
        )
        return hypothesis

    async def organizations_with_recent_signals(self, start: datetime) -> list[UUID]:
        rows = await self._rows(
            """
            SELECT DISTINCT organization_id FROM learning_signals
            WHERE occurred_at >= :start
            LIMIT 50
            """,
            {"start": start},
        )
        found: list[UUID] = []
        for row in rows:
            value = row["organization_id"]
            found.append(value if isinstance(value, UUID) else UUID(str(value)))
        return found

    async def save_conflict(self, conflict):
        await self._write_artifact(conflict.id, conflict.organization_id, "conflict", "", conflict)
        return conflict

    async def get_conflict(self, organization_id: UUID, conflict_id: UUID):
        return await self._get(organization_id, conflict_id, "conflict", load_conflict)

    async def _get(self, organization_id: UUID, item_id: UUID, kind: str, loader):
        row = await self._one(
            """
            SELECT payload FROM learning_artifacts
            WHERE organization_id = :oid AND kind = :kind AND id = :id
            """,
            {"oid": organization_id, "kind": kind, "id": item_id},
        )
        if row is None:
            return None
        return loader(row["payload"])

    async def _write_artifact(self, item_id: UUID, organization_id: UUID, kind: str, dedupe_key: str, obj: Any) -> None:
        await self._exec(
            """
            INSERT INTO learning_artifacts (id, organization_id, kind, dedupe_key, payload)
            VALUES (:id, :oid, :kind, :dedupe, CAST(:payload AS jsonb))
            ON CONFLICT (id) DO UPDATE
            SET payload = EXCLUDED.payload, dedupe_key = EXCLUDED.dedupe_key, updated_at = NOW()
            """,
            {
                "id": item_id,
                "oid": organization_id,
                "kind": kind,
                "dedupe": dedupe_key,
                "payload": dump(obj),
            },
        )

    async def _one(self, sql: str, params: dict) -> dict | None:
        rows = await self._rows(sql, params)
        return rows[0] if rows else None

    async def _rows(self, sql: str, params: dict) -> list[dict]:
        session = await get_async_session()
        try:
            result = await session.execute(text(sql), params)
            return [dict(row) for row in result.mappings().all()]
        finally:
            await session.close()

    async def _exec(self, sql: str, params: dict) -> None:
        session = await get_async_session()
        try:
            await session.execute(text(sql), params)
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
