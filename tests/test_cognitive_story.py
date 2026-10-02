# =============================================================================
# Cognitive story — proyección de flow["cognitive"] a 3 niveles (C6).
# =============================================================================
from __future__ import annotations

from src.rag.cognitive_story import build_cognitive_story

_COGNITIVE = {
    "mode": "active",
    "signals": {"exact_lookup_declared": True, "entity_resolved": True},
    "plan": {"complexity": "L3", "needs": ["comparison", "temporal_lookup"]},
    "strategy": {
        "primary": "exact",
        "representations": [{"representation": "exact", "reason": "literales"}],
    },
    "entities": {
        "resolved": True,
        "mentions": [{"mention": "Category 31", "status": "resolved", "matches": []}],
    },
    "runners": [
        {"representation": "graph", "status": "ok", "count": 2, "items": [], "latency_ms": 12.0}
    ],
    "evidence": {
        "count": 3,
        "chars": 900,
        "budget_chars": 12000,
        "counts": {"fact": 1, "excerpt": 2},
        "conflicts": [{"key": "c1|rule x|aplica", "unit_ids": ["U1", "U2"], "values": ["2024", "2026"]}],
        "dropped_count": 1,
        "units": [],
    },
    "brief": {
        "chars": 400,
        "budget_chars": 8000,
        "sections": [{"kind": "facts", "count": 1, "chars": 120, "truncated": 0, "items": []}],
    },
    "verification": {"action": "answer_with_limits", "count": 2, "supported": 1, "unsupported": 1},
    "budget": {"complexity": "L3", "llm_calls": 2, "tokens": 1200, "within_budget": True},
    "loop": {"rounds": [], "count": 1, "extra_round": False, "max_rounds": 3, "exhausted": False},
    "learning": [{"kind": "conflict", "concept": "c1", "detail": "x", "priority": 0.65}],
    "run_id": "run-1",
    "deep": {"status": "completed", "failure_mode": "", "metrics": {"tokens": 1200}},
}


def test_sin_cognitive_devuelve_shape_vacio() -> None:
    story = build_cognitive_story({})
    assert story["schema_version"] == 1
    assert story["normal"] == []
    assert story["expanded"] == {}
    assert story["raw"] == {}


def test_normal_deriva_pasos_con_metricas() -> None:
    story = build_cognitive_story({"cognitive": _COGNITIVE})
    kinds = [step["kind"] for step in story["normal"]]
    assert kinds == [
        "cognitive_plan",
        "cognitive_strategy",
        "cognitive_entities",
        "cognitive_runner",
        "cognitive_evidence",
        "cognitive_brief",
        "cognitive_verification",
        "cognitive_budget",
        "cognitive_loop",
        "cognitive_learning",
        "cognitive_deep_run",
    ]
    plan = story["normal"][0]
    assert plan["phase"] == "planning"
    assert plan["metrics"]["complexity"] == "L3"
    assert plan["metrics"]["needs"] == 2


def test_expanded_y_raw_acotados() -> None:
    story = build_cognitive_story({"cognitive": _COGNITIVE})
    assert story["expanded"]["strategy"]["primary"] == "exact"
    assert story["expanded"]["evidence"]["conflicts"] == 1
    assert story["expanded"]["budget"]["within_budget"] is True
    assert story["raw"]["run_id"] == "run-1"
    assert story["raw"]["deep_metrics"]["tokens"] == 1200


def test_nunca_lanza_con_cognitive_roto() -> None:
    story = build_cognitive_story({"cognitive": {"plan": "roto", "runners": 7}})
    assert isinstance(story["normal"], list)
    assert isinstance(story["expanded"], dict)
