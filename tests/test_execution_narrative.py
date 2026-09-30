from __future__ import annotations

from src.rag.execution_narrative import build_execution_narrative


def _flow(*, complete: bool, overall: str, status: str = "completed") -> dict:
    missing = [] if complete else ["&&&F"]
    return {
        "status": status,
        "generation": {"skipped": False},
        "verification": {
            "overall": overall,
            "checks": [{"key": "grounding", "state": "warn"}],
        },
        "steps": [
            {
                "type": "generation_package",
                "ready": complete,
                "mode": "generate_full" if complete else "generate_with_limits",
                "missing_evidence": missing,
                "evidence": {
                    "evidence_complete": complete,
                    "generation_mode": (
                        "generate_full" if complete else "generate_with_limits"
                    ),
                    "missing_documentable_evidence": missing,
                    "conflicts": [],
                    "coverage": [],
                },
            },
            {"id": "final-1", "type": "final", "status": "ok"},
        ],
        "sources": [],
    }


def test_complete_evidence_with_verification_warning_is_not_insufficient() -> None:
    narrative = build_execution_narrative(
        _flow(complete=True, overall="partial"), []
    )

    assert narrative["evidence"]["complete"] is True
    assert narrative["evidence"]["missing_documentable_evidence"] == []
    assert narrative["outcome"]["code"] == "ANSWERED_WITH_LIMITS"
    assert narrative["outcome"]["reason_code"] == "verification_partial"


def test_explicit_abstention_precedes_generic_block() -> None:
    flow = _flow(complete=False, overall="blocked")
    flow["verification"]["checks"] = [
        {"key": "answer_gate", "state": "blocked", "detail": "abstain"}
    ]
    flow["generation"]["skipped"] = True

    narrative = build_execution_narrative(flow, [])

    assert narrative["outcome"]["code"] == "ABSTAINED"
    assert narrative["outcome"]["reason_code"] == "explicit_abstention"


def test_retry_success_uses_retried_outcome() -> None:
    flow = _flow(complete=True, overall="verified")
    flow["jev_preflight"] = {
        "decisions": [
            {
                "phase": "post_retrieval",
                "question_id": "needs_more_evidence",
                "action": "retrieve_more",
                "applied": True,
            }
        ]
    }

    narrative = build_execution_narrative(flow, [])

    assert narrative["outcome"]["code"] == "RETRIED_AND_ANSWERED"


def test_requirements_distinguish_sources_from_user_input() -> None:
    flow = _flow(complete=True, overall="verified")
    flow["steps"].insert(
        0,
        {
            "id": "anchors-1",
            "type": "anchor_roles",
            "fields": ["FCLAS"],
            "rules": ["&&&F"],
            "examples": ["QNNF0SME"],
            "application": "Aplicar la regla al fare basis de ejemplo",
            "requirement_coverage": [
                {
                    "label": "FCLAS",
                    "status": "FOUND",
                    "evidence_refs": ["a"],
                },
                {
                    "label": "&&&F",
                    "status": "FOUND",
                    "evidence_refs": ["b"],
                },
            ],
        },
    )

    result = build_execution_narrative(flow, [])
    by_label = {item["label"]: item for item in result["requirements"]}

    assert by_label["FCLAS"]["kind"] == "DOCUMENTABLE"
    assert by_label["&&&F"]["source_required"] is True
    assert by_label["QNNF0SME"]["kind"] == "USER_INPUT"
    assert by_label["QNNF0SME"]["source_required"] is False
    assert result["understanding"]["application"] == (
        "Aplicar la regla al fare basis de ejemplo"
    )


def test_numeric_canonical_coverage_and_anchor_roles_are_supported() -> None:
    flow = _flow(complete=True, overall="verified")
    package = next(
        item for item in flow["steps"] if item["type"] == "generation_package"
    )
    package["evidence"] = {
        "evidence_complete": True,
        "coverage": 1.0,
        "anchors": [
            {
                "value": "FCLAS",
                "role": "field_anchor",
                "found": True,
                "requires_source_match": True,
            },
            {
                "value": "QNNF0SME",
                "role": "example_value",
                "found": False,
                "requires_source_match": False,
            },
        ],
        "missing_documentable_evidence": [],
        "conflicts": [],
    }

    result = build_execution_narrative(flow, [])

    assert result["evidence"]["coverage_ratio"] == 1.0
    assert result["evidence"]["requirements"] == []
    assert result["requirements"] == [
        {
            "id": "documentable:fclas",
            "label": "FCLAS",
            "kind": "DOCUMENTABLE",
            "status": "FOUND",
            "source_required": True,
            "evidence_refs": [],
            "source_event_ids": [],
        },
        {
            "id": "user-input:qnnf0sme",
            "label": "QNNF0SME",
            "kind": "USER_INPUT",
            "status": "PROVIDED",
            "source_required": False,
            "evidence_refs": [],
            "source_event_ids": [],
        },
    ]


