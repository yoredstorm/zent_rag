# =============================================================================
# Event Schema Registry — catálogo de eventos en lenguaje de negocio (Fase B).
#
# El usuario final nunca elige `sales.closed`: la UI muestra "Ventas > Se cerró
# una venta" y campos etiquetados. El id técnico se mantiene para el engine y
# los filtros. Los eventos no registrados se sintetizan para no romper
# integraciones custom.*.
# =============================================================================
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.platform.workflows.business_events import split_event_type
from src.platform.workflows.events import STANDARD_EVENTS

MODEL_CONFIG = ConfigDict(extra="forbid")

CATEGORIES: dict[str, str] = {
    "ventas": "Ventas",
    "inventario": "Inventario",
    "clientes": "Clientes",
    "documentos": "Documentos",
    "knowledge": "Knowledge",
    "agentes": "Agentes",
    "sistema": "Sistema",
}

CATEGORY_ORDER: tuple[str, ...] = tuple(CATEGORIES)


class EventField(BaseModel):
    model_config = MODEL_CONFIG

    key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=160)
    type: str = Field(default="text", max_length=40)
    description: str | None = Field(default=None, max_length=400)
    example: Any = None


class EventSchema(BaseModel):
    model_config = MODEL_CONFIG

    id: str = Field(min_length=1, max_length=160)
    version: int = Field(default=1, ge=1)
    business_name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=600)
    category: str = Field(default="sistema", max_length=40)
    icon: str = Field(default="lightning", max_length=40)
    source_kind: str = Field(default="internal_event", max_length=40)
    delivery: str = Field(default="at_least_once", max_length=20)
    fields: list[EventField] = Field(default_factory=list)

    @property
    def technical_type(self) -> str:
        return f"{self.id}@v{self.version}" if self.version > 1 else self.id


def _field(
    key: str,
    label: str,
    type_: str = "text",
    example: Any = None,
    description: str | None = None,
) -> EventField:
    return EventField(key=key, label=label, type=type_, example=example, description=description)


