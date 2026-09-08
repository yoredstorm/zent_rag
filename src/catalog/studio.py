# =============================================================================
# Mapping Studio — governed review over CatalogEntity / CatalogField
# =============================================================================
from __future__ import annotations

import re
from uuid import UUID

from src.catalog.store import PostgresCatalogStore
from src.catalog.suggestions import ReviewQueueService
from src.catalog.templates import template_for
from src.core.domain.catalog import (
    CatalogEntity,
    CatalogField,
    CatalogProvenance,
    CatalogSuggestion,
    SuggestionType,
)
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

_IMPACT_ORDER = {
    "IDENTIFIER": 0,
    "MEASURE": 1,
    "DATE": 2,
    "RELATIONSHIP": 3,
    "STATUS": 4,
    "CATEGORY": 5,
    "DESCRIPTION": 6,
    "UNKNOWN": 9,
}

_FREE_TEXT_ROLES = (
    ("identificador", "IDENTIFIER"),
    ("código", "IDENTIFIER"),
    ("codigo", "IDENTIFIER"),
    ("descripción", "DESCRIPTION"),
    ("descripcion", "DESCRIPTION"),
    ("nombre", "DESCRIPTION"),
    ("precio", "MEASURE"),
    ("costo", "MEASURE"),
    ("fecha", "DATE"),
    ("estado", "STATUS"),
    ("categoría", "CATEGORY"),
    ("categoria", "CATEGORY"),
)


