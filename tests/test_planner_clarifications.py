from src.platform.workflows.architect_clarifications import (
    build_clarifications,
    clarification_payload,
)
from src.platform.workflows.architect_models import PlanIssue, SemanticPlan


def _plan() -> SemanticPlan:
    return SemanticPlan.model_validate(
        {
            "goal": "Comparar fuentes",
            "steps": [
                {
                    "id": "q1",
                    "type": "business_query",
                    "goal": "Consultar el total",
                    "params": {"ask": "total"},
                },
                {"id": "end", "type": "stop", "goal": "Terminar"},
            ],
        }
    )


def test_contract_issue_becomes_structured_question() -> None:
    issue = PlanIssue(
        code="contract.output_unknown",
        severity="error",
        message="La salida total no existe en el contrato.",
        step_id="q1",
        field="outputs.total",
        expected="total",
        received="amount",
        alternatives=["monto_total"],
        action_required="Elige un campo de salida válido.",
    )
    questions = build_clarifications(_plan(), [issue])
    assert len(questions) == 1
    item = questions[0]
    assert item["question_id"].startswith("q_")
    assert item["code"] == "contract.output_unknown"
    assert item["field"] == "outputs.total"
    assert item["expected"] == "total"
    assert item["alternatives"] == ["monto_total"]
    assert item["resolved"] is False
    assert item["severity"] == "error"


def test_questions_are_deterministic_and_limited() -> None:
    issues = [
        PlanIssue(
            code="missing.input",
            severity="warning",
            message=f"Falta el dato {index}",
            step_id=f"s{index}",
        )
        for index in range(8)
    ]
    first = build_clarifications(_plan(), issues, limit=5)
    second = build_clarifications(_plan(), issues, limit=5)
    assert first == second
    assert len(first) == 5
    assert [item["step_id"] for item in first] == ["s0", "s1", "s2", "s3", "s4"]


def test_clarification_payload_has_stable_identity() -> None:
    one = clarification_payload("¿Cuál es el umbral?", code="missing.decision_input")
    two = clarification_payload("¿Cuál es el umbral?", code="missing.decision_input")
    assert one["question_id"] == two["question_id"]
    assert one["impact"] == "medium"
    assert one["alternatives"] == []
