# =============================================================================
# KnowledgeSystemEvent — dominio puro de eventos de conocimiento (C8, W5).
# =============================================================================
from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from src.core.domain.knowledge_events import (
    KnowledgeEventType,
    KnowledgeSystemEvent,
    default_requires_review,
)

TIPOS_ESPERADOS = {
    "new_entity",
    "new_rule",
    "rule_changed",
    "conflict_detected",
    "source_superseded",
    "knowledge_gap_detected",
    "high_impact_change",
}

SIN_REVISION = {"new_entity", "new_rule"}


def test_tipos_exactos_snake_case() -> None:
    assert {tipo.value for tipo in KnowledgeEventType} == TIPOS_ESPERADOS
    assert KnowledgeEventType.NEW_ENTITY == "new_entity"
    assert all(isinstance(tipo, str) for tipo in KnowledgeEventType)


def test_event_name_usa_prefijo_knowledge() -> None:
    for tipo in KnowledgeEventType:
        event = KnowledgeSystemEvent(
            type=tipo, organization_id=uuid4(), payload={}
        )
        assert event.event_name == f"knowledge.{tipo.value}"


def test_requires_review_por_tipo() -> None:
    for tipo in KnowledgeEventType:
        esperado = tipo.value not in SIN_REVISION
        assert default_requires_review(tipo) is esperado
        event = KnowledgeSystemEvent(type=tipo, organization_id=uuid4(), payload={})
        assert event.requires_review is esperado


def test_requires_review_explicito_gana() -> None:
    event = KnowledgeSystemEvent(
        type=KnowledgeEventType.NEW_RULE,
        organization_id=uuid4(),
        payload={},
        requires_review=True,
    )
    assert event.requires_review is True


def test_payload_publico_serializable_con_ids() -> None:
    org, source, document, obj = uuid4(), uuid4(), uuid4(), uuid4()
    event = KnowledgeSystemEvent(
        type=KnowledgeEventType.HIGH_IMPACT_CHANGE,
        organization_id=org,
        payload={"diff": {"before": 1, "after": 2}},
        confidence=0.87,
        source_id=source,
        document_id=document,
        object_id=obj,
        rule_key="rule.pricing.vat",
    )
    public = event.to_public_dict()
    assert public["type"] == "high_impact_change"
    assert public["event"] == "knowledge.high_impact_change"
    assert public["organization_id"] == str(org)
    assert public["source_id"] == str(source)
    assert public["document_id"] == str(document)
    assert public["object_id"] == str(obj)
    assert public["rule_key"] == "rule.pricing.vat"
    assert public["payload"] == {"diff": {"before": 1, "after": 2}}
    assert public["confidence"] == 0.87
    assert public["requires_review"] is True
    assert json.loads(json.dumps(public))["payload"] == public["payload"]


def test_payload_publico_omite_ids_nulos() -> None:
    public = KnowledgeSystemEvent(
        type=KnowledgeEventType.NEW_ENTITY,
        organization_id=uuid4(),
        payload={"name": "ACME"},
    ).to_public_dict()
    assert "source_id" not in public
    assert "document_id" not in public
    assert "object_id" not in public
    assert "rule_key" not in public
    assert public["requires_review"] is False
    assert public["confidence"] is None


def test_payload_none_es_fail_soft() -> None:
    event = KnowledgeSystemEvent(
        type=KnowledgeEventType.KNOWLEDGE_GAP_DETECTED,
        organization_id=uuid4(),
        payload=None,
    )
    assert event.payload == {}
    assert event.to_public_dict()["payload"] == {}
    json.dumps(event.to_public_dict())


def test_evento_frozen() -> None:
    event = KnowledgeSystemEvent(
        type=KnowledgeEventType.NEW_RULE, organization_id=uuid4(), payload={}
    )
    with pytest.raises(FrozenInstanceError):
        event.payload = {"x": 1}


def test_tipo_str_se_coacciona_y_desconocido_falla() -> None:
    event = KnowledgeSystemEvent(
        type="source_superseded",  # type: ignore[arg-type]
        organization_id=uuid4(),
        payload={},
    )
    assert event.type is KnowledgeEventType.SOURCE_SUPERSEDED
    assert event.requires_review is True
    with pytest.raises(ValueError):
        KnowledgeSystemEvent(
            type="nope",  # type: ignore[arg-type]
            organization_id=uuid4(),
            payload={},
        )


def test_confidence_fuera_de_rango_falla() -> None:
    with pytest.raises(ValueError):
        KnowledgeSystemEvent(
            type=KnowledgeEventType.NEW_RULE,
            organization_id=uuid4(),
            payload={},
            confidence=1.5,
        )
