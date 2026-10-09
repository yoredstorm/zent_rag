# =============================================================================
# El binding narrativo alimenta la verificación canónica.
# =============================================================================
from __future__ import annotations

from src.core.domain.adaptive import EvidenceItem
from src.rag.trace_diagnostics import run_invariants
from src.runtime.agent_flow import verification_summary
from src.runtime.decision_verification import (
    GROUNDING_COMPLETE,
    NARRATIVE_PARTIAL,
    NARRATIVE_TRUNCATED,
    NARRATIVE_VERIFIED,
    NARRATIVE_VERIFIED_WITHOUT_CITATIONS,
    OVERALL_CONFIRMED,
    OVERALL_PARTIAL_COMPLETE,
    OVERALL_PARTIAL_GROUNDED,
    NarrativeVerificationInput,
    compose_verification_split,
    narrative_input_from_binding,
)
from src.runtime.narrative_package import (
    CitationPackage,
    FinalNarrativeEvidencePackage,
    bind_narrative_answer,
    narrative_claim_support,
)

_DOC = (
    "La regla de Record 2 describe el cierre de la vigencia publicada en el manual."
)


def _package() -> FinalNarrativeEvidencePackage:
    texts = (
        _DOC,
        "La nota de Record 2 explica el simbolo especial y su posicion.",
        "El apendice guarda un ejemplo de secuencia numerica larga.",
        "Footnote de relleno sin la pregunta.",
        "Otra seccion de relleno del mismo documento.",
    )
    items = tuple(
        EvidenceItem(source_type="qdrant", content=text, evidence_id=f"E{index}")
        for index, text in enumerate(texts, start=1)
    )
    ids = tuple(item.evidence_id for item in items)
    return FinalNarrativeEvidencePackage(
        citation=CitationPackage(
            package_id="final",
            package_version=1,
            evidence_ids=ids,
            doc_number_to_evidence_id={index: item.evidence_id for index, item in enumerate(items, start=1)},
            evidence_id_to_doc_number={item.evidence_id: index for index, item in enumerate(items, start=1)},
            created_after_registry_version="pkg",
        ),
        rendered_context="",
        items=items,
    )


def _answer() -> str:
    return (
        "La regla de Record 2 describe el cierre de la vigencia publicada [Doc: 1]. "
        "La nota de Record 2 explica el simbolo especial [Doc: 2]. "
        "El apendice guarda un ejemplo de secuencia numerica larga."
    )


def test_truncated_grounded_narrative_is_not_unverified() -> None:
    binding = bind_narrative_answer(_answer(), _package())
    assert len(binding.cited_evidence_ids) == 2
    assert len(binding.used_evidence_ids) >= 2
    recorded = narrative_input_from_binding(
        binding, finish_reason="length", query_mode="INFORMATIONAL"
    )
    split = compose_verification_split(narrative_input=recorded, query_mode="INFORMATIONAL")
    narrative = split["narrative_verification"]
    assert narrative["status"] == NARRATIVE_TRUNCATED
    assert split["narrative_grounding"] == GROUNDING_COMPLETE
    assert split["completeness"] == "TRUNCATED"
    assert split["overall_verification"] == OVERALL_PARTIAL_COMPLETE
    assert "NO_VERIFICATION_RECORDED" not in narrative["warnings"]
    assert split["decision_verification"]["applies"] is False
    assert split["presentation"]["summary"] == "Respaldo confirmado · respuesta incompleta"
    assert split["presentation"]["decision"] == "No aplica para esta consulta"
    assert split["presentation"]["explanation"] == "Verificada documentalmente"
    assert split["presentation"]["completeness"] == "Truncada por límite de salida"


def test_stopped_supported_narrative_is_verified() -> None:
    binding = bind_narrative_answer(_answer(), _package())
    recorded = narrative_input_from_binding(
        binding, finish_reason="stop", query_mode="INFORMATIONAL"
    )
    split = compose_verification_split(narrative_input=recorded, query_mode="INFORMATIONAL")
    assert split["narrative_verification"]["status"] == NARRATIVE_VERIFIED
    assert split["narrative_grounding"] == GROUNDING_COMPLETE
    assert split["completeness"] == "COMPLETE"
    assert split["overall_verification"] == OVERALL_CONFIRMED
    assert split["presentation"]["summary"] == "Respaldo confirmado"


