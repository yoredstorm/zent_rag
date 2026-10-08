# =============================================================================
# ODL / pdfplumber parity — mismo benchmark semántico, misma operación
# =============================================================================
# El MISMO contenido (Record 2: máscara &&&F aplicada a ABCFGEGE) llega por dos
# provenances de parser distintas:
#
#   opendataloader  -> payload JSON mapeado por map_opendataloader_document
#   pdfplumber      -> StructuredDocument desde el texto RAW del fixture
#
# No se exigen los MISMOS Rule IDs (los ids dependen del documento/provenance).
# Sí se exige:
#   - misma familia de operación: MATCHING -> POSITIONAL_MATCH
#   - mismo resultado determinista final: MATCH
#   - mismas capabilities requeridas por la query.
#
# ATPCO (&&&F / ABCFGEGE) se usa SOLO como fixture de regresión, nunca como
# lógica productiva.
# =============================================================================
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from src.core.domain.knowledge_v2 import (
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
)
from src.intelligence.reasoning.grounded_engine import reason_over_evidence
from src.knowledge.structure.base import content_hash, token_count
from src.knowledge.structure.opendataloader_client import OpenDataLoaderConversion
from src.knowledge.structure.opendataloader_mapping import (
    OpenDataLoaderMappingContext,
    map_opendataloader_document,
)
from src.runtime.decision_envelope import build_decision_envelope
from src.runtime.operation_compatibility import (
    FAMILY_MATCHING,
    derive_query_operation_requirements,
    gate_rules_for_requirements,
    operation_family_for_operation,
)
from src.runtime.query_local_rules import compile_query_local_rules

FIXTURES = Path(__file__).parent / "fixtures"
QUESTION = "¿ABCFGEGE cumple el patrón &&&F?"

SYMBOL_SENTENCE = (
    "The Exclamation Point (!) or Ampersand (&) is used in conjunction with "
    "alphanumeric characters in the fare family match process to positionally "
    "match fare class characters."
)
INDICATE_SENTENCE = (
    "The “!” or “&” indicate a match to any alphanumeric character in that "
    "position of the fare class (following the business rules outlined below)."
)
LENGTH_SENTENCE = (
    "When using special characters “!” or “&”, a fare class must contain at "
    "least the number of characters referenced in the fare class field "
    "(additional characters may follow)."
)
POSITIONAL_SENTENCE = "Matching is positional, left to right."
PARAGRAPHS = (SYMBOL_SENTENCE, INDICATE_SENTENCE, POSITIONAL_SENTENCE, LENGTH_SENTENCE)


class _Item:
    """Chunk recuperado mínimo (contrato RetrievalChunk)."""

    def __init__(self, content: str, *, evidence_id: str, document_id: str = "") -> None:
        self.content = content
        self.evidence_id = evidence_id
        self.source_id = "source-parity"
        self.document_id = document_id
        self.page = 1
        self.section_path = ("Record 2",)
        self.metadata = {
            "document_id": document_id,
            "source_id": "source-parity",
            "page": 1,
            "section_path": ["Record 2"],
        }


def _odl_document() -> StructuredDocument:
    payload = json.loads(
        (FIXTURES / "parser_lab" / "atpco_ampersand_record2.json").read_text(
            encoding="utf-8"
        )
    )
    return map_opendataloader_document(
        payload,
        context=OpenDataLoaderMappingContext(
            organization_id=uuid4(),
            external_id="atpco_ampersand_record2.pdf",
            source_name="atpco_ampersand_record2.pdf",
            page_heights=(792.0,),
            parser_info={
                "engine": "opendataloader",
                "version": "2.5.12",
                "mode": "local",
            },
            structure_source="inferred_layout",
            conversion=OpenDataLoaderConversion(data=payload, elapsed_seconds=0.2),
        ),
    )


