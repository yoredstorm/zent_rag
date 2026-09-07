# =============================================================================
# Concept Classification — Phase 26A Semantic Compiler foundation
# =============================================================================
# Deterministic classification of extracted concepts into BusinessObjectType.
# Unknown tokens default to ENTITY (never auto-require a definition).
# Intent concept_definition may promote unknowns to BUSINESS_TERM.
# =============================================================================
from __future__ import annotations

import re
from typing import Iterable

from src.core.domain.semantic import (
    DEFINITIONAL_TYPES,
    BusinessObjectType,
    ClassifiedConcept,
)

# Normalized lexicon: singular/plural and common variants map to a type.
_LEXICON: dict[str, BusinessObjectType] = {
    # ENTITY
    "cliente": BusinessObjectType.ENTITY,
    "clientes": BusinessObjectType.ENTITY,
    "customer": BusinessObjectType.ENTITY,
    "customers": BusinessObjectType.ENTITY,
    "producto": BusinessObjectType.ENTITY,
    "productos": BusinessObjectType.ENTITY,
    "product": BusinessObjectType.ENTITY,
    "products": BusinessObjectType.ENTITY,
    "pedido": BusinessObjectType.ENTITY,
    "pedidos": BusinessObjectType.ENTITY,
    "orden": BusinessObjectType.ENTITY,
    "ordenes": BusinessObjectType.ENTITY,
    "order": BusinessObjectType.ENTITY,
    "orders": BusinessObjectType.ENTITY,
    "empleado": BusinessObjectType.ENTITY,
    "empleados": BusinessObjectType.ENTITY,
    "proveedor": BusinessObjectType.ENTITY,
    "proveedores": BusinessObjectType.ENTITY,
    "factura": BusinessObjectType.ENTITY,
    "facturas": BusinessObjectType.ENTITY,
    "marca": BusinessObjectType.ENTITY,
    "marcas": BusinessObjectType.ENTITY,
    "campaña": BusinessObjectType.ENTITY,
    "campana": BusinessObjectType.ENTITY,
    "subscription": BusinessObjectType.ENTITY,
    "suscripcion": BusinessObjectType.ENTITY,
    "suscripción": BusinessObjectType.ENTITY,
    "suscripciones": BusinessObjectType.ENTITY,
    # FACT
    "venta": BusinessObjectType.FACT,
    "ventas": BusinessObjectType.FACT,
    "sale": BusinessObjectType.FACT,
    "sales": BusinessObjectType.FACT,
    "devolucion": BusinessObjectType.FACT,
    "devolución": BusinessObjectType.FACT,
    "devoluciones": BusinessObjectType.FACT,
    "ingreso": BusinessObjectType.FACT,
    "ingresos": BusinessObjectType.FACT,
    "gasto": BusinessObjectType.FACT,
    "gastos": BusinessObjectType.FACT,
    # DIMENSION
    "region": BusinessObjectType.DIMENSION,
    "región": BusinessObjectType.DIMENSION,
    "regiones": BusinessObjectType.DIMENSION,
    "canal": BusinessObjectType.DIMENSION,
    "canales": BusinessObjectType.DIMENSION,
    "categoria": BusinessObjectType.DIMENSION,
    "categoría": BusinessObjectType.DIMENSION,
    "categorias": BusinessObjectType.DIMENSION,
    "categorías": BusinessObjectType.DIMENSION,
    "sucursal": BusinessObjectType.DIMENSION,
    "sucursales": BusinessObjectType.DIMENSION,
    # MEASURE
    "amount": BusinessObjectType.MEASURE,
    "cantidad": BusinessObjectType.MEASURE,
    "monto": BusinessObjectType.MEASURE,
    "quantity": BusinessObjectType.MEASURE,
    "costo": BusinessObjectType.MEASURE,
    "costos": BusinessObjectType.MEASURE,
    "precio": BusinessObjectType.MEASURE,
    "precios": BusinessObjectType.MEASURE,
    "descuento": BusinessObjectType.MEASURE,
    "descuentos": BusinessObjectType.MEASURE,
    "stock": BusinessObjectType.MEASURE,
    "inventario": BusinessObjectType.MEASURE,
    "inventarios": BusinessObjectType.MEASURE,
    # DERIVED_METRIC
    "margen": BusinessObjectType.DERIVED_METRIC,
    "margenes": BusinessObjectType.DERIVED_METRIC,
    "márgenes": BusinessObjectType.DERIVED_METRIC,
    "gross_margin": BusinessObjectType.DERIVED_METRIC,
    "margen_bruto": BusinessObjectType.DERIVED_METRIC,
    "margen_neto": BusinessObjectType.DERIVED_METRIC,
    "net_sales": BusinessObjectType.DERIVED_METRIC,
    "rentabilidad": BusinessObjectType.DERIVED_METRIC,
    # BUSINESS_RULE
    "activo": BusinessObjectType.BUSINESS_RULE,
    "activos": BusinessObjectType.BUSINESS_RULE,
    "rentable": BusinessObjectType.BUSINESS_RULE,
    "rentables": BusinessObjectType.BUSINESS_RULE,
    "moroso": BusinessObjectType.BUSINESS_RULE,
    "morosos": BusinessObjectType.BUSINESS_RULE,
    "cliente_activo": BusinessObjectType.BUSINESS_RULE,
    "clientes_activos": BusinessObjectType.BUSINESS_RULE,
    "cliente_rentable": BusinessObjectType.BUSINESS_RULE,
    "clientes_rentables": BusinessObjectType.BUSINESS_RULE,
    "active_customer": BusinessObjectType.BUSINESS_RULE,
    # BUSINESS_TERM
    "premium": BusinessObjectType.BUSINESS_TERM,
    "prioridad": BusinessObjectType.BUSINESS_TERM,
    "urgencia": BusinessObjectType.BUSINESS_TERM,
    "vigente": BusinessObjectType.BUSINESS_TERM,
    # SEGMENT
    "corporativo": BusinessObjectType.SEGMENT,
    "corporativos": BusinessObjectType.SEGMENT,
    "corporate": BusinessObjectType.SEGMENT,
    # ENUM
    "estado": BusinessObjectType.ENUM,
    "status": BusinessObjectType.ENUM,
    "status_cd": BusinessObjectType.ENUM,
}

