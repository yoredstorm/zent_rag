# =============================================================================
# KnowledgeSystemEventEmitter — adaptador dominio → bus durable (C8, W5).
# =============================================================================
# El emisor no persiste ni publica por sí mismo: delega en el emitter real
# (`KnowledgeEventEmitter.emit`), que decide el gate realtime. Fail-soft.
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import uuid4

from src.core.domain.knowledge_events import (
    KnowledgeEventType,
    KnowledgeSystemEvent,
)
from src.platform.knowledge_events import KnowledgeSystemEventEmitter


class FakeInner:
    """Registra los kwargs reales con los que se invocó a emit."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error = error

    async def emit(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {"seq": len(self.calls)}


async def test_emit_mapea_evento_nuevo_al_bus() -> None:
    org, source = uuid4(), uuid4()
    inner = FakeInner()
    emitter = KnowledgeSystemEventEmitter(inner)
    event = KnowledgeSystemEvent(
        type=KnowledgeEventType.NEW_RULE,
        organization_id=org,
        payload={"rule_key": "rule.vat"},
        source_id=source,
    )

    await emitter.emit(event)

    assert len(inner.calls) == 1
    call = inner.calls[0]
    assert call["organization_id"] == org
    assert call["event_type"] == "knowledge.new_rule"
    assert call["source_id"] == source
    assert call["severity"] == "info"
    assert "knowledge.new_rule" in call["message"]
    payload = call["payload"]
    assert payload["category"] == "knowledge"
    assert payload["event"] == "knowledge.new_rule"
    assert payload["requires_review"] is False
    assert payload["payload"] == {"rule_key": "rule.vat"}


async def test_evento_con_revision_usa_severity_warning() -> None:
    inner = FakeInner()
    event = KnowledgeSystemEvent(
        type=KnowledgeEventType.CONFLICT_DETECTED,
        organization_id=uuid4(),
        payload={"a": 1},
    )

    await KnowledgeSystemEventEmitter(inner).emit(event)

    call = inner.calls[0]
    assert call["severity"] == "warning"
    assert call["payload"]["requires_review"] is True
    assert call["source_id"] is None


async def test_fallo_del_inner_no_propaga() -> None:
    inner = FakeInner(error=RuntimeError("bus caído"))
    event = KnowledgeSystemEvent(
        type=KnowledgeEventType.NEW_ENTITY,
        organization_id=uuid4(),
        payload={},
    )

    await KnowledgeSystemEventEmitter(inner).emit(event)  # no debe propagar

    assert len(inner.calls) == 1
