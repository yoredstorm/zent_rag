"""Traceability Schema v2 — escenarios canónicos (§32) y regresión §33.

Estos tests fijan la única verdad: identidad de fuentes, deduplicación real,
conteos separados, semántica JEV, taxonomía de fallbacks, evaluación de
max_tokens, tiempos paralelos, invariantes y adaptación de traces históricos.
"""

from __future__ import annotations

from src.rag.execution_narrative import build_execution_narrative
from src.rag.flow_story import with_story
from src.rag.trace_metrics import GLOSSARY_TERMS, METRIC_DEFINITIONS
from src.rag.traceability import (
    build_traceability,
    upgrade_flow_traceability,
    upgrade_traceability_v1,
)


def _item(**overrides):
    item = {
        "evidence_id": "E1",
        "document_id": "doc-1",
        "chunk_id": "chunk-1",
        "original_filename": "rules.pdf",
        "page": 1,
        "excerpt": "The carrier code must be reported on every ticket for record two.",
        "status": "USED",
        "score": 0.9,
        "doc_index": 1,
    }
    item.update(overrides)
    return item


def _flow(**overrides):
    flow = {
        "status": "completed",
        "method": "rag",
        "organization_id": "org-1",
        "generation": {"skipped": False},
        "steps": [],
        "sources": [],
        "fallbacks": [],
        "timings": {},
        "retrieval": {"used": True, "chunks": 1, "attempts": 1, "rounds": []},
    }
    flow.update(overrides)
    return flow


def _codes(items):
    return [item.get("code") for item in items]


def _diagnostic(trace, code):
    return next(
        (item for item in trace["diagnostics"]["items"] if item["code"] == code), None
    )


# ---------------------------------------------------------------------------
# §3 / §5 — documentos y deduplicación
# ---------------------------------------------------------------------------


def test_many_chunks_of_one_file_are_one_document() -> None:
    flow = _flow(
        sources=[
            _item(evidence_id="E1", chunk_id="c1", page=1),
            _item(
                evidence_id="E2",
                chunk_id="c2",
                page=2,
                excerpt="El fare basis aplica al tramo internacional del itinerario.",
            ),
            _item(
                evidence_id="E3",
                chunk_id="c3",
                page=3,
                excerpt="La regla de categoría 31 exige validar el código de tarifa.",
            ),
        ]
    )
    trace = build_traceability(flow)
    counts = trace["evidence"]["counts"]
    assert counts["documents_retrieved"] == 1
    assert counts["evidence_unique"] == 3
    source_ids = {
        item["canonical_source_id"] for item in trace["evidence"]["canonical_evidence"]
    }
    assert len(source_ids) == 1
    assert trace["evidence"]["collection"] == "complete"


def test_same_chunk_retrieved_twice_is_exact_duplicate() -> None:
    flow = _flow(
        sources=[
            _item(evidence_id="E1", chunk_id="c1"),
            _item(evidence_id="E2", chunk_id="c1"),
        ]
    )
    trace = build_traceability(flow)
    counts = trace["evidence"]["counts"]
    assert counts["evidence_retrieved"] == 2
    assert counts["evidence_unique"] == 1
    assert counts["evidence_deduplicated"] == 1
    assert trace["evidence"]["dedup"]["exact"] == 1
    [canonical] = trace["evidence"]["canonical_evidence"]
    assert canonical["dedup_kind"] == "exact"
    assert canonical["hit_count"] == 2
    assert len(canonical["raw_hits"]) == 2


def test_overlapping_chunks_are_merged_but_preserved_in_raw_hits() -> None:
    flow = _flow(
        sources=[
            _item(
                evidence_id="E1",
                chunk_id="c1",
                excerpt="The carrier code must be reported on every ticket for record two.",
            ),
            _item(
                evidence_id="E2",
                chunk_id="c2",
                excerpt=(
                    "Carrier code must be reported on every ticket for record two "
                    "per company policy."
                ),
            ),
        ]
    )
    trace = build_traceability(flow)
    counts = trace["evidence"]["counts"]
    assert counts["evidence_retrieved"] == 2
    assert counts["evidence_unique"] == 1
    assert counts["evidence_deduplicated"] == 1
    assert trace["evidence"]["dedup"]["overlap"] == 1
    [canonical] = trace["evidence"]["canonical_evidence"]
    assert canonical["dedup_kind"] == "overlap"
    assert {hit["evidence_id"] for hit in canonical["raw_hits"]} == {"E1", "E2"}


