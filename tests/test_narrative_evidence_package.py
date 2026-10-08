# =============================================================================
# Paquete narrativo: Doc:N es presentación. La identidad es evidence_id.
# =============================================================================
from __future__ import annotations

from src.runtime.evidence import (
    EvidenceItem,
    EvidenceMatch,
    EvidenceRegistry,
    EvidenceSelection,
)
from src.runtime.narrative_package import (
    bind_narrative_answer,
    citation_trace_status,
    freeze_narrative_package,
)

QUESTION = "cuentame sobre el record 2 en general sobre el cierre de fechas"
DOCUMENT = "doc-record-2"
TITLE = "Rec2_Rules_dapp_C.pdf"


def _item(evidence_id: str, content: str) -> EvidenceItem:
    return EvidenceItem(
        source_type="qdrant",
        content=content,
        document_id=DOCUMENT,
        source_id="source-record-2",
        chunk_id=f"chunk-{evidence_id}",
        title=TITLE,
        page=13,
        section_path=("Record 2", "Cierre de fechas"),
        evidence_id=evidence_id,
        score=0.8,
    )


def _nine():
    bodies = {
        "E1": "El cierre de fechas en record dos ocurre cuando la vigencia termina.",
        "E2": "La fecha efectiva abre el periodo y la fecha de discontinuidad lo cierra.",
        "E3": "Record dos guarda la secuencia y el estado de la tarifa publicada.",
        "E4": "La secuencia anterior queda cerrada por la fecha de discontinuidad.",
        "E5": "xylophone zebra unrelated fragment without shared wording here.",
        "E6": "nota adicional sobre el calendario de publicacion de tarifas.",
        "E7": "otro fragmento del mismo manual de record dos.",
        "E8": "glosario de vigencia y discontinuidad en el archivo.",
        "E9": "apendice con ejemplos de secuencias historicas.",
    }
    return [_item(evidence_id, content) for evidence_id, content in bodies.items()]


def _selection(items: list[EvidenceItem]) -> EvidenceSelection:
    matches = [
        EvidenceMatch(
            evidence_id=item.evidence_id,
            match="lexical",
            priority=1,
            score=0.8,
            chars=len(item.content or ""),
            content=item.content or "",
            complete=True,
        )
        for item in items
    ]
    return EvidenceSelection(
        items=list(items),
        matches=matches,
        chars=sum(len(item.content or "") for item in items),
        budget_chars=20_000,
    )


def test_informational_record2_counts_and_citations() -> None:
    registry = EvidenceRegistry()
    registry.add(_nine())
    chosen = [registry.get(evidence_id) for evidence_id in ("E1", "E2", "E3", "E4", "E5")]
    selection = _selection([item for item in chosen if item is not None])
    package = freeze_narrative_package(selection, version=1, registry_version=registry.fingerprint())
    answer = (
        "El cierre de fechas en record dos ocurre cuando la vigencia termina [Doc: 1]. "
        "La fecha efectiva abre el periodo y la fecha de discontinuidad lo cierra [Doc: 2]. "
        "Record dos guarda la secuencia y el estado de la tarifa publicada [Doc: 3]. "
        "La secuencia anterior queda cerrada por la fecha de discontinuidad."
    )
    binding = bind_narrative_answer(answer, package)
    assert binding.invalid_doc_numbers == ()
    assert binding.cited_evidence_ids == ("E1", "E2", "E3")
    assert set(binding.used_evidence_ids) == {"E1", "E2", "E3", "E4"}
    assert "E5" not in binding.used_evidence_ids
    assert binding.verification == "VERIFIED_GROUNDED"
    assert binding.grounding == "COMPLETE"
    assert citation_trace_status(binding) == "OK"
    public = registry.to_public_dict(
        selected_ids=tuple(item.evidence_id for item in selection.items),
        narrative_ids=binding.used_evidence_ids,
        cited_ids=binding.cited_evidence_ids,
    )
    assert public["retrieved_count"] == 9
    assert public["selected_count"] == 5
    assert public["narrative_evidence_used_count"] == 4
    assert public["used_count"] == 4
    assert public["cited_count"] == 3
    assert public["decision_evidence_count"] == 0
    assert public["documents_retrieved_count"] == 1
    assert public["documents_selected_count"] == 1
    assert public["documents_used_count"] == 1
    assert public["documents_cited_count"] == 1
    cited_flags = {
        item["evidence_id"]
        for item in public["items"]
        if item.get("cited")
    }
    assert cited_flags == {"E1", "E2", "E3"}


