# =============================================================================
# P0 — Golden Set: schema, matchers y símbolos puros
# =============================================================================
from __future__ import annotations

from pathlib import Path

from src.knowledge.parser_lab.p0.corpus import CORPUS, golden_for, write_golden_sets
from src.knowledge.parser_lab.p0.golden import best_match, match_score, normalize

REQUIRED_OBJECT_FIELDS = {
    "id",
    "semantic_type",
    "meaning",
    "pages",
    "section",
    "equivalents",
    "properties",
    "relations",
    "executable",
    "required_premises",
    "allowed_formulations",
}
REQUIRED_QUERY_FIELDS = {
    "id",
    "kind",
    "question",
    "expected_status",
    "values",
    "objects",
    "expected_answer_contains",
    "executable",
    "cross_page",
    "answerable",
}


def test_golden_sets_have_required_schema() -> None:
    for doc in CORPUS:
        golden = golden_for(doc)
        assert golden["document"] == doc.name
        assert golden["letter"] == doc.letter
        assert "anchor_terms" in golden
        for item in golden["objects"]:
            assert REQUIRED_OBJECT_FIELDS.issubset(item.keys())
            assert item["semantic_type"]
            assert item["pages"]
        for query in golden["queries"]:
            assert REQUIRED_QUERY_FIELDS.issubset(query.keys())
            assert query["kind"]


def test_golden_sets_cover_required_semantic_types() -> None:
    types: set[str] = set()
    for doc in CORPUS:
        for item in golden_for(doc)["objects"]:
            types.add(item["semantic_type"])
    required = {
        "definition",
        "fact",
        "rule",
        "exception",
        "relationship",
        "enumeration",
        "range",
        "formula",
        "table_mapping",
        "symbol_definition",
        "length_policy",
        "temporal_constraint",
        "cross_page_rule",
    }
    assert required.issubset(types)


def test_match_score_handles_pure_symbols() -> None:
    golden = {
        "equivalents": ["&", "alphanumeric character"],
        "properties": {},
    }
    assert match_score(golden, "An & indicates an alphanumeric character") == 1.0
    assert match_score(golden, "sin simbolo ni frase") == 0.0
    assert normalize("&") == ""


def test_best_match_threshold_and_kind() -> None:
    golden = {"equivalents": ["KPI-A", "promedio de ventas"], "properties": {}}
    haystacks = [
        ("El indicador KPI-A es el promedio de ventas diarias", object(), "unit"),
        ("otra cosa", object(), "unit"),
    ]
    match = best_match(golden, haystacks)
    assert match.matched is True
    assert match.score == 1.0
    assert match.produced_kind == "unit"
    assert match.produced_index == 0


def test_write_golden_sets(tmp_path: Path) -> None:
    written = write_golden_sets(tmp_path)
    assert len(written) == len(CORPUS)
    assert (tmp_path / "atpco.json").is_file()
