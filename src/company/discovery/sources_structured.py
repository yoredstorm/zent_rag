# =============================================================================
# Company Discovery — fuentes estructuradas deterministas (§2)
# =============================================================================
# La estructura física confirma relaciones con confianza muy alta:
#   Database CONTAINS Table, Table CONTAINS Field, Dataset CONTAINS Table.
# No hay interpretación: el catálogo y el schema son observación directa.
# Los loaders se inyectan para poder testear los extractores sin base de datos.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.company.discovery.source_base import DiscoverySource
from src.company.discovery.source_loaders import (
    load_catalog_column_identifiers,
    load_catalog_columns,
    load_catalog_entities,
    load_catalog_enum_values,
    load_catalog_fields,
    load_catalog_tables,
    load_tabular_columns,
    load_tabular_tables,
)
from src.core.domain.company_discovery import (
    CandidateKind,
    CandidateSupport,
    DiscoveryCandidate,
    DiscoveryEvidence,
    DiscoverySourceKind,
    EntityCandidatePayload,
    EntityRef,
    MappingCandidatePayload,
    RelationshipCandidatePayload,
)


def _table_name(row: dict) -> str:
    schema = (row.get("schema_name") or "").strip()
    name = (row.get("table_name") or "").strip()
    return f"{schema}.{name}" if schema else name


def _support(
    *,
    observations: int = 1,
    distinct_sources: int = 1,
    distinct_actors: int = 0,
    successful_runs: int = 0,
    structural: bool = True,
    authoritative_sources: int = 0,
    contradictions: int = 0,
) -> CandidateSupport:
    return CandidateSupport(
        observations=observations,
        distinct_sources=distinct_sources,
        distinct_actors=distinct_actors,
        successful_runs=successful_runs,
        structural=structural,
        authoritative_sources=authoritative_sources,
        contradictions=contradictions,
    )


