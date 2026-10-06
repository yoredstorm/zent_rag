# =============================================================================
# Parser Lab — Knowledge A/B offline (sin persistencia, sin LLM)
# =============================================================================
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from src.knowledge.parser_lab.knowledge_ab import (
    compare_knowledge_sides,
    run_and_compare,
    run_offline_knowledge,
)
from src.knowledge.structure.opendataloader_client import OpenDataLoaderConversion
from src.knowledge.structure.opendataloader_mapping import (
    OpenDataLoaderMappingContext,
    map_opendataloader_document,
)

FIXTURES = Path(__file__).parent / "fixtures" / "parser_lab"

REQUIRED_COUNTS = {
    "semantic_units_count",
    "definitions_count",
    "facts_count",
    "rules_count",
    "relationships_count",
    "semantic_threads_count",
    "canonical_rules_count",
    "supported_rules_count",
    "executable_rules_count",
    "conflicting_rules_count",
    "unknown_rules_count",
}


def _map(name: str):
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return map_opendataloader_document(
        payload,
        context=OpenDataLoaderMappingContext(
            organization_id=uuid4(),
            external_id=name,
            source_name=name,
            page_heights=(792.0, 792.0),
            parser_info={"engine": "opendataloader", "version": "2.5.12", "mode": "local"},
            structure_source="inferred_layout",
            conversion=OpenDataLoaderConversion(data=payload, elapsed_seconds=0.2),
        ),
    )


@pytest.mark.timeout(240)
def test_offline_chain_produces_knowledge_and_quality() -> None:
    document = _map("atpco_fare_class.json")
    expectations = json.loads(
        (FIXTURES / "atpco_fare_class.expectations.json").read_text(encoding="utf-8")
    )
    side = run_offline_knowledge(document, label="opendataloader", expectations=expectations)

    assert REQUIRED_COUNTS.issubset(side.counts)
    assert side.counts["semantic_units_count"] >= 1
    assert side.counts["rules_count"] >= 1
    assert side.counts["canonical_rules_count"] >= 1
    assert side.counts["supported_rules_count"] >= 1
    assert side.counts["semantic_threads_count"] >= 1

    quality = side.quality
    assert quality["supported_rate"] == 1.0
    assert quality["orphan_rule_rate"] == 0.0
    assert quality["property_provenance_completeness"] == 1.0
    assert quality["expectations_evaluated"] is True
    assert quality["recall_units"] == 1.0
    assert quality["recall_rules"] == 1.0

    premises = side.premise_dimensions
    assert premises["total"] >= 1
    assert premises["grounded_rate"] == 1.0
    assert not side.warnings


@pytest.mark.timeout(240)
def test_run_and_compare_returns_deltas() -> None:
    document = _map("atpco_fare_class.json")
    comparison = run_and_compare(
        document,
        document,
        labels=("pdfplumber", "opendataloader"),
        run_threads=False,
    )
    assert comparison["schema"] == "zent.knowledge_ab.1"
    assert comparison["labels"] == {"a": "pdfplumber", "b": "opendataloader"}
    for key in REQUIRED_COUNTS:
        assert key in comparison["counts"]
        assert comparison["counts"][key]["b_minus_a"] == 0
    assert "quality" in comparison
    assert "premises" in comparison
    assert set(comparison["sides"]) == {"pdfplumber", "opendataloader"}


def test_compare_sides_without_running_chain() -> None:
    side_a = run_offline_knowledge_stub("a", rules=3, supported=2)
    side_b = run_offline_knowledge_stub("b", rules=5, supported=1)
    comparison = compare_knowledge_sides(side_a, side_b)
    assert comparison["counts"]["canonical_rules_count"]["b_minus_a"] == 2
    assert comparison["counts"]["supported_rules_count"]["b_minus_a"] == -1


def run_offline_knowledge_stub(label: str, *, rules: int, supported: int):
    """Stub sin cadena: verifica el comparador puro."""
    from src.knowledge.parser_lab.knowledge_ab import KnowledgeSideResult

    return KnowledgeSideResult(
        label=label,
        counts={"canonical_rules_count": rules, "supported_rules_count": supported},
        threads={"total": rules},
        quality={"supported_rate": supported / rules if rules else None},
        premise_dimensions={"total": rules, "grounded": supported},
    )
