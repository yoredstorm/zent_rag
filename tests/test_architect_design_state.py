from src.platform.workflows.architect_models import PlanIssue
from src.platform.workflows.architect_observability import (
    STATE_DRAFT_READY,
    STATE_NEEDS_CONFIGURATION,
    design_state,
)


def _graph() -> dict:
    return {"nodes": [{"id": "n", "type": "llm"}], "edges": [], "entrypoints": ["n"]}


def test_agentless_llm_warning_is_not_draft_ready() -> None:
    state = design_state(
        graph=_graph(),
        issues=[
            PlanIssue(
                code="plan.agent_needs_selection",
                severity="warning",
                message="Falta elegir un agente para el paso de IA.",
            )
        ],
        clarifications=[],
        requirements=[],
        readiness={"ready": True, "checks": []},
        fallback_used=False,
    )
    assert state == STATE_NEEDS_CONFIGURATION


def test_clean_graph_is_draft_ready() -> None:
    state = design_state(
        graph=_graph(),
        issues=[],
        clarifications=[],
        requirements=[],
        readiness={"ready": True, "checks": []},
        fallback_used=False,
    )
    assert state == STATE_DRAFT_READY