def test_similar_text_in_different_documents_is_not_merged() -> None:
    flow = _flow(
        sources=[
            _item(evidence_id="E1", document_id="docA", original_filename="a.pdf"),
            _item(evidence_id="E2", document_id="docB", original_filename="b.pdf"),
        ]
    )
    trace = build_traceability(flow)
    counts = trace["evidence"]["counts"]
    assert counts["evidence_unique"] == 2
    assert counts["evidence_deduplicated"] == 0
    assert counts["documents_retrieved"] == 2


def test_complementary_chunks_on_adjacent_pages_stay_distinct() -> None:
    flow = _flow(
        sources=[
            _item(
                evidence_id="E1",
                chunk_id="c1",
                page=1,
                excerpt="Capítulo uno: define el código de transportista.",
            ),
            _item(
                evidence_id="E2",
                chunk_id="c2",
                page=2,
                excerpt="Capítulo dos: describe la validación del fare basis.",
            ),
        ]
    )
    trace = build_traceability(flow)
    assert trace["evidence"]["counts"]["evidence_unique"] == 2


# ---------------------------------------------------------------------------
# §4 / §7 — identidad y nombres
# ---------------------------------------------------------------------------


def test_evidence_without_id_gets_deterministic_fingerprint() -> None:
    source = {
        "document_id": "doc-1",
        "original_filename": "rules.pdf",
        "page": 4,
        "excerpt": "Fragmento sin identificador previo.",
        "status": "USED",
    }
    first = build_traceability(_flow(sources=[source]))
    second = build_traceability(_flow(sources=[dict(source)]))
    [canonical_a] = first["evidence"]["canonical_evidence"]
    [canonical_b] = second["evidence"]["canonical_evidence"]
    assert canonical_a["evidence_id"].startswith("ev_")
    assert canonical_a["evidence_id"] == canonical_b["evidence_id"]


def test_evidence_without_any_identity_is_flagged_not_invented() -> None:
    flow = _flow(sources=[{"status": "USED", "excerpt": "sin metadatos"}])
    trace = build_traceability(flow)
    assert "EVIDENCE_ID_MISSING" in _codes(trace["diagnostics"]["gaps"])
    [canonical] = trace["evidence"]["canonical_evidence"]
    assert canonical.get("evidence_id") is None


def test_source_name_resolution_hierarchy() -> None:
    flow = _flow(
        sources=[
            _item(evidence_id="E1", original_filename="original.pdf", title="Doc generado"),
            _item(
                evidence_id="E2",
                document_id="doc-2",
                original_filename=None,
                title=None,
                chunk_id="c2",
                source_uri="s3://bucket/almacen/storage-name.pdf",
            ),
        ]
    )
    trace = build_traceability(flow)
    names = {
        doc.get("display_name") or doc.get("document_name")
        for doc in trace["evidence"]["documents"]
    }
    assert "original.pdf" in names
    assert "storage-name.pdf" in names
    assert "SOURCE_NAME_MISSING" not in _codes(trace["diagnostics"]["gaps"])


def test_missing_source_name_uses_canonical_label_and_diagnostic() -> None:
    flow = _flow(sources=[_item(evidence_id="E1", original_filename=None, title=None)])
    trace = build_traceability(flow)
    [document] = trace["evidence"]["documents"]
    assert document["document_name"] == ""
    assert document["display_name"].startswith("Fuente ")
    assert document["name_missing"] is True
    gap = _diagnostic(trace, "SOURCE_NAME_MISSING")
    assert gap is not None
    assert gap["severity"] == "WARNING"
    assert gap["dimension"] == "metadata"


# ---------------------------------------------------------------------------
# §8 / §9 / §10 — JEV
# ---------------------------------------------------------------------------


def _preflight(decisions, questions=None, phase="pre_generation"):
    return {
        "mode": "on",
        "summary": {"calls": 1, "judgments": len(questions or [])},
        "packs": [
            {
                "phase": phase,
                "mode": "on",
                "status": "ok",
                "question_count": len(questions or []),
                "questions": questions or [],
                "effects": [],
            }
        ],
        "decisions": decisions,
    }