_EVENTS: list[EventSchema] = [
    # --- Ventas -------------------------------------------------------------
    EventSchema(
        id="sales.closed",
        business_name="Se cerró una venta",
        description="Una venta llegó a su estado final.",
        category="ventas",
        icon="receipt",
        source_kind="internal_event",
        fields=[
            _field("total", "Total", "money", 18500.0),
            _field("currency", "Moneda", "text", "PEN"),
            _field("customer", "Cliente", "text", "Distribuidora Lima SAC"),
            _field("seller", "Vendedor", "text", "Ana Torres"),
            _field("closed_at", "Fecha de cierre", "datetime", "2026-09-13T10:00:00Z"),
        ],
    ),
    EventSchema(
        id="sale.created",
        business_name="Se registró una venta",
        description="Se creó una venta nueva.",
        category="ventas",
        icon="shopping-cart",
        source_kind="internal_event",
        fields=[
            _field("total", "Total", "money", 25000.0),
            _field("currency", "Moneda", "text", "PEN"),
            _field("customer", "Cliente", "text", "Cliente nuevo SAC"),
            _field("seller", "Vendedor", "text", "Luis Ramos"),
        ],
    ),
    # --- Inventario ---------------------------------------------------------
    EventSchema(
        id="inventory.stock.changed",
        business_name="Cambió el stock",
        description="El stock de un producto cambió de valor.",
        category="inventario",
        icon="package",
        source_kind="watcher",
        fields=[
            _field("product", "Producto", "text", "MacBook Pro 14"),
            _field("sku", "SKU", "text", "SKU-123"),
            _field("warehouse", "Almacén", "text", "Lima"),
            _field("before", "Stock anterior", "number", 12),
            _field("after", "Stock nuevo", "number", 8),
        ],
    ),
    EventSchema(
        id="inventory.stock.low",
        business_name="El stock bajó del mínimo",
        description="El stock pasó de cumplir a incumplir la condición configurada.",
        category="inventario",
        icon="package",
        source_kind="watcher",
        fields=[
            _field("product", "Producto", "text", "MacBook Pro 14"),
            _field("sku", "SKU", "text", "SKU-123"),
            _field("stock", "Stock actual", "number", 8),
            _field("threshold", "Mínimo configurado", "number", 10),
        ],
    ),
    # --- Clientes -----------------------------------------------------------
    EventSchema(
        id="customer.created",
        business_name="Se creó un cliente",
        description="Se registró un cliente nuevo.",
        category="clientes",
        icon="user-plus",
        source_kind="internal_event",
        fields=[
            _field("customer", "Cliente", "text", "Comercial Andina EIRL"),
            _field("tax_id", "RUC / Tax ID", "text", "20123456789"),
            _field("created_at", "Fecha de creación", "datetime", "2026-09-13T09:00:00Z"),
        ],
    ),
    # --- Documentos ---------------------------------------------------------
    EventSchema(
        id="document.uploaded",
        business_name="Se subió un documento",
        description="Un documento entró a la plataforma.",
        category="documentos",
        icon="file",
        source_kind="internal_event",
        fields=[
            _field("document", "Documento", "text", "contrato-2026.pdf"),
            _field("type", "Tipo", "text", "contrato"),
        ],
    ),
    EventSchema(
        id="document.processed",
        business_name="Se procesó un documento",
        description="El pipeline terminó de procesar un documento.",
        category="documentos",
        icon="file-text",
        source_kind="internal_event",
        fields=[
            _field("document", "Documento", "text", "factura-001.pdf"),
            _field("type", "Tipo", "text", "factura"),
            _field("pages", "Páginas", "number", 2),
        ],
    ),
    EventSchema(
        id="invoice.detected",
        business_name="Se detectó una factura",
        description="Se detectó una factura en una fuente o documento.",
        category="documentos",
        icon="receipt",
        source_kind="internal_event",
        fields=[
            _field("invoice", "Factura", "text", "F001-245"),
            _field("total", "Total", "money", 3200.0),
            _field("due_date", "Vencimiento", "date", "2026-10-01"),
        ],
    ),
    EventSchema(
        id="invoice.overdue",
        business_name="Una factura quedó vencida",
        description="Una factura pasó de no vencida a vencida (transición).",
        category="documentos",
        icon="warning",
        source_kind="watcher",
        fields=[
            _field("invoice", "Factura", "text", "F001-245"),
            _field("customer", "Cliente", "text", "Comercial Andina EIRL"),
            _field("total", "Total", "money", 3200.0),
            _field("due_date", "Vencimiento", "date", "2026-09-01"),
            _field("days_overdue", "Días vencida", "number", 12),
        ],
    ),
    # --- Knowledge ----------------------------------------------------------
    EventSchema(
        id="knowledge.changed",
        business_name="Cambió conocimiento aprobado",
        description="Un documento o política aprobada cambió de versión.",
        category="knowledge",
        icon="book",
        source_kind="internal_event",
        fields=[
            _field("collection", "Colección", "text", "Políticas de compras"),
            _field("document", "Documento", "text", "politica-reposicion"),
            _field("change", "Cambio", "text", "actualizado"),
        ],
    ),
    EventSchema(
        id="semantic.mapping.approved",
        business_name="Se aprobó un mapeo semántico",
        description="Un mapeo semántico pasó a aprobado.",
        category="knowledge",
        icon="check-circle",
        source_kind="internal_event",
        fields=[_field("mapping", "Mapeo", "text", "ventas.total → total")],
    ),
    # --- Agentes ------------------------------------------------------------
    EventSchema(
        id="agent.run.completed",
        business_name="Terminó un análisis de agente",
        description="Un agente completó una ejecución.",
        category="agentes",
        icon="robot",
        source_kind="internal_event",
        fields=[
            _field("agent", "Agente", "text", "Agente de inventario"),
            _field("status", "Estado", "text", "completed"),
            _field("summary", "Resumen", "text", "Stock crítico en 3 SKUs"),
        ],
    ),
    # --- Sistema ------------------------------------------------------------
    EventSchema(
        id="source.connected",
        business_name="Se conectó una fuente",
        description="Una fuente de datos quedó conectada.",
        category="sistema",
        icon="plug",
        source_kind="internal_event",
        fields=[_field("source", "Fuente", "text", "ERP Producción")],
    ),
    EventSchema(
        id="source.synced",
        business_name="Se sincronizó una fuente",
        description="Una fuente terminó de sincronizar.",
        category="sistema",
        icon="refresh",
        source_kind="internal_event",
        fields=[
            _field("source", "Fuente", "text", "ERP Producción"),
            _field("records", "Registros", "number", 1280),
        ],
    ),
    EventSchema(
        id="entity.created",
        business_name="Se creó un registro",
        description="Se creó una entidad en el catálogo.",
        category="sistema",
        icon="plus",
        source_kind="internal_event",
        fields=[_field("entity", "Entidad", "text", "producto")],
    ),
    EventSchema(
        id="entity.updated",
        business_name="Se actualizó un registro",
        description="Se actualizó una entidad del catálogo.",
        category="sistema",
        icon="pencil",
        source_kind="internal_event",
        fields=[_field("entity", "Entidad", "text", "producto")],
    ),
    EventSchema(
        id="integration.connected",
        business_name="Se conectó una integración",
        description="Una integración del marketplace quedó activa.",
        category="sistema",
        icon="puzzle",
        source_kind="internal_event",
        fields=[_field("integration", "Integración", "text", "Slack")],
    ),
    EventSchema(
        id="workflow.completed",
        business_name="Terminó una automatización",
        description="Un workflow terminó su ejecución.",
        category="sistema",
        icon="flow",
        source_kind="internal_event",
        fields=[
            _field("workflow", "Automatización", "text", "Alerta de stock"),
            _field("result", "Resultado", "text", "succeeded"),
        ],
    ),
    EventSchema(
        id="workflow.run",
        business_name="Corrió una automatización",
        description="Un workflow inició una ejecución.",
        category="sistema",
        icon="play",
        source_kind="internal_event",
        fields=[_field("workflow", "Automatización", "text", "Alerta de stock")],
    ),
]

