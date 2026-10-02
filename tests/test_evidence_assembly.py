# =============================================================================
# Evidence Assembly — dedupe, prioridad, conflictos y presupuesto (C3).
# =============================================================================
from __future__ import annotations

from src.core.domain.adaptive import EvidenceItem
from src.runtime.entity_resolution import (
    EntityMatch,
    EntityResolution,
    MentionResolution,
)
from src.runtime.evidence_assembly import assemble_evidence
from src.runtime.representation_runners import RunnerItem, RunnerResult


def _item(
    *,
    document_id: str = "doc-1",
    chunk_id: str = "chunk-1",
    content: str = "Registro 1 OPEN",
    score: float = 0.9,
    retrieval_method: str = "semantic",
    evidence_id: str = "E1",
    entity_pin: bool = False,
) -> EvidenceItem:
    return EvidenceItem(
        source_type="qdrant",
        content=content,
        score=score,
        document_id=document_id,
        chunk_id=chunk_id,
        evidence_id=evidence_id,
        retrieval_method=retrieval_method,
        entity_pin=entity_pin,
    )


def _runner_result(representation: str, *items: RunnerItem) -> RunnerResult:
    return RunnerResult(representation=representation, status="ok", items=items)


def _temporal_item(
    *, assertion_id: str, canonical_id: str, value: str, validity: str, predicate: str = "aplica"
) -> RunnerItem:
    return RunnerItem(
        title=f"Rule X {predicate} {value}",
        summary=f"vigencia {validity}",
        refs={
            "assertion_id": assertion_id,
            "canonical_id": canonical_id,
            "subject_label": "Rule X",
            "predicate": predicate,
            "object_value": value,
            "validity": validity,
        },
        score=0.8,
    )


def test_dedupe_por_documento_y_chunk() -> None:
    package = assemble_evidence(
        items=[_item(evidence_id="E1"), _item(evidence_id="E2")]
    )
    assert len(package.units) == 1
    assert package.counts["excerpt"] == 1


def test_runner_units_con_refs_y_kind() -> None:
    relation = RunnerItem(
        title="Record 4 requires Record 2",
        summary="depends_on",
        refs={"edge_id": "e1", "canonical_id": "c1"},
        score=0.7,
    )
    package = assemble_evidence(
        runner_results=[
            _runner_result("graph", relation),
            _runner_result(
                "temporal",
                _temporal_item(
                    assertion_id="a1",
                    canonical_id="c1",
                    value="2024",
                    validity="historical",
                ),
            ),
        ]
    )
    kinds = {unit.kind for unit in package.units}
    assert kinds == {"relation", "fact"}
    fact = next(unit for unit in package.units if unit.kind == "fact")
    assert fact.refs["assertion_id"] == "a1"
    assert fact.validity == "historical"


def test_conflicto_retenido_no_resuelto() -> None:
    package = assemble_evidence(
        runner_results=[
            _runner_result(
                "temporal",
                _temporal_item(
                    assertion_id="a1", canonical_id="c1", value="2024", validity="historical"
                ),
                _temporal_item(
                    assertion_id="a2", canonical_id="c1", value="2026", validity="current"
                ),
            )
        ]
    )
    assert len(package.conflicts) == 1
    conflict = package.conflicts[0]
    assert conflict.values == ("2024", "2026")
    assert len(conflict.unit_ids) == 2
    facts = [unit for unit in package.units if unit.kind == "fact"]
    assert all(unit.conflict for unit in facts)


def test_conflicto_no_se_reporta_si_el_budget_dropea_un_lado() -> None:
    # Presupuesto justo para un fact: el otro se dropea y el par ya no se
    # reporta como conflicto (semántica post-budget).
    package = assemble_evidence(
        runner_results=[
            _runner_result(
                "temporal",
                _temporal_item(
                    assertion_id="a1",
                    canonical_id="c1",
                    value="2024",
                    validity="historical",
                ),
                _temporal_item(
                    assertion_id="a2",
                    canonical_id="c1",
                    value="2026",
                    validity="current",
                ),
            )
        ],
        budget_chars=18,
    )
    facts = [unit for unit in package.units if unit.kind == "fact"]
    assert len(facts) == 1
    assert facts[0].conflict is False
    assert package.conflicts == ()
    assert package.dropped


def test_vigente_antes_que_historico() -> None:
    package = assemble_evidence(
        runner_results=[
            _runner_result(
                "temporal",
                _temporal_item(
                    assertion_id="a1", canonical_id="c1", value="viejo", validity="historical"
                ),
                _temporal_item(
                    assertion_id="a2", canonical_id="c2", value="nuevo", validity="current"
                ),
            )
        ]
    )
    facts = [unit for unit in package.units if unit.kind == "fact"]
    assert facts[0].validity == "current"


def test_presupuesto_recorta_y_registra_dropped() -> None:
    items = [
        _item(
            document_id=f"doc-{i}",
            chunk_id=f"chunk-{i}",
            content="x" * 500,
            evidence_id=f"E{i}",
        )
        for i in range(10)
    ]
    package = assemble_evidence(items=items, budget_chars=1_200)
    assert package.chars <= 1_200
    assert package.dropped
    assert len(package.units) < 10


def test_connected_usa_entidades_resueltas() -> None:
    entities = EntityResolution(
        mentions=(
            MentionResolution(
                mention="Category 31",
                status="resolved",
                matches=(
                    EntityMatch(
                        mention="Category 31",
                        canonical_id="c1",
                        name="Category 31",
                        kind="entity",
                        match="exact_name",
                        confidence=0.9,
                    ),
                ),
            ),
        )
    )
    package = assemble_evidence(
        runner_results=[
            _runner_result(
                "graph",
                RunnerItem(
                    title="Category 31 requires Record 4",
                    summary="",
                    refs={"edge_id": "e1", "canonical_id": "c1"},
                ),
            )
        ],
        entities=entities,
    )
    assert package.units[0].connected is True


def test_payload_publico_serializable() -> None:
    import json

    package = assemble_evidence(items=[_item()])
    payload = package.to_public_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert payload["units"][0]["unit_id"] == "U1"
