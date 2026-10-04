# =============================================================================
# SemanticStitcher — coser unidades y relaciones (Fase 5)
# =============================================================================
# Reglas que se prueban:
#   - unidades merged con provenance a bloques y ventanas;
#   - relaciones DEFINES/USES/HAS_EXCEPTION/REFERENCES/ALIAS_OF/HAS_ATTRIBUTE;
#   - contradicción entre claims del mismo sujeto/predicado con distinto objeto;
#   - supersession temporal cuando la ventana posterior tiene marcador temporal;
#   - duplicado semántico => SAME_AS;
#   - cierre de un thread OPEN con las unidades cosidas;
#   - store Postgres replace/list scoped por tenant.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.knowledge.semantic import (
    SemanticStitcher,
    SemanticThread,
    SemanticWindowResult,
    ThreadStatus,
    ThreadType,
    WindowItem,
)


def _result(window_index: int, document_id, organization_id, items):
    return SemanticWindowResult(
        window_index=window_index,
        organization_id=organization_id,
        document_id=document_id,
        items=tuple(items),
    )


def _item(kind: str, key: str, label: str, text: str = "", **kwargs) -> WindowItem:
    return WindowItem(
        kind=kind,
        key=key,
        label=label,
        text=text,
        confidence=kwargs.pop("confidence", 0.8),
        block_ids=kwargs.pop("block_ids", (str(uuid4()),)),
        attributes=kwargs.pop("attributes", {}),
    )


def _stitch(results, threads=()):
    document_id = results[0].document_id
    return SemanticStitcher().stitch(
        document=SimpleNamespace(id=document_id),
        results=list(results),
        threads=list(threads),
    )


def test_continuation_stitching_keeps_evidence_separate() -> None:
    """Fase 7: 'The ampersand represents' + 'one alphanumeric character.' = una
    unidad semántica; la evidencia cruda de cada ventana queda intacta."""
    document_id = uuid4()
    organization_id = uuid4()
    window_a = _result(
        0,
        document_id,
        organization_id,
        [
            WindowItem(
                kind="continuation",
                key="continuation:0:ampersand",
                label="The ampersand represents",
                text="The ampersand represents",
                confidence=0.6,
                block_ids=("b1",),
                attributes={"target_hint": "next_window"},
            )
        ],
    )
    window_b = _result(
        1,
        document_id,
        organization_id,
        [
            WindowItem(
                kind="definition",
                key="definition:&",
                label="&",
                text="one alphanumeric character.",
                confidence=0.8,
                block_ids=("b2",),
            )
        ],
    )
    outcome = _stitch([window_a, window_b])
    unit = next(unit for unit in outcome.units if unit.unit_key == "definition:&")
    assert unit.text == "The ampersand represents one alphanumeric character."
    assert set(unit.block_ids) == {"b1", "b2"}
    assert unit.attributes.get("continuation_stitched") is True
    assert set(unit.source_windows) == {0, 1}
    # La evidencia original permanece separada (un block por ventana).
    assert window_a.items[0].block_ids == ("b1",)
    assert window_b.items[0].block_ids == ("b2",)


def test_stitcher_builds_units_and_core_relations() -> None:
    document_id = uuid4()
    organization_id = uuid4()
    results = [
        _result(
            0,
            document_id,
            organization_id,
            [
                _item("symbol", "symbol:&&&F", "&&&F", confidence=0.9),
                _item(
                    "rule",
                    "rule:fare",
                    "The fare basis must match &&&F.",
                    "The fare basis must match &&&F.",
                ),
                _item(
                    "exception",
                    "exception:1",
                    "unless the validating carrier applies",
                    "unless the validating carrier applies",
                    attributes={"target": "&&&F"},
                ),
                _item(
                    "unresolved_reference",
                    "reference:note:nx7",
                    "NX7",
                    "See note NX7",
                    attributes={"target_kind": "note"},
                ),
            ],
        ),
        _result(
            1,
            document_id,
            organization_id,
            [
                _item(
                    "definition",
                    "definition:&&&f",
                    "&&&F",
                    "one alphanumeric character mask",
                ),
                _item(
                    "entity",
                    "field:fclas",
                    "FCLAS",
                    "Fare class field",
                    attributes={"entity_type": "field", "literal_pattern": "&&&F"},
                ),
                _item("concept", "concept:cat31", "Category 31", "Category 31"),
                _item(
                    "alias",
                    "alias:cat31",
                    "CAT31",
                    attributes={"canonical": "Category 31"},
                ),
                _item(
                    "definition",
                    "definition:nx7",
                    "NX7",
                    "Fare class note",
                ),
            ],
        ),
    ]
    outcome = _stitch(results)
    unit_kinds = {unit.unit_kind for unit in outcome.units}
    assert {"symbol", "rule", "exception", "definition", "entity"} <= unit_kinds
    relation_types = {relation.relation_type for relation in outcome.relations}
    assert {"DEFINES", "USES", "HAS_EXCEPTION", "REFERENCES", "ALIAS_OF"} <= relation_types
    assert outcome.duplicates == 0
    # Toda relación tiene evidencia física y ventanas.
    assert all(relation.evidence for relation in outcome.relations)
    assert all(relation.windows for relation in outcome.relations)


