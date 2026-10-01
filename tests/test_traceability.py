"""Contrato canónico de trazabilidad: evidencia, decisiones, verificación, timeline.

Reglas congeladas acá:
- documento != fragmento (métricas separadas);
- una decisión no aplicada NUNCA se muestra como cambio de ejecución;
- la probabilidad mostrada sale de una sola transformación (display);
- insuficiencia temporal exige una causa explícita;
- la timeline sólo contiene eventos reales.
"""

from __future__ import annotations

from src.rag.flow_story import with_story
from src.rag.traceability import build_traceability


def _base_flow(**overrides):
    flow = {
        "status": "completed",
        "retrieval": {"used": True, "chunks": 5, "attempts": 1, "rounds": []},
        "evidence": {
            "sufficient": True,
            "items": 5,
            "counts": {
                "documents_consulted": 3,
                "documents_used": 3,
                "evidence_retrieved": 5,
                "evidence_used": 4,
                "evidence_cited": 2,
            },
            "sufficiency": {
                "recommended_action": "generate",
                "reason": "exact_entity_match",
            },
            "items_detail": [
                {
                    "evidence_id": "E1",
                    "document_id": "docA",
                    "chunk_id": "c1",
                    "title": "Rec2_Rules.pdf",
                    "page": 18,
                    "section_path": ["Record 2"],
                    "excerpt": "Carrier Code ...",
                    "status": "USED",
                    "doc_index": 1,
                    "cited": True,
                },
                {
                    "evidence_id": "E2",
                    "document_id": "docA",
                    "chunk_id": "c2",
                    "title": "Rec2_Rules.pdf",
                    "page": 7,
                    "excerpt": "otro fragmento",
                    "status": "USED",
                    "doc_index": 2,
                },
                {
                    "evidence_id": "E3",
                    "document_id": "docB",
                    "title": "Cat31.pdf",
                    "status": "RETRIEVED",
                },
            ],
        },
        "grounding": {"grounded": True, "score": 0.8, "ms": 50},
        "generation": {"model": "m", "skipped": False, "ms": 800, "cost": 0.001},
        "steps": [],
        "fallbacks": [],
        "timings": {"total_ms": 1000},
    }
    flow.update(overrides)
    return flow


def _preflight(**overrides):
    block = {
        "mode": "on",
        "summary": {"calls": 1, "judgments": 1, "decisions_influenced": 1},
        "packs": [
            {
                "phase": "pre_generation",
                "mode": "on",
                "status": "ok",
                "question_count": 1,
                "questions": [
                    {
                        "id": "next_action",
                        "type": "choice",
                        "decision": "retrieve_more",
                        "confidence": 0.87,
                        "effect": "retrieval_round_requested",
                        "distribution": {
                            "type": "choice",
                            "choice": "retrieve_more",
                            "confidence": 0.87,
                            "certain": True,
                            "probabilities": {
                                "retrieve_more": 0.87,
                                "generate": 0.13,
                            },
                        },
                    }
                ],
            }
        ],
        "decisions": [
            {
                "phase": "pre_generation",
                "action": "retrieve_more",
                "allow_generation": True,
                "applied": True,
                "influer": True,
                "decided_by": "jev",
                "reasons": ["gate_not_satisfied"],
                "confidence": 0.87,
            }
        ],
    }
    block.update(overrides)
    return block


def test_documents_and_evidence_are_counted_separately() -> None:
    trace = build_traceability(_base_flow())
    counts = trace["counts"]
    assert counts["documents_consulted"] == 3
    assert counts["documents_used"] == 3
    assert counts["evidence_retrieved"] == 5
    assert counts["evidence_used"] == 4
    # Por construcción: usados <= recuperados.
    assert counts["evidence_used"] <= counts["evidence_retrieved"]