def test_jev_evaluates_without_intervention() -> None:
    flow = _flow(
        jev_preflight=_preflight(
            decisions=[
                {
                    "phase": "pre_generation",
                    "action": "generate",
                    "allow_generation": True,
                    "applied": True,
                    "reasons": ["default"],
                    "decided_by": "jev",
                }
            ],
            questions=[
                {
                    "id": "needs_tool",
                    "type": "noul",
                    "decision": "no",
                    "confidence": 0.47,
                    "distribution": {"type": "noul", "certainty": 0.06},
                },
                {
                    "id": "tool",
                    "type": "choice",
                    "decision": "none",
                    "confidence": 0.49,
                    "distribution": {
                        "type": "choice",
                        "probabilities": {"none": 0.75, "search_knowledge": 0.25},
                    },
                },
                {"id": "grounded", "type": "noul", "decision": "yes", "confidence": 0.9},
                {"id": "complete", "type": "noul", "decision": "yes", "confidence": 0.8},
            ],
        )
    )
    trace = build_traceability(flow)
    jev = trace["jev"]
    assert jev["executed"] is True
    assert jev["checks"] == 4
    assert jev["material_intervention"] is False
    assert jev["changed_route"] is False
    assert jev["requested_more_evidence"] is False
    [decision] = jev["decisions"]
    assert decision["is_default"] is True
    assert decision["material"] is False
    explanation = next(
        item
        for item in trace["presentation"]["explanations"]
        if item["code"] == "JEV_CONFIRMED_NO_CHANGE"
    )
    assert explanation["params"]["checks"] == 4

    narrative = build_execution_narrative(flow, [], trace=trace)
    assert narrative["summary"]["decisions_influenced"] == 0


def test_jev_changes_route_and_requests_more_evidence() -> None:
    flow = _flow(
        jev_preflight=_preflight(
            decisions=[
                {
                    "phase": "post_retrieval",
                    "action": "retrieve_more",
                    "allow_generation": True,
                    "applied": True,
                    "influer": True,
                    "reasons": ["evidence_gap"],
                    "decided_by": "jev",
                }
            ]
        ),
        retrieval={
            "used": True,
            "chunks": 5,
            "attempts": 2,
            "expanded": True,
            "rounds": [
                {"attempt": 1, "strategy": "hybrid", "sufficient": False, "n_items": 3},
                {"attempt": 2, "strategy": "hybrid", "sufficient": True, "n_items": 5},
            ],
        },
    )
    trace = build_traceability(flow)
    jev = trace["jev"]
    assert jev["material_intervention"] is True
    assert jev["changed_route"] is True
    assert jev["requested_more_evidence"] is True
    [decision] = jev["material_decisions"]
    assert decision["changed_route"] is True
    assert decision["delta_evidence"] == 2
    journey_kinds = [node["kind"] for node in trace["presentation"]["journey"]]
    assert "RETRIEVAL_RETRIED" in journey_kinds


def test_probability_mismatch_is_explained_with_both_magnitudes() -> None:
    flow = _flow(
        jev_preflight=_preflight(
            decisions=[],
            questions=[
                {
                    "id": "tool",
                    "type": "choice",
                    "decision": "none",
                    "confidence": 0.49,
                    "distribution": {
                        "type": "choice",
                        "confidence": 0.49,
                        "probabilities": {"none": 0.75, "search_knowledge": 0.25},
                    },
                }
            ],
        )
    )
    trace = build_traceability(flow)
    [judgment] = trace["judgments"]
    interpretation = judgment["interpretation"]
    assert interpretation["selected_probability"] == 0.75
    assert interpretation["confidence"] == 0.49
    assert interpretation["margin"] == 0.5
    assert judgment["display"]["probability"] == 0.75
    mismatch = _diagnostic(trace, "PROBABILITY_MISMATCH")
    assert mismatch is not None
    assert mismatch["params"]["selected_probability"] == 0.75
    assert mismatch["params"]["confidence"] == 0.49
    assert mismatch["dimension"] == "consistency"


