# =============================================================================
# Semantic Inference — sugerencias semánticas (OBSERVED / INFERRED estricto)
# =============================================================================
# Entrada: SOLO metadata (nombres, tipos, comentarios) — nunca datos crudos,
# nunca columnas sensibles. Salida: entidades/campos INFERRED + sugerencias a
# la Review Queue. NUNCA promover INFERRED -> APPROVED automáticamente.
# El LLM (opcional) enriquece las inferencias heurísticas; si falla, queda la
# heurística determinista.
# =============================================================================
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from src.catalog.signals import infer_column, infer_table_entity
from src.catalog.store import PostgresCatalogStore
from src.catalog.templates import template_for
from src.connectors.plugin.models import DeepSchemaDiscovery
from src.core.domain.catalog import (
    CatalogEntity,
    CatalogField,
    CatalogProvenance,
    CatalogSuggestion,
    SuggestionType,
)
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

_TECHNICAL_TABLE_RE = re.compile(
    r"(^|_)(audit|log|logs|staging|stg|tmp|temp|temp_|backup|bak)(_|$)",
    re.IGNORECASE,
)
_TECHNICAL_COLUMN_RE = re.compile(
    r"^(id|uuid|created_at|updated_at|deleted_at|modified_at|content_hash|"
    r"external_id|slug|version|row_version|created_by|updated_by)$",
    re.IGNORECASE,
)

_ENTITY_WORD_MAP = {
    "cust": "Customer",
    "customer": "Customer",
    "cliente": "Customer",
    "clientes": "Customer",
    "ord": "Order",
    "orders": "Order",
    "order": "Order",
    "pedido": "Order",
    "pedidos": "Order",
    "prod": "Product",
    "product": "Product",
    "products": "Product",
    "producto": "Product",
    "productos": "Product",
    "vend": "Vendor",
    "supplier": "Supplier",
    "suppliers": "Supplier",
    "proveedor": "Supplier",
    "proveedores": "Supplier",
    "emp": "Employee",
    "employee": "Employee",
    "empleado": "Employee",
    "inv": "Invoice",
    "invoice": "Invoice",
    "factura": "Invoice",
    "stk": "Stock",
    "stock": "Stock",
    "inventory": "Inventory",
    "inventario": "Inventory",
    "cat": "Category",
    "category": "Category",
    "categoria": "Category",
    "suc": "Branch",
    "branch": "Branch",
    "sucursal": "Branch",
    "venta": "Sale",
    "sales": "Sale",
    "devolucion": "Return",
    "returns": "Return",
}


def infer_entity_name(table_name: str) -> str | None:
    """Nombre de Business Entity sugerido a partir del nombre de tabla."""
    base = re.sub(r"^(tbl|dim|fct|stg|raw|d_|f_|dim_|fact_|stage_|staging_)", "", table_name, flags=re.I)
    base = base.split("_v")[0]
    words = [w for w in re.split(r"[_\s\-]+", base) if w]
    if not words:
        return None
    mapped = [_ENTITY_WORD_MAP.get(w.lower(), w.capitalize()) for w in words]
    # Tablas de puente / técnica: sin entidad sugerida.
    joined = "".join(mapped)
    if len(joined) < 2 or _TECHNICAL_TABLE_RE.search(table_name):
        return None
    return joined


def infer_field_name(column_name: str) -> str | None:
    """Nombre de Business Field sugerido a partir del nombre de columna."""
    if _TECHNICAL_COLUMN_RE.match(column_name) or column_name.endswith(("_at", "_by")):
        return None
    words = re.split(r"[_\s\-]+", column_name)
    return "".join(w.capitalize() for w in words if w) or None