def test_stitcher_detects_contradiction_and_supersession() -> None:
    document_id = uuid4()
    organization_id = uuid4()
    results = [
        _result(
            0,
            document_id,
            organization_id,
            [
                _item(
                    "claim",
                    "claim:commission:5",
                    "Commission",
                    "Commission 5%",
                    attributes={
                        "subject": "commission",
                        "predicate": "is",
                        "object_value": "5%",
                    },
                )
            ],
        ),
        _result(
            1,
            document_id,
            organization_id,
            [
                _item(
                    "claim",
                    "claim:commission:7",
                    "Commission",
                    "Commission 7%",
                    attributes={
                        "subject": "commission",
                        "predicate": "is",
                        "object_value": "7%",
                    },
                ),
                _item("temporal", "temporal:2026", "2026-01-01", "2026-01-01"),
            ],
        ),
    ]
    outcome = _stitch(results)
    relation_types = {relation.relation_type for relation in outcome.relations}
    assert "CONTRADICTS" in relation_types
    assert "SUPERSEDES" in relation_types
    assert outcome.contradictions == 1
    assert outcome.supersessions == 1
    supersedes = next(
        relation
        for relation in outcome.relations
        if relation.relation_type == "SUPERSEDES"
    )
    assert supersedes.attributes["requires_review"] is True


def test_stitcher_detects_duplicate_semantic_unit() -> None:
    document_id = uuid4()
    organization_id = uuid4()
    text = "Commission five percent applies to contracts."
    results = [
        _result(
            0,
            document_id,
            organization_id,
            [_item("claim", "claim:a", "Commission", text)],
        ),
        _result(
            1,
            document_id,
            organization_id,
            [_item("note", "note:b", "Commission", text)],
        ),
    ]
    outcome = _stitch(results)
    relation_types = {relation.relation_type for relation in outcome.relations}
    assert "SAME_AS" in relation_types
    assert outcome.duplicates == 1


def test_stitcher_closes_open_reference_thread() -> None:
    document_id = uuid4()
    organization_id = uuid4()
    results = [
        _result(
            1,
            document_id,
            organization_id,
            [_item("definition", "definition:nx7", "NX7", "Fare class note")],
        )
    ]
    thread = SemanticThread(
        id=uuid4(),
        thread_key="reference:note:nx7",
        thread_type=ThreadType.REFERENCE.value,
        status=ThreadStatus.OPEN.value,
        organization_id=organization_id,
        document_id=document_id,
        target_hint="NX7",
        opened_at_window=0,
        last_seen_window=0,
    )
    outcome = _stitch(results, threads=[thread])
    assert outcome.threads_closed == 1
    updated = outcome.threads_updated[0]
    assert updated.status == ThreadStatus.RESOLVED.value
    assert updated.resolved_by_unit
    assert updated.candidates[0]["kind"] == "definition"


# ---------------------------------------------------------------------------
# Store Postgres
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_postgres_store_units_relations_roundtrip() -> None:
    from src.infrastructure.postgres.relational_db import (
        PostgresOrganizationRepository,
    )
    from src.knowledge.semantic import (
        PostgresSemanticIngestionStore,
        StitchedUnit,
        StitchRelation,
    )

    org_repo = PostgresOrganizationRepository()
    organization = await org_repo.create_organization(
        uuid4(), f"SS Org {uuid4().hex[:6]}"
    )
    store = PostgresSemanticIngestionStore()
    document_id = uuid4()
    unit = StitchedUnit(
        id=uuid4(),
        unit_key="definition:nx7",
        unit_kind="definition",
        label="NX7",
        text="Fare class note",
        confidence=0.85,
        source_windows=(1,),
        block_ids=(str(uuid4()),),
        merged_from=("definition:nx7",),
    )
    relation = StitchRelation(
        id=uuid4(),
        relation_key="REFERENCES:reference:note:nx7->definition:nx7",
        relation_type="REFERENCES",
        subject_key="reference:note:nx7",
        subject_kind="unresolved_reference",
        subject_label="NX7",
        object_key="definition:nx7",
        object_kind="definition",
        object_label="NX7",
        confidence=0.8,
        evidence=(str(uuid4()),),
        windows=(0, 1),
    )
    await store.replace_stitch(
        organization.id,
        workspace_id=None,
        source_id=None,
        document_id=document_id,
        units=[unit],
        relations=[relation],
    )
    units = await store.list_units(organization.id, document_id=document_id)
    assert len(units) == 1
    assert units[0]["unit_key"] == "definition:nx7"
    relations = await store.list_relations(
        organization.id, document_id=document_id, relation_type="REFERENCES"
    )
    assert len(relations) == 1
    assert relations[0]["object_key"] == "definition:nx7"

    # Replace idempotente: la segunda corrida no duplica.
    await store.replace_stitch(
        organization.id,
        workspace_id=None,
        source_id=None,
        document_id=document_id,
        units=[unit],
        relations=[relation],
    )
    assert len(await store.list_units(organization.id, document_id=document_id)) == 1

    await store.delete_window_artifacts(organization.id, document_id=document_id)
    assert await store.list_units(organization.id, document_id=document_id) == []
    assert await store.list_relations(organization.id, document_id=document_id) == []