# ---------------------------------------------------------------------------
# §12 / §13 — límites y controles
# ---------------------------------------------------------------------------


def _max_tokens_flow(answer="Respuesta completa y verificada."):
    return _flow(
        generation={"skipped": False, "model": "zent-default"},
        steps=[
            {
                "id": "llm-1",
                "type": "llm",
                "action": {"answer": "ready"},
                "latency_ms": 900,
            },
            {"id": "guard-1", "type": "guardrail", "detail": "max_tokens exceeded"},
            {"id": "final-1", "type": "final", "status": "ok", "answer": answer},
            {
                "id": "gate-1",
                "type": "answer_gate",
                "verdict": "approve",
                "complete": True,
            },
        ],
        evidence={
            "items": 2,
            "counts": {
                "documents_consulted": 1,
                "documents_used": 1,
                "evidence_retrieved": 2,
                "evidence_used": 2,
                "evidence_cited": 2,
            },
            "items_detail": [
                _item(evidence_id="E1", chunk_id="c1"),
                _item(
                    evidence_id="E2",
                    chunk_id="c2",
                    page=2,
                    excerpt="Segundo fragmento usado y citado en la respuesta final.",
                ),
            ],
        },
        citations=[
            {"index": 1, "evidence_id": "E1", "cited": True},
            {"index": 2, "evidence_id": "E2", "cited": True},
        ],
        grounding={"grounded": True, "score": 0.8},
        verification={"overall": "verified", "checks": [{"key": "grounding", "state": "ok"}]},
    )


def test_max_tokens_recovered_without_impact() -> None:
    trace = build_traceability(_max_tokens_flow())
    control = next(
        item for item in trace["controls"]["controls"] if item["control_code"] == "MAX_TOKENS_REACHED"
    )
    assert control["severity"] == "WARNING"
    assert control["material_effect"] is False
    assert control["recovered"] is True
    assert control["params"]["impact"] == "RECOVERED_NO_IMPACT"
    assert trace["verification"]["status"] == "VERIFIED"
    assert "MAX_TOKENS_RECOVERED" in [
        item["code"] for item in trace["verification"]["explanation_codes"]
    ]
    notice = _diagnostic(trace, "MAX_TOKENS_RECOVERED")
    assert notice is not None
    assert notice["material_effect"] is False


def test_max_tokens_truncation_degrades_verification() -> None:
    trace = build_traceability(_max_tokens_flow(answer="Respuesta truncada sin final"))
    control = next(
        item for item in trace["controls"]["controls"] if item["control_code"] == "MAX_TOKENS_REACHED"
    )
    assert control["material_effect"] is True
    assert control["params"]["impact"] == "POSSIBLY_INCOMPLETE"
    assert trace["verification"]["status"] == "PARTIALLY_VERIFIED"
    assert "MAX_TOKENS_POSSIBLY_INCOMPLETE" in [
        item["code"] for item in trace["verification"]["explanation_codes"]
    ]
    warning = _diagnostic(trace, "MAX_TOKENS_MATERIAL_IMPACT")
    assert warning is not None
    assert warning["material_effect"] is True
    assert "VERIFIED_WITH_MATERIAL_DEGRADATION" not in _codes(
        trace["diagnostics"]["invariants"]
    )


def test_provider_fallback_is_classified_not_material() -> None:
    flow = _flow(fallbacks=["provider_timeout_fallback"])
    trace = build_traceability(flow)
    [event] = trace["fallbacks"]["events"]
    assert event["class"] == "provider_fallback"
    assert event["material_effect"] is False
    control = next(
        item
        for item in trace["controls"]["controls"]
        if item["control_code"] == "PROVIDER_FALLBACK"
    )
    assert control["severity"] == "NOTICE"
    assert trace["fallbacks"]["material"] is False


# ---------------------------------------------------------------------------
# §14 / §16 — generación y tiempos
# ---------------------------------------------------------------------------


