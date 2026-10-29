# =============================================================================
# P18.3-02 - Contratos puros del harness de evaluación
# =============================================================================
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from src.scripts.evaluate_knowledge_goldset import (
    _answer_matches,
    _behavior_correct,
    _citation_supports,
    _is_abstention,
    _norm,
    _run_case,
    compare_runs,
)


def _case(**overrides):
    base = {
        "case_id": "c1",
        "family": "tabular",
        "difficulty": 2,
        "split": "dev",
        "source_ref": "src",
        "question": "¿Cuál es el precio de la rosa?",
        "expected_behavior": "answer",
        "gold_answer": "10",
        "accepted_variants": ["10"],
        "expected_claim_type": "tabular_calculation",
        "supporting_evidence": [
            {
                "page": 1,
                "verbatim_excerpt": "rosa,10,4",
            }
        ],
    }
    base.update(overrides)
    return base


def test_normalization_and_numeric_match_do_not_accept_wrong_number() -> None:
    assert _norm("¿Cuál es el PRECIO?") == "cual es el precio"
    assert _answer_matches("El precio es 10.", _case())
    assert not _answer_matches("El precio es 12.", _case())


def test_abstention_and_behavior_detection() -> None:
    assert _is_abstention("No tengo suficiente información para responder.")
    assert not _is_abstention("La rosa cuesta 10.")
    assert _behavior_correct(
        "No tengo suficiente información.",
        _case(expected_behavior="abstain", gold_answer=None, expected_claim_type="unsupported"),
    )
    assert _behavior_correct("La rosa cuesta 10.", _case())


def test_citation_support_requires_page_and_excerpt_overlap() -> None:
    evidence = {"page": 1, "verbatim_excerpt": "rosa,10,4"}
    assert _citation_supports({"page": 1, "excerpt": "rosa,10,4"}, evidence)
    assert not _citation_supports({"page": 2, "excerpt": "rosa,10,4"}, evidence)
    assert not _citation_supports({"page": 1, "excerpt": "tulipán,12,0"}, evidence)


@pytest.mark.asyncio
async def test_http_503_is_blocked_provider_not_pass() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "provider unavailable"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://test"
    ) as client:
        row = await _run_case(
            client,
            corpus_id="corpus",
            case=_case(),
            source_map={},
            timeout=5,
            retries=0,
        )
    assert row["status"] == "BLOCKED_PROVIDER"
    assert row["error"].startswith("HTTP 503")


@pytest.mark.asyncio
async def test_successful_response_captures_citations_and_retrieval_candidates() -> None:
    payload = {
        "grounded": {
            "answer": "La rosa cuesta 10.",
            "claims": [{"text": "La rosa cuesta 10.", "status": "supported"}],
            "citations": [
                {
                    "document_id": "doc-1",
                    "page": 1,
                    "locator": "page/1",
                    "excerpt": "rosa,10,4",
                }
            ],
            "sources_used": ["src-1"],
        },
        "retrieval_debug": {
            "candidates": [
                {"source_id": "src-1", "page": 1, "excerpt": "rosa,10,4", "score": 0.9}
            ]
        },
        "telemetry": {"model": "m", "total_tokens": 10},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://test"
    ) as client:
        row = await _run_case(
            client,
            corpus_id="corpus",
            case=_case(),
            source_map={"src": "src-1"},
            timeout=5,
            retries=0,
        )
    assert row["status"] == "COMPLETED"
    assert row["behavior_correct"] is True
    assert row["citation_precision"] == 1.0
    assert row["retrieval_recall_at_k"] == 1.0
    assert row["telemetry"]["model"] == "m"


def test_compare_flags_more_than_two_point_regression(tmp_path: Path) -> None:
    baseline = {
        "label": "base",
        "overall": {"answer_accuracy": 0.9, "citation_precision": 0.9},
    }
    candidate = {
        "label": "cand",
        "overall": {"answer_accuracy": 0.85, "citation_precision": 0.9},
    }
    base_path = tmp_path / "base.json"
    cand_path = tmp_path / "cand.json"
    base_path.write_text(json.dumps(baseline), encoding="utf-8")
    cand_path.write_text(json.dumps(candidate), encoding="utf-8")
    result = compare_runs(base_path, cand_path)
    assert result["status"] == "REGRESSION"
    assert "answer_accuracy" in result["regressions"]
    assert result["deltas"]["citation_precision"]["delta"] == 0.0
