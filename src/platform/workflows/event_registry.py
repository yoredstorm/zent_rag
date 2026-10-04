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
        id="knowledge.new_entity",
        business_name="Se detectó una entidad nueva",
        description="El compilador descubrió una entidad que no existía en el modelo.",
        category="knowledge",
        icon="plus",
        source_kind="internal_event",
        fields=[
            _field("name", "Entidad", "text", "MacBook Pro 14"),
            _field("entity_type", "Tipo", "text", "producto"),
        ],
    ),
    EventSchema(
        id="knowledge.new_rule",
        business_name="Se detectó una regla nueva",
        description="El compilador extrajo una regla de negocio que no existía.",
        category="knowledge",
        icon="book",
        source_kind="internal_event",
        fields=[
            _field("subject", "Sujeto", "text", "reposición de stock"),
            _field("statement", "Regla", "text", "Reponer al llegar a 10 unidades"),
        ],
    ),
    EventSchema(
        id="knowledge.rule_changed",
        business_name="Cambió una regla de negocio",
        description="Una regla existente cambió de clave o de versión.",
        category="knowledge",
        icon="pencil",
        source_kind="internal_event",
        fields=[
            _field("subject", "Sujeto", "text", "reposición de stock"),
            _field("previous_rule_key", "Regla anterior", "text", "rule-4f2a"),
            _field("rule_key", "Regla nueva", "text", "rule-9c81"),
        ],
    ),
    EventSchema(
        id="knowledge.conflict_detected",
        business_name="Se detectó un conflicto de conocimiento",
        description="Dos afirmaciones del conocimiento se contradicen entre sí.",
        category="knowledge",
        icon="warning",
        source_kind="internal_event",
        fields=[
            _field("subject", "Sujeto", "text", "stock mínimo"),
            _field("predicate", "Predicado", "text", "cantidad"),
            _field("conflict_type", "Tipo de conflicto", "text", "VALUE_CONFLICT"),
            _field("value_a", "Valor A", "text", "10 unidades"),
            _field("value_b", "Valor B", "text", "15 unidades"),
        ],
    ),
    EventSchema(
        id="knowledge.source_superseded",
        business_name="Una fuente quedó reemplazada",
        description="Una versión nueva de un documento reemplazó a la anterior.",
        category="knowledge",
        icon="refresh",
        source_kind="internal_event",
        fields=[
            _field("document_id", "Documento", "text", "doc-123"),
            _field("previous_version", "Versión anterior", "number", 1),
            _field("current_version", "Versión nueva", "number", 2),
            _field("change_kind", "Tipo de cambio", "text", "updated"),
        ],
    ),
    EventSchema(
        id="knowledge.knowledge_gap_detected",
        business_name="Se detectó un vacío de conocimiento",
        description="El modelo encontró información faltante o sin respaldo.",
        category="knowledge",
        icon="search",
        source_kind="internal_event",
        fields=[
            _field("gap_type", "Tipo de vacío", "text", "unsupported_assertion"),
            _field("concept", "Concepto", "text", "margen por producto"),
            _field("priority", "Prioridad", "text", "high"),
        ],
    ),
    EventSchema(
        id="knowledge.high_impact_change",
        business_name="Cambio de alto impacto en conocimiento",
        description=(
            "Un cambio de conocimiento impacta a más objetos que el umbral configurado."
        ),
        category="knowledge",
        icon="zap",
        source_kind="internal_event",
        fields=[
            _field("object_id", "Objeto", "text", "entity-123"),
            _field("kind", "Tipo", "text", "rule"),
            _field("count", "Impacto", "number", 7),
            _field("threshold", "Umbral", "number", 5),
        ],
    ),
    # --- Knowledge Nutrition (§25) -----------------------------------------
    EventSchema(
        id="knowledge.semantic_enriched",
        business_name="Se enriqueció semánticamente un documento",
        description=(
            "La fase de enriquecimiento agregó conceptos, alias y preguntas "
            "sintéticas al documento ingerido."
        ),
        category="knowledge",
        icon="plus",
        source_kind="internal_event",
        fields=[
            _field("concepts", "Conceptos", "number", 12),
            _field("aliases", "Alias de retrieval", "number", 8),
            _field("questions", "Preguntas sintéticas", "number", 6),
            _field("identifiers", "Identificadores", "number", 4),
            _field("source_coverage", "Cobertura de fuente", "number", 0.93),
            _field("enrichment_version", "Versión de enriquecimiento", "text", "enr-v2"),
        ],
    ),
    EventSchema(
        id="knowledge.retrieval_acceptance_failed",
        business_name="Falló la aceptación de retrieval",
        description=(
            "El gate de aceptación midió recall@5 o MRR por debajo del umbral "
            "para el documento ingerido."
        ),
        category="knowledge",
        icon="zap",
        source_kind="internal_event",
        fields=[
            _field("mode", "Modo", "text", "quarantine"),
            _field("state", "Estado", "text", "FAIL"),
            _field("recall_at_5", "Recall@5", "number", 0.42),
            _field("mrr", "MRR", "number", 0.38),
            _field("probes_total", "Sondas totales", "number", 10),
            _field("probes_failed", "Sondas fallidas", "number", 4),
            _field("failed_types", "Tipos con fallas", "text", "aggregate"),
        ],
    ),
    EventSchema(
        id="knowledge.retrieval_acceptance_v2",
        business_name="Aceptación de retrieval V2 (conocimiento)",
        description=(
            "Probes derivados del Semantic Fabric: mide si apareció el "
            "conocimiento requerido (definiciones, reglas, excepciones, "
            "símbolos y dependencias), no solo el chunk esperado."
        ),
        category="knowledge",
        icon="check",
        source_kind="internal_event",
        fields=[
            _field("probes", "Sondas", "number", 12),
            _field("passed", "Aprobadas", "number", 10),
            _field("evidence_recall", "Recall de evidencia", "number", 0.83),
            _field("definition_recall", "Recall de definiciones", "number", 0.9),
            _field("rule_recall", "Recall de reglas", "number", 0.8),
            _field("exception_recall", "Recall de excepciones", "number", 0.75),
            _field("symbol_recall", "Recall de símbolos", "number", 0.7),
            _field("dependency_recall", "Recall de dependencias", "number", 0.66),
            _field("semantic_coverage", "Cobertura semántica", "number", 0.8),
            _field("orphans", "Huérfanos", "number", 2),
            _field("version", "Versión", "text", "knowledge-acceptance-v2"),
        ],
    ),
    EventSchema(
        id="knowledge.knowledge_nutrition_required",
        business_name="Un documento requiere nutrición de conocimiento",
        description=(
            "El documento quedó en cuarentena y necesita más contenido o "
            "representación antes de ser confiable."
        ),
        category="knowledge",
        icon="search",
        source_kind="internal_event",
        fields=[
            _field(
                "reason",
                "Motivo",
                "text",
                "retrieval_acceptance_below_threshold",
            ),
            _field("recall_at_5", "Recall@5", "number", 0.42),
            _field("min_recall_at_5", "Recall@5 mínimo", "number", 0.6),
        ],
    ),
    EventSchema(
        id="knowledge.retrieval_representation_updated",
        business_name="Se actualizó la representación de retrieval",
        description=(
            "La representación derivada del documento cambió y requiere "
            "reindexado."
        ),
        category="knowledge",
        icon="refresh",
        source_kind="internal_event",
        fields=[
            _field("reason", "Motivo", "text", "embedding_model_changed"),
            _field("previous_fingerprint", "Huella anterior", "text", "a1b2c3d4"),
            _field("fingerprint", "Huella nueva", "text", "e5f6a7b8"),
            _field("model", "Modelo", "text", "bge-m3"),
        ],
    ),
    EventSchema(
        id="knowledge.knowledge_reindexed",
        business_name="Se reindexó un documento",
        description="El documento se reindexó con su representación vigente.",
        category="knowledge",
        icon="refresh",
        source_kind="internal_event",
        fields=[
            _field("reason", "Motivo", "text", "representation_updated"),
            _field("chunks", "Fragmentos", "number", 48),
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