def test_evidence_groups_by_document_not_by_chunk() -> None:
    trace = build_traceability(_base_flow())
    documents = trace["evidence"]["documents"]
    assert len(documents) == 2
    doc_a = next(doc for doc in documents if doc["document_id"] == "docA")
    assert doc_a["evidence_count"] == 2
    assert doc_a["used_count"] == 2
    assert [item["evidence_id"] for item in doc_a["items"]] == ["E1", "E2"]


def test_source_name_fallback_never_invents_title() -> None:
    flow = _base_flow()
    flow["evidence"]["items_detail"] = [
        {"evidence_id": "E9", "document_id": "x", "status": "USED", "excerpt": "texto"}
    ]
    flow["evidence"]["counts"] = {
        "documents_consulted": 1,
        "documents_used": 1,
        "evidence_retrieved": 1,
        "evidence_used": 1,
    }
    trace = build_traceability(flow)
    document = trace["evidence"]["documents"][0]
    assert document["document_name"] == ""
    codes = [gap["code"] for gap in trace["diagnostics"]["gaps"]]
    assert "SOURCE_NAME_MISSING" in codes


def test_generated_names_are_treated_as_missing() -> None:
    flow = _base_flow()
    flow["sources"] = [
        {
            "title": "Documento ab12cd34",
            "document_id": "docC",
            "score": 0.5,
            "status": "USED",
        }
    ]
    flow["evidence"]["items_detail"] = []
    flow["evidence"]["counts"] = {}
    trace = build_traceability(flow)
    document = trace["evidence"]["documents"][0]
    assert document["document_name"] == ""


def test_used_evidence_without_excerpt_is_a_diagnostic_not_an_invention() -> None:
    flow = _base_flow()
    flow["evidence"]["items_detail"] = [
        {"evidence_id": "E5", "document_id": "docA", "status": "USED", "score": 0.9}
    ]
    trace = build_traceability(flow)
    gaps = trace["diagnostics"]["gaps"]
    assert any(
        gap["code"] == "EVIDENCE_EXCERPT_MISSING" and gap["evidence_id"] == "E5"
        for gap in gaps
    )


def test_agent_flow_without_document_id_still_groups_evidence() -> None:
    flow = _base_flow()
    flow["evidence"]["items_detail"] = [
        {"evidence_id": "E1", "source_id": "s1", "title": "manual.pdf", "status": "USED"},
        {"evidence_id": "E2", "source_id": "s1", "title": "manual.pdf", "status": "USED"},
    ]
    trace = build_traceability(flow)
    assert len(trace["evidence"]["documents"]) == 1
    assert trace["evidence"]["documents"][0]["evidence_count"] == 2


def test_applied_decision_is_actionable_with_before_after_state() -> None:
    flow = _base_flow()
    flow["retrieval"] = {
        "used": True,
        "chunks": 5,
        "attempts": 2,
        "expanded": True,
        "rounds": [
            {"attempt": 1, "strategy": "hybrid", "sufficient": False, "n_items": 3},
            {"attempt": 2, "strategy": "hybrid", "sufficient": True, "n_items": 5},
        ],
    }
    flow["jev_preflight"] = _preflight()
    trace = build_traceability(flow)
    decision = trace["decisions"][0]
    assert decision["action"] == "retrieve_more"
    assert decision["action_applied"] is True
    assert decision["classification"] == "ACTIONABLE"
    assert decision["before_state"] == {"evidence": 3, "sufficient": False}
    assert decision["after_state"] == {"evidence": 5, "sufficient": True}
    assert decision["delta_evidence"] == 2
    expanded = [item for item in trace["timeline"] if item["type"] == "RETRIEVAL_EXPANDED"]
    assert len(expanded) == 1
    assert expanded[0]["user_visible"] is True
    assert expanded[0]["summary_params"] == {"before": 3, "after": 5, "delta": 2}