def test_four_passages_become_two_documents() -> None:
    flow = _flow(complete=True, overall="verified")
    flow["sources"] = [
        {
            "evidence_id": "a",
            "document_id": "cat",
            "title": "Rec2_Cat10.pdf",
            "page": 1,
            "content": "FCLAS",
        },
        {
            "evidence_id": "b",
            "document_id": "rules",
            "title": "Rec2_Rules.pdf",
            "page": 4,
            "content": "&&&F",
        },
        {
            "evidence_id": "c",
            "document_id": "cat",
            "title": "Rec2_Cat10.pdf",
            "page": 2,
            "content": "Fare basis",
        },
        {
            "evidence_id": "d",
            "document_id": "cat",
            "title": "Rec2_Cat10.pdf",
            "page": 3,
            "content": "Mask",
        },
    ]

    evidence = build_execution_narrative(flow, [])["evidence"]

    assert evidence["document_count"] == 2
    assert evidence["passage_count"] == 4
    assert len(evidence["documents"]) == 2
    cat = next(item for item in evidence["documents"] if item["document_id"] == "cat")
    assert cat["passage_count"] == 3


def test_duplicate_evidence_id_is_counted_once() -> None:
    flow = _flow(complete=True, overall="verified")
    source = {
        "evidence_id": "same",
        "document_id": "cat",
        "title": "Cat.pdf",
        "content": "FCLAS",
    }
    flow["sources"] = [source, dict(source)]

    evidence = build_execution_narrative(flow, [])["evidence"]

    assert evidence["passage_count"] == 1


def test_distinct_passages_with_same_filename_are_preserved() -> None:
    flow = _flow(complete=True, overall="verified")
    flow["sources"] = [
        {
            "evidence_id": "one",
            "source_id": "source",
            "title": "Rules.pdf",
            "page": 1,
            "content": "first",
        },
        {
            "evidence_id": "two",
            "source_id": "source",
            "title": "Rules.pdf",
            "page": 2,
            "content": "second",
        },
    ]

    evidence = build_execution_narrative(flow, [])["evidence"]

    assert evidence["document_count"] == 1
    assert evidence["passage_count"] == 2


def test_identical_passage_fallback_in_distinct_documents_is_preserved() -> None:
    flow = _flow(complete=True, overall="verified")
    flow["sources"] = [
        {
            "document_id": "one",
            "title": "One.pdf",
            "page": 1,
            "content": "same excerpt",
        },
        {
            "document_id": "two",
            "title": "Two.pdf",
            "page": 1,
            "content": "same excerpt",
        },
    ]

    evidence = build_execution_narrative(flow, [])["evidence"]

    assert evidence["document_count"] == 2
    assert evidence["passage_count"] == 2


def test_one_applied_decision_drives_summary_and_journey() -> None:
    flow = _flow(complete=True, overall="verified")
    flow["jev_preflight"] = {
        "packs": [
            {
                "phase": "post_retrieval",
                "questions": [
                    {
                        "id": "needs_more_evidence",
                        "type": "noul",
                        "decision": "yes",
                        "certainty": 0.62,
                    },
                    {
                        "id": "needs_tool",
                        "type": "noul",
                        "decision": "yes",
                        "certainty": 0.91,
                    },
                    {
                        "id": "tool",
                        "type": "choice",
                        "decision": "search_knowledge",
                        "confidence": 0.79,
                    },
                    {
                        "id": "satisfied",
                        "type": "noul",
                        "decision": "no",
                        "certainty": 0.72,
                    },
                ],
            }
        ],
        "decisions": [
            {
                "phase": "post_retrieval",
                "question_id": "needs_more_evidence",
                "action": "retrieve_more",
                "applied": True,
                "reasons": ["evidence_gap"],
            }
        ],
        "summary": {"decisions_influenced": 99},
    }

    result = build_execution_narrative(flow, [])

    assert len(result["judgments"]) == 4
    assert len(result["applied_decisions"]) == 1
    applied_judgments = [
        item for item in result["judgments"] if item["applied_decision_id"]
    ]
    assert [item["id"] for item in applied_judgments] == ["needs_more_evidence"]
    assert result["summary"]["decisions_influenced"] == 1
    assert sum(item["kind"] == "JEV_CHANGED_PATH" for item in result["journey"]) == 1
    retry = next(item for item in result["journey"] if item["kind"] == "SEARCH_RETRIED")
    assert retry["decision_id"] == result["applied_decisions"][0]["id"]


def test_zero_applied_decisions_stays_zero() -> None:
    flow = _flow(complete=True, overall="verified")
    flow["jev_preflight"] = {
        "packs": [
            {
                "phase": "pre_generation",
                "questions": [{"id": "satisfied", "decision": "yes"}],
            }
        ],
        "decisions": [
            {"phase": "pre_generation", "action": "answer", "applied": False}
        ],
    }

    result = build_execution_narrative(flow, [])

    assert result["summary"]["decisions_influenced"] == 0
    assert result["applied_decisions"] == []


