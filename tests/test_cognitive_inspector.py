# =============================================================================
# Cognitive Inspector — Phase 9 (backend puro)
# =============================================================================
from __future__ import annotations

from uuid import uuid4

from src.platform.cognitive.inspector import build_inspector


def test_build_inspector_aggregates_without_chain_of_thought() -> None:
    run = {
        "id": str(uuid4()),
        "status": "completed",
        "complexity": "L4",
        "query": "analiza contratos",
        "plan": {
            "conflicts": [{"conflict_type": "temporal_update"}],
            "critique": {"issues": [{"kind": "weak_citation"}]},
            "debate": [{"kind": "defended"}],
            "final_answer": "respuesta final",
        },
    }
    tasks = [
        {
            "task_key": "retrieve",
            "agent_id": "retrieval_strategist",
            "status": "completed",
            "depends_on": ["locate_sources"],
        }
    ]
    executions = [
        {
            "agent_id": "retrieval_strategist",
            "status": "completed",
            "latency_ms": 12.5,
            "tokens": 120,
            "cost_usd": 0.01,
            "error": None,
            "result": {"evidence_ids": ["e1"]},
        },
        {
            "agent_id": "critic",
            "status": "skipped",
            "latency_ms": 0.0,
            "tokens": 0,
            "cost_usd": 0.0,
            "error": "handler not implemented",
            "result": {},
        },
    ]
    messages = [
        {
            "message_type": "evidence",
            "claim_ids": ["c1"],
            "evidence_ids": ["e1"],
        }
    ]

    view = build_inspector(
        run=run, tasks=tasks, executions=executions, messages=messages
    )

    assert view["chain_of_thought_exposed"] is False
    assert view["run"]["complexity"] == "L4"
    assert [s["agent_id"] for s in view["specialists"]] == [
        "retrieval_strategist",
        "critic",
    ]
    assert view["evidence"] == {"count": 1, "ids": ["e1"]}
    assert view["claims"] == {"count": 1, "ids": ["c1"]}
    assert view["conflicts"] == [{"conflict_type": "temporal_update"}]
    assert view["debate"] == [{"kind": "defended"}]
    assert view["final_answer"] == "respuesta final"
    assert view["totals"]["tokens"] == 120
    assert view["totals"]["latency_ms"] == 12.5
    assert view["tasks"][0]["depends_on"] == ["locate_sources"]