def test_retrieve_more_final_package_renumbers_only_the_final_set() -> None:
    registry = EvidenceRegistry()
    registry.add([_item(f"E{index}", f"fragmento {index} de cierre de fechas") for index in range(1, 6)])
    registry.add([_item(f"E{index}", f"fragmento {index} de cierre de fechas") for index in range(6, 10)])
    assert registry.ids() == tuple(f"E{index}" for index in range(1, 10))
    chosen = [registry.get(evidence_id) for evidence_id in ("E2", "E4", "E6", "E8")]
    selection = _selection([item for item in chosen if item is not None])
    package = freeze_narrative_package(selection, version=2, registry_version=registry.fingerprint())
    assert package.citation.doc_number_to_evidence_id == {1: "E2", 2: "E4", 3: "E6", 4: "E8"}
    binding = bind_narrative_answer(
        "El cierre de fechas aparece en el fragmento [Doc: 1] y tambien en [Doc: 3].",
        package,
    )
    assert binding.cited_evidence_ids == ("E2", "E6")
    assert "E1" not in binding.cited_evidence_ids


def test_revision_validates_against_the_package_the_model_saw() -> None:
    registry = EvidenceRegistry()
    registry.add([_item("E1", "cierre de fechas del record dos en la vigencia."), _item("E2", "otro texto")])
    package_v1 = freeze_narrative_package(
        _selection([registry.get("E1")]), version=1, registry_version="a"
    )
    second_items = [registry.get("E1"), registry.get("E2")]
    package_v2 = freeze_narrative_package(
        _selection([item for item in second_items if item is not None]),
        version=2,
        registry_version="b",
    )
    answer = "El cierre de fechas del record dos en la vigencia queda explicado [Doc: 1]."
    revised = bind_narrative_answer(answer, package_v2)
    stale = bind_narrative_answer(answer, package_v1)
    assert revised.cited_evidence_ids == ("E1",)
    assert stale.cited_evidence_ids == ("E1",)
    assert package_v2.package_version == 2
    assert package_v1.citation.evidence_ids == ("E1",)
    assert package_v2.citation.evidence_ids == ("E1", "E2")


def test_doc_99_is_stripped_and_never_creates_evidence() -> None:
    registry = EvidenceRegistry()
    registry.add([_item("E1", "cierre de fechas del record dos cuando la vigencia termina.")])
    package = freeze_narrative_package(
        _selection(list(registry.all_items())),
        version=1,
        registry_version=registry.fingerprint(),
    )
    binding = bind_narrative_answer(
        "El cierre de fechas del record dos cuando la vigencia termina [Doc: 1] [Doc: 99].",
        package,
    )
    assert 99 in binding.invalid_doc_numbers
    assert "[Doc: 99]" not in binding.answer
    assert binding.cited_evidence_ids == ("E1",)
    assert "E99" not in registry.ids()
    public = registry.to_public_dict(
        selected_ids=("E1",),
        narrative_ids=binding.used_evidence_ids,
        cited_ids=binding.cited_evidence_ids,
    )
    assert all(item["evidence_id"] != "E99" for item in public["items"])


def test_uncited_claims_are_used_but_not_cited() -> None:
    registry = EvidenceRegistry()
    registry.add([_item("E1", "cierre de fechas del record dos cuando la vigencia termina.")])
    package = freeze_narrative_package(
        _selection(list(registry.all_items())),
        version=1,
        registry_version=registry.fingerprint(),
    )
    binding = bind_narrative_answer(
        "El cierre de fechas del record dos cuando la vigencia termina segun el manual.",
        package,
    )
    assert binding.cited_evidence_ids == ()
    assert binding.used_evidence_ids == ("E1",)
    assert binding.verification == "PARTIAL"
    assert binding.grounding == "PARTIAL"