class StudioService:
    def __init__(self, store: PostgresCatalogStore) -> None:
        self._store = store
        self._queue = ReviewQueueService(store)

    async def tree(
        self,
        organization_id: UUID,
        source_id: UUID,
        *,
        q: str = "",
        limit: int = 80,
        offset: int = 0,
    ) -> dict:
        source = await self._store.get_source(organization_id, source_id)
        if source is None:
            return {}
        tables = await self._store.list_tables(organization_id, source_id, limit=500)
        entities = {
            e["id"]: e
            for e in await self._store.list_entities(organization_id, limit=1000)
        }
        fields = await self._store.list_fields_all(organization_id, limit=4000)
        fields_by_col = {
            f["mapped_column_id"]: f for f in fields if f.get("mapped_column_id")
        }
        needle = (q or "").strip().lower()
        rows: list[dict] = []
        for table in tables:
            cols = await self._store.list_columns(organization_id, UUID(table["id"]))
            neighbor_names = [c["column_name"] for c in cols]
            entity = next(
                (
                    e
                    for e in entities.values()
                    if e.get("mapped_table_id") == table["id"]
                ),
                None,
            )
            template = template_for((entity or {}).get("name") or "")
            for col in cols:
                field = fields_by_col.get(col["id"])
                suggestion = await self._store.get_pending_suggestion_for_column(
                    organization_id, UUID(col["id"])
                )
                group = self._group(field, suggestion)
                item = {
                    "table_id": table["id"],
                    "table_name": table["table_name"],
                    "schema_name": table.get("schema_name") or "",
                    "qualified_name": table.get("qualified_name")
                    or f"{table.get('schema_name')}.{table['table_name']}",
                    "column": col,
                    "field": field,
                    "entity": entity,
                    "suggestion": suggestion,
                    "group": group,
                    "impact": _IMPACT_ORDER.get(
                        (field or {}).get("role") or "UNKNOWN", 9
                    ),
                    "neighbors": neighbor_names,
                    "template": template,
                }
                if needle and needle not in self._search_blob(item):
                    continue
                rows.append(item)
        rows.sort(key=lambda r: (r["impact"], r["table_name"], r["column"]["column_name"]))
        page = rows[offset : offset + limit]
        groups = {"high": [], "needs_review": [], "unknown": [], "approved": []}
        for item in page:
            groups[item["group"]].append(item)
        high_ids = [
            r["suggestion"]["id"]
            for r in rows
            if r.get("suggestion") and r["group"] == "high"
        ]
        return {
            "source": source,
            "tables": tables,
            "groups": groups,
            "total": len(rows),
            "limit": limit,
            "offset": offset,
            "high_confidence_ids": high_ids,
        }

    async def table_detail(self, organization_id: UUID, table_id: UUID) -> dict | None:
        table = await self._store.get_table(organization_id, table_id)
        if table is None:
            return None
        cols = await self._store.list_columns(organization_id, table_id)
        fields = await self._store.list_fields_all(organization_id, limit=4000)
        by_col = {f["mapped_column_id"]: f for f in fields if f.get("mapped_column_id")}
        out_cols = []
        for col in cols:
            samples: list[str] = []
            if not col.get("sample_disabled") and not col.get("is_sensitive"):
                enums = await self._store.list_enum_values(
                    organization_id, UUID(col["id"])
                )
                samples = [v["value"] for v in enums[:8]]
            field = by_col.get(col["id"])
            suggestion = await self._store.get_pending_suggestion_for_column(
                organization_id, UUID(col["id"])
            )
            out_cols.append(
                {
                    **col,
                    "samples": samples,
                    "field": field,
                    "suggestion": suggestion,
                    "group": self._group(field, suggestion),
                }
            )
        entity = next(
            (
                e
                for e in await self._store.list_entities(organization_id, limit=1000)
                if e.get("mapped_table_id") == str(table_id)
            ),
            None,
        )
        return {
            "table": table,
            "columns": out_cols,
            "entity": entity,
            "template": template_for((entity or {}).get("name") or ""),
            "coming_later": ["TRANSFORMED", "DERIVED"],
        }

    async def review_field(
        self,
        organization_id: UUID,
        field_id: UUID,
        *,
        action: str,
        payload: dict | None = None,
        reviewed_by: UUID | None = None,
    ) -> dict | None:
        field = await self._store.get_field(organization_id, field_id)
        if field is None:
            return None
        payload = payload or {}
        suggestion_id = payload.get("suggestion_id")
        if not suggestion_id and field.get("mapped_column_id"):
            pending = await self._store.get_pending_suggestion_for_column(
                organization_id, UUID(field["mapped_column_id"])
            )
            if pending:
                suggestion_id = pending["id"]
        if action == "ignore" and suggestion_id:
            return await self._queue.defer(
                organization_id, UUID(str(suggestion_id)), reviewed_by=reviewed_by
            )
        if action == "reject":
            if suggestion_id:
                result = await self._queue.reject(
                    organization_id, UUID(str(suggestion_id)), reviewed_by=reviewed_by
                )
            else:
                result = None
            await self._store.upsert_field(
                CatalogField(
                    id=field_id,
                    organization_id=organization_id,
                    entity_id=UUID(field["entity_id"]),
                    name=field["name"],
                    description=field.get("description"),
                    provenance=CatalogProvenance.REJECTED,
                    confidence=field.get("confidence") or "low",
                    mapped_column_id=(
                        UUID(field["mapped_column_id"])
                        if field.get("mapped_column_id")
                        else None
                    ),
                    status="draft",
                    role=field.get("role") or "UNKNOWN",
                    mapping_type=field.get("mapping_type") or "DIRECT",
                    synonyms=field.get("synonyms") or [],
                    signal_scores=field.get("signal_scores") or {},
                    approved_by=reviewed_by,
                )
            )
            await self._store.record_mapping_version(
                organization_id=organization_id,
                field_id=field_id,
                column_id=(
                    UUID(field["mapped_column_id"])
                    if field.get("mapped_column_id")
                    else None
                ),
                old_mapping={"status": field.get("status"), "name": field["name"]},
                new_mapping={"status": "rejected"},
                reason="studio reject",
                created_by=reviewed_by,
            )
            return result or {"id": str(field_id), "status": "rejected"}
        edited = None
        if action == "change":
            edited = {
                "field_id": str(field_id),
                "mapped_column_id": payload.get("mapped_column_id")
                or field.get("mapped_column_id"),
                "description": payload.get("description") or field.get("description"),
                "business_name": payload.get("name") or field["name"],
                "role": payload.get("role") or field.get("role"),
            }
        if suggestion_id:
            result = await self._queue.approve(
                organization_id,
                UUID(str(suggestion_id)),
                reviewed_by=reviewed_by,
                edited_payload=edited,
            )
            return result
        old = dict(field)
        mapped = payload.get("mapped_column_id") or field.get("mapped_column_id")
        await self._store.upsert_field(
            CatalogField(
                id=field_id,
                organization_id=organization_id,
                entity_id=UUID(field["entity_id"]),
                name=payload.get("name") or field["name"],
                description=payload.get("description") or field.get("description"),
                provenance=CatalogProvenance.APPROVED,
                confidence="high",
                mapped_column_id=UUID(str(mapped)) if mapped else None,
                status="approved",
                role=payload.get("role") or field.get("role") or "UNKNOWN",
                mapping_type=field.get("mapping_type") or "DIRECT",
                synonyms=field.get("synonyms") or [],
                signal_scores=field.get("signal_scores") or {},
                approved_by=reviewed_by,
            )
        )
        await self._store.record_mapping_version(
            organization_id=organization_id,
            field_id=field_id,
            column_id=UUID(str(mapped)) if mapped else None,
            old_mapping={"status": old.get("status"), "name": old.get("name")},
            new_mapping={"status": "approved", "name": payload.get("name") or field["name"]},
            reason="studio confirm",
            created_by=reviewed_by,
        )
        return await self._store.get_field(organization_id, field_id)

    async def create_custom_field(
        self,
        organization_id: UUID,
        *,
        entity_id: UUID | None,
        entity_name: str | None,
        name: str,
        mapped_column_id: UUID | None,
        role: str = "UNKNOWN",
        created_by: UUID | None = None,
    ) -> dict:
        if entity_id is None:
            entity = CatalogEntity(
                organization_id=organization_id,
                name=(entity_name or "Custom").strip() or "Custom",
                display_name=entity_name or "Custom",
                provenance=CatalogProvenance.INFERRED,
                confidence="low",
                status="draft",
                created_by=created_by,
            )
            await self._store.upsert_entity(entity)
            entity_id = entity.id
        field = CatalogField(
            organization_id=organization_id,
            entity_id=entity_id,
            name=name.strip(),
            provenance=CatalogProvenance.INFERRED,
            confidence="low",
            mapped_column_id=mapped_column_id,
            status="draft",
            role=role or "UNKNOWN",
            created_by=created_by,
        )
        await self._store.upsert_field(field)
        suggestion_id = None
        if mapped_column_id:
            suggestion_id = await self._store.create_suggestion(
                CatalogSuggestion(
                    organization_id=organization_id,
                    type=SuggestionType.FIELD_MAPPING,
                    title=f"{name} ← columna física",
                    description="Campo de negocio creado en Studio. Confirmar para aprobar.",
                    evidence=["studio custom field"],
                    confidence="low",
                    payload={
                        "entity_id": str(entity_id),
                        "field_id": str(field.id),
                        "column_id": str(mapped_column_id),
                        "mapped_column_id": str(mapped_column_id),
                    },
                )
            )
        return {
            "id": str(field.id),
            "entity_id": str(entity_id),
            "name": field.name,
            "status": "draft",
            "suggestion_id": str(suggestion_id) if suggestion_id else None,
            "needs_confirm": True,
        }

    async def free_text_draft(
        self,
        organization_id: UUID,
        text: str,
        *,
        column_id: UUID | None = None,
        created_by: UUID | None = None,
    ) -> dict:
        parsed = self._parse_free_text(text)
        created = await self.create_custom_field(
            organization_id,
            entity_id=None,
            entity_name=parsed["entity"],
            name=parsed["name"],
            mapped_column_id=column_id,
            role=parsed["role"],
            created_by=created_by,
        )
        created["parsed"] = parsed
        created["needs_confirm"] = True
        return created

    async def bulk_approve(
        self,
        organization_id: UUID,
        suggestion_ids: list[str],
        *,
        reviewed_by: UUID | None = None,
    ) -> dict:
        approved = []
        errors = []
        for sid in suggestion_ids:
            try:
                result = await self._queue.approve(
                    organization_id, UUID(sid), reviewed_by=reviewed_by
                )
                if result is None:
                    errors.append({"id": sid, "error": "not found or not pending"})
                else:
                    approved.append(result)
            except Exception as exc:  # noqa: BLE001
                errors.append({"id": sid, "error": str(exc)[:200]})
        return {"approved": len(approved), "items": approved, "errors": errors}

    @staticmethod
    def _group(field: dict | None, suggestion: dict | None) -> str:
        if field and field.get("status") == "approved":
            return "approved"
        conf = (suggestion or {}).get("confidence") or (field or {}).get("confidence") or "low"
        if conf == "high":
            return "high"
        if conf == "medium":
            return "needs_review"
        return "unknown"

    @staticmethod
    def _search_blob(item: dict) -> str:
        col = item.get("column") or {}
        field = item.get("field") or {}
        entity = item.get("entity") or {}
        return " ".join(
            [
                str(item.get("table_name") or ""),
                str(col.get("column_name") or ""),
                str(field.get("name") or ""),
                str(entity.get("name") or ""),
            ]
        ).lower()

    @staticmethod
    def _parse_free_text(text: str) -> dict:
        raw = (text or "").strip()
        lower = raw.lower()
        role = "UNKNOWN"
        for needle, mapped in _FREE_TEXT_ROLES:
            if needle in lower:
                role = mapped
                break
        entity = "Custom"
        match = re.search(r"(?:del|de la|de los|de)\s+([a-záéíóúñ]+)", lower)
        if match:
            entity = match.group(1).capitalize()
        name = raw[:80] or "Campo"
        if role == "DESCRIPTION":
            name = "Description"
        elif role == "MEASURE" and "precio" in lower:
            name = "UnitPrice"
        elif role == "IDENTIFIER":
            name = "Identifier"
        return {"entity": entity, "name": name, "role": role, "source_text": raw}
