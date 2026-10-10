# =============================================================================
# Semantic-global query: aliases salen del fabric, no de un diccionario.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

from src.core.domain.knowledge_v2 import StructuredBlockKind
from src.knowledge.semantic.extract import extract_window_items
from src.knowledge.semantic.query_plan import (
    LEGACY_RETRIEVAL,
    SEMANTIC_GLOBAL,
    activate_nodes,
    build_plan,
    expand_one_hop,
)
from src.knowledge.semantic.rollout import resolve_fabric_mode, resolve_semantic_mode


class _Block:
    def __init__(self, text: str, kind) -> None:
        self.id = uuid4()
        self.text = text
        self.kind = kind
        self.metadata: dict = {}


class _Doc:
    metadata: dict = {}


def test_rollout_workspace_overrides_global_off(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.knowledge.semantic.rollout._settings",
        lambda: type(
            "S",
            (),
            {
                "KNOWLEDGE_SEMANTIC_ROLLOUT": (
                    '{"workspaces": {"a768d054-3a08-42e4-b566-909a0813533f": "active"}}'
                )
            },
        )(),
    )
    workspace = "a768d054-3a08-42e4-b566-909a0813533f"
    assert (
        resolve_semantic_mode(workspace_id=workspace, global_mode="off") == "active"
    )
    assert resolve_semantic_mode(workspace_id=uuid4(), global_mode="off") == "off"
    assert (
        resolve_fabric_mode(workspace_id=workspace, global_semantic_mode="off")
        == "active"
    )


def test_table_header_becomes_a_field_with_quote() -> None:
    block = _Block(
        "Footnote | Eff Date | Disc Date | See the Date processing Section on Effective date Matching.",
        StructuredBlockKind.TABLE,
    )
    items = extract_window_items(
        document=_Doc(),
        window_blocks=[block],
        window_index=0,
    )
    fields = [item for item in items if item.attributes.get("entity_type") == "field"]
    labels = {item.label for item in fields}
    assert "Eff Date" in labels
    assert "Disc Date" in labels
    eff = next(item for item in fields if item.label == "Eff Date")
    assert "Date processing" in eff.text
    refs = [item for item in items if item.kind == "unresolved_reference"]
    assert any("date processing" in item.label.lower() for item in refs)


def test_mask_labels_never_become_vocabulary() -> None:
    """Una máscara (&a&m&2, *a) no entra como entidad/concepto/alias/topic.

    Las definiciones de máscara se conservan (gramática) y los símbolos viajan
    con kind="symbol" para que la resolución de premisas funcione.
    """
    block = _Block(
        "&a&m&2 - máscara del Record 2. Eff Date - fecha efectiva.",
        StructuredBlockKind.PARAGRAPH,
    )
    doc = _Doc()
    doc.metadata = {
        "understanding": {
            "definitions": [
                {
                    "term": "&a&m&2",
                    "definition": "máscara del Record 2",
                    "block_id": str(block.id),
                    "confidence": 0.9,
                },
                {
                    "term": "Eff Date",
                    "definition": "fecha efectiva",
                    "block_id": str(block.id),
                    "confidence": 0.9,
                },
            ],
            "technical_fields": [
                {"name": "*a", "block_id": str(block.id), "confidence": 0.8}
            ],
            "exact_literals": [
                {
                    "value": "&a&m&2",
                    "pattern_type": "mask",
                    "block_id": str(block.id),
                    "confidence": 0.9,
                }
            ],
        }
    }
    items = extract_window_items(document=doc, window_blocks=[block], window_index=0)

    entities = {item.label for item in items if item.kind == "entity"}
    assert "*a" not in entities
    assert "&a&m&2" not in entities

    # La máscara definida sigue disponible como definición y símbolo.
    definitions = {item.label for item in items if item.kind == "definition"}
    assert "&a&m&2" in definitions
    symbols = {item.label for item in items if item.kind == "symbol"}
    assert "&a&m&2" in symbols


def test_activation_uses_embedding_neighbors_not_a_dictionary() -> None:
    nodes = [
        {"id": "1", "label": "Footnote", "node_type": "Concept", "block_ids": ["b1"]},
        {"id": "2", "label": "Eff Date", "node_type": "Attribute", "block_ids": ["b2"]},
    ]
    # El vector de la pregunta coincide con Eff Date, no con Footnote.
    activated = activate_nodes([1.0, 0.0], nodes, [[0.0, 1.0], [1.0, 0.0]], min_score=0.5)
    assert [item["label"] for item in activated] == ["Eff Date"]
    hopped = expand_one_hop(
        [{"id": "9", "label": "Record 2", "node_type": "Concept", "block_ids": []}],
        [
            {
                "id": "2",
                "label": "Disc Date",
                "node_type": "Attribute",
                "block_ids": ["b3"],
            }
        ],
        [
            {
                "relation_type": "HAS_FIELD",
                "subject_id": "9",
                "object_id": "2",
                "confidence": 0.8,
            }
        ],
    )
    plan = build_plan("cuentame sobre fechas", activated + hopped, hops=1)
    assert plan.knowledge_mode == SEMANTIC_GLOBAL
    assert "Eff Date" in plan.aspect_labels
    assert "Disc Date" in plan.aspect_labels
    assert "eff date" in plan.search_query.lower()
    assert "footnote" not in plan.search_query.lower()


def test_empty_activation_stays_on_legacy_retrieval() -> None:
    plan = build_plan("qué es record 2", [])
    assert plan.knowledge_mode == LEGACY_RETRIEVAL
    assert plan.search_query == ""


def test_symbol_masks_do_not_activate() -> None:
    """&a&m&2 / *a son máscaras del manual, no vocabulario."""
    nodes = [
        {"id": "1", "label": "&a&m&2", "node_type": "Concept", "block_ids": ["b1"]},
        {"id": "2", "label": "*a", "node_type": "Concept", "block_ids": ["b2"]},
        {"id": "3", "label": "&&test", "node_type": "Concept", "block_ids": ["b3"]},
    ]
    activated = activate_nodes(
        [1.0, 0.0],
        nodes,
        [[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]],
        min_score=0.5,
    )
    assert activated == []


def test_entity_without_aspect_stays_on_legacy_retrieval() -> None:
    """Sin aspecto aprendido no hay puente de idioma que justifique el plan."""
    plan = build_plan(
        "cuentame sobre el cambio de fechas",
        [
            {
                "id": "9",
                "label": "Fare Record = PAR",
                "node_type": "Concept",
                "block_ids": [],
            }
        ],
    )
    assert plan.knowledge_mode == LEGACY_RETRIEVAL
    assert plan.search_query == ""
