# =============================================================================
# P18.1-06/07 — Puerta de candidatos y reclasificación de afirmaciones
# =============================================================================
from __future__ import annotations

from uuid import uuid4

from src.core.domain.knowledge_v2 import StructuredBlock, StructuredBlockKind, StructuredDocument
from src.knowledge.compiler.candidates import (
    assess_entity_candidate,
    assess_rule_candidate,
    classify_claim_kind,
)
from src.knowledge.compiler.rules import extract_rules
from src.knowledge.quality.ingestion import QualityCollector


def _doc(text: str, *, genre: str = "unknown", title: str = "documento"):
    blocks = tuple(
        StructuredBlock(kind=StructuredBlockKind.PARAGRAPH, text=line, order=index)
        for index, line in enumerate(text.splitlines())
        if line.strip()
    )
    return StructuredDocument(
        id=uuid4(),
        organization_id=uuid4(),
        external_id="fixture.txt",
        title=title,
        content_hash="pending",
        blocks=blocks,
        metadata={
            "understanding": {
                "profile": {"document_genre": genre}
            }
        },
    )


def test_question_and_dialogue_labels_are_not_concepts() -> None:
    for label in ("planeta?", "¿recuerdas?", "—dijo el zorro"):
        decision = assess_entity_candidate(
            label, kind="concept", document=_doc("texto", genre="narrative")
        )
        assert decision.accepted is False
        assert decision.reason in {
            "QUESTION_OR_DIALOGUE",
            "DIALOGUE_FRAGMENT",
        }
        assert decision.needs_review is True


def test_number_is_valid_only_with_schema_context() -> None:
    assert (
        assess_entity_candidate("52", kind="concept", document=_doc("x"))
        .accepted
        is False
    )
    assert assess_entity_candidate(
        "52",
        kind="field",
        document=_doc("El campo 52 declara una posición del registro."),
        text="campo 52 posición 10 longitud 2",
    ).accepted is True


def test_narrative_rule_is_rejected_with_explanation() -> None:
    doc = _doc(
        "El principito debe cuidar la flor, dijo el zorro con voz suave.",
        genre="narrative",
    )
    quality = QualityCollector()
    rules = extract_rules(doc, quality=quality)
    assert rules == []
    assert any(
        issue["detail"].get("semantic_gate") == "NON_NORMATIVE_CONTEXT"
        for issue in quality.issues
    )


def test_policy_and_contract_obligations_survive() -> None:
    policy = _doc(
        "El empleado debe aprobar el gasto antes de enviarlo al proveedor.",
        genre="policy",
    )
    rules = extract_rules(policy)
    assert len(rules) == 1
    assert rules[0].claim_kind == "policy_rule"

    contract = _doc(
        "El proveedor deberá pagar la indemnización prevista en el contrato.",
        genre="legal",
    )
    rules = extract_rules(contract)
    assert len(rules) == 1
    assert rules[0].claim_kind == "contract_obligation"


def test_quoted_dialogue_is_not_a_rule() -> None:
    decision = assess_rule_candidate(
        "—Tienes que mantener tu promesa, dijo el principito.",
        subject="El principito",
        document=_doc("texto", genre="narrative"),
    )
    assert decision.accepted is False
    assert decision.claim_kind == "quoted_dialogue"


def test_claim_classification_is_explicit() -> None:
    assert (
        classify_claim_kind(
            "El empleado debe aprobar el gasto.",
            document=_doc("x", genre="policy"),
        )
        == "policy_rule"
    )
    assert (
        classify_claim_kind(
            "El proveedor deberá pagar la indemnización.",
            document=_doc("x", genre="legal"),
        )
        == "contract_obligation"
    )
    assert (
        classify_claim_kind(
            "—Debes cuidar la flor, dijo el zorro.",
            document=_doc("x", genre="narrative"),
        )
        == "quoted_dialogue"
    )