def test_non_applied_decision_is_observational_and_never_changes_path() -> None:
    flow = _base_flow()
    preflight = _preflight()
    preflight["decisions"] = [
        {
            "phase": "pre_generation",
            "action": "generate",
            "allow_generation": True,
            "applied": False,
            "influer": False,
            "decided_by": "jev",
        }
    ]
    flow["jev_preflight"] = preflight
    trace = build_traceability(flow)
    decision = trace["decisions"][0]
    assert decision["classification"] == "OBSERVATIONAL"
    assert decision["action_applied"] is False
    assert not [item for item in trace["timeline"] if item["type"] == "RETRIEVAL_EXPANDED"]
    assert not [item for item in trace["timeline"] if item["type"] == "JEV_DECISION"]


def test_jev_without_intervention_hides_decisions_from_user_timeline() -> None:
    flow = _base_flow()
    preflight = _preflight()
    preflight["packs"][0]["questions"][0] = {
        "id": "answer_grounded",
        "type": "noul",
        "decision": "yes",
        "certainty": 0.8,
        "distribution": {"type": "noul", "noul": 0.9, "certainty": 0.8},
    }
    preflight["decisions"] = []
    flow["jev_preflight"] = preflight
    trace = build_traceability(flow)
    assert trace["judgments"]
    assert not [item for item in trace["timeline"] if item["type"] == "JEV_DECISION"]
    assert trace["diagnostics"]["sources"]["packs"] == 1


def test_probability_has_a_single_display_source() -> None:
    flow = _base_flow()
    flow["jev_preflight"] = _preflight()
    trace = build_traceability(flow)
    judgment = trace["judgments"][0]
    display = judgment["display"]
    assert display["outcome_key"] == "retrieve_more"
    assert display["probability"] == 0.87
    assert display["confidence_band"] == "high"
    # La alternativa mostrada usa EXACTAMENTE la probabilidad del display.
    alternative = next(
        alt for alt in judgment["alternatives"] if alt["key"] == "retrieve_more"
    )
    assert alternative["probability"] == display["probability"]


def test_probability_mismatch_is_flagged_as_invariant() -> None:
    flow = _base_flow()
    preflight = _preflight()
    question = preflight["packs"][0]["questions"][0]
    question["distribution"]["probabilities"] = {
        "retrieve_more": 0.27,
        "generate": 0.73,
    }
    flow["jev_preflight"] = preflight
    trace = build_traceability(flow)
    codes = [inv["code"] for inv in trace["diagnostics"]["invariants"]]
    assert "PROBABILITY_MISMATCH" in codes


def test_verification_partial_when_secondary_check_not_observed() -> None:
    flow = _base_flow()
    flow["verification"] = {
        "overall": "partial",
        "checks": [
            {"key": "grounding", "state": "ok"},
            {"key": "answer_gate", "state": "not_observed"},
        ],
    }
    trace = build_traceability(flow)
    verification = trace["verification"]
    assert verification["status"] == "PARTIALLY_VERIFIED"
    codes = [item["code"] for item in verification["explanation_codes"]]
    assert "DOCUMENTARY_SUPPORT_CONFIRMED" in codes
    assert "SECONDARY_CHECK_UNAVAILABLE" in codes


def test_verification_insufficient_when_generation_retained() -> None:
    flow = _base_flow()
    flow["fallbacks"] = ["preflight_abstained"]
    flow["generation"] = {"skipped": True}
    flow["grounding"] = {"grounded": False, "score": 0.0}
    trace = build_traceability(flow)
    assert trace["verification"]["status"] == "INSUFFICIENT_EVIDENCE"
    codes = [item["code"] for item in trace["verification"]["explanation_codes"]]
    assert "GENERATION_RETAINED" in codes


def test_verification_conflicting_evidence() -> None:
    flow = _base_flow()
    flow["evidence"]["sufficiency"] = {
        "recommended_action": "generate",
        "reason": "partial_entity_coverage",
        "conflicting_chunks": 2,
    }
    trace = build_traceability(flow)
    assert trace["verification"]["status"] == "CONFLICTING_EVIDENCE"


