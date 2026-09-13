# =============================================================================
# Shadow Evaluator — Phase 8
# =============================================================================
# Ejecuta el MISMO query dos veces (baseline single-specialist vs cognitive
# completo), compara métricas y persiste el veredicto. La respuesta visible no
# cambia: es una señal de promoción (brief §64/§79).
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

from src.core.domain.cognitive import (
    CognitiveBudget,
    CognitiveRun,
    CognitiveScope,
    CognitiveTask,
    CognitiveTaskGraph,
    classify_complexity,
)
from src.core.domain.shadow import (
    ShadowComparison,
    ShadowMetrics,
    compare_shadow,
)
from src.core.ports.cognitive import CognitiveRepository
from src.core.ports.shadow import ShadowRepository
from src.platform.cognitive.orchestrator import (
    CognitivePlan,
    KnowledgeCognitiveOrchestrator,
)
from src.platform.cognitive.registry import default_registry

_BASELINE_BUDGET = CognitiveBudget(
    max_agents=3,
    max_llm_calls=4,
    max_tokens=12000,
    max_cost_usd=0.6,
    max_seconds=90.0,
    max_tool_calls=6,
)


def metrics_from_result(result: dict) -> ShadowMetrics:
    data = result.get("metrics") or {}
    return ShadowMetrics(
        evidence_count=int(data.get("evidence_count", 0)),
        claims=int(data.get("claims", 0)),
        supported=int(data.get("supported", 0)),
        partial=int(data.get("partial", 0)),
        unsupported=int(data.get("unsupported", 0)),
        outdated=int(data.get("outdated", 0)),
        conflicted=int(data.get("conflicted", 0)),
        conflicts=int(data.get("conflicts", 0)),
        critique_issues=int(data.get("critique_issues", 0)),
        debate_outcomes=int(data.get("debate_outcomes", 0)),
        llm_calls=int(data.get("llm_calls", 0)),
        tokens=int(data.get("tokens", 0)),
        cost_usd=float(data.get("cost_usd", 0.0)),
        latency_ms=float(data.get("latency_ms", 0.0)),
        has_answer=bool(data.get("has_answer", False)),
    )


class ShadowEvaluator:
    def __init__(
        self,
        repository: ShadowRepository,
        cognitive_repo: CognitiveRepository,
        executor,
        orchestrator: KnowledgeCognitiveOrchestrator | None = None,
    ) -> None:
        self._repo = repository
        self._cognitive = cognitive_repo
        self._executor = executor
        self._orchestrator = orchestrator or KnowledgeCognitiveOrchestrator()

    async def evaluate(
        self, *, organization_id: UUID, query: str, scope: CognitiveScope
    ) -> ShadowComparison:
        baseline_plan = self._baseline_plan(query=query, scope=scope)
        cognitive_plan = self._orchestrator.plan(query=query, scope=scope)

        baseline_result = await self._execute_plan(baseline_plan, scope)
        cognitive_result = await self._execute_plan(cognitive_plan, scope)

        baseline_metrics = metrics_from_result(baseline_result)
        cognitive_metrics = metrics_from_result(cognitive_result)
        verdict, reasons = compare_shadow(
            baseline=baseline_metrics, cognitive=cognitive_metrics
        )

        comparison = ShadowComparison(
            organization_id=organization_id,
            workspace_id=scope.workspace_id,
            query=query,
            level=classify_complexity(query),
            baseline=baseline_metrics,
            cognitive=cognitive_metrics,
            verdict=verdict,
            reasons=reasons,
            baseline_run_id=baseline_plan.run.id,
            cognitive_run_id=cognitive_plan.run.id,
        )
        return await self._repo.save(comparison)

    async def _execute_plan(self, plan: CognitivePlan, scope: CognitiveScope) -> dict:
        await self._cognitive.create_run(plan.run)
        await self._cognitive.save_tasks(
            organization_id=scope.organization_id, tasks=plan.graph.tasks
        )
        return await self._executor.execute_run(
            organization_id=scope.organization_id,
            run_id=plan.run.id,
            scope=scope,
        )

    def _baseline_plan(
        self, *, query: str, scope: CognitiveScope
    ) -> CognitivePlan:
        run_id = uuid4()
        blueprint = (
            ("locate_sources", "librarian", (), "Localizar fuentes autorizadas."),
            (
                "retrieve",
                "retrieval_strategist",
                ("locate_sources",),
                "Recuperar evidencia.",
            ),
            (
                "synthesize",
                "synthesizer",
                ("retrieve",),
                "Responder con la evidencia recuperada (single-specialist).",
            ),
        )
        tasks = tuple(
            CognitiveTask(
                run_id=run_id,
                key=key,
                description=description,
                agent_id=agent_id,
                depends_on=depends_on,
                position=position,
                budget=_BASELINE_BUDGET,
                input_scope=scope.to_dict(),
            )
            for position, (key, agent_id, depends_on, description) in enumerate(
                blueprint
            )
        )
        graph = CognitiveTaskGraph(tasks=tasks)
        run = CognitiveRun(
            id=run_id,
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            query=query,
            complexity=classify_complexity(query),
            budget=_BASELINE_BUDGET,
            scope=scope.to_dict(),
            plan={"mode": "baseline"},
        )
        registry = default_registry()
        definitions = tuple(
            definition
            for definition in (
                registry.get("librarian"),
                registry.get("retrieval_strategist"),
                registry.get("synthesizer"),
            )
            if definition is not None
        )
        return CognitivePlan(
            run=run, graph=graph, definitions=definitions, budget=_BASELINE_BUDGET
        )
