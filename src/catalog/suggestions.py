# =============================================================================
# Semantic Review Queue — sugerencias + acciones con materialización
# =============================================================================
# Acciones: APPROVE / REJECT / EDIT_AND_APPROVE / DEFER. Toda acción se
# audita (desde la capa API) y materializa el conocimiento aprobado con
# provenance APPROVED + lineage. NUNCA hay auto-aprobación.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.catalog.lineage import LineageService
from src.catalog.metrics import MetricsService
from src.catalog.store import PostgresCatalogStore
from src.core.domain.catalog import (
    CatalogEntity,
    CatalogField,
    CatalogProvenance,
    SuggestionStatus,
    SuggestionType,
)
from src.infrastructure.observability.logging_config import get_logger
from src.intelligence.store import PostgresIntelligenceStore

logger = get_logger(__name__)


class ReviewQueueService:
    """Procesa acciones sobre sugerencias del catálogo."""

    def __init__(
        self,
        store: PostgresCatalogStore,
        intelligence_store: PostgresIntelligenceStore | None = None,
    ) -> None:
        self._store = store
        self._intel = intelligence_store or PostgresIntelligenceStore()
        self._lineage = LineageService(store)

    async def list(
        self,
        organization_id: UUID,
        *,
        status: str | None = None,
        type: str | None = None,  # noqa: A002
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        return await self._store.list_suggestions(
            organization_id, status=status, type=type, limit=limit, offset=offset
        )

    async def approve(
        self,
        organization_id: UUID,
        suggestion_id: UUID,
        *,
        reviewed_by: UUID | None = None,
        edited_payload: dict | None = None,
    ) -> dict | None:
        suggestion = await self._store.get_suggestion(organization_id, suggestion_id)
        if suggestion is None or suggestion["status"] != "pending":
            return None
        payload = edited_payload or suggestion["payload"]
        await self._materialize(
            organization_id,
            suggestion,
            payload,
            status=SuggestionStatus.EDITED_APPROVED.value if edited_payload else SuggestionStatus.APPROVED.value,
            reviewed_by=reviewed_by,
        )
        await self._store.update_suggestion_status(
            organization_id,
            suggestion_id,
            status=(
                SuggestionStatus.EDITED_APPROVED.value
                if edited_payload
                else SuggestionStatus.APPROVED.value
            ),
            reviewed_by=reviewed_by,
        )
        return await self._store.get_suggestion(organization_id, suggestion_id)

    async def reject(
        self,
        organization_id: UUID,
        suggestion_id: UUID,
        *,
        reviewed_by: UUID | None = None,
    ) -> dict | None:
        suggestion = await self._store.get_suggestion(organization_id, suggestion_id)
        if suggestion is None or suggestion["status"] != "pending":
            return None
        stype = suggestion["type"]
        if stype == SuggestionType.ENTITY_IDENTIFICATION.value:
            entity_id = suggestion["payload"].get("entity_id")
            if entity_id:
                entity = await self._store.get_entity(organization_id, UUID(entity_id))
                if entity:
                    await self._store.upsert_entity(
                        CatalogEntity(
                            id=UUID(entity_id),
                            organization_id=organization_id,
                            name=entity["name"],
                            display_name=entity["display_name"],
                            description=entity["description"],
                            provenance=CatalogProvenance.REJECTED,
                            confidence=entity["confidence"],
                            evidence=entity["evidence"],
                            status="draft",
                        )
                    )
        if stype == SuggestionType.FIELD_MAPPING.value:
            field_id = suggestion["payload"].get("field_id")
            if field_id:
                field = await self._store.get_field(organization_id, UUID(str(field_id)))
                if field:
                    await self._store.upsert_field(
                        CatalogField(
                            id=UUID(str(field_id)),
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
                        )
                    )
        if stype == SuggestionType.RELATIONSHIP_CANDIDATE.value:
            rel_id = suggestion["payload"].get("relationship_id")
            if rel_id:
                await self._store.update_relationship_status(
                    organization_id, UUID(rel_id), status="rejected", reviewed_by=reviewed_by
                )
        if stype == SuggestionType.DOCUMENT_FACT.value:
            insight_id = suggestion["payload"].get("insight_id")
            if insight_id:
                from src.platform.data_onboarding.document_insights import DocumentInsightsStore

                await DocumentInsightsStore().update_status(
                    organization_id,
                    UUID(str(insight_id)),
                    status="rejected",
                    reviewed_by=reviewed_by,
                )
        if stype == SuggestionType.BUSINESS_RULE.value:
            rule_name = suggestion["payload"].get("rule") or suggestion["payload"].get("name")
            definition = suggestion["payload"].get("definition")
            if rule_name and definition:
                from src.platform.knowledge_learning.repository import (
                    PostgresKnowledgeLearningRepository,
                )

                await PostgresKnowledgeLearningRepository().upsert_business_rule(
                    organization_id,
                    name=rule_name,
                    definition=definition,
                    applies_to=suggestion["payload"].get("applies_to") or [],
                    provenance="REJECTED",
                    confidence=suggestion.get("confidence") or "low",
                    source=suggestion["payload"].get("source") or "llm",
                    suggestion_id=UUID(str(suggestion["id"])),
                    created_by=reviewed_by,
                )
        await self._store.update_suggestion_status(
            organization_id,
            suggestion_id,
            status=SuggestionStatus.REJECTED.value,
            reviewed_by=reviewed_by,
        )
        return await self._store.get_suggestion(organization_id, suggestion_id)

    async def defer(
        self,
        organization_id: UUID,
        suggestion_id: UUID,
        *,
        reviewed_by: UUID | None = None,
    ) -> dict | None:
        ok = await self._store.update_suggestion_status(
            organization_id,
            suggestion_id,
            status=SuggestionStatus.DEFERRED.value,
            reviewed_by=reviewed_by,
        )
        if not ok:
            return None
        return await self._store.get_suggestion(organization_id, suggestion_id)

    # ------------------------------------------------------------ materialization
    async def _materialize(
        self,
        organization_id: UUID,
        suggestion: dict,
        payload: dict,
        *,
        status: str,
        reviewed_by: UUID | None,
    ) -> None:
        stype = suggestion["type"]

        if stype == SuggestionType.ENTITY_IDENTIFICATION.value:
            entity_id = payload.get("entity_id")
            if entity_id:
                entity = await self._store.get_entity(organization_id, UUID(entity_id))
                if entity:
                    await self._store.upsert_entity(
                        CatalogEntity(
                            id=UUID(entity_id),
                            organization_id=organization_id,
                            name=entity["name"],
                            display_name=payload.get("display_name") or entity["display_name"],
                            description=payload.get("description") or entity["description"],
                            provenance=CatalogProvenance.APPROVED,
                            confidence=entity["confidence"],
                            evidence=entity["evidence"],
                            mapped_table_id=(
                                UUID(payload["table_id"]) if payload.get("table_id") else (
                                    UUID(entity["mapped_table_id"]) if entity.get("mapped_table_id") else None
                                )
                            ),
                            status="approved",
                            approved_by=reviewed_by,
                        )
                    )
                    table_id = payload.get("table_id") or entity.get("mapped_table_id")
                    if table_id:
                        await self._lineage.record_entity_mapping(
                            organization_id=organization_id,
                            entity_id=UUID(entity_id),
                            table_id=UUID(table_id),
                        )

        elif stype == SuggestionType.FIELD_MAPPING.value:
            field_id = payload.get("field_id")
            column_id = (
                payload.get("mapped_column_id")
                or payload.get("column_id")
            )
            field = None
            if field_id:
                field = await self._store.get_field(organization_id, UUID(str(field_id)))
            if field is None:
                field = await self._ensure_field_from_payload(
                    organization_id, payload, reviewed_by=reviewed_by
                )
                field_id = field["id"] if field else field_id
            if field:
                mapped = column_id or field.get("mapped_column_id")
                new_name = payload.get("business_name") or payload.get("name") or field["name"]
                await self._store.upsert_field(
                    CatalogField(
                        id=UUID(str(field_id)),
                        organization_id=organization_id,
                        entity_id=UUID(str(field["entity_id"])),
                        name=new_name,
                        description=payload.get("description") or field.get("description"),
                        provenance=CatalogProvenance.APPROVED,
                        confidence="high",
                        mapped_column_id=UUID(str(mapped)) if mapped else None,
                        status="approved",
                        role=payload.get("role") or field.get("role") or "UNKNOWN",
                        mapping_type=payload.get("mapping_type") or field.get("mapping_type") or "DIRECT",
                        synonyms=payload.get("synonyms") or field.get("synonyms") or [],
                        signal_scores=field.get("signal_scores") or {},
                        approved_by=reviewed_by,
                    )
                )
                await self._store.record_mapping_version(
                    organization_id=organization_id,
                    field_id=UUID(str(field_id)),
                    column_id=UUID(str(mapped)) if mapped else None,
                    old_mapping={
                        "status": field.get("status"),
                        "name": field.get("name"),
                        "mapped_column_id": field.get("mapped_column_id"),
                    },
                    new_mapping={
                        "status": "approved",
                        "name": new_name,
                        "mapped_column_id": str(mapped) if mapped else None,
                    },
                    reason="review queue approve",
                    source="review_queue",
                    created_by=reviewed_by,
                )
                if mapped:
                    await self._lineage.record_field_mapping(
                        organization_id=organization_id,
                        field_id=UUID(str(field_id)),
                        column_id=UUID(str(mapped)),
                    )

        elif stype == SuggestionType.RELATIONSHIP_CANDIDATE.value:
            rel_id = payload.get("relationship_id")
            if rel_id:
                await self._store.update_relationship_status(
                    organization_id,
                    UUID(rel_id),
                    status="confirmed",
                    provenance="APPROVED",
                    reviewed_by=reviewed_by,
                )

        elif stype == SuggestionType.ENUM_DEFINITION.value:
            meaning = payload.get("meaning")
            column_id = payload.get("column_id")
            if meaning and column_id:
                values = payload.get("values") or []
                for value in values:
                    await self._store.upsert_enum_meaning(
                        organization_id=organization_id,
                        column_id=UUID(column_id),
                        value=value,
                        meaning=meaning,
                        reviewed_by=reviewed_by,
                    )

        elif stype == SuggestionType.GLOSSARY_TERM.value:
            concept = payload.get("concept")
            definition = payload.get("definition")
            if concept and definition:
                await self._intel.upsert_definition(
                    organization_id=organization_id,
                    concept=concept,
                    definition=definition,
                    expression=payload.get("expression"),
                    data_type=payload.get("data_type") or "concept",
                    status="approved",
                    created_by=reviewed_by,
                    synonyms=payload.get("synonyms"),
                    owner=payload.get("owner"),
                    approved_by=reviewed_by,
                    provenance="APPROVED",
                )

        elif stype == SuggestionType.DOCUMENT_FACT.value:
            from src.platform.data_onboarding.document_insights import DocumentInsightsStore

            insight_id = payload.get("insight_id")
            if insight_id:
                await DocumentInsightsStore().update_status(
                    organization_id,
                    UUID(str(insight_id)),
                    status=(
                        "edited"
                        if status == SuggestionStatus.EDITED_APPROVED.value
                        else "approved"
                    ),
                    value=payload.get("value") or payload.get("business_name"),
                    normalized_value=payload.get("normalized_value"),
                    key=payload.get("key"),
                    reviewed_by=reviewed_by,
                )

        elif stype == SuggestionType.METRIC_PROPOSAL.value:
            metric_key = payload.get("metric_key")
            name = payload.get("name") or metric_key
            definition = payload.get("definition")
            if metric_key and definition:
                service = MetricsService(self._store, intelligence_store=self._intel)
                await service.upsert(
                    organization_id=organization_id,
                    metric_key=metric_key,
                    name=name,
                    definition=definition,
                    formula=payload.get("formula"),
                    semantic_dependencies=payload.get("semantic_dependencies"),
                    physical_mappings=payload.get("physical_mappings"),
                    filters=payload.get("filters"),
                    time_semantics=payload.get("time_semantics"),
                    currency_semantics=payload.get("currency_semantics"),
                    owner=payload.get("owner"),
                    status="approved",
                    created_by=reviewed_by,
                )

        elif stype == SuggestionType.BUSINESS_RULE.value:
            rule_name = payload.get("rule") or payload.get("name")
            definition = payload.get("definition")
            if rule_name and definition:
                from src.platform.knowledge_learning.repository import (
                    PostgresKnowledgeLearningRepository,
                )

                await PostgresKnowledgeLearningRepository().upsert_business_rule(
                    organization_id,
                    name=rule_name,
                    definition=definition,
                    applies_to=payload.get("applies_to") or [],
                    provenance="APPROVED",
                    confidence=suggestion.get("confidence") or "medium",
                    source=payload.get("source") or "llm",
                    suggestion_id=UUID(str(suggestion["id"])),
                    created_by=reviewed_by,
                    learned_run_id=None,
                )

    async def _ensure_field_from_payload(
        self,
        organization_id: UUID,
        payload: dict,
        *,
        reviewed_by: UUID | None = None,
    ) -> dict | None:
        entity_id = payload.get("entity_id")
        column_id = payload.get("column_id") or payload.get("mapped_column_id")
        name = (
            payload.get("business_name")
            or payload.get("name")
            or payload.get("physical_name")
            or "field"
        )
        if not entity_id:
            entity_name = payload.get("entity_name") or "Dataset"
            existing = None
            for e in await self._store.list_entities(organization_id, limit=1000):
                if e["name"].lower() == entity_name.lower():
                    existing = e
                    break
            if existing:
                entity_id = existing["id"]
            else:
                entity = CatalogEntity(
                    organization_id=organization_id,
                    name=entity_name,
                    display_name=entity_name,
                    provenance=CatalogProvenance.APPROVED,
                    confidence="high",
                    status="approved",
                    approved_by=reviewed_by,
                )
                await self._store.upsert_entity(entity)
                entity_id = str(entity.id)
        field = CatalogField(
            organization_id=organization_id,
            entity_id=UUID(str(entity_id)),
            name=str(name),
            description=payload.get("description"),
            provenance=CatalogProvenance.APPROVED,
            confidence="high",
            mapped_column_id=UUID(str(column_id)) if column_id else None,
            status="approved",
            role=payload.get("role") or "UNKNOWN",
            mapping_type=payload.get("mapping_type") or "DIRECT",
            approved_by=reviewed_by,
        )
        await self._store.upsert_field(field)
        return await self._store.get_field(organization_id, field.id)