_RULE_COMPOUND_RE = re.compile(
    r"^(?:cliente|clientes|customer|customers)_(?:activo|activos|rentable|rentables|premium)$"
    r"|^(?:activo|rentable|premium)_(?:cliente|clientes|customer|customers)$",
    re.IGNORECASE,
)


def _normalize(concept: str) -> str:
    return concept.strip().lower().replace(" ", "_")


class ConceptClassifier:
    """Classify concept tokens into BusinessObjectType (deterministic)."""

    def classify(
        self,
        concept: str,
        *,
        intent: str | None = None,
    ) -> ClassifiedConcept:
        normalized = _normalize(concept)
        if not normalized:
            return ClassifiedConcept(
                concept=normalized,
                object_type=BusinessObjectType.ENTITY,
            )

        if normalized in _LEXICON:
            return ClassifiedConcept(
                concept=normalized,
                object_type=_LEXICON[normalized],
            )

        if _RULE_COMPOUND_RE.match(normalized):
            return ClassifiedConcept(
                concept=normalized,
                object_type=BusinessObjectType.BUSINESS_RULE,
            )

        # Adjectival / rule-like compounds ending in known rule stems
        if any(
            normalized.endswith(f"_{stem}") or normalized.startswith(f"{stem}_")
            for stem in ("activo", "activos", "rentable", "rentables", "moroso")
        ):
            return ClassifiedConcept(
                concept=normalized,
                object_type=BusinessObjectType.BUSINESS_RULE,
            )

        if intent == "concept_definition":
            return ClassifiedConcept(
                concept=normalized,
                object_type=BusinessObjectType.BUSINESS_TERM,
            )

        return ClassifiedConcept(
            concept=normalized,
            object_type=BusinessObjectType.ENTITY,
        )

    def classify_many(
        self,
        concepts: Iterable[str],
        *,
        intent: str | None = None,
    ) -> tuple[dict[str, str], list[str]]:
        """Return (concept_types map, requires_definition list) preserving order."""
        concept_types: dict[str, str] = {}
        requires_definition: list[str] = []
        for raw in concepts:
            classified = self.classify(raw, intent=intent)
            key = classified.concept
            if not key or key in concept_types:
                continue
            concept_types[key] = classified.object_type.value
            if classified.object_type in DEFINITIONAL_TYPES:
                requires_definition.append(key)
        return concept_types, requires_definition
