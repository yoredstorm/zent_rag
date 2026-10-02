# =============================================================================
# Knowledge Model Materializer — de datos reales a conocimiento durable
# =============================================================================
# Construye knowledge_canonical_objects / knowledge_edges / knowledge_assertions
# / evidence_ledger a partir de la infraestructura existente (catalog_*,
# business_definitions, knowledge_business_rules, verified_queries,
# structured_documents). Idempotente por natural_key; org-scoped; sin datos
# simulados: solo lo que existe en las tablas.
#
# EVIDENCE FIRST: cada objeto estructurado recibe evidencia con locator real
# (schema.tabla.columna) antes de cualquier inferencia semántica.
# =============================================================================
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text

from src.core.config import get_settings
from src.core.domain.canonical import CanonicalKind, canonical_uuid
from src.core.domain.knowledge_events import (
    KnowledgeEventType,
    KnowledgeSystemEvent,
)
from src.core.domain.knowledge_model import (
    EVIDENCE_STRENGTH,
    AssertionMethod,
    AssertionStatus,
    AssertionType,
    ConfidenceSignals,
    EdgeStatus,
    EvidenceType,
    GapImpact,
    GapType,
    KnowledgeObjectStatus,
    KnowledgeObjectType,
    KnowledgeProvenance,
    RelationshipType,
    compute_confidence,
    compute_gap_priority,
)
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_CONFIDENCE_LABELS: dict[str, float] = {"high": 0.9, "medium": 0.7, "low": 0.5}

# C8: topes de eventos de sistema por materialización.
_GAP_EVENT_CAP = 10
_HIGH_IMPACT_CHANGE_CAP = 5
_HIGH_IMPACT_MAX_EVALUATIONS = 25
_HIGH_IMPACT_KINDS = frozenset({CanonicalKind.ENTITY.value, CanonicalKind.RULE.value})

_STATUS_MAP: dict[str, str] = {
    "approved": KnowledgeObjectStatus.VERIFIED.value,
    "draft": KnowledgeObjectStatus.INFERRED.value,
    "deprecated": KnowledgeObjectStatus.DEPRECATED.value,
}

_EDGE_STATUS_MAP: dict[str, str] = {
    "confirmed": EdgeStatus.VERIFIED.value,
    "suggested": EdgeStatus.INFERRED.value,
    "rejected": EdgeStatus.REJECTED.value,
}

_PROVENANCE_MAP: dict[str, str] = {
    "OBSERVED": KnowledgeProvenance.OBSERVED.value,
    "INFERRED": KnowledgeProvenance.INFERRED.value,
    "APPROVED": KnowledgeProvenance.APPROVED.value,
    "REJECTED": KnowledgeProvenance.REJECTED.value,
    "DEPRECATED": KnowledgeProvenance.DEPRECATED.value,
}

_METHOD_MAP: dict[str, str] = {
    "deterministic": AssertionMethod.DETERMINISTIC.value,
    "schema": AssertionMethod.SCHEMA.value,
    "statistical": AssertionMethod.STATISTICAL.value,
    "document": AssertionMethod.DOCUMENT.value,
    "human": AssertionMethod.HUMAN.value,
    "jev": AssertionMethod.JEV.value,
    "llm": AssertionMethod.LLM.value,
    "combined": AssertionMethod.COMBINED.value,
}

_METHOD_TO_EVIDENCE: dict[str, str] = {
    AssertionMethod.DETERMINISTIC.value: EvidenceType.DETERMINISTIC.value,
    AssertionMethod.SCHEMA.value: EvidenceType.SCHEMA.value,
    AssertionMethod.STATISTICAL.value: EvidenceType.STATISTICAL.value,
    AssertionMethod.DOCUMENT.value: EvidenceType.DOCUMENT.value,
    AssertionMethod.HUMAN.value: EvidenceType.HUMAN.value,
    AssertionMethod.JEV.value: EvidenceType.JEV.value,
    AssertionMethod.LLM.value: EvidenceType.LLM.value,
    AssertionMethod.COMBINED.value: EvidenceType.COMBINED.value,
}


def _slug(value: str) -> str:
    out = []
    for ch in (value or "").strip().lower():
        out.append(ch if ch.isalnum() else "-")
    slug = "".join(out).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:120] or "general"


def _hash(*parts: str) -> str:
    raw = "|".join(p or "" for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:64]


def _loads(value, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    import json

    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _freshness_ratio(last_seen: datetime | None, stale_days: int = 14) -> float:
    if last_seen is None:
        return 0.5
    now = datetime.now(timezone.utc)
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - last_seen).total_seconds() / 86400.0)
    return max(0.0, min(1.0, 1.0 - age_days / max(stale_days, 1)))