class DatabaseSchemaSource(DiscoverySource):
    """Schema de base de datos: Database CONTAINS Table CONTAINS Field."""

    source_kind = DiscoverySourceKind.DATABASE_SCHEMA
    name = "database_schema"

    def __init__(
        self,
        *,
        loader_tables=load_catalog_tables,
        loader_columns=load_catalog_columns,
        max_items: int | None = None,
    ) -> None:
        super().__init__(max_items=max_items)
        self._load_tables = loader_tables
        self._load_columns = loader_columns

    async def discover(
        self, organization_id: UUID, *, workspace_id: UUID | None = None
    ) -> list[DiscoveryCandidate]:
        tables = await self._load_tables(organization_id, self.max_items)
        columns = await self._load_columns(organization_id, self.max_items * 5)
        by_table: dict[str, list[dict]] = {}
        for column in columns:
            by_table.setdefault(str(column.get("table_id")), []).append(column)

        candidates: list[DiscoveryCandidate] = []
        for table in tables:
            table_ref = EntityRef(entity_type="table", canonical_name=_table_name(table))
            table_entity = EntityCandidatePayload(
                entity_type="table",
                canonical_name=table_ref.canonical_name,
                display_name=table_ref.canonical_name,
                description=str(table.get("table_comment") or ""),
                domain="data",
                technical_identifiers=(table_ref.canonical_name,),
                keyword=_table_name(table).lower(),
            )
            candidates.append(
                self._entity_candidate(
                    organization_id,
                    table_entity,
                    ref=str(table.get("id") or table_ref.canonical_name),
                    structural=True,
                    workspace_id=workspace_id,
                    detail={"schema": table.get("schema_name"), "kind": "table"},
                )
            )
            source_name = str(table.get("source_name") or table.get("engine") or "").strip()
            if source_name:
                candidates.append(
                    self._relationship_candidate(
                        organization_id,
                        from_ref=EntityRef("database", source_name),
                        to_ref=table_ref,
                        relationship_type="CONTAINS",
                        ref=str(table.get("id") or table_ref.canonical_name),
                        workspace_id=workspace_id,
                    )
                )
            for column in by_table.get(str(table.get("id")), []):
                column_name = str(column.get("column_name") or "").strip()
                if not column_name:
                    continue
                field_ref = EntityRef(entity_type="field", canonical_name=column_name)
                qualified = f"{table_ref.canonical_name}.{column_name}"
                candidates.append(
                    self._entity_candidate(
                        organization_id,
                        EntityCandidatePayload(
                            entity_type="field",
                            canonical_name=column_name,
                            display_name=qualified,
                            domain="data",
                            technical_identifiers=(qualified,),
                            description=str(column.get("column_comment") or ""),
                            keyword=column_name.lower(),
                        ),
                        ref=str(column.get("id") or qualified),
                        structural=True,
                        workspace_id=workspace_id,
                        detail={
                            "table": table_ref.canonical_name,
                            "data_type": column.get("data_type"),
                            "primary_key": bool(column.get("is_primary_key")),
                        },
                    )
                )
                candidates.append(
                    self._relationship_candidate(
                        organization_id,
                        from_ref=table_ref,
                        to_ref=field_ref,
                        relationship_type="CONTAINS",
                        ref=str(column.get("id") or qualified),
                        workspace_id=workspace_id,
                    )
                )
        return candidates

    def _entity_candidate(
        self,
        organization_id: UUID,
        payload: EntityCandidatePayload,
        *,
        ref: str,
        structural: bool,
        workspace_id: UUID | None,
        detail: dict | None = None,
    ) -> DiscoveryCandidate:
        return self.build_candidate(
            organization_id=organization_id,
            kind=CandidateKind.ENTITY,
            payload=payload.to_dict(),
            title=payload.display_name or payload.canonical_name,
            summary=f"{payload.entity_type} observed in structured metadata",
            support=_support(structural=structural),
            evidence=DiscoveryEvidence(
                source_kind=self.source_kind,
                ref=ref,
                detail=detail or {},
            ),
            workspace_id=workspace_id,
        )

    def _relationship_candidate(
        self,
        organization_id: UUID,
        *,
        from_ref: EntityRef,
        to_ref: EntityRef,
        relationship_type: str,
        ref: str,
        workspace_id: UUID | None,
    ) -> DiscoveryCandidate:
        payload = RelationshipCandidatePayload(
            from_ref=from_ref, to_ref=to_ref, relationship_type=relationship_type
        )
        return self.build_candidate(
            organization_id=organization_id,
            kind=CandidateKind.RELATIONSHIP,
            payload=payload.to_dict(),
            title=f"{from_ref.canonical_name} {relationship_type} {to_ref.canonical_name}",
            summary="structural relationship confirmed by metadata",
            support=_support(),
            evidence=DiscoveryEvidence(source_kind=self.source_kind, ref=ref),
            workspace_id=workspace_id,
        )


