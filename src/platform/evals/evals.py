# =============================================================================
# AI Quality & Evals v2
# Datasets versionados, runs con scoring heurístico, gate de promo y
# detección de regresión con auto-rollback.
# =============================================================================
from __future__ import annotations

import asyncio
import re
from uuid import UUID

from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9áéíóúñü]{2,}", (text or "").lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def score_answer(answer: str, expected: str, context: str | None) -> dict:
    """Heurística sin LLM extra: solapamiento semántico + groundedness."""
    a_tok, e_tok = _tokens(answer), _tokens(expected)
    c_tok = _tokens(context) if context else set()
    similarity = _jaccard(a_tok, e_tok)
    if answer.strip().lower() == expected.strip().lower():
        similarity = 1.0
    grounded = _jaccard(a_tok, e_tok | c_tok) if (e_tok | c_tok) else 0.0
    faithfulness = min(1.0, grounded)
    hallucination = max(0.0, 1.0 - faithfulness)
    score = round(similarity * 100, 1)
    return {
        "score": score,
        "faithfulness": round(faithfulness, 3),
        "hallucination_rate": round(hallucination, 3),
    }


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------
async def create_dataset(organization_id: UUID, name: str, description: str | None, created_by: UUID | None) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO eval_v2_datasets (id, organization_id, name, description, "
                    "created_by) VALUES (gen_random_uuid(), :oid, :name, :desc, :by) "
                    "RETURNING id, name, version, status"
                ),
                {"oid": organization_id, "name": name, "desc": description, "by": created_by},
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {"id": str(row.id), "name": row.name, "version": int(row.version), "status": row.status}


async def list_datasets(organization_id: UUID | None = None) -> list[dict]:
    session = await get_async_session()
    try:
        sql = (
            "SELECT d.id, d.organization_id, d.name, d.description, d.version, d.status, "
            "d.created_at, (SELECT COUNT(*) FROM eval_v2_items i WHERE i.dataset_id = d.id) AS items "
            "FROM eval_v2_datasets d WHERE 1=1 "
        )
        params: dict = {}
        if organization_id is not None:
            sql += " AND d.organization_id = :oid "
            params["oid"] = organization_id
        sql += " ORDER BY d.created_at DESC"
        rows = (await session.execute(text(sql), params)).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "organization_id": str(r.organization_id),
            "name": r.name,
            "description": r.description,
            "version": int(r.version),
            "status": r.status,
            "items": int(r.items or 0),
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


async def add_dataset_items(dataset_id: UUID, items: list[dict], bump_version: bool = True) -> dict:
    session = await get_async_session()
    try:
        dataset = (
            await session.execute(
                text("SELECT organization_id, version FROM eval_v2_datasets WHERE id = :did"),
                {"did": dataset_id},
            )
        ).fetchone()
        if dataset is None:
            return {"status": "not_found"}
        for item in items:
            await session.execute(
                text(
                    "INSERT INTO eval_v2_items (id, dataset_id, question, expected_answer, "
                    "context, score_weight) VALUES (gen_random_uuid(), :did, :q, :e, :ctx, :w)"
                ),
                {
                    "did": dataset_id,
                    "q": item["question"],
                    "e": item["expected_answer"],
                    "ctx": item.get("context"),
                    "w": item.get("score_weight", 1.0),
                },
            )
        new_version = int(dataset.version) + 1 if bump_version else int(dataset.version)
        await session.execute(
            text(
                "UPDATE eval_v2_datasets SET version = :v, status = 'active', "
                "updated_at = NOW() WHERE id = :did"
            ),
            {"v": new_version, "did": dataset_id},
        )
        await session.commit()
        return {"status": "saved", "items_added": len(items), "version": new_version}
    finally:
        await session.close()