class KnowledgeModelMaterializer:
    """Materializa el Knowledge Model desde la infraestructura existente."""

    def __init__(
        self, repository, *, max_columns: int = 5000, system_emitter=None
    ) -> None:
        self._repo = repository
        self._max_columns = max_columns
        self._summary: dict | None = None
        # Emisor de eventos de dominio C8 (opcional): sin él, la
        # materialización mantiene exactamente su comportamiento actual.
        self._system_emitter = system_emitter

    async def materialize(
        self,
        organization_id: UUID,
        *,
        source_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> dict:
        session = await get_async_session()
        try:
            bundle = await self._load_bundle(session, organization_id, source_id)
        finally:
            await session.close()

        summary = {
            "objects_created": 0,
            "objects_updated": 0,
            "edges": 0,
            "assertions": 0,
            "evidence": 0,
            "conflicts": 0,
            "truncated_columns": False,
            "by_kind_created": {},
            "by_kind_updated": {},
            "assertions_by_method": {},
        }
        self._summary = summary
        # Índices para resolver referencias dentro de la materialización.
        source_objects: dict[str, UUID] = {}
        table_objects: dict[str, UUID] = {}
        column_objects: dict[str, UUID] = {}
        entity_objects: dict[str, UUID] = {}
        entity_tables: dict[str, str] = {}
        domain_objects: dict[str, UUID] = {}
        # Objetos que ya existían y se volvieron a materializar (C8).
        changed_objects: list[tuple[str, UUID]] = []

        async def upsert_object(**kwargs) -> UUID:
            kind = kwargs.pop("kind")
            natural_key = kwargs.pop("natural_key")
            oid = canonical_uuid(organization_id, CanonicalKind(kind), natural_key)
            existed, changed = await self._upsert_with_status(
                organization_id,
                object_id=oid,
                kind=kind,
                natural_key=natural_key,
                **kwargs,
            )
            if existed:
                summary["objects_updated"] += 1
                summary["by_kind_updated"][kind] = (
                    summary["by_kind_updated"].get(kind, 0) + 1
                )
                if changed and kind in _HIGH_IMPACT_KINDS:
                    changed_objects.append((kind, oid))
            else:
                summary["objects_created"] += 1
                summary["by_kind_created"][kind] = (
                    summary["by_kind_created"].get(kind, 0) + 1
                )
            return oid

        # ------------------------------------------------------------- fuentes
        for src in bundle["sources"]:
            name = src["connector_name"] or src["engine"] or "Fuente"
            authority = bundle["authority"].get(name, "high")
            oid = await upsert_object(
                kind=CanonicalKind.SOURCE.value,
                natural_key=f"source:{src['id']}",
                name=name,
                display_name=name,
                description=f"Fuente {src['connector_type'] or src['engine'] or ''}".strip(),
                status=KnowledgeObjectStatus.DISCOVERED.value,
                provenance=KnowledgeProvenance.OBSERVED.value,
                source_id=src["id"],
                authority_level=authority,
                source_of_truth=name,
                metadata={"engine": src["engine"], "phase": src["phase"]},
                freshness_at=src["last_scan_at"],
            )
            source_objects[str(src["id"])] = oid

        # -------------------------------------------------------------- tablas
        for table in bundle["tables"]:
            qualified = f"{table['schema_name']}.{table['table_name']}".strip(".")
            oid = await upsert_object(
                kind=CanonicalKind.TABLE.value,
                natural_key=f"table:{table['id']}",
                name=qualified,
                display_name=table["table_name"],
                description=table["table_comment"],
                domain=table["schema_name"] or None,
                status=KnowledgeObjectStatus.DISCOVERED.value,
                provenance=KnowledgeProvenance.OBSERVED.value,
                source_id=table["source_id"],
                source_of_truth=qualified,
                metadata={
                    "is_view": bool(table["is_view"]),
                    "row_count_approx": table["row_count_approx"],
                },
                freshness_at=table.get("detected_at"),
            )
            table_objects[str(table["id"])] = oid
            summary["evidence"] += await self._add_evidence(
                organization_id,
                canonical_id=oid,
                source_id=table["source_id"],
                evidence_type=EvidenceType.SCHEMA.value,
                locator=f"catalog://table/{qualified}",
                excerpt=f"Tabla {qualified} descubierta por discovery de schema.",
                table_reference=qualified,
                authority="high",
                metadata={"content_hash": table["content_hash"]},
            )
            parent = source_objects.get(str(table["source_id"]))
            if parent:
                await self._repo.upsert_edge(
                    organization_id,
                    subject_id=parent,
                    predicate="contains",
                    object_id=oid,
                    relationship_type=RelationshipType.PHYSICAL.value,
                    confidence=1.0,
                    status=EdgeStatus.DISCOVERED.value,
                    provenance=KnowledgeProvenance.OBSERVED.value,
                    source_id=table["source_id"],
                )
                summary["edges"] += 1

        # ------------------------------------------------------------ columnas
        for column in bundle["columns"]:
            qualified = (
                f"{column['schema_name']}.{column['table_name']}.{column['column_name']}"
            )
            oid = await upsert_object(
                kind=CanonicalKind.COLUMN.value,
                natural_key=f"column:{column['id']}",
                name=qualified,
                display_name=column["column_name"],
                description=column["column_comment"],
                domain=column["schema_name"] or None,
                status=KnowledgeObjectStatus.DISCOVERED.value,
                provenance=KnowledgeProvenance.OBSERVED.value,
                source_id=column["source_id"],
                source_of_truth=qualified,
                metadata={
                    "data_type": column["data_type"],
                    "nullable": bool(column["nullable"]),
                    "is_primary_key": bool(column["is_primary_key"]),
                    "is_sensitive": bool(column["is_sensitive"]),
                    "cardinality_approx": column["cardinality_approx"],
                },
            )
            column_objects[str(column["id"])] = oid
            parent = table_objects.get(str(column["table_id"]))
            if parent:
                await self._repo.upsert_edge(
                    organization_id,
                    subject_id=parent,
                    predicate="has_column",
                    object_id=oid,
                    relationship_type=RelationshipType.PHYSICAL.value,
                    confidence=1.0,
                    status=EdgeStatus.DISCOVERED.value,
                    provenance=KnowledgeProvenance.OBSERVED.value,
                    source_id=column["source_id"],
                )
                summary["edges"] += 1

        # ------------------------------------------------------------ dominios
        for entity in bundle["entities"]:
            domain_name = entity["schema_name"] or "General"
            key = _slug(domain_name)
            if key not in domain_objects:
                domain_objects[key] = await upsert_object(
                    kind=KnowledgeObjectType.DOMAIN.value,
                    natural_key=f"domain:{key}",
                    name=domain_name,
                    display_name=domain_name,
                    description=f"Dominio detectado desde el schema {domain_name}.",
                    status=KnowledgeObjectStatus.DISCOVERED.value,
                    provenance=KnowledgeProvenance.OBSERVED.value,
                    metadata={"detection": "schema_name"},
                )

        # ------------------------------------------------------------ entidades
        for entity in bundle["entities"]:
            domain_name = entity["schema_name"] or "General"
            confidence = _CONFIDENCE_LABELS.get(entity["confidence"], 0.5)
            entity_status = _STATUS_MAP.get(
                entity["status"], KnowledgeObjectStatus.INFERRED.value
            )
            entity_provenance = _PROVENANCE_MAP.get(
                entity["provenance"], KnowledgeProvenance.INFERRED.value
            )
            if entity_status == KnowledgeObjectStatus.VERIFIED.value:
                # La aprobación humana del catálogo ES el camino de promoción.
                entity_provenance = KnowledgeProvenance.APPROVED.value
            oid = await upsert_object(
                kind=CanonicalKind.ENTITY.value,
                natural_key=f"entity:{entity['id']}",
                name=entity["name"],
                display_name=entity["display_name"] or entity["name"],
                description=entity["description"],
                domain=domain_name,
                status=entity_status,
                provenance=entity_provenance,
                confidence=confidence,
                source_id=entity["source_id"],
                source_of_truth=entity["table_name"],
                metadata={"catalog_entity_id": str(entity["id"])},
                freshness_at=entity["updated_at"],
            )
            entity_objects[str(entity["id"])] = oid
            if entity["table_name"]:
                entity_tables[str(entity["id"])] = entity["table_name"]
            domain_oid = domain_objects.get(_slug(domain_name))
            if domain_oid:
                await self._repo.upsert_edge(
                    organization_id,
                    subject_id=oid,
                    predicate="belongs_to_domain",
                    object_id=domain_oid,
                    relationship_type=RelationshipType.LOGICAL.value,
                    confidence=0.8,
                    status=EdgeStatus.INFERRED.value,
                    provenance=KnowledgeProvenance.INFERRED.value,
                    metadata={"rule": "schema_name"},
                )
                summary["edges"] += 1
            table_oid = table_objects.get(str(entity["mapped_table_id"]))
            if table_oid:
                await self._repo.upsert_edge(
                    organization_id,
                    subject_id=oid,
                    predicate="mapped_to_table",
                    object_id=table_oid,
                    relationship_type=RelationshipType.LOGICAL.value,
                    confidence=confidence,
                    status=_EDGE_STATUS_MAP.get(entity["status"], EdgeStatus.INFERRED.value),
                    provenance=entity_provenance,
                    source_id=entity["source_id"],
                )
                summary["edges"] += 1
                assertion_oid = await self._upsert_assertion(
                    organization_id,
                    subject_id=oid,
                    subject_label=entity["name"],
                    predicate="mapped_to_table",
                    object_value=entity["table_name"],
                    assertion_type=AssertionType.FACT.value,
                    method=AssertionMethod.SCHEMA.value,
                    confidence=confidence,
                    evidence_count=1,
                    source_id=entity["source_id"],
                    status=(
                        AssertionStatus.VERIFIED.value
                        if entity_status == KnowledgeObjectStatus.VERIFIED.value
                        else AssertionStatus.CANDIDATE.value
                    ),
                    provenance=entity_provenance,
                )
                summary["assertions"] += 1
                summary["evidence"] += await self._add_evidence(
                    organization_id,
                    canonical_id=oid,
                    assertion_id=assertion_oid,
                    source_id=entity["source_id"],
                    evidence_type=EvidenceType.SCHEMA.value,
                    locator=f"catalog://entity/{entity['name']}",
                    excerpt=(
                        f"La entidad {entity['name']} mapea a "
                        f"{entity['schema_name']}.{entity['table_name']}."
                    ),
                    table_reference=f"{entity['schema_name']}.{entity['table_name']}",
                    metadata={"catalog_entity_id": str(entity["id"])},
                )

        # ------------------------------------------------------------ atributos
        for field in bundle["fields"]:
            if str(field["entity_id"]) not in entity_objects:
                continue
            confidence = _CONFIDENCE_LABELS.get(field["confidence"], 0.5)
            field_status = _STATUS_MAP.get(
                field["status"], KnowledgeObjectStatus.INFERRED.value
            )
            field_provenance = _PROVENANCE_MAP.get(
                field["provenance"], KnowledgeProvenance.INFERRED.value
            )
            if field_status == KnowledgeObjectStatus.VERIFIED.value:
                field_provenance = KnowledgeProvenance.APPROVED.value
            oid = await upsert_object(
                kind=KnowledgeObjectType.ATTRIBUTE.value,
                natural_key=f"attribute:{field['id']}",
                name=field["name"],
                display_name=field["name"],
                description=field["description"],
                status=field_status,
                provenance=field_provenance,
                confidence=confidence,
                metadata={
                    "role": field["role"],
                    "unit": field["unit"],
                    "synonyms": _loads(field["synonyms"], []),
                    "signal_scores": _loads(field["signal_scores"], {}),
                },
                freshness_at=field["updated_at"],
            )
            parent = entity_objects[str(field["entity_id"])]
            await self._repo.upsert_edge(
                organization_id,
                subject_id=parent,
                predicate="has_attribute",
                object_id=oid,
                relationship_type=RelationshipType.LOGICAL.value,
                confidence=confidence,
                status=_EDGE_STATUS_MAP.get(field["status"], EdgeStatus.INFERRED.value),
                provenance=field_provenance,
            )
            summary["edges"] += 1
            column_oid = column_objects.get(str(field["mapped_column_id"]))
            if column_oid is None and field["mapped_column_id"]:
                # La columna puede no estar en el índice si el field apunta a otra tabla.
                column_oid = canonical_uuid(
                    organization_id,
                    CanonicalKind.COLUMN,
                    f"column:{field['mapped_column_id']}",
                )
            if column_oid is not None:
                await self._repo.upsert_edge(
                    organization_id,
                    subject_id=oid,
                    predicate="mapped_to_column",
                    object_id=column_oid,
                    relationship_type=RelationshipType.PHYSICAL.value,
                    confidence=confidence,
                    status=EdgeStatus.INFERRED.value,
                    provenance=field_provenance,
                )
                summary["edges"] += 1
            if field["description"]:
                summary["assertions"] += 1
                await self._upsert_assertion(
                    organization_id,
                    subject_id=parent,
                    subject_label=field["name"],
                    predicate="field_meaning",
                    object_value=field["description"],
                    assertion_type=AssertionType.FIELD_MEANING.value,
                    method=AssertionMethod.SCHEMA.value,
                    confidence=confidence,
                    evidence_count=1,
                    status=AssertionStatus.CANDIDATE.value,
                )

        # --------------------------------------------------------- relaciones
        for rel in bundle["relationships"]:
            qualified_from = f"{rel['from_schema']}.{rel['from_table']}"
            qualified_to = f"{rel['to_schema']}.{rel['to_table']}"
            name = (
                f"{qualified_from}.{rel['from_column']} → "
                f"{qualified_to}.{rel['to_column']}"
            )
            confidence = (
                float(rel["confidence_score"])
                if rel.get("confidence_score") is not None
                else _CONFIDENCE_LABELS.get(rel["confidence"], 0.5)
            )
            rel_type = (
                RelationshipType.PHYSICAL.value
                if rel["relation_type"] == "foreign_key"
                else RelationshipType.SEMANTIC.value
            )
            status = _EDGE_STATUS_MAP.get(rel["status"], EdgeStatus.INFERRED.value)
            provenance = (
                KnowledgeProvenance.OBSERVED.value
                if rel["relation_type"] == "foreign_key"
                else KnowledgeProvenance.INFERRED.value
            )
            if status == EdgeStatus.VERIFIED.value:
                provenance = KnowledgeProvenance.APPROVED.value
            verb = rel.get("business_verb") or "references"
            oid = await upsert_object(
                kind=CanonicalKind.RELATIONSHIP.value,
                natural_key=f"relationship:{rel['id']}",
                name=name,
                display_name=verb,
                description=(
                    f"Relación {rel['relation_type']} entre "
                    f"{rel['from_table']} y {rel['to_table']}."
                ),
                domain=rel["from_schema"] or None,
                status=(
                    KnowledgeObjectStatus.VERIFIED.value
                    if status == EdgeStatus.VERIFIED.value
                    else KnowledgeObjectStatus.INFERRED.value
                ),
                provenance=provenance,
                confidence=confidence,
                source_id=rel["source_id"],
                metadata={
                    "relation_type": rel["relation_type"],
                    "cardinality": rel.get("cardinality"),
                    "business_verb": rel.get("business_verb"),
                    "evidence": _loads(rel["evidence"], []),
                },
            )
            summary["evidence"] += await self._add_evidence(
                organization_id,
                canonical_id=oid,
                source_id=rel["source_id"],
                evidence_type=(
                    EvidenceType.SCHEMA.value
                    if rel["relation_type"] == "foreign_key"
                    else EvidenceType.STATISTICAL.value
                ),
                locator=(
                    f"catalog://relationship/{qualified_from}.{rel['from_column']}"
                    f"->{qualified_to}.{rel['to_column']}"
                ),
                excerpt=(
                    f"{qualified_from}.{rel['from_column']} referencia "
                    f"{qualified_to}.{rel['to_column']} ({rel['relation_type']})."
                ),
                table_reference=qualified_from,
                metadata={"to_table": qualified_to},
            )
            from_table_oid = table_objects.get(str(rel["from_table_id"]))
            to_table_oid = table_objects.get(str(rel["to_table_id"]))
            if from_table_oid and to_table_oid:
                await self._repo.upsert_edge(
                    organization_id,
                    subject_id=from_table_oid,
                    predicate=verb,
                    object_id=to_table_oid,
                    relationship_type=rel_type,
                    confidence=confidence,
                    status=status,
                    provenance=provenance,
                    source_id=rel["source_id"],
                    evidence=[str(oid)],
                    metadata={"catalog_relationship_id": str(rel["id"])},
                )
                summary["edges"] += 1
            # Arista semántica entity→entity cuando ambas tablas tienen entidad.
            from_entity = next(
                (
                    eid
                    for eid, tname in entity_tables.items()
                    if tname == rel["from_table"]
                ),
                None,
            )
            to_entity = next(
                (eid for eid, tname in entity_tables.items() if tname == rel["to_table"]),
                None,
            )
            if from_entity and to_entity:
                await self._repo.upsert_edge(
                    organization_id,
                    subject_id=entity_objects[from_entity],
                    predicate=verb,
                    object_id=entity_objects[to_entity],
                    relationship_type=RelationshipType.BUSINESS.value,
                    confidence=confidence,
                    status=status,
                    provenance=provenance,
                    source_id=rel["source_id"],
                    evidence=[str(oid)],
                )
                summary["edges"] += 1
                if rel.get("cardinality"):
                    cardinality = str(rel["cardinality"]).lower()
                    predicate = (
                        "has_many"
                        if cardinality in ("1:n", "n:m", "one_to_many", "many_to_many")
                        else "has_one"
                    )
                    summary["assertions"] += 1
                    await self._upsert_assertion(
                        organization_id,
                        subject_id=entity_objects[from_entity],
                        subject_label=bundle["entity_names"][from_entity],
                        predicate=predicate,
                        object_value=bundle["entity_names"][to_entity],
                        assertion_type=AssertionType.RELATIONSHIP_CARDINALITY.value,
                        method=AssertionMethod.SCHEMA.value,
                        confidence=confidence,
                        evidence_count=1,
                        source_id=rel["source_id"],
                        status=(
                            AssertionStatus.VERIFIED.value
                            if status == EdgeStatus.VERIFIED.value
                            else AssertionStatus.CANDIDATE.value
                        ),
                    )

        # ------------------------------------------------------------ métricas
        for metric in bundle["metrics"]:
            confidence = 0.95 if metric["status"] == "approved" else 0.7
            oid = await upsert_object(
                kind=CanonicalKind.METRIC.value,
                natural_key=f"metric:{metric['metric_key']}",
                name=metric["name"],
                display_name=metric["name"],
                description=metric["definition"],
                status=_STATUS_MAP.get(metric["status"], KnowledgeObjectStatus.INFERRED.value),
                provenance=(
                    KnowledgeProvenance.APPROVED.value
                    if metric["status"] == "approved"
                    else KnowledgeProvenance.INFERRED.value
                ),
                confidence=confidence,
                source_of_truth=metric["owner"],
                metadata={
                    "formula": metric["formula"],
                    "filters": _loads(metric["filters"], []),
                    "physical_mappings": _loads(metric["physical_mappings"], []),
                    "version": metric["version"],
                },
                freshness_at=metric["updated_at"],
            )
            for mapping in _loads(metric["physical_mappings"], []):
                table_name = None
                if isinstance(mapping, dict):
                    table_name = (
                        mapping.get("table")
                        or mapping.get("table_name")
                        or mapping.get("physical_table")
                    )
                if not table_name:
                    continue
                for tid, tname in bundle["table_names"].items():
                    if tname == table_name or tname.endswith(f".{table_name}"):
                        await self._repo.upsert_edge(
                            organization_id,
                            subject_id=oid,
                            predicate="defined_on",
                            object_id=table_objects.get(tid),
                            relationship_type=RelationshipType.PHYSICAL.value,
                            confidence=confidence,
                            status=EdgeStatus.INFERRED.value,
                            provenance=KnowledgeProvenance.INFERRED.value,
                        )
                        summary["edges"] += 1
                        break
            summary["assertions"] += 1
            await self._upsert_assertion(
                organization_id,
                subject_id=oid,
                subject_label=metric["name"],
                predicate="defined_as",
                object_value=metric["formula"] or metric["definition"],
                assertion_type=AssertionType.METRIC_DEFINITION.value,
                method=AssertionMethod.HUMAN.value,
                confidence=confidence,
                evidence_count=1 if metric["formula"] else 0,
                status=(
                    AssertionStatus.VERIFIED.value
                    if metric["status"] == "approved"
                    else AssertionStatus.CANDIDATE.value
                ),
                provenance=(
                    KnowledgeProvenance.APPROVED.value
                    if metric["status"] == "approved"
                    else KnowledgeProvenance.INFERRED.value
                ),
            )

        # -------------------------------------------------------------- términos
        entity_by_name = {
            str(row["name"]).lower(): str(row["id"]) for row in bundle["entities"]
        }
        for term in bundle["definitions"]:
            if term["data_type"] == "metric":
                continue
            kind = (
                KnowledgeObjectType.TERM
                if term["data_type"] in ("concept", "status_value")
                else KnowledgeObjectType.CONCEPT
            )
            confidence = 0.9 if term["status"] == "approved" else 0.6
            oid = await upsert_object(
                kind=kind.value,
                natural_key=f"glossary:{term['concept']}",
                name=term["concept"],
                display_name=term["concept"],
                description=term["definition"],
                status=(
                    KnowledgeObjectStatus.VERIFIED.value
                    if term["status"] == "approved"
                    else KnowledgeObjectStatus.INFERRED.value
                ),
                provenance=_PROVENANCE_MAP.get(
                    term["provenance"], KnowledgeProvenance.APPROVED.value
                ),
                confidence=confidence,
                source_of_truth=term["owner"],
                metadata={
                    "data_type": term["data_type"],
                    "expression": term["expression"],
                    "version": term["version"],
                },
                freshness_at=term["updated_at"],
            )
            synonyms = _loads(term["synonyms"], [])
            for synonym in synonyms:
                if not isinstance(synonym, str) or not synonym.strip():
                    continue
                syn_oid = await upsert_object(
                    kind=KnowledgeObjectType.SYNONYM.value,
                    natural_key=f"synonym:{_slug(term['concept'])}:{_slug(synonym)}",
                    name=synonym.strip(),
                    display_name=synonym.strip(),
                    status=KnowledgeObjectStatus.DISCOVERED.value,
                    provenance=KnowledgeProvenance.OBSERVED.value,
                    confidence=0.9,
                )
                await self._repo.upsert_edge(
                    organization_id,
                    subject_id=oid,
                    predicate="has_synonym",
                    object_id=syn_oid,
                    relationship_type=RelationshipType.SEMANTIC.value,
                    confidence=0.9,
                    status=EdgeStatus.VERIFIED.value,
                    provenance=KnowledgeProvenance.APPROVED.value,
                )
                summary["edges"] += 1
            entity_id = entity_by_name.get(str(term["concept"]).lower())
            if entity_id:
                await self._repo.upsert_edge(
                    organization_id,
                    subject_id=oid,
                    predicate="defines",
                    object_id=entity_objects[entity_id],
                    relationship_type=RelationshipType.BUSINESS.value,
                    confidence=confidence,
                    status=EdgeStatus.INFERRED.value,
                    provenance=KnowledgeProvenance.INFERRED.value,
                )
                summary["edges"] += 1
            summary["assertions"] += 1
            await self._upsert_assertion(
                organization_id,
                subject_id=oid,
                subject_label=term["concept"],
                predicate="means",
                object_value=term["definition"],
                assertion_type=AssertionType.TERM_DEFINITION.value,
                method=AssertionMethod.HUMAN.value,
                confidence=confidence,
                evidence_count=0,
                status=(
                    AssertionStatus.VERIFIED.value
                    if term["status"] == "approved"
                    else AssertionStatus.CANDIDATE.value
                ),
                provenance=_PROVENANCE_MAP.get(
                    term["provenance"], KnowledgeProvenance.APPROVED.value
                ),
            )

        # --------------------------------------------------------------- reglas
        for rule in bundle["rules"]:
            confidence = _CONFIDENCE_LABELS.get(rule["confidence"], 0.5)
            method = (
                AssertionMethod.HUMAN.value
                if rule["source"] == "human"
                else AssertionMethod.LLM.value
            )
            status = (
                KnowledgeObjectStatus.VERIFIED.value
                if rule["approved_by"]
                else KnowledgeObjectStatus.INFERRED.value
            )
            oid = await upsert_object(
                kind=CanonicalKind.RULE.value,
                natural_key=f"rule:{rule['rule_key']}",
                name=rule["name"],
                display_name=rule["name"],
                description=rule["definition"],
                status=status,
                provenance=(
                    KnowledgeProvenance.APPROVED.value
                    if rule["approved_by"]
                    else _PROVENANCE_MAP.get(
                        rule["provenance"], KnowledgeProvenance.INFERRED.value
                    )
                ),
                confidence=confidence,
                metadata={
                    "applies_to": _loads(rule["applies_to"], []),
                    "source": rule["source"],
                },
                freshness_at=rule["updated_at"],
            )
            for target in _loads(rule["applies_to"], []):
                if not isinstance(target, str):
                    continue
                entity_id = entity_by_name.get(target.lower())
                if entity_id:
                    await self._repo.upsert_edge(
                        organization_id,
                        subject_id=oid,
                        predicate="applies_to",
                        object_id=entity_objects[entity_id],
                        relationship_type=RelationshipType.BUSINESS.value,
                        confidence=confidence,
                        status=EdgeStatus.INFERRED.value,
                        provenance=KnowledgeProvenance.INFERRED.value,
                    )
                    summary["edges"] += 1
            summary["assertions"] += 1
            await self._upsert_assertion(
                organization_id,
                subject_id=oid,
                subject_label=rule["name"],
                predicate="states",
                object_value=rule["definition"],
                assertion_type=AssertionType.BUSINESS_RULE.value,
                method=method,
                confidence=confidence,
                evidence_count=0,
                status=(
                    AssertionStatus.VERIFIED.value
                    if rule["approved_by"]
                    else AssertionStatus.CANDIDATE.value
                ),
                provenance=(
                    KnowledgeProvenance.APPROVED.value
                    if rule["approved_by"]
                    else _PROVENANCE_MAP.get(
                        rule["provenance"], KnowledgeProvenance.INFERRED.value
                    )
                ),
            )

        # ----------------------------------------------------- verified queries
        metric_by_name = {
            str(row["name"]).lower(): str(row["id"]) for row in bundle["metrics"]
        }
        for query in bundle["verified_queries"]:
            verified = query["status"] == "VERIFIED"
            confidence = 0.9 if verified else 0.6
            oid = await upsert_object(
                kind=KnowledgeObjectType.VERIFIED_QUERY.value,
                natural_key=f"verified_query:{query['id']}",
                name=query["name"],
                display_name=query["name"],
                description=query["canonical_question"],
                status=(
                    KnowledgeObjectStatus.VERIFIED.value
                    if verified
                    else KnowledgeObjectStatus.INFERRED.value
                ),
                provenance=(
                    KnowledgeProvenance.APPROVED.value
                    if verified
                    else KnowledgeProvenance.INFERRED.value
                ),
                confidence=confidence,
                metadata={"version": query["version"]},
            )
            for dependency in _loads(query["metric_dependencies"], []):
                if not isinstance(dependency, str):
                    continue
                metric_id = metric_by_name.get(dependency.lower())
                if metric_id:
                    await self._repo.upsert_edge(
                        organization_id,
                        subject_id=oid,
                        predicate="uses_metric",
                        object_id=canonical_uuid(
                            organization_id,
                            CanonicalKind.METRIC,
                            f"metric:{bundle['metric_keys'].get(metric_id, dependency)}",
                        ),
                        relationship_type=RelationshipType.BUSINESS.value,
                        confidence=confidence,
                        status=EdgeStatus.INFERRED.value,
                        provenance=KnowledgeProvenance.INFERRED.value,
                    )
                    summary["edges"] += 1

        # ------------------------------------------------------------ documentos
        for document in bundle["documents"]:
            oid = await upsert_object(
                kind=CanonicalKind.DOCUMENT.value,
                natural_key=f"document:{document['id']}",
                name=document["title"] or document["external_id"],
                display_name=document["title"] or document["external_id"],
                description=document["document_type"],
                status=_STATUS_MAP.get(document["status"], KnowledgeObjectStatus.DISCOVERED.value),
                provenance=_PROVENANCE_MAP.get(
                    document["provenance"], KnowledgeProvenance.OBSERVED.value
                ),
                source_id=document["source_id"],
                metadata={
                    "mime_type": document["mime_type"],
                    "page_count": document["page_count"],
                    "section_count": document["section_count"],
                    "table_count": document["table_count"],
                    "block_count": document["block_count"],
                },
                freshness_at=document["updated_at"],
            )
            parent = source_objects.get(str(document["source_id"]))
            if parent:
                await self._repo.upsert_edge(
                    organization_id,
                    subject_id=parent,
                    predicate="contains",
                    object_id=oid,
                    relationship_type=RelationshipType.PHYSICAL.value,
                    confidence=1.0,
                    status=EdgeStatus.DISCOVERED.value,
                    provenance=KnowledgeProvenance.OBSERVED.value,
                    source_id=document["source_id"],
                )
                summary["edges"] += 1
            summary["evidence"] += await self._add_evidence(
                organization_id,
                canonical_id=oid,
                source_id=document["source_id"],
                evidence_type=EvidenceType.DOCUMENT.value,
                locator=f"document://{document['external_id']}",
                excerpt=(
                    f"Documento {document['title'] or document['external_id']} "
                    f"({document['page_count']} páginas)."
                ),
                document_id=document["id"],
                metadata={"content_hash": document["content_hash"]},
            )

        # --------------------------------------------------- conflictos + contadores
        summary["conflicts"] = await self._repo.detect_conflicts(organization_id)
        await self._repo.refresh_object_counters(organization_id)
        summary["gaps"] = await self._generate_gaps(organization_id)
        await self._emit_high_impact_changes(organization_id, changed_objects)
        self._record_metrics(summary)
        await self._emit_event(
            organization_id, summary, run_id=run_id, source_id=source_id
        )
        summary["run_id"] = str(run_id) if run_id else None
        summary["source_id"] = str(source_id) if source_id else None
        logger.info(
            "knowledge model materialized",
            organization_id=str(organization_id),
            objects_created=summary["objects_created"],
            objects_updated=summary["objects_updated"],
            edges=summary["edges"],
            assertions=summary["assertions"],
        )
        return summary

    # ------------------------------------------------------------------ helpers
    def _record_metrics(self, summary: dict) -> None:
        try:
            from src.infrastructure.observability.metrics import (
                knowledge_model_assertions_total,
                knowledge_model_conflicts_total,
                knowledge_model_gaps_total,
                knowledge_model_materializations_total,
                knowledge_model_objects_total,
            )

            knowledge_model_materializations_total.labels(status="completed").inc()
            for kind, count in summary.get("by_kind_created", {}).items():
                knowledge_model_objects_total.labels(
                    operation="created", kind=kind
                ).inc(count)
            for kind, count in summary.get("by_kind_updated", {}).items():
                knowledge_model_objects_total.labels(
                    operation="updated", kind=kind
                ).inc(count)
            for method, count in summary.get("assertions_by_method", {}).items():
                knowledge_model_assertions_total.labels(
                    method=method, status="materialized"
                ).inc(count)
            if summary.get("conflicts"):
                knowledge_model_conflicts_total.inc(summary["conflicts"])
            if summary.get("gaps"):
                knowledge_model_gaps_total.labels(type="generated").inc(
                    summary["gaps"]
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("knowledge model metrics skipped", error=str(exc)[:160])

    async def _emit_event(
        self,
        organization_id: UUID,
        summary: dict,
        *,
        run_id: UUID | None,
        source_id: UUID | None,
    ) -> None:
        """Evento durable knowledge.model.materialized (best-effort)."""
        try:
            from src.platform.knowledge_learning.events import (
                KnowledgeEventEmitter,
            )
            from src.platform.knowledge_learning.repository import (
                PostgresKnowledgeLearningRepository,
            )

            await KnowledgeEventEmitter(
                PostgresKnowledgeLearningRepository()
            ).emit(
                organization_id=organization_id,
                event_type="model.materialized",
                run_id=run_id,
                source_id=source_id,
                message=(
                    "Modelo de conocimiento actualizado: "
                    f"{summary['objects_created']} nuevos, "
                    f"{summary['objects_updated']} actualizados, "
                    f"{summary['assertions']} afirmaciones."
                ),
                severity="success",
                payload={
                    key: summary[key]
                    for key in (
                        "objects_created",
                        "objects_updated",
                        "edges",
                        "assertions",
                        "evidence",
                        "conflicts",
                        "gaps",
                    )
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("knowledge model event skipped", error=str(exc)[:160])

    # ---------------------------------------------------------- eventos C8
    async def _upsert_with_status(
        self,
        organization_id: UUID,
        *,
        object_id: UUID,
        kind: str,
        natural_key: str,
        **kwargs,
    ) -> tuple[bool, bool]:
        """Upsert del objeto y detección de cambio real (C8).

        Prefiere `upsert_object_with_status` del repo. Si el repo no lo expone
        (fakes/adapters viejos), cae al contrato previo: `existed` = changed.
        """
        upsert_with_status = getattr(
            self._repo, "upsert_object_with_status", None
        )
        if upsert_with_status is not None:
            return await upsert_with_status(
                organization_id,
                object_id=object_id,
                kind=kind,
                natural_key=natural_key,
                **kwargs,
            )
        existed = await self._repo.upsert_object(
            organization_id,
            object_id=object_id,
            kind=kind,
            natural_key=natural_key,
            **kwargs,
        )
        return bool(existed), bool(existed)

    def _high_impact_threshold(self) -> int:
        """Umbral determinístico de referencias (setting, fail-soft a 5)."""
        try:
            return max(
                int(
                    getattr(
                        get_settings(), "RAG_KNOWLEDGE_HIGH_IMPACT_MIN_REFS", 5
                    )
                    or 5
                ),
                1,
            )
        except Exception:  # noqa: BLE001 — sin settings, umbral por default
            return 5

    async def _emit_high_impact_changes(
        self, organization_id: UUID, changed_objects: list[tuple[str, UUID]]
    ) -> None:
        """HIGH_IMPACT_CHANGE para reglas/entidades cambiadas con más referencias.

        Score determinístico (`repo.impact`): nunca LLM. Las reglas se evalúan
        primero (no quedan hambreadas por muchas entidades) y el cap de 5 aplica
        a las EMISIONES, no a las evaluaciones; las evaluaciones se acotan a
        `max(cap, 25)` candidatos para no recorrer modelos enormes.
        """
        if self._system_emitter is None or not changed_objects:
            return
        threshold = self._high_impact_threshold()
        ordered = sorted(
            changed_objects,
            key=lambda item: 0 if item[0] in ("rule", "business_rule") else 1,
        )
        max_evaluations = max(_HIGH_IMPACT_CHANGE_CAP, _HIGH_IMPACT_MAX_EVALUATIONS)
        emitted = 0
        evaluated = 0
        for kind, object_id in ordered:
            if emitted >= _HIGH_IMPACT_CHANGE_CAP or evaluated >= max_evaluations:
                break
            evaluated += 1
            try:
                impact = await self._repo.impact(organization_id, object_id)
                count = int((impact or {}).get("count") or 0)
            except Exception as exc:  # noqa: BLE001 — el impacto es best-effort
                logger.debug(
                    "knowledge impact lookup failed",
                    object_id=str(object_id),
                    error=str(exc)[:160],
                )
                continue
            if count < threshold:
                continue
            await self._emit_system(
                KnowledgeEventType.HIGH_IMPACT_CHANGE,
                organization_id=organization_id,
                payload={
                    "object_id": str(object_id),
                    "kind": kind,
                    "count": count,
                    "threshold": threshold,
                },
                object_id=object_id,
                requires_review=True,
            )
            emitted += 1

    async def _emit_new_gaps(
        self, organization_id: UUID, new_gaps: list[dict]
    ) -> None:
        """KNOWLEDGE_GAP_DETECTED para gaps nuevos (cap 10)."""
        for gap in new_gaps[:_GAP_EVENT_CAP]:
            await self._emit_system(
                KnowledgeEventType.KNOWLEDGE_GAP_DETECTED,
                organization_id=organization_id,
                payload=gap,
            )

    async def _emit_system(
        self,
        event_type: KnowledgeEventType,
        *,
        organization_id: UUID,
        payload: dict | None = None,
        confidence: float | None = None,
        requires_review: bool | None = None,
        source_id: UUID | None = None,
        document_id: UUID | None = None,
        object_id: UUID | None = None,
        rule_key: str | None = None,
    ) -> None:
        """Emite un evento de dominio C8. Best-effort: nunca interrumpe."""
        emitter = self._system_emitter
        if emitter is None:
            return
        try:
            await emitter.emit(
                KnowledgeSystemEvent(
                    type=event_type,
                    organization_id=organization_id,
                    payload=payload,
                    confidence=confidence,
                    requires_review=requires_review,
                    source_id=source_id,
                    document_id=document_id,
                    object_id=object_id,
                    rule_key=rule_key,
                )
            )
        except Exception as exc:  # noqa: BLE001 — la emisión es best-effort
            logger.debug(
                "knowledge system event skipped",
                event_type=str(event_type),
                error=str(exc)[:160],
            )

    async def _generate_gaps(self, organization_id: UUID) -> int:
        """Gaps accionables persistidos (context_gaps), priorizados por impacto.

        Cada gap nuevo (occurrences==1 tras el upsert) se emite como
        KNOWLEDGE_GAP_DETECTED (cap 10) cuando hay emisor de sistema C8.
        """
        session = await get_async_session()
        created = 0
        new_gaps: list[dict] = []

        async def upsert_gap(**kwargs) -> None:
            """Upsert del gap + detección de gap nuevo para la emisión C8."""
            await self._repo.upsert_gap(organization_id, **kwargs)
            if self._system_emitter is None:
                # Paridad sin emisor: ningún SELECT extra de ocurrencias.
                return
            try:
                row = (
                    await session.execute(
                        text(
                            "SELECT occurrences FROM context_gaps "
                            "WHERE organization_id = :org AND gap_type = :gap_type "
                            "AND concept = :concept"
                        ),
                        {
                            "org": organization_id,
                            "gap_type": kwargs["gap_type"],
                            "concept": str(kwargs["concept"])[:160],
                        },
                    )
                ).first()
            except Exception as exc:  # noqa: BLE001 — la detección es best-effort
                logger.debug("gap occurrence lookup failed", error=str(exc)[:160])
                return
            if row is not None and int(row[0] or 1) == 1:
                new_gaps.append(
                    {
                        "gap_type": kwargs["gap_type"],
                        "concept": str(kwargs["concept"])[:160],
                        "priority": kwargs.get("priority", "medium"),
                    }
                )

        try:
            # 1) Assertions sin evidencia.
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, subject_label, predicate, object_value, confidence,
                               source_id
                        FROM knowledge_assertions
                        WHERE organization_id = :org AND evidence_count = 0
                          AND status NOT IN ('rejected','verified')
                        LIMIT 100
                        """
                    ),
                    {"org": organization_id},
                )
            ).fetchall()
            for r in rows:
                impact = GapImpact(
                    affected_objects=1,
                    business_impact=0.6,
                    retrieval_impact=0.4,
                )
                priority, score = compute_gap_priority(
                    impact=impact, confidence=r.confidence, ambiguity=0.6, dependents=0.2
                )
                await upsert_gap(
                    gap_type=GapType.UNSUPPORTED_ASSERTION.value,
                    concept=f"assertion:{r.subject_label}:{r.predicate}"[:160],
                    title=f"Sin evidencia: {r.subject_label} {r.predicate}",
                    description=(
                        f"La afirmación «{r.subject_label} {r.predicate} "
                        f"{r.object_value or ''}» no tiene evidencia registrada."
                    ),
                    priority=priority,
                    priority_score=score,
                    source_id=r.source_id,
                    impact=impact.to_dict(),
                    impact_objects=1,
                    question="¿De dónde proviene esta afirmación?",
                )
                created += 1

            # 2) Objetos con baja confianza.
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, kind, name, confidence, source_id
                        FROM knowledge_canonical_objects
                        WHERE organization_id = :org
                          AND confidence IS NOT NULL AND confidence < 0.6
                          AND status NOT IN ('verified','rejected','deprecated')
                          AND kind NOT IN ('source','table','column','document','section','chunk')
                        ORDER BY confidence ASC LIMIT 100
                        """
                    ),
                    {"org": organization_id},
                )
            ).fetchall()
            for r in rows:
                impact = GapImpact(affected_objects=1, business_impact=0.5, retrieval_impact=0.5)
                priority, score = compute_gap_priority(
                    impact=impact, confidence=r.confidence, ambiguity=0.7, dependents=0.3
                )
                await upsert_gap(
                    gap_type=GapType.LOW_CONFIDENCE.value,
                    concept=f"object:{r.name}"[:160],
                    title=f"Baja confianza: {r.name}",
                    description=(
                        f"«{r.name}» tiene confianza {round(float(r.confidence), 2)}. "
                        "Necesita validación humana o más evidencia."
                    ),
                    priority=priority,
                    priority_score=score,
                    object_id=r.id,
                    source_id=r.source_id,
                    impact=impact.to_dict(),
                    impact_objects=1,
                    question=f"¿Es correcta la definición de «{r.name}»?",
                )
                created += 1

            # 3) Objetos sin descripción.
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, kind, name, domain, source_id
                        FROM knowledge_canonical_objects
                        WHERE organization_id = :org
                          AND (description IS NULL OR description = '')
                          AND kind IN ('entity','metric','business_rule','term','process','concept')
                        ORDER BY name LIMIT 100
                        """
                    ),
                    {"org": organization_id},
                )
            ).fetchall()
            for r in rows:
                impact = GapImpact(affected_objects=1, business_impact=0.3, retrieval_impact=0.4)
                priority, score = compute_gap_priority(
                    impact=impact, confidence=None, ambiguity=0.5, dependents=0.2
                )
                await upsert_gap(
                    gap_type=GapType.UNKNOWN_DEFINITION.value,
                    concept=f"definition:{r.name}"[:160],
                    title=f"Sin definición: {r.name}",
                    description=f"«{r.name}» no tiene descripción de negocio.",
                    priority=priority,
                    priority_score=score,
                    object_id=r.id,
                    source_id=r.source_id,
                    impact=impact.to_dict(),
                    impact_objects=1,
                    question=f"¿Qué significa «{r.name}» en tu negocio?",
                )
                created += 1

            # 4) Entidades sin relaciones ni atributos.
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT e.id, e.name, e.source_id
                        FROM knowledge_canonical_objects e
                        WHERE e.organization_id = :org AND e.kind = 'entity'
                          AND NOT EXISTS (
                            SELECT 1 FROM knowledge_edges x
                            WHERE x.organization_id = e.organization_id
                              AND (x.subject_id = e.id OR x.object_id = e.id)
                              AND x.predicate <> 'belongs_to_domain'
                              AND x.predicate <> 'mapped_to_table'
                          )
                        ORDER BY e.name LIMIT 100
                        """
                    ),
                    {"org": organization_id},
                )
            ).fetchall()
            for r in rows:
                impact = GapImpact(affected_objects=1, business_impact=0.5, retrieval_impact=0.4)
                priority, score = compute_gap_priority(
                    impact=impact, confidence=None, ambiguity=0.5, dependents=0.1
                )
                await upsert_gap(
                    gap_type=GapType.MISSING_RELATIONSHIP.value,
                    concept=f"relationship:{r.name}"[:160],
                    title=f"Sin relaciones: {r.name}",
                    description=(
                        f"La entidad «{r.name}» no tiene atributos ni relaciones descubiertas."
                    ),
                    priority=priority,
                    priority_score=score,
                    object_id=r.id,
                    source_id=r.source_id,
                    impact=impact.to_dict(),
                    impact_objects=1,
                    question=f"¿Con qué se relaciona «{r.name}»?",
                )
                created += 1

            # 5) Métricas sin fórmula.
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, name, source_id FROM knowledge_canonical_objects
                        WHERE organization_id = :org AND kind = 'metric'
                          AND (description IS NULL OR description = ''
                               OR metadata->>'formula' IS NULL)
                        LIMIT 50
                        """
                    ),
                    {"org": organization_id},
                )
            ).fetchall()
            for r in rows:
                impact = GapImpact(
                    affected_objects=1, business_impact=0.8, retrieval_impact=0.6
                )
                priority, score = compute_gap_priority(
                    impact=impact, confidence=None, ambiguity=0.6, dependents=0.5
                )
                await upsert_gap(
                    gap_type=GapType.MISSING_METRIC_DEFINITION.value,
                    concept=f"metric:{r.name}"[:160],
                    title=f"Métrica sin definición: {r.name}",
                    description=f"«{r.name}» no tiene fórmula/definición verificable.",
                    priority=priority,
                    priority_score=score,
                    object_id=r.id,
                    source_id=r.source_id,
                    impact=impact.to_dict(),
                    impact_objects=1,
                    question=f"¿Cómo se calcula «{r.name}»?",
                )
                created += 1

            # 6) Fuentes desactualizadas.
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT s.id, c.name AS connector_name, s.last_scan_at
                        FROM catalog_sources s
                        LEFT JOIN connectors c ON c.id = s.connector_id
                        WHERE s.organization_id = :org
                          AND (s.last_scan_at IS NULL
                               OR s.last_scan_at < now() - make_interval(days => :days))
                        LIMIT 50
                        """
                    ),
                    {"org": organization_id, "days": 14},
                )
            ).fetchall()
            for r in rows:
                impact = GapImpact(
                    affected_objects=0, business_impact=0.4, retrieval_impact=0.6
                )
                priority, score = compute_gap_priority(
                    impact=impact, confidence=None, ambiguity=0.3, dependents=0.4
                )
                await upsert_gap(
                    gap_type=GapType.STALE_KNOWLEDGE.value,
                    concept=f"source:{r.id}"[:160],
                    title=f"Fuente desactualizada: {r.connector_name or 'Fuente'}",
                    description="La fuente no se ha escaneado en los últimos 14 días.",
                    priority=priority,
                    priority_score=score,
                    source_id=r.id,
                    impact=impact.to_dict(),
                    question=None,
                )
                created += 1

            # 7) Conflictos abiertos → gap de contradicción.
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, subject_label, predicate, object_id
                        FROM knowledge_conflicts
                        WHERE organization_id = :org AND status = 'open'
                        LIMIT 50
                        """
                    ),
                    {"org": organization_id},
                )
            ).fetchall()
            for r in rows:
                impact = GapImpact(
                    affected_objects=1, business_impact=0.9, retrieval_impact=0.7
                )
                priority, score = compute_gap_priority(
                    impact=impact, confidence=None, ambiguity=0.9, dependents=0.6
                )
                await upsert_gap(
                    gap_type=GapType.CONTRADICTION.value,
                    concept=f"conflict:{r.subject_label}:{r.predicate}"[:160],
                    title=f"Contradicción: {r.subject_label} {r.predicate}",
                    description=(
                        "Dos fuentes afirman valores distintos para el mismo hecho."
                    ),
                    priority=priority,
                    priority_score=score,
                    object_id=r.object_id,
                    impact=impact.to_dict(),
                    impact_objects=1,
                    question=f"¿Cuál es el valor correcto de {r.predicate}?",
                )
                created += 1

            await self._emit_new_gaps(organization_id, new_gaps)
            return created
        except Exception as exc:  # noqa: BLE001
            logger.warning("gap generation failed", error=str(exc)[:240])
            return created
        finally:
            await session.close()

    async def _upsert_assertion(
        self,
        organization_id: UUID,
        *,
        subject_id: UUID | None,
        subject_label: str,
        predicate: str,
        object_value: str | None,
        assertion_type: str,
        method: str,
        confidence: float,
        evidence_count: int,
        status: str,
        provenance: str = KnowledgeProvenance.INFERRED.value,
        source_id: UUID | None = None,
    ) -> UUID:
        if status == AssertionStatus.VERIFIED.value:
            provenance = KnowledgeProvenance.APPROVED.value
        tracker = getattr(self, "_summary", None)
        if isinstance(tracker, dict):
            tracker["assertions_by_method"][method] = (
                tracker["assertions_by_method"].get(method, 0) + 1
            )
        signals = ConfidenceSignals(
            source_reliability=1.0 if provenance == KnowledgeProvenance.OBSERVED.value else 0.7,
            evidence_strength=EVIDENCE_STRENGTH.get(
                _METHOD_TO_EVIDENCE.get(method, EvidenceType.COMBINED.value), 0.7
            ),
            evidence_count=evidence_count,
            semantic_certainty=0.9 if method in ("schema", "human", "deterministic") else 0.6,
            freshness=1.0,
            validation=(
                1.0
                if status == AssertionStatus.VERIFIED.value
                else (0.0 if status == AssertionStatus.REJECTED.value else 0.85)
            ),
        )
        score, detail = compute_confidence(signals)
        return await self._repo.upsert_assertion(
            organization_id,
            subject_id=subject_id,
            subject_label=subject_label,
            predicate=predicate,
            object_value=object_value,
            assertion_type=assertion_type,
            confidence=score,
            confidence_detail=detail,
            status=status,
            provenance=provenance,
            method=method,
            source_id=source_id,
            evidence_count=evidence_count,
        )

    async def _add_evidence(
        self,
        organization_id: UUID,
        *,
        canonical_id: UUID | None,
        source_id: UUID | None,
        evidence_type: str,
        locator: str,
        excerpt: str,
        assertion_id: UUID | None = None,
        table_reference: str | None = None,
        database_reference: str | None = None,
        document_id: UUID | None = None,
        authority: str | None = None,
        metadata: dict | None = None,
    ) -> int:
        strength = EVIDENCE_STRENGTH.get(evidence_type, 0.5)
        await self._repo.add_evidence(
            organization_id,
            canonical_id=canonical_id,
            assertion_id=assertion_id,
            source_id=source_id,
            evidence_type=evidence_type,
            locator=locator,
            excerpt=excerpt,
            content_hash=_hash(locator, excerpt),
            strength=strength,
            authority=authority,
            table_reference=table_reference,
            database_reference=database_reference,
            document_id=document_id,
            metadata=metadata,
        )
        return 1

    # ------------------------------------------------------------ carga de datos
    async def _load_bundle(
        self, session, organization_id: UUID, source_id: UUID | None
    ) -> dict:
        params: dict = {"org": organization_id}
        source_filter = ""
        if source_id is not None:
            params["sid"] = source_id
            source_filter = " AND s.id = :sid"

        sources = (
            await session.execute(
                text(
                    """
                    SELECT s.id, s.connector_id, s.engine, s.phase, s.last_scan_at,
                           c.name AS connector_name, c.type AS connector_type
                    FROM catalog_sources s
                    LEFT JOIN connectors c ON c.id = s.connector_id
                    WHERE s.organization_id = :org"""
                    + source_filter
                ),
                params,
            )
        ).fetchall()

        table_filter = ""
        if source_id is not None:
            table_filter = " AND t.source_id = :sid"

        tables = (
            await session.execute(
                text(
                    """
                    SELECT t.id, t.source_id, t.schema_name, t.table_name, t.is_view,
                           t.row_count_approx, t.table_comment, t.content_hash,
                           t.detected_at
                    FROM catalog_tables t
                    WHERE t.organization_id = :org AND t.removed_at IS NULL"""
                    + table_filter
                ),
                params,
            )
        ).fetchall()

        columns = (
            await session.execute(
                text(
                    """
                    SELECT c.id, c.table_id, c.column_name, c.data_type, c.nullable,
                           c.is_primary_key, c.column_comment, c.is_sensitive,
                           c.cardinality_approx, t.schema_name, t.table_name,
                           t.source_id
                    FROM catalog_columns c
                    JOIN catalog_tables t ON t.id = c.table_id
                    WHERE c.organization_id = :org AND t.removed_at IS NULL"""
                    + table_filter
                    + " ORDER BY t.schema_name, t.table_name, c.ordinal_position"
                    + " LIMIT :cap"
                ),
                {**params, "cap": self._max_columns},
            )
        ).fetchall()

        entities = (
            await session.execute(
                text(
                    """
                    SELECT e.id, e.name, e.display_name, e.description, e.provenance,
                           e.confidence, e.status, e.mapped_table_id, e.updated_at,
                           t.schema_name, t.table_name, t.source_id
                    FROM catalog_entities e
                    LEFT JOIN catalog_tables t ON t.id = e.mapped_table_id
                    WHERE e.organization_id = :org"""
                    + (" AND t.source_id = :sid" if source_id is not None else "")
                ),
                params,
            )
        ).fetchall()

        fields = (
            await session.execute(
                text(
                    """
                    SELECT f.id, f.entity_id, f.name, f.description, f.provenance,
                           f.confidence, f.status, f.mapped_column_id, f.role,
                           f.unit, f.synonyms, f.signal_scores, f.updated_at
                    FROM catalog_fields f
                    WHERE f.organization_id = :org
                    """
                ),
                params,
            )
        ).fetchall()

        relationships = (
            await session.execute(
                text(
                    """
                    SELECT r.id, r.source_id, r.from_table_id, r.from_column,
                           r.to_table_id, r.to_column, r.relation_type, r.confidence,
                           r.status, r.evidence, r.confidence_score, r.cardinality,
                           r.business_verb, ft.schema_name AS from_schema,
                           ft.table_name AS from_table, tt.schema_name AS to_schema,
                           tt.table_name AS to_table
                    FROM catalog_relationships r
                    JOIN catalog_tables ft ON ft.id = r.from_table_id
                    JOIN catalog_tables tt ON tt.id = r.to_table_id
                    WHERE r.organization_id = :org"""
                    + (" AND r.source_id = :sid" if source_id is not None else "")
                ),
                params,
            )
        ).fetchall()

        metrics = (
            await session.execute(
                text(
                    """
                    SELECT id, metric_key, name, definition, formula,
                           semantic_dependencies, physical_mappings, filters,
                           owner, status, version, updated_at
                    FROM catalog_metrics WHERE organization_id = :org
                    """
                ),
                params,
            )
        ).fetchall()

        definitions = (
            await session.execute(
                text(
                    """
                    SELECT id, concept, definition, expression, data_type, status,
                           synonyms, owner, provenance, version, updated_at
                    FROM business_definitions WHERE organization_id = :org
                    """
                ),
                params,
            )
        ).fetchall()

        rules = (
            await session.execute(
                text(
                    """
                    SELECT id, rule_key, name, definition, applies_to, provenance,
                           confidence, source, approved_by, updated_at
                    FROM knowledge_business_rules WHERE organization_id = :org
                    """
                ),
                params,
            )
        ).fetchall()

        verified_queries = (
            await session.execute(
                text(
                    """
                    SELECT id, name, canonical_question, question_variants,
                           metric_dependencies, concept_dependencies,
                           table_dependencies, status, version
                    FROM verified_queries WHERE organization_id = :org
                    """
                ),
                params,
            )
        ).fetchall()

        documents = (
            await session.execute(
                text(
                    """
                    SELECT id, source_id, external_id, title, mime_type, document_type,
                           page_count, section_count, table_count, block_count,
                           content_hash, status, provenance, updated_at
                    FROM structured_documents
                    WHERE organization_id = :org"""
                    + (" AND source_id = :sid" if source_id is not None else "")
                    + " ORDER BY updated_at DESC LIMIT 2000"
                ),
                params,
            )
        ).fetchall()

        authority = await self._repo.source_authority_map(organization_id)

        entity_rows = [
            {
                "id": r.id,
                "name": r.name,
                "display_name": r.display_name,
                "description": r.description,
                "provenance": r.provenance,
                "confidence": r.confidence,
                "status": r.status,
                "mapped_table_id": r.mapped_table_id,
                "updated_at": r.updated_at,
                "schema_name": r.schema_name,
                "table_name": r.table_name,
                "source_id": r.source_id,
            }
            for r in entities
        ]
        return {
            "sources": [
                {
                    "id": r.id,
                    "connector_id": r.connector_id,
                    "engine": r.engine,
                    "phase": r.phase,
                    "last_scan_at": r.last_scan_at,
                    "connector_name": r.connector_name,
                    "connector_type": r.connector_type,
                }
                for r in sources
            ],
            "tables": [
                {
                    "id": r.id,
                    "source_id": r.source_id,
                    "schema_name": r.schema_name,
                    "table_name": r.table_name,
                    "is_view": r.is_view,
                    "row_count_approx": r.row_count_approx,
                    "table_comment": r.table_comment,
                    "content_hash": r.content_hash,
                    "detected_at": r.detected_at,
                }
                for r in tables
            ],
            "columns": [
                {
                    "id": r.id,
                    "table_id": r.table_id,
                    "column_name": r.column_name,
                    "data_type": r.data_type,
                    "nullable": r.nullable,
                    "is_primary_key": r.is_primary_key,
                    "column_comment": r.column_comment,
                    "is_sensitive": r.is_sensitive,
                    "cardinality_approx": r.cardinality_approx,
                    "schema_name": r.schema_name,
                    "table_name": r.table_name,
                    "source_id": r.source_id,
                }
                for r in columns
            ],
            "entities": entity_rows,
            "entity_names": {str(r["id"]): r["name"] for r in entity_rows},
            "fields": [
                {
                    "id": r.id,
                    "entity_id": r.entity_id,
                    "name": r.name,
                    "description": r.description,
                    "provenance": r.provenance,
                    "confidence": r.confidence,
                    "status": r.status,
                    "mapped_column_id": r.mapped_column_id,
                    "role": r.role,
                    "unit": r.unit,
                    "synonyms": r.synonyms,
                    "signal_scores": r.signal_scores,
                    "updated_at": r.updated_at,
                }
                for r in fields
            ],
            "relationships": [
                {
                    "id": r.id,
                    "source_id": r.source_id,
                    "from_table_id": r.from_table_id,
                    "from_column": r.from_column,
                    "to_table_id": r.to_table_id,
                    "to_column": r.to_column,
                    "relation_type": r.relation_type,
                    "confidence": r.confidence,
                    "status": r.status,
                    "evidence": r.evidence,
                    "confidence_score": r.confidence_score,
                    "cardinality": r.cardinality,
                    "business_verb": r.business_verb,
                    "from_schema": r.from_schema,
                    "from_table": r.from_table,
                    "to_schema": r.to_schema,
                    "to_table": r.to_table,
                }
                for r in relationships
            ],
            "metrics": [
                {
                    "id": r.id,
                    "metric_key": r.metric_key,
                    "name": r.name,
                    "definition": r.definition,
                    "formula": r.formula,
                    "semantic_dependencies": r.semantic_dependencies,
                    "physical_mappings": r.physical_mappings,
                    "filters": r.filters,
                    "owner": r.owner,
                    "status": r.status,
                    "version": r.version,
                    "updated_at": r.updated_at,
                }
                for r in metrics
            ],
            "metric_keys": {str(r.id): r.metric_key for r in metrics},
            "definitions": [
                {
                    "id": r.id,
                    "concept": r.concept,
                    "definition": r.definition,
                    "expression": r.expression,
                    "data_type": r.data_type,
                    "status": r.status,
                    "synonyms": r.synonyms,
                    "owner": r.owner,
                    "provenance": r.provenance,
                    "version": r.version,
                    "updated_at": r.updated_at,
                }
                for r in definitions
            ],
            "rules": [
                {
                    "id": r.id,
                    "rule_key": r.rule_key,
                    "name": r.name,
                    "definition": r.definition,
                    "applies_to": r.applies_to,
                    "provenance": r.provenance,
                    "confidence": r.confidence,
                    "source": r.source,
                    "approved_by": r.approved_by,
                    "updated_at": r.updated_at,
                }
                for r in rules
            ],
            "verified_queries": [
                {
                    "id": r.id,
                    "name": r.name,
                    "canonical_question": r.canonical_question,
                    "question_variants": r.question_variants,
                    "metric_dependencies": r.metric_dependencies,
                    "concept_dependencies": r.concept_dependencies,
                    "table_dependencies": r.table_dependencies,
                    "status": r.status,
                    "version": r.version,
                }
                for r in verified_queries
            ],
            "documents": [
                {
                    "id": r.id,
                    "source_id": r.source_id,
                    "external_id": r.external_id,
                    "title": r.title,
                    "mime_type": r.mime_type,
                    "document_type": r.document_type,
                    "page_count": r.page_count,
                    "section_count": r.section_count,
                    "table_count": r.table_count,
                    "block_count": r.block_count,
                    "content_hash": r.content_hash,
                    "status": r.status,
                    "provenance": r.provenance,
                    "updated_at": r.updated_at,
                }
                for r in documents
            ],
            "table_names": {
                str(r.id): f"{r.schema_name}.{r.table_name}" for r in tables
            },
            "authority": authority,
        }