def test_uncited_supported_claims_follow_citation_policy() -> None:
    binding = bind_narrative_answer(
        "La regla de Record 2 describe el cierre de la vigencia publicada en el manual.",
        _package(),
    )
    required = narrative_input_from_binding(binding, citations_required=True)
    optional = narrative_input_from_binding(binding, citations_required=False)
    required_split = compose_verification_split(narrative_input=required)
    optional_split = compose_verification_split(narrative_input=optional)
    assert required_split["narrative_verification"]["status"] == NARRATIVE_PARTIAL
    assert optional_split["narrative_verification"]["status"] == NARRATIVE_VERIFIED_WITHOUT_CITATIONS
    assert "Doc:" not in binding.answer or binding.cited_evidence_ids == ()


def test_invalid_doc_is_not_verified() -> None:
    recorded = NarrativeVerificationInput(
        verification="CITATION_INVALID",
        citations_valid=False,
        invalid_doc_numbers=(99,),
        citation_trace="ERROR",
        supports=({"claim": "dato [Doc: 99]", "status": "UNSUPPORTED", "doc_number": 99},),
        query_mode="INFORMATIONAL",
    )
    split = compose_verification_split(narrative_input=recorded, query_mode="INFORMATIONAL")
    assert split["narrative_verification"]["status"] != NARRATIVE_VERIFIED
    assert "CITATION_ERROR" in split["narrative_verification"]["warnings"]


def test_partial_concept_stays_partial_and_complete() -> None:
    recorded = NarrativeVerificationInput(
        verification="PARTIAL",
        grounding="PARTIAL",
        citations_valid=True,
        supports=(
            {"claim": "Record 2", "status": "SUPPORTED", "evidence_id": "E1"},
            {"claim": "cambio de fechas", "status": "UNSUPPORTED", "evidence_id": ""},
        ),
        cited_evidence_ids=("E1",),
        used_evidence_ids=("E1",),
        query_mode="INFORMATIONAL",
    )
    split = compose_verification_split(narrative_input=recorded, query_mode="INFORMATIONAL")
    assert split["narrative_verification"]["status"] == NARRATIVE_PARTIAL
    assert split["narrative_grounding"] == "PARTIAL"
    assert split["completeness"] == "COMPLETE"
    assert split["overall_verification"] == OVERALL_PARTIAL_GROUNDED


def test_flow_reads_the_structured_input() -> None:
    recorded = narrative_input_from_binding(
        bind_narrative_answer(_answer(), _package()),
        finish_reason="length",
        query_mode="INFORMATIONAL",
    ).to_public_dict()
    summary = verification_summary(
        [
            {
                "type": "narrative_evidence",
                "query_mode": "INFORMATIONAL",
                "verification_input": recorded,
            },
            {"type": "narrative_fast_path", "route": "NARRATIVE_FAST_PATH"},
        ],
        {},
    )
    assert summary["narrative_verification"]["status"] == NARRATIVE_TRUNCATED
    assert "NO_VERIFICATION_RECORDED" not in summary["narrative_verification"]["warnings"]
    assert summary["overall_verification"] == OVERALL_PARTIAL_COMPLETE


def test_fast_path_without_verifier_is_a_broken_invariant() -> None:
    found = run_invariants(
        evidence={},
        jev={},
        generation={},
        controls={},
        verification={
            "narrative_verification": {
                "status": "UNVERIFIED",
                "warnings": ["NO_VERIFICATION_RECORDED"],
            }
        },
        timeline=[{"type": "narrative_fast_path", "route": "NARRATIVE_FAST_PATH"}],
    )
    assert any(item["code"] == "NARRATIVE_FAST_PATH_VERIFICATION_MISSING" for item in found)


def test_table_row_is_a_claim() -> None:
    package = _package()
    answer = "| La regla de Record 2 describe el cierre de la vigencia publicada | [Doc: 1] |"
    supports = narrative_claim_support(answer, package)
    assert supports
    assert supports[0]["status"] == "SUPPORTED"
    assert supports[0]["evidence_id"] == "E1"
