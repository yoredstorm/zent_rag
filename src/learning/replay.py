# =============================================================================
# Evaluation Replay — antes/después de cambios de conocimiento aprobados
# =============================================================================
# Al aprobar métrica/relación/glosario/enum/autoridad, ejecuta (o permite
# ejecutar) los casos de evaluación afectados. Verdict determinista: pass si
# el after no regresa vs before; fail si regresa. Los cambios críticos sin
# evaluación no se promueven cuando la política lo requiere.
# =============================================================================
from __future__ import annotations

import re
from uuid import UUID

from src.core.domain.learning import LearningReplay, ReplayVerdict
from src.infrastructure.observability.logging_config import get_logger
from src.learning.store import PostgresLearningStore

logger = get_logger(__name__)

EVAL_REPLAY_JOB_PREFIX = "eval_replay"

_TOKEN_RE = re.compile(r"[a-zA-ZáéíóúñüÁÉÍÓÚÑÜ0-9_]+")


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) > 1}


class EvaluationReplayService:
    """Replay de evaluación sobre conocimiento aprobado (job durable)."""

    def __init__(
        self,
        store: PostgresLearningStore,
        job_repo=None,
        orchestrator=None,
    ) -> None:
        self._store = store
        self._jobs = job_repo
        self._orchestrator = orchestrator

    async def start(
        self,
        *,
        organization_id: UUID,
        knowledge_type: str,
        knowledge_id: str,
        trigger: str = "manual",
    ) -> UUID | None:
        """Crea el replay (queued) y encola el job eval_replay:*."""
        replay = LearningReplay(
            organization_id=organization_id,
            knowledge_type=knowledge_type,
            knowledge_id=str(knowledge_id),
            trigger=trigger,
            status="queued",
        )
        replay_id = await self._store.create_replay(replay)
        if self._jobs is None:
            return replay_id
        try:
            from src.knowledge.queue import enqueue_knowledge_job

            job = await self._jobs.create_job(
                organization_id,
                job_type=f"{EVAL_REPLAY_JOB_PREFIX}:{knowledge_type}",
                source_id=None,
                knowledge_base_id=None,
            )
            await self._jobs.update_job(
                job.id, cursor_snapshot={"replay_id": str(replay_id)}
            )
            await enqueue_knowledge_job(str(job.id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Replay job enqueue failed", error=str(exc)[:200])
        return replay_id

    async def execute(self, replay_id: UUID) -> dict:
        """Ejecuta el replay: casos afectados -> before/after -> verdict."""
        replay_row = await self._get_replay(replay_id)
        if replay_row is None:
            raise ValueError(f"Replay {replay_id} not found")
        org = UUID(replay_row["organization_id"])
        await self._store.update_replay(replay_id, status="running")

        try:
            cases, datasets = await self._affected_cases(
                org, replay_row["knowledge_id"]
            )
            if not cases:
                await self._store.update_replay(
                    replay_id,
                    status="completed",
                    verdict="unknown",
                    after={"datasets": len(datasets), "cases": 0},
                    error="no affected cases",
                )
                return await self._get_replay(replay_id) or {}

            before = await self._baseline(org, datasets)
            after = await self._run_eval(org, cases)
            verdict = self._verdict(before, after)

            eval_run_id = after.get("run_id")
            await self._store.update_replay(
                replay_id,
                status="completed",
                verdict=verdict,
                eval_run_id=UUID(eval_run_id) if eval_run_id else None,
                before=before,
                after=after,
            )
            return await self._get_replay(replay_id) or {}
        except Exception as exc:  # noqa: BLE001
            logger.error("Evaluation replay failed", replay_id=str(replay_id), error=str(exc))
            await self._store.update_replay(
                replay_id, status="failed", error=f"{type(exc).__name__}: {exc}"[:2000]
            )
            return await self._get_replay(replay_id) or {}

    # ---------------------------------------------------------------- helpers
    async def _get_replay(self, replay_id: UUID) -> dict | None:
        return await self._store.get_replay(replay_id)

    async def _affected_cases(
        self, organization_id: UUID, knowledge_id: str
    ) -> tuple[list[dict], list[str]]:
        """Golden cases cuyo question/concepto intersecta el conocimiento."""
        from sqlalchemy import text

        from src.infrastructure.postgres.session import get_async_session

        tokens = _tokens(knowledge_id)
        if not tokens:
            return [], []
        cases_out: list[dict] = []
        datasets: list[str] = []
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, name, cases FROM eval_datasets "
                        "WHERE organization_id = :oid ORDER BY created_at DESC LIMIT 20"
                    ),
                    {"oid": organization_id},
                )
            ).fetchall()
        finally:
            await session.close()
        for row in rows:
            for case in (row.cases or []):
                if not isinstance(case, dict):
                    continue
                question = str(case.get("question") or "")
                if tokens & _tokens(question) or case.get("expected_answerability"):
                    cases_out.append(case)
                    datasets.append(str(row.id))
        return cases_out[:50], list(dict.fromkeys(datasets))[:5]

    async def _baseline(
        self, organization_id: UUID, dataset_ids: list[str]
    ) -> dict:
        """Último run de evaluación para los datasets afectados (before)."""
        from src.rag.evaluation.store import list_eval_runs

        best: dict | None = None
        runs = await list_eval_runs(organization_id, limit=20)
        for run in runs:
            dataset_id = str(run.get("dataset_id") or "")
            if dataset_ids and dataset_id not in dataset_ids:
                continue
            quality = run.get("quality") or {}
            if best is None or (quality.get("composite_score") or 0) > (
                (best.get("quality") or {}).get("composite_score") or 0
            ):
                best = run
        if best is None:
            return {"baseline": "no previous run"}
        return {
            "dataset_id": str(best.get("dataset_id") or ""),
            "composite_score": (best.get("quality") or {}).get("composite_score"),
            "answerability_accuracy": (best.get("quality") or {}).get(
                "answerability_accuracy"
            ),
        }

    async def _run_eval(
        self, organization_id: UUID, cases: list[dict]
    ) -> dict:
        """Ejecuta EvalRunner sobre los casos afectados (judge off -> determinista)."""
        from src.rag.evaluation.datasets import load_dataset
        from src.rag.evaluation.runner import EvalRunner
        from src.rag.evaluation.store import save_eval_run
        from src.rag.evaluation.targets import RAGTarget

        dataset = load_dataset(cases, name="replay-affected")
        target = RAGTarget(
            self._orchestrator,
            organization_id,
            organization_id,  # user_id placeholder (org default user)
            target_name="learning-replay",
        )
        runner = EvalRunner(target, judge=None)
        summary = await runner.run(dataset)
        summary["dataset_name"] = f"replay-{dataset.name}"
        summary["target_type"] = "rag"
        try:
            run_id = await save_eval_run(organization_id, summary)
            summary["run_id"] = str(run_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Replay run save failed", error=str(exc)[:200])
        quality = summary.get("quality") or {}
        return {
            "run_id": summary.get("run_id"),
            "cases": len(cases),
            "composite_score": quality.get("composite_score"),
            "answerability_accuracy": quality.get("answerability_accuracy"),
            "hallucination_rate": quality.get("hallucination_rate"),
        }

    @staticmethod
    def _verdict(before: dict, after: dict) -> str:
        if "cases" in after and after.get("cases", 0) == 0:
            return ReplayVerdict.UNKNOWN.value
        before_score = before.get("composite_score")
        after_score = after.get("composite_score")
        if before_score is None or after_score is None:
            return ReplayVerdict.WARN.value
        delta = after_score - before_score
        if delta >= -0.05:
            return ReplayVerdict.PASSED.value
        if delta >= -0.15:
            return ReplayVerdict.WARN.value
        return ReplayVerdict.FAIL.value
