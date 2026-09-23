# =============================================================================
# Canonical flow events (Execution Story) — contrato versionado
# =============================================================================
# El flow guardado en rag_flows.flow sigue siendo la fuente; estos tests fijan
# la semántica que el portal consume: fases, tipos, estados y métricas.
# =============================================================================
from __future__ import annotations

from src.rag.flow_story import (
    FLOW_VERSION,
    PHASE_CONTEXT,
    PHASE_EVIDENCE,
    PHASE_GENERATION,
    PHASE_REASONING,
    PHASE_UNDERSTANDING,
    PHASE_VERIFICATION,
    build_flow_events,
    canonical_status,
    with_story,
)

AGENT_FLOW = {
    "query_id": "q-1",
    "method": "agent",
    "status": "completed",
    "steps": [
        {
            "type": "reasoning_classification",
            "status": "ok",
            "reasoning": {"shape": "STATE_TRANSITION", "is_complex": True},
        },
        {
            "type": "company_context",
            "status": "ok",
            "company_context": {"concepts": 3, "rules": 2, "memories": 1},
        },
        {
            "type": "reasoning_plan",
            "status": "ok",
            "plan": {"shape": "STATE_TRANSITION", "operations": ["parse_events"]},
        },
        {
            "type": "scenario_parse",
            "status": "warn",
            "scenario": {"events": 17, "unparsed": 3, "missing_requirements": [{"kind": "RECORD_LAYOUT_REQUIRED"}]},
        },
        {
            "type": "state_reconstruction",
            "status": "ok",
            "transitions": {
                "total": 10,
                "confirmed": 10,
                "unresolved": 0,
                "chain": [{"from": "5", "to": "6", "status": "CONFIRMED"}],
            },
        },
        {
            "type": "hypothesis_test",
            "status": "ok",
            "hypotheses": {"supported": 1, "rejected": 1, "unresolved": 0, "items": []},
        },
        {
            "type": "analysis_completion",
            "status": "warn",
            "completion": {"complete": False, "blockers": ["scenario_incomplete"]},
        },
        {"type": "tool_call", "status": "ok", "tool": "search_knowledge"},
        {"type": "final", "status": "ok"},
    ],
    "sources": [],
    "fallbacks": [],
}

RAG_FLOW = {
    "query_id": "q-2",
    "method": "rag",
    "status": "completed",
    "verdict": {"decider": "JEV", "route": "Documentos"},
    "decision": {"evaluated": True, "provider": "jev", "confidence": 0.93, "ms": 120},
    "retrieval": {"used": True, "chunks": 4, "top_score": 0.91, "ms": 340},
    "evidence": {"sufficient": True, "score": 0.8, "ms": 60, "items": 3},
    "grounding": {"grounded": True, "score": 0.9, "ms": 40},
    "generation": {"model": "deepseek-v3.2", "total_tokens": 980, "ms": 700, "cost": 0.0002},
    "timings": {"total_ms": 1450},
    "steps": [
        {"name": "Decisión", "status": "ok", "ms": 120, "detail": "jev"},
        {"name": "Búsqueda", "status": "ok", "ms": 340, "detail": "4 fragmentos"},
    ],
    "sources": [
        {"title": "spec.pdf", "document_id": "d-1", "score": 0.91, "authority": "authoritative"},
        {"title": "memo.docx", "document_id": "d-2", "score": 0.5, "authority": "informational", "status": "DISCARDED"},
    ],
    "fallbacks": ["ungrounded"],
}


def test_with_story_is_additive_and_versioned() -> None:
    enriched = with_story(dict(RAG_FLOW))
    assert enriched["flow_version"] == FLOW_VERSION == 2
    # Nada histórico se toca: un portal viejo sigue renderizando.
    for key in ("decision", "retrieval", "steps", "sources", "fallbacks", "timings"):
        assert key in enriched