def test_jev_questions_and_applied_impact_can_come_from_canonical_events() -> None:
    flow = _flow(complete=True, overall="verified")
    events = [
        {
            "id": "jev-1",
            "kind": "jev_pack",
            "phase": "evidence",
            "metrics": {
                "phase": "post_retrieval",
                "questions": [
                    {
                        "id": "needs_more_evidence",
                        "type": "noul",
                        "decision": "yes",
                        "certainty": 0.6,
                    }
                ],
            },
            "decision": {
                "action": "retrieve_more",
                "applied": True,
                "question_id": "needs_more_evidence",
                "reason_codes": ["evidence_gap"],
            },
        }
    ]

    result = build_execution_narrative(flow, events)

    assert [item["id"] for item in result["judgments"]] == [
        "needs_more_evidence"
    ]
    assert result["summary"]["jev_calls"] == 1
    assert result["summary"]["decisions_influenced"] == 1
    assert result["judgments"][0]["applied_decision_id"]


def test_tool_uncertainty_preserves_probability_and_certainty_separately() -> None:
    flow = _flow(complete=True, overall="verified")
    flow["jev_preflight"] = {
        "packs": [
            {
                "phase": "pre_reasoning",
                "questions": [
                    {
                        "id": "tool",
                        "type": "choice",
                        "decision": "none",
                        "confidence": 0.55,
                        "certainty": 0.20,
                        "ambiguous": True,
                        "distribution": {
                            "probabilities": {
                                "none": 0.55,
                                "search_knowledge": 0.45,
                            }
                        },
                    }
                ],
            }
        ],
        "decisions": [],
    }

    [judgment] = build_execution_narrative(flow, [])["judgments"]

    assert judgment["probability"] == 0.55
    assert judgment["certainty"] == 0.20
    assert judgment["ambiguous"] is True
    assert judgment["alternatives"] == [
        {"key": "none", "probability": 0.55},
        {"key": "search_knowledge", "probability": 0.45},
    ]


def test_invalid_probability_becomes_technical_diagnostic() -> None:
    flow = _flow(complete=True, overall="verified")
    flow["jev_preflight"] = {
        "packs": [
            {
                "phase": "pre_reasoning",
                "questions": [
                    {
                        "id": "tool",
                        "type": "choice",
                        "decision": "search_knowledge",
                        "confidence": 709.1,
                    }
                ],
            }
        ]
    }

    result = build_execution_narrative(flow, [])

    assert result["judgments"][0]["probability"] is None
    assert result["diagnostics"] == [
        {
            "code": "INVALID_PROBABILITY",
            "field": "judgments.tool.probability",
            "raw_value": 709.1,
            "source_event_id": None,
        }
    ]


def test_two_llm_calls_have_distinct_purposes() -> None:
    flow = _flow(complete=True, overall="verified")
    flow["steps"] = [
        {
            "id": "llm-1",
            "type": "llm",
            "action": {"tool": "search_knowledge"},
            "latency_ms": 7700,
        },
        {
            "id": "llm-2",
            "type": "llm",
            "action": {"answer": "ready"},
            "latency_ms": 5700,
        },
        *flow["steps"],
    ]

    calls = build_execution_narrative(flow, [])["model_calls"]

    assert [item["purpose"] for item in calls] == ["ANALYSIS", "ANSWER"]
    assert [item["duration_ms"] for item in calls] == [7700.0, 5700.0]


def test_generation_call_counts_supply_purposes_when_steps_are_absent() -> None:
    flow = _flow(complete=True, overall="verified")
    flow["generation"].update(
        {"calls": 2, "reasoning_calls": 1, "answer_calls": 1, "ms": 1300}
    )

    calls = build_execution_narrative(flow, [])["model_calls"]

    assert [item["purpose"] for item in calls] == ["ANALYSIS", "ANSWER"]


def test_generation_without_call_metadata_is_one_unknown_model_stage() -> None:
    flow = _flow(complete=True, overall="verified")

    calls = build_execution_narrative(flow, [])["model_calls"]

    assert [item["purpose"] for item in calls] == ["UNKNOWN"]


def test_revision_journey_exists_only_for_observed_revision() -> None:
    flow = _flow(complete=True, overall="verified")
    assert "ANSWER_REVISED" not in {
        item["kind"] for item in build_execution_narrative(flow, [])["journey"]
    }

    flow["steps"].insert(0, {"id": "revision-1", "type": "answer_revision"})
    kinds = {item["kind"] for item in build_execution_narrative(flow, [])["journey"]}
    assert "ANSWER_REVISED" in kinds