def test_two_model_calls_distinct_purposes_do_not_duplicate_generation() -> None:
    flow = _flow(
        generation={"skipped": False, "calls": 2, "reasoning_calls": 1, "answer_calls": 1},
        steps=[
            {"id": "llm-1", "type": "llm", "action": {"tool": "search_knowledge"}},
            {"id": "llm-2", "type": "llm", "action": {"answer": "ready"}},
            {"id": "final-1", "type": "final", "status": "ok"},
        ],
    )
    enriched = with_story(flow)
    trace = enriched["traceability"]
    assert [call["purpose"] for call in trace["generation"]["call_details"]] == [
        "reasoning",
        "answer_generation",
    ]
    visible_generations = [
        entry
        for entry in trace["timeline"]
        if entry["type"] == "GENERATION_COMPLETED" and entry["user_visible"]
    ]
    assert len(visible_generations) == 1
    answer_steps = [
        node
        for node in trace["presentation"]["journey"]
        if node["kind"] == "ANSWER_GENERATED"
    ]
    assert len(answer_steps) == 1
    reasoning_steps = [
        node
        for node in trace["presentation"]["journey"]
        if node["kind"] == "REASONING_PREPARED"
    ]
    assert len(reasoning_steps) == 1
    assert "JOURNEY_DUPLICATE_PURPOSE" not in _codes(trace["diagnostics"]["invariants"])

    narrative = enriched["execution_narrative"]
    assert [call["purpose"] for call in narrative["model_calls"]] == [
        "ANALYSIS",
        "ANSWER",
    ]


def test_parallel_spans_inform_but_never_error() -> None:
    flow = _flow(timings={"total_ms": 18089, "tools_ms": 24332})
    trace = build_traceability(flow)
    timing = trace["timing"]
    assert timing["wall_clock_ms"] == 18089
    assert timing["accumulated_ms"] == 24332
    assert timing["parallel"] is True
    finding = _diagnostic(trace, "PARALLEL_SPANS")
    assert finding is not None
    assert finding["severity"] == "NOTICE"
    assert finding["material_effect"] is False
    assert trace["diagnostics"]["dimensions"]["timing"]["status"] == "notice"
    assert trace["diagnostics"]["overall"]["status"] != "error"
    explanation = next(
        item
        for item in trace["presentation"]["explanations"]
        if item["code"] == "PARALLEL_TIME"
    )
    assert explanation["params"]["accumulated_ms"] == 24332


# ---------------------------------------------------------------------------
# §24 / §25 — invariantes y consistencia
# ---------------------------------------------------------------------------


def test_invariant_used_exceeding_unique_is_a_diagnostic() -> None:
    flow = _flow(
        sources=[_item(evidence_id="E1")],
        evidence={
            "counts": {
                "documents_consulted": 1,
                "documents_used": 1,
                "evidence_retrieved": 1,
                "evidence_used": 3,
                "evidence_cited": 1,
            }
        },
    )
    trace = build_traceability(flow)
    invariant = _diagnostic(trace, "EVIDENCE_USED_EXCEEDS_UNIQUE")
    assert invariant is not None
    assert invariant["severity"] == "ERROR"
    assert invariant["params"]["used"] == 3
    assert trace["diagnostics"]["consistency"]["status"] == "inconsistent"


def test_every_diagnostic_answers_three_questions() -> None:
    flow = _max_tokens_flow(answer="Respuesta truncada sin final")
    flow["fallbacks"] = ["provider_timeout_fallback"]
    trace = build_traceability(flow)
    assert trace["diagnostics"]["items"]
    for item in trace["diagnostics"]["items"]:
        assert item["severity"] in {"INFO", "NOTICE", "WARNING", "ERROR", "CRITICAL"}
        assert item["dimension"] in {
            "execution",
            "evidence",
            "jev",
            "generation",
            "verification",
            "memory",
            "timing",
            "cost",
            "metadata",
            "consistency",
            "fallbacks",
            "presentation",
        }
        assert item["meaning_code"]
        assert item["impact_code"]
        assert isinstance(item["material_effect"], bool)


