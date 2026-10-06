# =============================================================================
# P0 — Premisas y KnowledgeDiff (sin cadena completa: estados mínimos)
# =============================================================================
from __future__ import annotations

from uuid import uuid4

from src.core.domain.knowledge_v2 import (
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.compiler.model import CompilationResult
from src.knowledge.parser_lab.p0.diff import knowledge_diff
from src.knowledge.parser_lab.p0.evaluate import premise_satisfied
from src.knowledge.parser_lab.p0.golden import GoldenMatch
from src.knowledge.parser_lab.p0.state import KnowledgeState
from src.knowledge.structure.base import content_hash, token_count


def _document(text: str) -> StructuredDocument:
    block = StructuredBlock(
        kind=StructuredBlockKind.PARAGRAPH,
        text=text,
        order=0,
        page=1,
        token_count=token_count(text),
        content_hash=content_hash(text),
    )
    return StructuredDocument(
        id=uuid4(),
        organization_id=uuid4(),
        external_id="premise.pdf",
        title="premise",
        content_hash=content_hash(text),
        blocks=(block,),
    )


def _state(text: str) -> KnowledgeState:
    document = _document(text)
    return KnowledgeState(
        label="stub",
        document=document,
        understood=document,
        compiled=CompilationResult(organization_id=document.organization_id),
        units=[],
    )


def test_premises_satisfied_from_atpco_like_text() -> None:
    text = (
        "The ! or & indicate a match to any alphanumeric character in that "
        "position of the fare class. A fare class must contain at least the "
        "number of characters referenced in the fare class field "
        "(additional characters may follow)."
    )
    state = _state(text)
    golden = {"properties": {"symbol": "&"}, "equivalents": ["&"]}
    assert premise_satisfied("symbol.definition", state, golden) is True
    assert premise_satisfied("matching.operator", state, golden) is True
    assert premise_satisfied("length.policy", state, golden) is True
    assert premise_satisfied("formula.expression", state, golden) is False


def test_premise_missing_when_text_lacks_semantics() -> None:
    state = _state("texto sin semantica de patrones")
    golden = {"properties": {"symbol": "&"}, "equivalents": ["&"]}
    assert premise_satisfied("symbol.definition", state, golden) is False
    assert premise_satisfied("length.policy", state, golden) is False


def _match(golden_id: str, matched: bool, score: float, kind: str = "canonical_rule") -> GoldenMatch:
    return GoldenMatch(
        golden_id=golden_id,
        semantic_type="rule",
        score=score,
        matched=matched,
        produced_kind=kind,
    )


def test_knowledge_diff_categories() -> None:
    golden = {
        "objects": [
            {"id": "r1", "semantic_type": "rule", "meaning": "uno", "pages": [1]},
            {"id": "r2", "semantic_type": "rule", "meaning": "dos", "pages": [1]},
            {"id": "r3", "semantic_type": "rule", "meaning": "tres", "pages": [1]},
        ]
    }
    state_a = _state("texto")
    state_b = _state("texto")
    matches_a = {
        "r1": _match("r1", True, 1.0),
        "r2": _match("r2", True, 1.0),
        "r3": _match("r3", False, 0.2),
    }
    matches_b = {
        "r1": _match("r1", True, 1.0),
        "r2": _match("r2", False, 0.2),
        "r3": _match("r3", True, 1.0),
    }
    diff = knowledge_diff(golden, state_a, state_b, matches_a, matches_b)
    assert diff["counts"]["ADDED_CORRECT"] == 1  # r3
    assert diff["counts"]["MISSING"] == 1  # r2
    assert diff["categories"]["ADDED_CORRECT"][0]["id"] == "r3"
    assert diff["categories"]["MISSING"][0]["id"] == "r2"