def _pdfplumber_document() -> StructuredDocument:
    """Fixture pdfplumber: texto RAW extraído del mismo manual (sin layout ODL)."""
    blocks = [
        StructuredBlock(
            kind=StructuredBlockKind.PARAGRAPH,
            text=text,
            order=index,
            page=1,
            token_count=token_count(text),
            content_hash=content_hash(text),
        )
        for index, text in enumerate(PARAGRAPHS)
    ]
    return StructuredDocument(
        id=uuid4(),
        organization_id=uuid4(),
        external_id="record2_fare_class_ampersand.txt",
        title="DATA APPLICATION FOR RECORD 2 – CATEGORY CONTROL",
        content_hash="fixture",
        source_id=uuid4(),
        blocks=tuple(blocks),
        metadata={"filename": "record2_fare_class_ampersand.txt"},
    )


class _ParityRun:
    def __init__(self, label: str, document: StructuredDocument) -> None:
        self.label = label
        self.document = document
        self.items = [
            _Item(block.text, evidence_id=f"ev:{label}:{index}", document_id=str(document.id))
            for index, block in enumerate(document.blocks)
            if str(block.text or "").strip()
        ]
        self.compilation = compile_query_local_rules(
            self.items, document_id=str(document.id)
        )
        self.requirements = derive_query_operation_requirements(question=QUESTION)
        self.gate = gate_rules_for_requirements(
            self.compilation.rules, self.requirements
        )
        self.grounded = reason_over_evidence(
            question=QUESTION,
            evidence_items=self.items,
            canonical_rules=self.compilation.rules or None,
        )
        self.envelope = build_decision_envelope(self.grounded)

    def winner(self):
        winner_id = self.gate.winner_id()
        return next(
            (
                rule
                for rule in self.compilation.rules
                if str(getattr(rule, "rule_id", "") or "") == winner_id
            ),
            None,
        )


def _runs() -> tuple[_ParityRun, _ParityRun]:
    return (
        _ParityRun("opendataloader", _odl_document()),
        _ParityRun("pdfplumber", _pdfplumber_document()),
    )


class TestParserProvenanceParity:
    def test_both_sides_derive_identical_operation_and_result(self) -> None:
        odl, pdf = _runs()
        for run in (odl, pdf):
            assert run.envelope is not None, f"{run.label}: sin DecisionEnvelope"
            assert run.envelope.authoritative is True, run.label
            assert run.envelope.operation == "POSITIONAL_MATCH", run.label
            assert run.envelope.normalized_result == "MATCH", run.label
        # No se exigen los mismos Rule IDs: se exige la misma familia/resultado.
        assert operation_family_for_operation(
            odl.envelope.operation
        ) == operation_family_for_operation(pdf.envelope.operation) == FAMILY_MATCHING
        assert odl.envelope.normalized_result == pdf.envelope.normalized_result

    def test_required_capabilities_match_across_parsers(self) -> None:
        odl, pdf = _runs()
        assert (
            odl.requirements.required_capabilities
            == pdf.requirements.required_capabilities
        )
        assert "MASK_MATCH" in odl.requirements.required_capabilities
        assert "POSITIONAL_SYMBOL_SEMANTICS" in odl.requirements.required_capabilities

    def test_winner_executes_the_queried_symbol_in_both_sides(self) -> None:
        odl, pdf = _runs()
        for run in (odl, pdf):
            winner = run.winner()
            assert winner is not None, f"{run.label}: sin ganador compatible"
            compatibility = run.gate.result_for(winner)
            assert compatibility is not None
            assert compatibility.compatible is True
            assert "&" in compatibility.symbol_executable, run.label

    def test_no_positional_rule_is_ever_replaced_by_comparison(self) -> None:
        """La paridad no admite un COMPARISON colado por provenence de parser."""
        odl, pdf = _runs()
        for run in (odl, pdf):
            operations = {
                claim.operation
                for claim in run.grounded.derivations.claims
                if claim.deterministic
            }
            assert "COMPARISON" not in operations, run.label
            assert operations == {"POSITIONAL_MATCH"}, run.label