class CatalogSemanticSource(DiscoverySource):
    """Catálogo semántico gobernado: conceptos y mappings técnicos."""

    source_kind = DiscoverySourceKind.CATALOG
    name = "catalog_semantic"

    def __init__(
        self,
        *,
        loader_entities=load_catalog_entities,
        loader_fields=load_catalog_fields,
        loader_columns=load_catalog_column_identifiers,
        loader_enums=load_catalog_enum_values,
        max_items: int | None = None,
    ) -> None:
        super().__init__(max_items=max_items)
        self._load_entities = loader_entities
        self._load_fields = loader_fields
        self._load_columns = loader_columns
        self._load_enums = loader_enums

    async def discover(
        self, organization_id: UUID, *, workspace_id: UUID | None = None
    ) -> list[DiscoveryCandidate]:
        entities = await self._load_entities(organization_id, self.max_items)
        fields = await self._load_fields(organization_id, self.max_items * 3)
        column_ids = [
            field.get("mapped_column_id")
            for field in fields
            if field.get("mapped_column_id")
        ]
        columns = {
            str(row["id"]): row
            for row in await self._load_columns(organization_id, column_ids)
        }
        enums = await self._load_enums(organization_id, self.max_items * 3)
        values_by_column: dict[str, list[str]] = {}
        for enum in enums:
            key = str(enum.get("column_id"))
            values_by_column.setdefault(key, []).append(str(enum.get("value")))

        candidates: list[DiscoveryCandidate] = []
        entity_names: dict[str, str] = {}
        for entity in entities:
            name = str(entity.get("name") or "").strip()
            if not name:
                continue
            entity_names[str(entity.get("id"))] = name
            approved = str(entity.get("provenance") or "").upper() == "APPROVED"
            payload = EntityCandidatePayload(
                entity_type="concept",
                canonical_name=name,
                display_name=str(entity.get("display_name") or name),
                description=str(entity.get("description") or ""),
                domain="business",
                aliases=(str(entity.get("display_name") or ""),),
                keyword=name.lower(),
            )
            candidates.append(
                self.build_candidate(
                    organization_id=organization_id,
                    kind=CandidateKind.ENTITY,
                    payload=payload.to_dict(),
                    title=payload.display_name,
                    summary="business concept from governed catalog",
                    support=_support(structural=approved),
                    evidence=DiscoveryEvidence(
                        source_kind=self.source_kind,
                        ref=str(entity.get("id")),
                        detail={"provenance": entity.get("provenance")},
                    ),
                    workspace_id=workspace_id,
                )
            )
        for field in fields:
            column_id = field.get("mapped_column_id")
            if not column_id:
                continue
            column = columns.get(str(column_id))
            if not column:
                continue
            concept_name = entity_names.get(str(field.get("entity_id")), "")
            field_name = str(field.get("name") or "").strip()
            if not concept_name or not field_name:
                continue
            values = tuple(values_by_column.get(str(column_id), ()))
            payload = MappingCandidatePayload(
                concept_ref=EntityRef("concept", concept_name),
                target_ref=EntityRef("field", str(column.get("column_name"))),
                values=values,
                mapping_type=str(field.get("mapping_type") or "DIRECT"),
            )
            qualified = (
                f"{column.get('schema_name')}.{column.get('table_name')}."
                f"{column.get('column_name')}"
            )
            candidates.append(
                self.build_candidate(
                    organization_id=organization_id,
                    kind=CandidateKind.MAPPING,
                    payload=payload.to_dict(),
                    title=f"{concept_name} MAPS_TO {qualified}",
                    summary="technical mapping declared in semantic catalog",
                    support=_support(
                        structural=str(field.get("provenance") or "").upper()
                        == "APPROVED",
                        observations=1,
                    ),
                    evidence=DiscoveryEvidence(
                        source_kind=self.source_kind,
                        ref=str(field.get("id")),
                        detail={
                            "column": qualified,
                            "synonyms": list(field.get("synonyms") or ()),
                            "role": field.get("role"),
                        },
                    ),
                    workspace_id=workspace_id,
                )
            )
        return candidates