def test_verification_fallback_verifier_is_explained() -> None:
    flow = _base_flow()
    flow["verification"] = {
        "overall": "verified",
        "checks": [{"key": "grounding", "state": "ok"}],
        "fallback_used": True,
        "fallback_code": "backup_verifier",
    }
    trace = build_traceability(flow)
    codes = [item["code"] for item in trace["verification"]["explanation_codes"]]
    assert "FALLBACK_VERIFIER_USED" in codes


def test_temporal_invariant_flags_insufficient_then_generated_without_cause() -> None:
    flow = _base_flow()
    flow["retrieval"] = {
        "used": True,
        "chunks": 3,
        "attempts": 1,
        "rounds": [
            {"attempt": 1, "strategy": "hybrid", "sufficient": False, "n_items": 3}
        ],
    }
    trace = build_traceability(flow)
    codes = [inv["code"] for inv in trace["diagnostics"]["invariants"]]
    assert "INSUFFICIENT_THEN_GENERATED" in codes


def test_temporal_invariant_accepts_expansion_as_explanation() -> None:
    flow = _base_flow()
    flow["retrieval"] = {
        "used": True,
        "chunks": 5,
        "attempts": 2,
        "expanded": True,
        "rounds": [
            {"attempt": 1, "strategy": "hybrid", "sufficient": False, "n_items": 3},
            {"attempt": 2, "strategy": "hybrid", "sufficient": True, "n_items": 5},
        ],
    }
    flow["jev_preflight"] = _preflight()
    trace = build_traceability(flow)
    codes = [inv["code"] for inv in trace["diagnostics"]["invariants"]]
    assert "INSUFFICIENT_THEN_GENERATED" not in codes


def test_timeline_never_invents_answer_revision() -> None:
    flow = _base_flow()
    trace = build_traceability(flow)
    assert not [item for item in trace["timeline"] if item["type"] == "ANSWER_REVISED"]

    flow["steps"] = [
        {
            "type": "answer_revision",
            "id": "step-9",
            "status": "ok",
            "detail": "se quitó una advertencia que contradecía la respuesta",
        }
    ]
    enriched = with_story(flow)
    trace = build_traceability(enriched)
    revised = [item for item in trace["timeline"] if item["type"] == "ANSWER_REVISED"]
    assert len(revised) == 1
    assert revised[0]["source_event_ids"] == ["step-9"]


def test_with_story_adds_traceability_without_touching_history() -> None:
    flow = _base_flow()
    enriched = with_story(dict(flow))
    assert enriched["traceability"]["schema_version"] == 1
    for key in ("evidence", "grounding", "generation", "retrieval"):
        assert key in enriched


def test_evidence_from_tool_step_meta_is_ingested() -> None:
    flow = {
        "status": "completed",
        "generation": {"skipped": False},
        "steps": [
            {
                "type": "tool_call",
                "id": "s-1",
                "tool": "search_knowledge",
                "meta": {
                    "evidence": [
                        {
                            "ref": "d-1",
                            "document_id": "d-1",
                            "chunk_id": "c-1",
                            "title": "manual.pdf",
                            "excerpt": "texto del fragmento",
                            "status": "USED",
                            "doc_index": 1,
                        }
                    ]
                },
            }
        ],
        "sources": [],
    }
    trace = with_story(flow)["traceability"]
    assert trace["counts"]["evidence_retrieved"] == 1
    assert trace["evidence"]["documents"][0]["document_name"] == "manual.pdf"
    search_steps = [
        item
        for item in trace["timeline"]
        if item["type"] == "EVIDENCE_FOUND" and item["user_visible"]
    ]
    assert search_steps
    assert search_steps[0]["summary_params"]["evidence"] == 1


def test_every_used_evidence_keeps_identifier() -> None:
    flow = _base_flow()
    trace = build_traceability(flow)
    used = [item for item in trace["evidence"]["items"] if item["used_in_answer"] is True]
    assert used
    assert all(item.get("evidence_id") for item in used)