_REGISTRY: dict[str, EventSchema] = {event.id: event for event in _EVENTS}

# Sanity: el registro cubre el catálogo estándar existente.
for _event_type in STANDARD_EVENTS:
    _base, _version = split_event_type(_event_type)
    if _base not in _REGISTRY:
        _REGISTRY[_base] = EventSchema(
            id=_base,
            version=_version,
            business_name=_base.replace(".", " ").capitalize(),
            category="sistema",
            source_kind="internal_event",
            delivery="best_effort",
        )


def get_event_schema(event_type: str, version: int | None = None) -> EventSchema:
    """Schema registrado o sintético (custom.* y eventos nuevos no rompen)."""
    base, parsed_version = split_event_type(event_type)
    registered = _REGISTRY.get(base)
    if registered is not None:
        if version is not None and version != registered.version:
            return registered.model_copy(update={"version": version})
        return registered
    return EventSchema(
        id=base,
        version=version or parsed_version,
        business_name=base.replace(".", " ").replace("_", " ").capitalize(),
        description="Evento personalizado.",
        category="sistema",
        source_kind="custom",
        delivery="best_effort",
    )


def business_name_for(event_type: str) -> str:
    return get_event_schema(event_type).business_name


def is_registered(event_type: str) -> bool:
    """True si el evento está en el catálogo de negocio (no sintetizado)."""
    base, _version = split_event_type(event_type)
    return base in _REGISTRY


def list_catalog(category: str | None = None) -> list[EventSchema]:
    events = sorted(
        _REGISTRY.values(),
        key=lambda e: (
            CATEGORY_ORDER.index(e.category) if e.category in CATEGORY_ORDER else 99,
            e.id,
        ),
    )
    if category:
        events = [e for e in events if e.category == category]
    return events


def catalog_payload() -> dict[str, Any]:
    """Payload para el Workflow Builder: categorías con nombre de negocio."""
    grouped: list[dict[str, Any]] = []
    for key in CATEGORY_ORDER:
        items = [e.model_dump(mode="json") for e in list_catalog(key)]
        if items:
            grouped.append({"key": key, "label": CATEGORIES[key], "events": items})
    return {"categories": grouped, "count": sum(len(c["events"]) for c in grouped)}


__all__ = [
    "CATEGORIES",
    "CATEGORY_ORDER",
    "EventField",
    "EventSchema",
    "business_name_for",
    "catalog_payload",
    "get_event_schema",
    "is_registered",
    "list_catalog",
]