def test_verification_states_are_separate_from_consistency() -> None:
    good = build_traceability(_max_tokens_flow())
    assert good["verification"]["status"] == "VERIFIED"
    assert good["diagnostics"]["consistency"]["status"] == "consistent"
    assert good["diagnostics"]["dimensions"]["verification"]["status"] == "ok"
    assert good["presentation"]["headline"]["code"] == "RESPONSE_SUPPORTED"

    partial = build_traceability(
        _flow(
            evidence={
                "items": 1,
                "counts": {"evidence_retrieved": 1, "evidence_used": 1},
                "items_detail": [_item(evidence_id="E1")],
            },
            grounding={"grounded": True, "score": 0.8},
            verification={
                "overall": "partial",
                "checks": [
                    {"key": "grounding", "state": "ok"},
                    {"key": "answer_gate", "state": "not_observed"},
                ],
            },
        )
    )
    assert partial["verification"]["status"] == "PARTIALLY_VERIFIED"
    assert partial["presentation"]["headline"]["code"] == "RESPONSE_PARTIALLY_SUPPORTED"

    insufficient = build_traceability(
        _flow(
            fallbacks=["preflight_abstained"],
            generation={"skipped": True},
            grounding={"grounded": False, "score": 0.0},
        )
    )
    assert insufficient["verification"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert insufficient["presentation"]["headline"]["code"] == "RESPONSE_BLOCKED"


# ---------------------------------------------------------------------------
# §27 / §31 — catálogo y compatibilidad
# ---------------------------------------------------------------------------


def test_metric_and_glossary_refs_are_declared() -> None:
    trace = build_traceability(_max_tokens_flow())
    for ref in trace["presentation"]["metric_refs"]:
        assert ref in METRIC_DEFINITIONS
    for ref in trace["presentation"]["glossary_refs"]:
        assert ref in GLOSSARY_TERMS


def test_schema1_trace_is_upgraded_on_read() -> None:
    v1 = {
        "schema_version": 1,
        "counts": {
            "documents_consulted": 2,
            "documents_used": 2,
            "evidence_retrieved": 3,
            "evidence_used": 2,
            "evidence_cited": 1,
        },
        "evidence": {
            "documents": [
                {
                    "document_key": "document:docA",
                    "document_id": "docA",
                    "document_name": "rules.pdf",
                    "evidence_count": 2,
                    "used_count": 1,
                    "items": [],
                }
            ],
            "items": [
                {
                    "document_id": "docA",
                    "chunk_id": "c1",
                    "document_name": "rules.pdf",
                    "excerpt": "texto",
                    "used_in_answer": True,
                }
            ],
        },
        "decisions": [
            {
                "decision_id": "decision:1:pre_generation",
                "phase": "pre_generation",
                "action": "generate",
                "action_applied": True,
                "classification": "OBSERVATIONAL",
            }
        ],
        "judgments": [
            {
                "id": "tool",
                "phase": "pre_reasoning",
                "question_code": "tool",
                "type": "choice",
                "display": {"outcome_key": "none", "probability": 0.75},
                "alternatives": [{"key": "none", "probability": 0.75}],
                "technical": {},
            }
        ],
        "verification": {"status": "VERIFIED", "checks": [], "signals": {}},
        "diagnostics": {"invariants": [], "gaps": []},
        "timeline": [],
        "retrieval": {"rounds": []},
    }
    upgraded = upgrade_traceability_v1(v1)
    assert upgraded["schema_version"] == 2
    assert upgraded["upgraded_from_schema"] == 1
    assert upgraded["evidence"]["counts"]["evidence_retrieved"] == 3
    assert upgraded["evidence"]["collection"] == "partial"
    assert "HISTORICAL_TRACE_UPGRADED" in _codes(upgraded["diagnostics"]["items"])
    assert upgraded["presentation"]["headline"]["code"] == "RESPONSE_SUPPORTED"

    flow = {"traceability": v1, "status": "completed"}
    result = upgrade_flow_traceability(flow)
    assert result["traceability"]["schema_version"] == 2
    assert flow["traceability"]["schema_version"] == 1  # no muta el original

    already = {"traceability": {"schema_version": 2, "counts": {}}}
    assert upgrade_flow_traceability(already)["traceability"]["schema_version"] == 2


# ---------------------------------------------------------------------------
# §33 — regresión con la ejecución real reportada
# ---------------------------------------------------------------------------


def test_real_execution_regression_explains_every_difference() -> None:
    flow = _flow(
        question="¿Qué código de transportista aplica al record dos?",
        evidence={
            "items": 5,
            "counts": {
                "documents_consulted": 5,
                "documents_used": 5,
                "evidence_retrieved": 5,
                "evidence_used": 5,
                "evidence_cited": 4,
            },
            "sufficiency": {"recommended_action": "generate"},
            "items_detail": [
                _item(evidence_id="E1", document_id="doc1", chunk_id="c1", cited=True),
                _item(
                    evidence_id="E2",
                    document_id="doc2",
                    chunk_id="c2",
                    original_filename="cat31.pdf",
                    page=7,
                    excerpt="Categoría 31 exige validar el código de tarifa del tramo.",
                    cited=True,
                ),
                _item(
                    evidence_id="E3",
                    document_id="doc3",
                    chunk_id="c3",
                    original_filename=None,
                    title=None,
                    page=3,
                    excerpt="La validación documental quedó asociada a la respuesta.",
                    cited=True,
                ),
                _item(
                    evidence_id="E4",
                    document_id="doc4",
                    chunk_id="c4",
                    original_filename="memo.docx",
                    page=2,
                    excerpt="Procedimiento interno de revisión de tarifas.",
                    cited=True,
                ),
                _item(
                    evidence_id=None,
                    document_id="doc5",
                    chunk_id=None,
                    original_filename="anexo.pdf",
                    page=9,
                    excerpt=None,
                    status="USED",
                ),
            ],
        },
        citations=[
            {"index": 1, "evidence_id": "E1", "cited": True},
            {"index": 2, "evidence_id": "E2", "cited": True},
            {"index": 3, "evidence_id": "E3", "cited": True},
            {"index": 4, "evidence_id": "E4", "cited": True},
            {"index": 5, "evidence_id": "E1", "cited": True},
        ],
        generation={
            "skipped": False,
            "model": "zent-default",
            "calls": 2,
            "reasoning_calls": 1,
            "answer_calls": 1,
            "prompt_tokens": 6687,
            "completion_tokens": 1068,
            "total_tokens": 7755,
            "ms": 6700,
            "cost": 0.001018,
        },
        steps=[
            {"id": "llm-1", "type": "llm", "action": {"tool": "search_knowledge"}},
            {"id": "llm-2", "type": "llm", "action": {"answer": "ready"}},
            {"id": "guard-1", "type": "guardrail", "detail": "max_tokens exceeded"},
            {
                "id": "final-1",
                "type": "final",
                "status": "ok",
                "answer": "El código aplicable es el reportado en el record dos.",
            },
            {"id": "gate-1", "type": "answer_gate", "verdict": "approve", "complete": True},
        ],
        jev_preflight=_preflight(
            decisions=[
                {
                    "phase": "pre_generation",
                    "action": "generate",
                    "allow_generation": True,
                    "applied": True,
                    "reasons": ["default"],
                    "decided_by": "jev",
                }
            ],
            questions=[
                {
                    "id": "needs_tool",
                    "type": "noul",
                    "decision": "no",
                    "confidence": 0.47,
                    "distribution": {"type": "noul", "certainty": 0.06},
                },
                {
                    "id": "tool",
                    "type": "choice",
                    "decision": "none",
                    "confidence": 0.49,
                    "distribution": {
                        "type": "choice",
                        "confidence": 0.49,
                        "probabilities": {"none": 0.75, "search_knowledge": 0.25},
                    },
                },
                {"id": "grounded", "type": "noul", "decision": "yes", "confidence": 0.9},
                {"id": "complete", "type": "noul", "decision": "yes", "confidence": 0.8},
            ],
        ),
        grounding={"grounded": True, "score": 0.8},
        verification={
            "overall": "verified",
            "checks": [{"key": "grounding", "state": "ok"}],
        },
        timings={"total_ms": 18089, "tools_ms": 24332},
    )
    trace = build_traceability(flow)
    counts = trace["evidence"]["counts"]
    assert counts["documents_retrieved"] == 5
    assert counts["documents_used"] == 5
    assert counts["evidence_retrieved"] == 5
    assert counts["evidence_unique"] == 5
    assert counts["evidence_used"] == 5
    assert counts["evidence_cited"] == 4

    citations = trace["evidence"]["citations_summary"]
    assert citations["references"] == 5
    assert citations["unique_cited"] == 4
    assert citations["collapsed"] == 1
    assert "CITATION_REFERENCES_COLLAPSED" in _codes(trace["diagnostics"]["items"])

    jev = trace["jev"]
    assert jev["checks"] == 4
    assert jev["material_intervention"] is False
    assert jev["changed_route"] is False

    generation = trace["generation"]
    assert generation["calls"] == 2
    assert generation["answer_calls"] == 1
    assert generation["reasoning_calls"] == 1
    assert generation["tokens"]["total"] == 7755
    assert [call["purpose"] for call in generation["call_details"]] == [
        "reasoning",
        "answer_generation",
    ]

    assert trace["timing"]["wall_clock_ms"] == 18089
    assert trace["timing"]["accumulated_ms"] == 24332
    assert trace["timing"]["parallel"] is True

    control = next(
        item
        for item in trace["controls"]["controls"]
        if item["control_code"] == "MAX_TOKENS_REACHED"
    )
    assert control["params"]["impact"] == "RECOVERED_NO_IMPACT"
    assert trace["verification"]["status"] == "VERIFIED"

    # Las tres inconsistencias reportadas se explican, no se maquillan.
    assert _diagnostic(trace, "PROBABILITY_MISMATCH") is not None
    assert _diagnostic(trace, "SOURCE_NAME_MISSING") is not None
    assert _diagnostic(trace, "EVIDENCE_ID_MISSING") is not None
    metadata_warnings = [
        item
        for item in trace["diagnostics"]["items"]
        if item["dimension"] == "metadata" and item["severity"] == "WARNING"
    ]
    assert metadata_warnings
    # La respuesta sigue verificada; la telemetría es la que queda parcial.
    assert trace["diagnostics"]["consistency"]["status"] == "partial"
    assert trace["diagnostics"]["consistency"]["response_quality"] == "VERIFIED"
    assert trace["presentation"]["headline"]["code"] == "RESPONSE_SUPPORTED"

    used_not_cited = next(
        item
        for item in trace["presentation"]["explanations"]
        if item["code"] == "USED_NOT_CITED"
    )
    assert used_not_cited["params"]["difference"] == 1

    searched = next(
        node
        for node in trace["presentation"]["journey"]
        if node["kind"] == "KNOWLEDGE_SEARCHED"
    )
    assert searched["params"]["retrieved"] == 5
    assert searched["params"]["unique"] == 5

    # Explicación del max_tokens: problema interno resuelto, sin impacto.
    recovery = next(
        item
        for item in trace["presentation"]["explanations"]
        if item["code"] == "MAX_TOKENS_RECOVERY"
    )
    assert recovery["params"]["impact"] == "RECOVERED_NO_IMPACT"


# ---------------------------------------------------------------------------
# §C6 — sección cognitiva
# ---------------------------------------------------------------------------


def test_seccion_cognitive_presente_y_estable() -> None:
    flow = _flow()
    flow["cognitive"] = {
        "mode": "active",
        "run_id": "run-1",
        "plan": {"complexity": "L3"},
        "strategy": {"primary": "exact", "representations": [{"representation": "exact"}]},
        "entities": {"resolved": True, "mentions": []},
        "evidence": {"count": 2, "counts": {"fact": 1}, "conflicts": [{"key": "k"}]},
        "brief": {"chars": 200},
        "verification": {"action": "approve"},
        "budget": {"within_budget": True},
        "loop": {"count": 1, "exhausted": False},
        "learning": [{"kind": "conflict"}],
        "deep": {"status": "completed", "failure_mode": ""},
    }
    trace = build_traceability(flow)
    cognitive = trace["cognitive"]
    assert cognitive["mode"] == "active"
    assert cognitive["run_id"] == "run-1"
    assert cognitive["complexity"] == "L3"
    assert cognitive["strategy_primary"] == "exact"
    assert cognitive["representations"] == 1
    assert cognitive["entities_resolved"] is True
    assert cognitive["conflicts"] == 1
    assert cognitive["verification_action"] == "approve"
    assert cognitive["budget_within"] is True
    assert cognitive["loop_rounds"] == 1
    assert cognitive["learning_count"] == 1
    assert cognitive["deep_status"] == "completed"

    empty = build_traceability(_flow())
    assert empty["cognitive"]["mode"] is None
    assert empty["cognitive"]["run_id"] is None