def test_legacy_rag_flow_maps_to_canonical_phases() -> None:
    events = build_flow_events(dict(RAG_FLOW))
    phases = [event["phase"] for event in events]
    kinds = [event["kind"] for event in events]
    assert PHASE_EVIDENCE in phases
    assert PHASE_GENERATION in phases
    assert PHASE_VERIFICATION in phases
    assert "retrieval" in kinds
    assert "generation" in kinds
    assert "grounding" in kinds
    assert "sources" in kinds
    # El orden canónico se respeta: evidencia antes que generación.
    assert phases.index(PHASE_EVIDENCE) < phases.index(PHASE_GENERATION)


def test_retrieval_event_counts_sources_used_and_discarded() -> None:
    events = build_flow_events(dict(RAG_FLOW))
    retrieval = next(item for item in events if item["kind"] == "retrieval")
    assert retrieval["metrics"]["chunks"] == 4
    assert retrieval["metrics"]["sources_used"] == 2
    assert retrieval["metrics"]["sources_discarded"] == 2


def test_sources_event_carries_authority_and_status() -> None:
    events = build_flow_events(dict(RAG_FLOW))
    sources = next(item for item in events if item["kind"] == "sources")
    assert sources["metrics"]["authority_counts"] == {
        "authoritative": 1,
        "informational": 1,
    }
    items = sources["technical"]["items"]
    assert items[0]["authority"] == "authoritative"
    assert items[1]["status"] == "DISCARDED"


def test_reasoning_steps_map_to_phases_with_structured_metrics() -> None:
    events = build_flow_events(dict(AGENT_FLOW))
    by_kind = {event["kind"]: event for event in events}
    assert by_kind["reasoning_classification"]["phase"] == PHASE_UNDERSTANDING
    assert by_kind["company_context"]["phase"] == PHASE_CONTEXT
    assert by_kind["scenario_parse"]["phase"] == PHASE_REASONING
    assert by_kind["hypothesis_test"]["metrics"]["hypotheses"]["rejected"] == 1
    assert by_kind["state_reconstruction"]["metrics"]["transitions"]["confirmed"] == 10
    assert by_kind["analysis_completion"]["status"] == "warn"
    # Un paso con problema no se marca como error del run.
    assert by_kind["scenario_parse"]["status"] == "warn"


def test_events_never_carry_ui_strings_or_chain_of_thought() -> None:
    events = build_flow_events(dict(AGENT_FLOW))
    blob = str(events).lower()
    for forbidden in ("chain-of-thought", "thought", "scratchpad", "let me think"):
        assert forbidden not in blob
    # Los eventos son semánticos: fase, tipo, estado y métricas.
    assert all("phase" in event and "kind" in event and "status" in event for event in events)


def test_canonical_status_mapping() -> None:
    assert canonical_status("ok") == "ok"
    assert canonical_status("warn") == "warn"
    assert canonical_status("failed") == "error"
    assert canonical_status("skipped") == "skipped"
    assert canonical_status(None) == "ok"


def test_flow_without_optional_blocks_stays_minimal() -> None:
    events = build_flow_events({"steps": [], "sources": []})
    assert events == []


def test_fallback_becomes_event_with_semantic_reason() -> None:
    events = build_flow_events(dict(RAG_FLOW))
    fallback = next(item for item in events if item["kind"] == "fallback")
    assert fallback["status"] == "warn"
    assert fallback["summary"] == "grounding_failed"


def test_typed_steps_do_not_duplicate_block_events() -> None:
    flow = {
        "steps": [{"type": "decision", "status": "ok", "duration_ms": 90}],
        "decision": {"evaluated": True, "ms": 90},
        "sources": [],
    }
    events = build_flow_events(flow)
    assert [event["kind"] for event in events] == ["decision"]


def test_with_story_never_raises_on_broken_flow() -> None:
    """Si la derivación falla, se devuelve el flow original sin eventos."""

    class RaisingStep(dict):
        def get(self, *args, **kwargs):  # type: ignore[override]
            raise RuntimeError("boom")

    flow = {"steps": [RaisingStep()], "sources": []}
    result = with_story(flow)
    assert result is flow
    assert "events" not in result