class SemanticInference:
    """Genera entidades/campos INFERRED + sugerencias semánticas."""

    def __init__(
        self,
        store: PostgresCatalogStore,
        llm_provider: Any | None = None,
        llm_enabled: bool = True,
    ) -> None:
        self._store = store
        self._llm = llm_provider
        self._llm_enabled = llm_enabled

    async def run(
        self,
        *,
        organization_id: UUID,
        catalog_source_id: UUID,
        deep: DeepSchemaDiscovery,
        tables_meta: list[dict],
    ) -> list[dict]:
        """Crea entidades/campos INFERRED y sugerencias; retorna resumen."""
        await self._store.ensure_tables()
        suggestions: list[dict] = []
        existing_entities = await self._store.list_entities(organization_id, limit=1000)
        existing_names = {e["name"].lower() for e in existing_entities}

        for table in deep.tables:
            if _TECHNICAL_TABLE_RE.search(table.table_name):
                continue
            entity_name, entity_conf, entity_evidence = infer_table_entity(table.table_name)
            heuristic = infer_entity_name(table.table_name)
            if heuristic:
                entity_name = heuristic
            if not entity_name:
                continue
            table_meta = next(
                (
                    t
                    for t in tables_meta
                    if t["schema_name"] == table.schema and t["table_name"] == table.table_name
                ),
                None,
            )
            table_id = UUID(table_meta["id"]) if table_meta else None

            if entity_name.lower() not in existing_names:
                entity = CatalogEntity(
                    organization_id=organization_id,
                    name=entity_name,
                    display_name=entity_name,
                    description=f"Entidad inferida desde {table.schema}.{table.table_name}",
                    provenance=CatalogProvenance.INFERRED,
                    confidence=entity_conf,
                    evidence=entity_evidence or ["column names", "table naming patterns"],
                    mapped_table_id=table_id,
                    status="draft",
                )
                await self._store.upsert_entity(entity)
                existing_names.add(entity_name.lower())
                suggestions.append(
                    {
                        "type": "entity_identification",
                        "entity": entity_name,
                        "table": f"{table.schema}.{table.table_name}",
                    }
                )
                await self._store.create_suggestion(
                    CatalogSuggestion(
                        organization_id=organization_id,
                        type=SuggestionType.ENTITY_IDENTIFICATION,
                        title=f"'{table.schema}.{table.table_name}' probablemente representa {entity_name}.",
                        description=(
                            "Sugerencia generada por heurística de naming "
                            "(INFERRED). Confirmar o rechazar; nunca se "
                            "auto-aprueba."
                        ),
                        evidence=["table naming patterns", "column names"],
                        confidence="medium",
                        payload={
                            "entity_id": str(entity.id),
                            "entity_name": entity_name,
                            "table_id": str(table_id) if table_id else None,
                            "qualified": f"{table.schema}.{table.table_name}",
                        },
                        affected_sources=[str(catalog_source_id)],
                    )
                )

            # Campos del negocio (mapping físico -> semántico).
            entity_row = await self._get_entity_by_name(organization_id, entity_name)
            if entity_row is None:
                continue
            entity_id = UUID(entity_row["id"])
            existing_fields = await self._store.list_fields(organization_id, entity_id)
            existing_field_names = {f["name"].lower() for f in existing_fields}
            columns = await self._store.list_columns(organization_id, table_id)
            col_by_name = {c["column_name"]: c for c in columns}
            neighbor_names = [c["column_name"] for c in columns]
            try:
                org_lexicon = self._store.lexicon_as_signals(
                    await self._store.list_lexicon(organization_id)
                )
            except Exception:  # noqa: BLE001
                org_lexicon = {}
            for col in table.columns:
                if col.sensitive:
                    continue
                mapped_col = col_by_name.get(col.name)
                inferred = infer_column(
                    column_name=col.name,
                    table_name=table.table_name,
                    data_type=col.data_type,
                    is_pk=col.is_primary_key,
                    null_ratio=getattr(col, "null_ratio", None),
                    cardinality=getattr(col, "cardinality", None),
                    neighbor_names=neighbor_names,
                    org_lexicon=org_lexicon,
                )
                field_name = inferred.label.replace(" ", "")
                if not field_name:
                    continue
                already = field_name.lower() in existing_field_names
                if already:
                    continue
                field = CatalogField(
                    organization_id=organization_id,
                    entity_id=entity_id,
                    name=field_name,
                    description=f"Campo inferido desde columna {col.name}",
                    provenance=CatalogProvenance.INFERRED,
                    confidence=inferred.confidence,
                    mapped_column_id=UUID(mapped_col["id"]) if mapped_col else None,
                    status="draft",
                    role=inferred.role,
                    mapping_type="ENUM" if inferred.role == "STATUS" else "DIRECT",
                    synonyms=[inferred.label],
                    signal_scores=inferred.signal_scores,
                )
                await self._store.upsert_field(field)
                existing_field_names.add(field_name.lower())
                suggestions.append(
                    {
                        "type": "field_mapping",
                        "entity": entity_name,
                        "field": field_name,
                        "column": col.name,
                    }
                )
                if mapped_col:
                    await self._store.create_suggestion(
                        CatalogSuggestion(
                            organization_id=organization_id,
                            type=SuggestionType.FIELD_MAPPING,
                            title=f"'{col.name}' probablemente es {inferred.label}.",
                            description=(
                                "Inferencia multi-señal (INFERRED). Confirmar o cambiar; "
                                "nunca se auto-aprueba."
                            ),
                            evidence=inferred.evidence,
                            confidence=inferred.confidence,
                            payload={
                                "entity_id": str(entity_id),
                                "field_id": str(field.id),
                                "column_id": mapped_col["id"],
                                "mapped_column_id": mapped_col["id"],
                                "physical_name": col.name,
                                "business_name": inferred.label,
                                "role": inferred.role,
                                "alternatives": [
                                    {"label": lab, "score": score}
                                    for lab, score in inferred.alternatives
                                ],
                                "signal_scores": inferred.signal_scores,
                                "conflicting": inferred.conflicting,
                            },
                            affected_sources=[str(catalog_source_id)],
                        )
                    )
            tpl = template_for(entity_name)
            if tpl:
                suggestions.append({"type": "template", "entity": entity_name, "slots": tpl["slots"]})

        return suggestions

    async def _get_entity_by_name(
        self, organization_id: UUID, name: str
    ) -> dict | None:
        for e in await self._store.list_entities(organization_id, limit=1000):
            if e["name"].lower() == name.lower():
                return e
        return None