class TabularStructureSource(DiscoverySource):
    """Excel/CSV estructurado: Dataset CONTAINS Table CONTAINS Field."""

    source_kind = DiscoverySourceKind.TABULAR
    name = "tabular_structure"

    def __init__(
        self,
        *,
        loader_tables=load_tabular_tables,
        loader_columns=load_tabular_columns,
        max_items: int | None = None,
    ) -> None:
        super().__init__(max_items=max_items)
        self._load_tables = loader_tables
        self._load_columns = loader_columns

    async def discover(
        self, organization_id: UUID, *, workspace_id: UUID | None = None
    ) -> list[DiscoveryCandidate]:
        tables = await self._load_tables(organization_id, self.max_items)
        columns = await self._load_columns(organization_id, self.max_items * 5)
        by_table: dict[str, list[dict]] = {}
        for column in columns:
            by_table.setdefault(str(column.get("table_id")), []).append(column)

        candidates: list[DiscoveryCandidate] = []
        for table in tables:
            filename = str(table.get("filename") or "").strip()
            table_name = str(table.get("name") or table.get("title") or "").strip()
            if not table_name:
                continue
            dataset_ref = EntityRef("dataset", filename or "tabular")
            table_ref = EntityRef("table", f"{filename}:{table_name}" if filename else table_name)
            dataset_payload = EntityCandidatePayload(
                entity_type="dataset",
                canonical_name=dataset_ref.canonical_name,
                display_name=filename or dataset_ref.canonical_name,
                domain="data",
                technical_identifiers=(filename,) if filename else (),
                keyword=dataset_ref.canonical_name.lower(),
            )
            candidates.append(
                self.build_candidate(
                    organization_id=organization_id,
                    kind=CandidateKind.ENTITY,
                    payload=dataset_payload.to_dict(),
                    title=dataset_payload.display_name,
                    support=_support(),
                    evidence=DiscoveryEvidence(
                        source_kind=self.source_kind,
                        ref=str(table.get("workbook_id") or dataset_ref.canonical_name),
                    ),
                    workspace_id=workspace_id,
                )
            )
            table_payload = EntityCandidatePayload(
                entity_type="table",
                canonical_name=table_ref.canonical_name,
                display_name=table_name,
                domain="data",
                technical_identifiers=(table_name,),
                keyword=table_name.lower(),
            )
            candidates.append(
                self.build_candidate(
                    organization_id=organization_id,
                    kind=CandidateKind.ENTITY,
                    payload=table_payload.to_dict(),
                    title=table_name,
                    support=_support(),
                    evidence=DiscoveryEvidence(
                        source_kind=self.source_kind, ref=str(table.get("id"))
                    ),
                    workspace_id=workspace_id,
                )
            )
            rel_payload = RelationshipCandidatePayload(
                from_ref=dataset_ref, to_ref=table_ref, relationship_type="CONTAINS"
            )
            candidates.append(
                self.build_candidate(
                    organization_id=organization_id,
                    kind=CandidateKind.RELATIONSHIP,
                    payload=rel_payload.to_dict(),
                    title=f"{dataset_ref.canonical_name} CONTAINS {table_name}",
                    support=_support(),
                    evidence=DiscoveryEvidence(
                        source_kind=self.source_kind, ref=str(table.get("id"))
                    ),
                    workspace_id=workspace_id,
                )
            )
            for column in by_table.get(str(table.get("id")), []):
                column_name = str(
                    column.get("normalized_name") or column.get("original_name") or ""
                ).strip()
                if not column_name:
                    continue
                field_ref = EntityRef("field", f"{table_ref.canonical_name}.{column_name}")
                field_payload = EntityCandidatePayload(
                    entity_type="field",
                    canonical_name=field_ref.canonical_name,
                    display_name=str(column.get("original_name") or column_name),
                    domain="data",
                    aliases=tuple(column.get("aliases") or ()),
                    technical_identifiers=(column_name,),
                    keyword=column_name.lower(),
                )
                candidates.append(
                    self.build_candidate(
                        organization_id=organization_id,
                        kind=CandidateKind.ENTITY,
                        payload=field_payload.to_dict(),
                        title=field_payload.display_name,
                        support=_support(),
                        evidence=DiscoveryEvidence(
                            source_kind=self.source_kind,
                            ref=str(column.get("id")),
                            detail={"semantic_type": column.get("semantic_type")},
                        ),
                        workspace_id=workspace_id,
                    )
                )
                field_rel = RelationshipCandidatePayload(
                    from_ref=table_ref, to_ref=field_ref, relationship_type="CONTAINS"
                )
                candidates.append(
                    self.build_candidate(
                        organization_id=organization_id,
                        kind=CandidateKind.RELATIONSHIP,
                        payload=field_rel.to_dict(),
                        title=f"{table_name} CONTAINS {column_name}",
                        support=_support(),
                        evidence=DiscoveryEvidence(
                            source_kind=self.source_kind, ref=str(column.get("id"))
                        ),
                        workspace_id=workspace_id,
                    )
                )
        return candidates
