# =============================================================================
# Semantic Reconstruction Layer — Event / Email / Conversation Adapters
# =============================================================================
# Eventos, correos y conversaciones entran como registros con emisor, tiempo
# y contenido. No se aplastan a un blob: cada mensaje conserva su rol, su
# orden y su procedencia (metadata estructurada o bloque de texto).
# =============================================================================
from __future__ import annotations

from typing import Any

from src.core.domain.knowledge_v2 import StructuredDocument

from ..contracts import (
    ElementKind,
    RawElement,
    RawExtraction,
    SourceKind,
    SourceProvenance,
    element_uuid,
)
from .base import SourceAdapter
from .document import TextSourceAdapter


class EventSourceAdapter(SourceAdapter):
    kind = SourceKind.EVENT.value
    description = "Eventos/emails/conversaciones: emisor, tiempo, asunto y contenido"

    def extract(
        self,
        document: StructuredDocument,
        *,
        raw_text: str | None = None,
    ) -> RawExtraction:
        extraction = RawExtraction(
            source_kind=self.kind,
            adapter=self.name,
            title=document.title or document.external_id,
        )
        records = _event_records(document)
        if not records:
            fallback = TextSourceAdapter().extract(document, raw_text=raw_text)
            fallback.source_kind = self.kind
            fallback.adapter = self.name
            fallback.warnings.append("structured events unavailable; used document blocks")
            return fallback

        for position, record in enumerate(records):
            text = str(
                record.get("content")
                or record.get("message")
                or record.get("body")
                or record.get("text")
                or record.get("subject")
                or ""
            ).strip()
            if not text:
                continue
            event_id = element_uuid(document.id, position, text)
            extraction.elements.append(
                RawElement(
                    id=event_id,
                    kind=ElementKind.EVENT.value,
                    text=text,
                    order=position,
                    provenance=SourceProvenance(
                        source_kind=self.kind,
                        adapter=self.name,
                        source_id=document.source_id,
                        document_id=document.id,
                        document_title=document.title,
                        row=position + 1,
                        excerpt=text[:400],
                    ),
                    confidence=0.85,
                    attributes={
                        "event_type": record.get("event_type") or record.get("type"),
                        "occurred_at": record.get("occurred_at") or record.get("timestamp") or record.get("date"),
                        "actor": record.get("actor") or record.get("from") or record.get("sender"),
                        "recipient": record.get("recipient") or record.get("to"),
                        "subject": record.get("subject"),
                        "role": record.get("role") or record.get("speaker"),
                        "channel": record.get("channel"),
                    },
                )
            )
        extraction.stats = {"events": len(extraction.elements)}
        return extraction


class EmailSourceAdapter(EventSourceAdapter):
    kind = SourceKind.EMAIL.value
    description = "Correo: de/para/asunto/fecha/cuerpo como un evento por mensaje"


class ConversationSourceAdapter(EventSourceAdapter):
    kind = SourceKind.CONVERSATION.value
    description = "Conversación: turnos con rol, orden y contenido"


def _event_records(document: StructuredDocument) -> list[dict[str, Any]]:
    for key in ("events", "records", "messages", "conversation"):
        value = document.metadata.get(key)
        if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            return value
        if isinstance(value, dict):
            nested = value.get("items") or value.get("messages") or value.get("events")
            if isinstance(nested, list) and all(isinstance(item, dict) for item in nested):
                return nested
    return []


__all__ = ["ConversationSourceAdapter", "EmailSourceAdapter", "EventSourceAdapter"]