async def list_items(dataset_id: UUID) -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, question, expected_answer, context, score_weight "
                    "FROM eval_v2_items WHERE dataset_id = :did ORDER BY created_at"
                ),
                {"did": dataset_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "question": r.question,
            "expected_answer": r.expected_answer,
            "context": r.context,
            "score_weight": float(r.score_weight or 1.0),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------
async def trigger_run(
    organization_id: UUID,
    dataset_id: UUID,
    agent_id: UUID,
    runtime,
    auto_promote: bool = False,
    auto_rollback: bool = False,
    created_by: UUID | None = None,
) -> dict:
    from src.infrastructure.postgres.relational_db import PostgresAgentRepository

    session = await get_async_session()
    try:
        dataset = (
            await session.execute(
                text(
                    "SELECT version FROM eval_v2_datasets WHERE id = :did AND organization_id = :oid"
                ),
                {"did": dataset_id, "oid": organization_id},
            )
        ).fetchone()
        if dataset is None:
            return {"status": "dataset_not_found"}
        items = (
            await session.execute(
                text(
                    "SELECT id, question, expected_answer, context, score_weight "
                    "FROM eval_v2_items WHERE dataset_id = :did"
                ),
                {"did": dataset_id},
            )
        ).fetchall()
    finally:
        await session.close()
    if not items:
        return {"status": "empty_dataset"}

    agent = await PostgresAgentRepository().get_agent(organization_id, agent_id)
    if agent is None:
        return {"status": "agent_not_found"}

    run_id = (
        await session.execute(
            text(
                "INSERT INTO eval_v2_runs (id, organization_id, dataset_id, dataset_version, "
                "agent_id, model, created_by) VALUES (gen_random_uuid(), :oid, :did, :dv, "
                ":aid, :model, :by) RETURNING id"
            ),
            {
                "oid": organization_id,
                "did": dataset_id,
                "dv": int(dataset.version),
                "aid": agent_id,
                "model": agent.model,
                "by": created_by,
            },
        )
    ).scalar()
    await session.commit()

    asyncio.get_running_loop().create_task(
        _execute_run(
            organization_id, run_id, agent, dataset_id, int(dataset.version),
            [dict(r._mapping) for r in items], runtime, auto_promote, auto_rollback,
        )
    )
    return {"status": "started", "run_id": str(run_id)}


async def _execute_run(
    organization_id: UUID,
    run_id: UUID,
    agent,
    dataset_id: UUID,
    dataset_version: int,
    items: list[dict],
    runtime,
    auto_promote: bool,
    auto_rollback: bool,
) -> None:
    from src.agents.runtime.agent_runtime import AgentRunRequest

    settings = get_settings()
    latencies: list[float] = []
    total_cost = 0.0
    results: list[dict] = []
    try:
        for item in items:
            try:
                result = await runtime.run(
                    AgentRunRequest(
                        agent=agent,
                        message=item["question"],
                        user_id=None,
                        permissions=frozenset(),
                        org_config={},
                    )
                )
                answer = result.answer or ""
                scored = score_answer(answer, item["expected_answer"], item.get("context"))
                latencies.append(result.total_latency_ms)
                total_cost += result.cost
                results.append(
                    {
                        "item_id": item["id"],
                        "question": item["question"],
                        "answer": answer[:2000],
                        "expected_answer": item["expected_answer"],
                        **scored,
                        "latency_ms": result.total_latency_ms,
                        "cost": result.cost,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Eval item failed", error=str(exc)[:150])
                results.append(
                    {
                        "item_id": item["id"],
                        "question": item["question"],
                        "answer": "",
                        "expected_answer": item["expected_answer"],
                        "score": 0.0,
                        "faithfulness": 0.0,
                        "hallucination_rate": 1.0,
                        "latency_ms": 0.0,
                        "cost": 0.0,
                    }
                )

        weights = [max(float(i.get("score_weight") or 1.0), 0.0) for i in items]
        total_w = sum(weights) or 1.0
        score_overall = sum(r["score"] * w for r, w in zip(results, weights)) / total_w
        faithfulness = sum(r["faithfulness"] * w for r, w in zip(results, weights)) / total_w
        hallucination = sum(r["hallucination_rate"] * w for r, w in zip(results, weights)) / total_w
        p95 = sorted(latencies)[int(len(latencies) * 0.95) - 1] if latencies else 0.0

        passed_gate = (
            score_overall >= settings.EVAL_PROMOTION_MIN_SCORE
            and hallucination <= settings.EVAL_PROMOTION_MAX_HALLUCINATION
        )

        # Regresión vs mejor run previo del mismo agente.
        regression = False
        session = await get_async_session()
        try:
            best = (
                await session.execute(
                    text(
                        "SELECT score_overall, faithfulness, hallucination_rate FROM eval_v2_runs "
                        "WHERE agent_id = :aid AND dataset_id = :did AND status = 'completed' "
                        "AND id <> :rid ORDER BY score_overall DESC LIMIT 1"
                    ),
                    {"aid": agent.id, "did": dataset_id, "rid": run_id},
                )
            ).fetchone()
            if best is not None and best.score_overall is not None:
                regression = (
                    score_overall < best.score_overall - settings.EVAL_REGRESSION_QUALITY_MIN_DELTA
                    or faithfulness < (best.faithfulness or 0) - settings.EVAL_REGRESSION_FAITHFULNESS_MIN_DELTA
                    or hallucination > (best.hallucination_rate or 1) - settings.EVAL_REGRESSION_HALLUCINATION_MAX_DELTA
                )
        finally:
            await session.close()

        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE eval_v2_runs SET status = 'completed', score_overall = :s, "
                    "faithfulness = :f, hallucination_rate = :h, latency_p95 = :p, "
                    "cost_total = :c, passed_gate = :gate, regression = :reg, "
                    "completed_at = NOW() WHERE id = :rid"
                ),
                {
                    "s": round(score_overall, 2),
                    "f": round(faithfulness, 3),
                    "h": round(hallucination, 3),
                    "p": round(p95, 1),
                    "c": round(total_cost, 6),
                    "gate": passed_gate,
                    "reg": regression,
                    "rid": run_id,
                },
            )
            for r in results:
                await session.execute(
                    text(
                        "INSERT INTO eval_v2_run_items (id, run_id, item_id, question, "
                        "answer, expected_answer, score, faithfulness, hallucination_rate, "
                        "latency_ms, cost) VALUES (gen_random_uuid(), :rid, :iid, :q, :a, :e, "
                        ":s, :f, :h, :lat, :cost)"
                    ),
                    {
                        "rid": run_id,
                        "iid": r["item_id"],
                        "q": r["question"],
                        "a": r["answer"],
                        "e": r["expected_answer"],
                        "s": r["score"],
                        "f": r["faithfulness"],
                        "h": r["hallucination_rate"],
                        "lat": r["latency_ms"],
                        "cost": r["cost"],
                    },
                )
            await session.commit()
        finally:
            await session.close()

        # Auto-acciones.
        if auto_promote and passed_gate and not regression:
            await _promote_version(organization_id, agent.id)
        if auto_rollback and regression:
            await _rollback_deployment(organization_id, agent.id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Eval run failed", run_id=str(run_id), error=str(exc)[:200])
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE eval_v2_runs SET status = 'failed', completed_at = NOW() "
                    "WHERE id = :rid"
                ),
                {"rid": run_id},
            )
            await session.commit()
        finally:
            await session.close()


