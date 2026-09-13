# =============================================================================
# Cognitive OS — Phase 3 domain: complexity, task graph, registry, planner
# =============================================================================
# Planificación/delegación determinista (sin LLM). Nada se ejecuta en esta
# fase: el planner produce el CognitiveTaskGraph y el supervisor lo valida.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.cognitive import (
    AgentMessage,
    AgentMessageType,
    CognitiveBudget,
    CognitiveRunStatus,
    CognitiveScope,
    CognitiveTask,
    CognitiveTaskGraph,
    ComplexityLevel,
    EvidenceBlackboard,
    classify_complexity,
)
from src.platform.cognitive.orchestrator import (
    CognitivePlan,
    KnowledgeCognitiveOrchestrator,
)
from src.platform.cognitive.registry import default_registry


def test_complexity_classifier_maps_brief_examples() -> None:
    assert classify_complexity("¿Qué significa SLA?") is ComplexityLevel.L0_DIRECT
    assert (
        classify_complexity("¿Dónde aparece la política de vacaciones?")
        is ComplexityLevel.L1_RETRIEVAL
    )
    assert (
        classify_complexity("Resume las obligaciones de este contrato.")
        is ComplexityLevel.L2_ANALYSIS
    )
    assert (
        classify_complexity("Compara el contrato y la adenda.")
        is ComplexityLevel.L3_MULTI_SOURCE
    )
    assert (
        classify_complexity(
            "Analiza todos los contratos de proveedores, identifica riesgos, "
            "contradicciones y cambios en los últimos tres años."
        )
        is ComplexityLevel.L5_DEEP_INVESTIGATION
    )


def test_cognitive_budget_validation() -> None:
    default = CognitiveBudget()
    assert default.max_debate_rounds == 0
    with pytest.raises(ValueError):
        CognitiveBudget(max_agents=0)
    with pytest.raises(ValueError):
        CognitiveBudget(max_debate_rounds=-1)
    with pytest.raises(ValueError):
        CognitiveBudget(max_cost_usd=0)


def test_task_graph_detects_cycles_duplicates_and_orders() -> None:
    run_id = uuid4()
    a = CognitiveTask(run_id=run_id, key="a", description="A")
    b = CognitiveTask(run_id=run_id, key="b", description="B", depends_on=("a",))
    c = CognitiveTask(run_id=run_id, key="c", description="C", depends_on=("b",))
    graph = CognitiveTaskGraph(tasks=(c, a, b))
    assert graph.ready_keys(set()) == ("a",)
    assert graph.ready_keys({"a"}) == ("b",)
    assert graph.topological_order() == ("a", "b", "c")

    cycle = (
        CognitiveTask(run_id=run_id, key="x", description="X", depends_on=("y",)),
        CognitiveTask(run_id=run_id, key="y", description="Y", depends_on=("x",)),
    )
    with pytest.raises(ValueError):
        CognitiveTaskGraph(tasks=cycle)
    with pytest.raises(ValueError):
        CognitiveTaskGraph(
            tasks=(
                CognitiveTask(
                    run_id=run_id, key="z", description="Z", depends_on=("missing",)
                ),
            )
        )
    with pytest.raises(ValueError):
        CognitiveTaskGraph(
            tasks=(a, CognitiveTask(run_id=run_id, key="a", description="dup"))
        )


def test_message_and_blackboard() -> None:
    run_id = uuid4()
    message = AgentMessage(
        run_id=run_id,
        type=AgentMessageType.FINDING,
        from_agent="temporal_analyst",
        text="La adenda cambia la penalidad",
        evidence_ids=(uuid4(),),
        confidence=0.96,
    )
    blackboard = EvidenceBlackboard(run_id=run_id)
    blackboard.record_message(message)
    blackboard.record_finding(
        text="La penalidad es 7%",
        subject="penalidad",
        predicate="es",
        object_value="7%",
        evidence_ids=(uuid4(),),
        confidence=0.9,
    )
    blackboard.record_question("¿Existe una adenda vigente?")
    blackboard.record_conflict(
        from_claim_id=uuid4(), to_claim_id=uuid4(), reason="valores distintos"
    )
    snapshot = blackboard.snapshot()
    assert snapshot["messages"] == 1
    assert snapshot["findings"] == 1
    assert snapshot["questions"] == 1
    assert snapshot["conflicts"] == 1
    assert len(snapshot["evidence_ids"]) == 2

    with pytest.raises(ValueError):
        AgentMessage(
            run_id=run_id, type=AgentMessageType.FINDING, from_agent="", text="x"
        )


def test_registry_declarative_selection() -> None:
    registry = default_registry()
    ids = {definition.id for definition in registry.list()}
    assert {
        "librarian",
        "retrieval_strategist",
        "document_analyst",
        "data_analyst",
        "temporal_analyst",
        "policy_analyst",
        "conflict_detector",
        "critic",
        "fact_checker",
        "synthesizer",
    } <= ids
    l4 = registry.select_for_level(ComplexityLevel.L4_MULTI_SPECIALIST)
    assert "temporal_analyst" in {definition.id for definition in l4}
    assert registry.get("missing") is None


def test_planner_builds_graph_per_level_and_respects_budget() -> None:
    orchestrator = KnowledgeCognitiveOrchestrator()
    scope = CognitiveScope(organization_id=uuid4())

    simple = orchestrator.plan(
        query="¿Dónde aparece la política de vacaciones?", scope=scope
    )
    assert isinstance(simple, CognitivePlan)
    assert simple.run.complexity is ComplexityLevel.L1_RETRIEVAL
    assert simple.run.status is CognitiveRunStatus.PLANNED
    assert len(simple.graph.tasks) >= 2
    assert simple.graph.topological_order()
    # las tareas pertenecen al run planificado (no a un id distinto)
    assert {task.run_id for task in simple.graph.tasks} == {simple.run.id}

    deep = orchestrator.plan(
        query=(
            "Analiza todos los contratos de proveedores, identifica riesgos, "
            "contradicciones y cambios en los últimos tres años."
        ),
        scope=scope,
    )
    assert deep.run.complexity is ComplexityLevel.L5_DEEP_INVESTIGATION
    agent_ids = {task.agent_id for task in deep.graph.tasks}
    assert {
        "temporal_analyst",
        "conflict_detector",
        "critic",
        "fact_checker",
    } <= agent_ids
    assert len(deep.graph.tasks) >= 8
    # todos los agentes asignados existen en el registro
    registry_ids = {d.id for d in default_registry().list()}
    assert agent_ids <= registry_ids

    with pytest.raises(ValueError):
        orchestrator.plan(
            query=(
                "Analiza todos los contratos e identifica riesgos y "
                "contradicciones."
            ),
            scope=scope,
            budget=CognitiveBudget(max_agents=1),
        )
