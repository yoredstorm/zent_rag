# =============================================================================
# Cognitive Workflows — Fase 8: narrativa de ejecución.
#
# Solo datos estructurados; sin chain of thought ni JSON crudo en las frases.
# =============================================================================
from __future__ import annotations

from src.platform.workflows.narrative import run_story


def test_run_story_builds_business_sentences() -> None:
    run = {
        "status": "pending_approval",
        "trigger_payload": {"total": 45000, "customer": "ACME"},
        "steps": [
            {"node_type": "trigger_event", "status": "succeeded", "output": {}},
            {
                "node_type": "query_business_data",
                "status": "succeeded",
                "output": {"rows": [{"a": 1}], "answer": "hay 1"},
            },
            {
                "node_type": "kb_query",
                "status": "succeeded",
                "output": {"operation": "answer", "count": 2, "evidence_ids": ["e1", "e2"]},
            },
            {
                "node_type": "llm",
                "status": "succeeded",
                "output": {"risk": "HIGH", "requires_review": True},
            },
            {
                "node_type": "condition",
                "status": "succeeded",
                "output": {"condition": "risk == HIGH", "result": True},
            },
            {
                "node_type": "join",
                "status": "succeeded",
                "output": {"branches": {"Ventas": {}, "Política": {}}},
            },
            {
                "node_type": "human_approval",
                "status": "succeeded",
                "output": {"action": "Aprobar pago"},
            },
            {"node_type": "notify", "status": "simulated", "output": {"simulated": True}},
        ],
    }
    story = run_story(run)
    text = " ".join(story)
    assert "total=45000" in text
    assert "datos de negocio" in text
    assert "conocimiento (answer): 2" in text
    assert "HIGH" in text
    assert "respuesta fue sí" in text
    assert "Ventas, Política" in text
    assert "aprobación humana: Aprobar pago" in text
    assert "simuló un aviso" in text
    assert "pending_approval" in text
    assert not any("{" in line for line in story)


def test_run_story_handles_empty_and_errors() -> None:
    assert run_story(None) == []
    empty = run_story({"trigger_payload": {}, "steps": []})
    assert empty[0] == "Se inició el flujo."
    run = {
        "status": "failed",
        "trigger_payload": {},
        "steps": [
            {"node_type": "llm", "status": "failed", "error": "boom", "output": {}},
        ],
    }
    story = run_story(run)
    assert story[-1] == "El run terminó con 1 error(es)."