async def _promote_version(organization_id: UUID, agent_id: UUID) -> None:
    from src.infrastructure.postgres.relational_db import (
        PostgresAgentVersionRepository,
    )
    from src.platform.deployments.versions import promote_version

    try:
        session = await get_async_session()
        try:
            version = (
                await session.execute(
                    text(
                        "SELECT id FROM agent_versions WHERE agent_id = :aid "
                        "AND status IN ('draft', 'pending') ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"aid": agent_id},
                )
            ).fetchone()
        finally:
            await session.close()
        if version:
            await promote_version(
                PostgresAgentVersionRepository(),
                organization_id,
                agent_id,
                version.id,
                status="ready",
            )
            logger.info("Eval gate: version promoted", version_id=str(version.id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Eval auto-promote failed", error=str(exc)[:200])


async def _rollback_deployment(organization_id: UUID, agent_id: UUID) -> None:
    from src.infrastructure.postgres.relational_db import PostgresDeploymentRepository
    from src.platform.deployments.deployments import rollback_deployment

    try:
        session = await get_async_session()
        try:
            dep = (
                await session.execute(
                    text(
                        "SELECT id FROM deployments WHERE agent_id = :aid "
                        "AND organization_id = :oid AND status = 'healthy' "
                        "ORDER BY deployed_at DESC LIMIT 1"
                    ),
                    {"aid": agent_id, "oid": organization_id},
                )
            ).fetchone()
        finally:
            await session.close()
        if dep:
            await rollback_deployment(
                PostgresDeploymentRepository(), organization_id, dep.id
            )
            logger.info("Eval regression: deployment rolled back", deployment_id=str(dep.id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Eval auto-rollback failed", error=str(exc)[:200])


async def list_runs(organization_id: UUID | None, status: str | None = None, limit: int = 50) -> list[dict]:
    session = await get_async_session()
    try:
        sql = (
            "SELECT id, organization_id, dataset_id, dataset_version, agent_id, "
            "agent_version_id, model, status, score_overall, faithfulness, "
            "hallucination_rate, latency_p95, cost_total, passed_gate, regression, "
            "started_at, completed_at FROM eval_v2_runs WHERE 1=1 "
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
            "organization_id": str(r.organization_id),
            "dataset_id": str(r.dataset_id),
            "dataset_version": int(r.dataset_version),
            "agent_id": str(r.agent_id),
            "agent_version_id": str(r.agent_version_id) if r.agent_version_id else None,
            "model": r.model,
            "status": r.status,
            "score_overall": r.score_overall,
            "faithfulness": r.faithfulness,
            "hallucination_rate": r.hallucination_rate,
            "latency_p95": r.latency_p95,
            "cost_total": r.cost_total,
            "passed_gate": r.passed_gate,
            "regression": bool(r.regression),
            "started_at": r.started_at.isoformat(),
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in rows
    ]


async def get_run_detail(run_id: UUID) -> dict | None:
    session = await get_async_session()
    try:
        run = (
            await session.execute(
                text(
                    "SELECT * FROM eval_v2_runs WHERE id = :rid"
                ),
                {"rid": run_id},
            )
        ).fetchone()
        if run is None:
            return None
        items = (
            await session.execute(
                text(
                    "SELECT question, answer, expected_answer, score, faithfulness, "
                    "hallucination_rate, latency_ms, cost FROM eval_v2_run_items "
                    "WHERE run_id = :rid"
                ),
                {"rid": run_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "id": str(run.id),
        "dataset_id": str(run.dataset_id),
        "dataset_version": int(run.dataset_version),
        "agent_id": str(run.agent_id),
        "model": run.model,
        "status": run.status,
        "score_overall": run.score_overall,
        "faithfulness": run.faithfulness,
        "hallucination_rate": run.hallucination_rate,
        "latency_p95": run.latency_p95,
        "cost_total": run.cost_total,
        "passed_gate": run.passed_gate,
        "regression": bool(run.regression),
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "items": [
            {
                "question": r.question,
                "answer": r.answer,
                "expected_answer": r.expected_answer,
                "score": r.score,
                "faithfulness": r.faithfulness,
                "hallucination_rate": r.hallucination_rate,
                "latency_ms": r.latency_ms,
                "cost": r.cost,
            }
            for r in items
        ],
    }
