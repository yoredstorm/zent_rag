# =============================================================================
# Business Resource Resolution (Prompt 05).
#
# Resuelve recursos reales del tenant reutilizando:
#   - Semantic Catalog: tablas, columnas, entidades, campos y autoridad.
#   - Mapping Studio: catalog_fields.mapped_column_id + unidad/moneda/rol.
#   - Knowledge OS: knowledge_bases.
#   - Conectores y managed databases.
#   - Capability Registry / Marketplace / bindings / agentes.
#
# Read-only. Nunca ejecuta SQL propuesto por el LLM, nunca devuelve credenciales
# y nunca elige una fuente arbitrariamente cuando hay ambigüedad de autoridad.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.platform.workflows.capability_registry import (
    CapabilitySnapshot,
    build_capability_snapshot,
    canonical_hash,
    search_descriptors,
    token_set,
)
from src.platform.workflows.capability_services import resolve_binding_for_tenant

logger = get_logger(__name__)

REPORT_SCHEMA = "zent.resource.resolution/v1"
MODEL_CONFIG = ConfigDict(extra="allow")

_TYPE_MAP: dict[str, str] = {
    "character varying": "string",
    "character": "string",
    "text": "string",
    "uuid": "string",
    "varchar": "string",
    "char": "string",
    "citext": "string",
    "timestamp with time zone": "string",
    "timestamp without time zone": "string",
    "timestamp": "string",
    "date": "string",
    "time": "string",
    "json": "object",
    "jsonb": "object",
    "integer": "integer",
    "int": "integer",
    "int2": "integer",
    "int4": "integer",
    "int8": "integer",
    "smallint": "integer",
    "bigint": "integer",
    "numeric": "number",
    "decimal": "number",
    "real": "number",
    "double precision": "number",
    "float": "number",
    "boolean": "boolean",
    "bool": "boolean",
    "bytea": "string",
}


class ResourceField(BaseModel):
    model_config = MODEL_CONFIG

    name: str
    data_type: str = "unknown"
    nullable: bool = True
    unit: str | None = None
    currency: str | None = None
    role: str | None = None
    mapping_type: str | None = None
    mapped_column: str | None = None
    source_field: str | None = None
    sensitive: bool = False
    synonyms: list[str] = Field(default_factory=list)


class ResourceCandidate(BaseModel):
    model_config = MODEL_CONFIG

    resource_ref: str
    kind: str
    resource_class: str = "data"
    display_name: str
    description: str = ""
    status: str = "unknown"
    score: float = 0.0
    source: dict[str, Any] = Field(default_factory=dict)
    fields: list[ResourceField] = Field(default_factory=list)
    schema_data: dict[str, Any] = Field(default_factory=dict)
    schema_source: str = "unknown"
    contract_hash: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    authority: list[dict[str, Any]] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    type_mismatches: list[dict[str, str]] = Field(default_factory=list)
    unit_mismatches: list[dict[str, str]] = Field(default_factory=list)
    currency_mismatches: list[dict[str, str]] = Field(default_factory=list)
    executable: bool = False
    read_only: bool = True
    access: dict[str, Any] = Field(
        default_factory=lambda: {"read": True, "write": False}
    )

    def compact(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"schema_data"})


class AuthorityDecision(BaseModel):
    model_config = MODEL_CONFIG

    concept: str
    status: str  # resolved | ambiguous | missing
    chosen: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    reason: str = ""


class BindingReport(BaseModel):
    model_config = MODEL_CONFIG

    capability_ref: str
    version: int | None = None
    availability: str = "UNKNOWN"
    executable: bool = False
    binding_found: bool = False
    binding_id: str | None = None
    provider_kind: str | None = None
    binding_status: str | None = None
    credential_ref_present: bool = False
    contract_version: int | None = None
    contract_hash: str | None = None
    configured: bool = False
    permission_denied: bool = False
    approval_required: bool = False
    degraded: bool = False
    reasons: list[str] = Field(default_factory=list)
    marketplace_available: bool = False
    installed: bool = False


class GuidedConfiguration(BaseModel):
    model_config = MODEL_CONFIG

    code: str
    requirement: str
    title: str
    reason: str
    module: str
    marketplace_available: bool = False
    steps: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)


class ResolutionReport(BaseModel):
    model_config = MODEL_CONFIG

    schema_id: str = REPORT_SCHEMA
    need: str
    resolved: bool = False
    selected: ResourceCandidate | None = None
    candidates: list[ResourceCandidate] = Field(default_factory=list)
    authority: list[AuthorityDecision] = Field(default_factory=list)
    ambiguities: list[dict[str, Any]] = Field(default_factory=list)
    unresolved: list[dict[str, Any]] = Field(default_factory=list)
    bindings: list[BindingReport] = Field(default_factory=list)
    capability_candidates: list[dict[str, Any]] = Field(default_factory=list)
    agent_candidates: list[dict[str, Any]] = Field(default_factory=list)
    guided_configuration: list[GuidedConfiguration] = Field(default_factory=list)
    trace: dict[str, Any] = Field(default_factory=dict)


def _normalize_type(value: str | None) -> str:
    text_value = str(value or "").strip().lower()
    if "(" in text_value:
        text_value = text_value.split("(", 1)[0].strip()
    return _TYPE_MAP.get(text_value, text_value or "unknown")


def _active(row: dict[str, Any], now: datetime) -> bool:
    def parse(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None

    start = parse(row.get("effective_from"))
    end = parse(row.get("effective_to"))
    return (start is None or start <= now) and (end is None or end >= now)


def _field_schema(field: ResourceField) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": field.data_type}
    if field.nullable:
        schema["nullable"] = True
    if field.unit:
        schema["x-unit"] = field.unit
    if field.currency:
        schema["x-currency"] = field.currency
    if field.role:
        schema["x-role"] = field.role
    if field.mapping_type:
        schema["x-mapping-type"] = field.mapping_type
    if field.mapped_column:
        schema["x-mapped-column"] = field.mapped_column
    if field.synonyms:
        schema["x-synonyms"] = field.synonyms
    return schema


def _resource_schema(fields: list[ResourceField]) -> dict[str, Any]:
    required = [field.name for field in fields if not field.nullable]
    return {
        "type": "object",
        "properties": {field.name: _field_schema(field) for field in fields},
        **({"required": required} if required else {}),
    }


def _field_matches(field: ResourceField, expected: dict[str, Any]) -> bool:
    name = str(expected.get("name") or "").lower()
    names = {field.name.lower(), *(item.lower() for item in field.synonyms)}
    if name and name not in names:
        return False
    expected_type = _normalize_type(str(expected.get("data_type") or expected.get("type") or ""))
    if expected_type and expected_type not in ("unknown", "json", "any"):
        if field.data_type != expected_type and not (
            field.data_type == "integer" and expected_type == "number"
        ):
            return False
    return True


class BusinessResourceResolver:
    """Resolver determinista de recursos y bindings para un tenant/workspace."""

    def __init__(
        self,
        organization_id: UUID,
        *,
        workspace_id: UUID | None = None,
        permissions: frozenset[str] | None = None,
        snapshot: CapabilitySnapshot | None = None,
    ) -> None:
        self.organization_id = organization_id
        self.workspace_id = workspace_id
        self.permissions = permissions or frozenset()
        self.snapshot = snapshot
        self._catalog: dict[str, Any] | None = None

    async def _ensure_snapshot(self) -> CapabilitySnapshot:
        if self.snapshot is None:
            self.snapshot = await build_capability_snapshot(
                self.organization_id,
                self.workspace_id,
                permissions=self.permissions,
                force_refresh=True,
            )
        return self.snapshot

    async def _ensure_catalog(self) -> dict[str, Any]:
        if self._catalog is not None:
            return self._catalog
        catalog: dict[str, Any] = {
            "sources": [],
            "tables": [],
            "columns": [],
            "entities": [],
            "fields": [],
            "authorities": [],
        }
        session = await get_async_session()
        try:
            try:
                source_sql = (
                    "SELECT s.id, s.connector_id, s.workspace_id, s.engine, s.phase, "
                    "c.name AS connector_name, c.type AS connector_type, "
                    "c.status AS connector_status "
                    "FROM catalog_sources s "
                    "LEFT JOIN connectors c ON c.id = s.connector_id "
                    "AND c.organization_id = s.organization_id "
                    "WHERE s.organization_id = :oid"
                )
                source_params: dict[str, Any] = {"oid": str(self.organization_id)}
                if self.workspace_id is not None:
                    source_sql += " AND (s.workspace_id IS NULL OR s.workspace_id = :ws)"
                    source_params["ws"] = str(self.workspace_id)
                source_sql += " ORDER BY s.created_at"
                source_rows = (
                    await session.execute(text(source_sql), source_params)
                ).fetchall()
                catalog["sources"] = [
                    {
                        "source_id": str(row.id),
                        "connector_id": str(row.connector_id) if row.connector_id else None,
                        "workspace_id": str(row.workspace_id) if row.workspace_id else None,
                        "engine": row.engine,
                        "phase": row.phase,
                        "connector_name": row.connector_name,
                        "connector_type": row.connector_type,
                        "connector_status": row.connector_status,
                    }
                    for row in source_rows
                ]
            except Exception as exc:  # noqa: BLE001 — catálogo opcional
                await session.rollback()
                logger.warning("resource resolver catalog sources failed", error=str(exc)[:160])

            try:
                table_rows = (
                    await session.execute(
                        text(
                            "SELECT id, source_id, schema_name, table_name, is_view, "
                            "row_count_approx, table_comment, content_hash "
                            "FROM catalog_tables WHERE organization_id = :oid "
                            "AND removed_at IS NULL ORDER BY schema_name, table_name LIMIT 500"
                        ),
                        {"oid": str(self.organization_id)},
                    )
                ).fetchall()
                catalog["tables"] = [
                    {
                        "table_id": str(row.id),
                        "source_id": str(row.source_id),
                        "schema_name": row.schema_name,
                        "table_name": row.table_name,
                        "is_view": bool(row.is_view),
                        "row_count": int(row.row_count_approx or 0),
                        "comment": row.table_comment,
                        "content_hash": row.content_hash,
                    }
                    for row in table_rows
                    if str(row.source_id) in {item["source_id"] for item in catalog["sources"]}
                ]
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                logger.warning("resource resolver catalog tables failed", error=str(exc)[:160])

            try:
                column_rows = (
                    await session.execute(
                        text(
                            "SELECT id, table_id, column_name, ordinal_position, data_type, "
                            "nullable, is_primary_key, column_comment, is_sensitive, pii_flags "
                            "FROM catalog_columns WHERE organization_id = :oid "
                            "ORDER BY table_id, ordinal_position LIMIT 5000"
                        ),
                        {"oid": str(self.organization_id)},
                    )
                ).fetchall()
                catalog["columns"] = [
                    {
                        "column_id": str(row.id),
                        "table_id": str(row.table_id),
                        "column_name": row.column_name,
                        "ordinal_position": int(row.ordinal_position or 0),
                        "data_type": _normalize_type(row.data_type),
                        "nullable": bool(row.nullable),
                        "is_primary_key": bool(row.is_primary_key),
                        "comment": row.column_comment,
                        "sensitive": bool(row.is_sensitive),
                        "pii_flags": list(row.pii_flags or []),
                    }
                    for row in column_rows
                ]
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                logger.warning("resource resolver catalog columns failed", error=str(exc)[:160])

            try:
                entity_rows = (
                    await session.execute(
                        text(
                            "SELECT id, name, display_name, description, provenance, confidence, "
                            "mapped_table_id, status FROM catalog_entities "
                            "WHERE organization_id = :oid ORDER BY name LIMIT 300"
                        ),
                        {"oid": str(self.organization_id)},
                    )
                ).fetchall()
                catalog["entities"] = [
                    {
                        "entity_id": str(row.id),
                        "name": row.name,
                        "display_name": row.display_name,
                        "description": row.description,
                        "provenance": row.provenance,
                        "confidence": row.confidence,
                        "mapped_table_id": str(row.mapped_table_id) if row.mapped_table_id else None,
                        "status": row.status,
                    }
                    for row in entity_rows
                    if not row.mapped_table_id
                    or str(row.mapped_table_id)
                    in {item["table_id"] for item in catalog["tables"]}
                ]
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                logger.warning("resource resolver catalog entities failed", error=str(exc)[:160])

            try:
                field_rows = (
                    await session.execute(
                        text(
                            "SELECT id, entity_id, name, description, provenance, confidence, "
                            "mapped_column_id, status, role, mapping_type, unit, currency, grain, "
                            "aggregation_behavior, synonyms FROM catalog_fields "
                            "WHERE organization_id = :oid ORDER BY entity_id, name LIMIT 5000"
                        ),
                        {"oid": str(self.organization_id)},
                    )
                ).fetchall()
                catalog["fields"] = [
                    {
                        "field_id": str(row.id),
                        "entity_id": str(row.entity_id),
                        "name": row.name,
                        "description": row.description,
                        "provenance": row.provenance,
                        "confidence": row.confidence,
                        "mapped_column_id": str(row.mapped_column_id) if row.mapped_column_id else None,
                        "status": row.status,
                        "role": row.role,
                        "mapping_type": row.mapping_type,
                        "unit": row.unit,
                        "currency": row.currency,
                        "grain": row.grain,
                        "aggregation_behavior": row.aggregation_behavior,
                        "synonyms": list(row.synonyms or []),
                    }
                    for row in field_rows
                ]
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                logger.warning("resource resolver catalog fields failed", error=str(exc)[:160])

            try:
                authority_rows = (
                    await session.execute(
                        text(
                            "SELECT id, domain, concept, source_name, source_type, connector_id, "
                            "authority_level, priority, effective_from, effective_to "
                            "FROM catalog_authority WHERE organization_id = :oid "
                            "ORDER BY concept, priority DESC, source_name"
                        ),
                        {"oid": str(self.organization_id)},
                    )
                ).fetchall()
                catalog["authorities"] = [
                    {
                        "authority_id": str(row.id),
                        "domain": row.domain,
                        "concept": row.concept,
                        "source_name": row.source_name,
                        "source_type": row.source_type,
                        "connector_id": str(row.connector_id) if row.connector_id else None,
                        "authority_level": row.authority_level,
                        "priority": int(row.priority or 1),
                        "effective_from": row.effective_from.isoformat() if row.effective_from else None,
                        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
                    }
                    for row in authority_rows
                    if not row.connector_id
                    or str(row.connector_id)
                    in {
                        str(item.get("connector_id"))
                        for item in catalog["sources"]
                        if item.get("connector_id")
                    }
                ]
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                logger.warning("resource resolver catalog authority failed", error=str(exc)[:160])
        finally:
            await session.close()
        self._catalog = catalog
        return catalog

    async def _catalog_candidates(self) -> list[ResourceCandidate]:
        catalog = await self._ensure_catalog()
        sources = {item["source_id"]: item for item in catalog["sources"]}
        tables = {item["table_id"]: item for item in catalog["tables"]}
        columns_by_table: dict[str, list[dict]] = {}
        for column in catalog["columns"]:
            columns_by_table.setdefault(column["table_id"], []).append(column)
        fields_by_entity: dict[str, list[dict]] = {}
        for field in catalog["fields"]:
            fields_by_entity.setdefault(field["entity_id"], []).append(field)
        columns_by_id = {item["column_id"]: item for item in catalog["columns"]}
        authorities = catalog["authorities"]
        now = datetime.now(timezone.utc)
        candidates: list[ResourceCandidate] = []

        for table in catalog["tables"]:
            source = sources.get(table["source_id"]) or {}
            source_phase = str(source.get("phase") or "").upper()
            source_ready = source_phase in ("COMPLETED", "PARTIAL", "")
            columns = columns_by_table.get(table["table_id"], [])
            fields = [
                ResourceField(
                    name=column["column_name"],
                    data_type=column["data_type"],
                    nullable=column["nullable"],
                    mapped_column=column["column_name"],
                    source_field=column["column_name"],
                    sensitive=column["sensitive"],
                    role="IDENTIFIER" if column["is_primary_key"] else None,
                )
                for column in columns
            ]
            source_connector = source.get("connector_id")
            table_authorities = [
                item
                for item in authorities
                if _active(item, now)
                and (
                    (source_connector and item.get("connector_id") == source_connector)
                    or str(item.get("source_name") or "").lower()
                    in {
                        str(source.get("connector_name") or "").lower(),
                        str(source.get("source_id") or "").lower(),
                    }
                )
            ]
            candidates.append(
                ResourceCandidate(
                    resource_ref=f"catalog.table.{table['table_id']}",
                    kind="catalog_table",
                    resource_class="data",
                    display_name=f"{table['schema_name']}.{table['table_name']}"
                    if table["schema_name"]
                    else table["table_name"],
                    description=str(table.get("comment") or "Tabla del catálogo semántico."),
                    status="available" if source_ready else "NEEDS_SCAN",
                    source={
                        "source_id": table["source_id"],
                        "connector_id": source_connector,
                        "connector_name": source.get("connector_name"),
                        "connector_type": source.get("connector_type"),
                        "engine": source.get("engine"),
                    },
                    fields=fields,
                    schema_data=_resource_schema(fields),
                    schema_source="catalog",
                    contract_hash=canonical_hash(
                        {
                            "resource_ref": f"catalog.table.{table['table_id']}",
                            "fields": [field.model_dump() for field in fields],
                        }
                    )[:64],
                    metadata={
                        "catalog_table_id": table["table_id"],
                        "schema_name": table["schema_name"],
                        "table_name": table["table_name"],
                        "row_count": table["row_count"],
                        "is_view": table["is_view"],
                        "content_hash": table.get("content_hash"),
                    },
                    authority=table_authorities,
                    executable=source_ready,
                    read_only=True,
                )
            )

        for entity in catalog["entities"]:
            mapped_table = tables.get(entity.get("mapped_table_id") or "")
            source = sources.get(mapped_table["source_id"]) if mapped_table else {}
            source_ready = bool(source) and str(source.get("phase") or "").upper() in (
                "COMPLETED",
                "PARTIAL",
                "",
            )
            entity_fields = fields_by_entity.get(entity["entity_id"], [])
            fields: list[ResourceField] = []
            for field in entity_fields:
                column = columns_by_id.get(field.get("mapped_column_id") or "")
                fields.append(
                    ResourceField(
                        name=field["name"],
                        data_type=_normalize_type((column or {}).get("data_type")),
                        nullable=bool((column or {}).get("nullable", True)),
                        unit=field.get("unit"),
                        currency=field.get("currency"),
                        role=field.get("role"),
                        mapping_type=field.get("mapping_type"),
                        mapped_column=(column or {}).get("column_name"),
                        source_field=(column or {}).get("column_name"),
                        sensitive=bool((column or {}).get("sensitive")),
                        synonyms=list(field.get("synonyms") or []),
                    )
                )
            source_connector = source.get("connector_id") if source else None
            entity_authorities = [
                item
                for item in authorities
                if _active(item, now)
                and (
                    (source_connector and item.get("connector_id") == source_connector)
                    or str(item.get("source_name") or "").lower()
                    in {
                        str(source.get("connector_name") or "").lower(),
                        str(entity.get("name") or "").lower(),
                    }
                )
            ]
            candidates.append(
                ResourceCandidate(
                    resource_ref=f"catalog.entity.{entity['entity_id']}",
                    kind="catalog_entity",
                    resource_class="data",
                    display_name=str(entity.get("display_name") or entity["name"]),
                    description=str(entity.get("description") or "Entidad gobernada de Mapping Studio."),
                    status=str(entity.get("status") or "draft"),
                    source={
                        "source_id": mapped_table["source_id"] if mapped_table else None,
                        "connector_id": source_connector,
                        "connector_name": source.get("connector_name") if source else None,
                    },
                    fields=fields,
                    schema_data=_resource_schema(fields),
                    schema_source="mapping_studio",
                    contract_hash=canonical_hash(
                        {
                            "resource_ref": f"catalog.entity.{entity['entity_id']}",
                            "fields": [field.model_dump() for field in fields],
                        }
                    )[:64],
                    metadata={
                        "catalog_entity_id": entity["entity_id"],
                        "entity_name": entity["name"],
                        "mapped_table_id": entity.get("mapped_table_id"),
                        "mapped_table": (
                            f"{mapped_table['schema_name']}.{mapped_table['table_name']}"
                            if mapped_table
                            else None
                        ),
                        "provenance": entity.get("provenance"),
                        "confidence": entity.get("confidence"),
                        "mapping_source": "mapping_studio",
                    },
                    authority=entity_authorities,
                    executable=str(entity.get("status")) == "approved"
                    and (not mapped_table or source_ready),
                    read_only=True,
                )
            )
        return candidates

    @staticmethod
    def _score_resource(candidate: ResourceCandidate, need: str, required_fields: list[dict[str, Any]]) -> float:
        q_tokens = token_set(need)
        text_parts = [
            candidate.resource_ref,
            candidate.display_name,
            candidate.description,
            candidate.kind,
            " ".join(field.name for field in candidate.fields),
            str(candidate.source.get("connector_name") or ""),
        ]
        haystack = token_set(" ".join(text_parts))
        score = float(len(q_tokens & haystack) * 2)
        if need.lower() in " ".join(text_parts).lower():
            score += 3
        for expected in required_fields:
            name = str(expected.get("name") or "").lower()
            if any(
                name == field.name.lower()
                or name in {item.lower() for item in field.synonyms}
                for field in candidate.fields
            ):
                score += 2
        if candidate.kind == "catalog_entity":
            score += 0.5
        if candidate.executable:
            score += 0.5
        return score

    @staticmethod
    def _apply_field_contracts(
        candidate: ResourceCandidate, required_fields: list[dict[str, Any]]
    ) -> ResourceCandidate:
        for expected in required_fields:
            name = str(expected.get("name") or "")
            matches = [
                field
                for field in candidate.fields
                if field.name.lower() == name.lower()
                or name.lower() in {item.lower() for item in field.synonyms}
            ]
            if not matches:
                candidate.missing_fields.append(name)
                continue
            actual = matches[0]
            expected_type = _normalize_type(str(expected.get("data_type") or expected.get("type") or ""))
            if expected_type and expected_type not in ("unknown", "json", "any"):
                if actual.data_type != expected_type and not (
                    actual.data_type == "integer" and expected_type == "number"
                ):
                    candidate.type_mismatches.append(
                        {"field": name, "expected": expected_type, "actual": actual.data_type}
                    )
            expected_unit = str(expected.get("unit") or "")
            if expected_unit and actual.unit and expected_unit != actual.unit:
                candidate.unit_mismatches.append(
                    {"field": name, "expected": expected_unit, "actual": actual.unit}
                )
            expected_currency = str(expected.get("currency") or "")
            if expected_currency and actual.currency and expected_currency != actual.currency:
                candidate.currency_mismatches.append(
                    {"field": name, "expected": expected_currency, "actual": actual.currency}
                )
        return candidate

    async def _authority_decisions(
        self, concepts: list[str], *, domain: str = "general"
    ) -> list[AuthorityDecision]:
        catalog = await self._ensure_catalog()
        now = datetime.now(timezone.utc)
        decisions: list[AuthorityDecision] = []
        for concept in concepts:
            rows = [
                item
                for item in catalog["authorities"]
                if item.get("concept") == concept
                and (domain == "general" or item.get("domain") in (domain, "general"))
                and _active(item, now)
            ]
            if not rows:
                decisions.append(
                    AuthorityDecision(
                        concept=concept,
                        status="missing",
                        reason="No hay fuente autoritativa registrada para el concepto.",
                    )
                )
                continue
            top_priority = max(int(item.get("priority") or 1) for item in rows)
            top = [item for item in rows if int(item.get("priority") or 1) == top_priority]
            unique = {
                (
                    item.get("connector_id") or "",
                    str(item.get("source_name") or "").lower(),
                )
                for item in top
            }
            if len(unique) > 1:
                decisions.append(
                    AuthorityDecision(
                        concept=concept,
                        status="ambiguous",
                        candidates=top,
                        reason=(
                            "Hay más de una fuente con la misma prioridad; no se elige "
                            "automáticamente."
                        ),
                    )
                )
            else:
                decisions.append(
                    AuthorityDecision(
                        concept=concept,
                        status="resolved",
                        chosen=top[0],
                        candidates=top,
                        reason="Fuente autoritativa única para el concepto.",
                    )
                )
        return decisions

    @staticmethod
    def _source_matches(candidate: ResourceCandidate, authority: dict[str, Any]) -> bool:
        connector = str(candidate.source.get("connector_id") or "")
        source_name = str(candidate.source.get("connector_name") or "").lower()
        wanted_connector = str(authority.get("connector_id") or "")
        wanted_name = str(authority.get("source_name") or "").lower()
        return bool(
            (connector and wanted_connector and connector == wanted_connector)
            or (wanted_name and source_name and wanted_name == source_name)
        )

    @staticmethod
    def _guidance_for_status(report: BindingReport) -> GuidedConfiguration | None:
        ref = report.capability_ref
        if report.availability == "AVAILABLE" and report.executable:
            return None
        if report.availability == "NEEDS_INSTALLATION":
            return GuidedConfiguration(
                code="CAPABILITY_NEEDS_INSTALLATION",
                requirement=f"capability:{ref}",
                title="Instalar integración",
                reason=f"La capacidad {ref} existe en el Marketplace pero no está instalada.",
                module="marketplace",
                marketplace_available=report.marketplace_available,
                steps=[
                    "Abrir Marketplace.",
                    "Instalar la integración del proveedor.",
                    "Configurar credenciales y conexión.",
                    "Probar la acción antes de publicar.",
                ],
                permissions=["integrations:install"],
                tests=["Verificar acción con datos de prueba", "Confirmar estado ejecutable"],
            )
        if report.availability == "NEEDS_CREDENTIALS":
            return GuidedConfiguration(
                code="CAPABILITY_NEEDS_CREDENTIALS",
                requirement=f"capability:{ref}",
                title="Configurar credenciales",
                reason="La integración está instalada pero faltan credenciales o binding.",
                module="integrations",
                marketplace_available=report.marketplace_available,
                steps=[
                    "Abrir Integraciones o Bindings.",
                    "Seleccionar el proveedor del tenant.",
                    "Guardar credenciales mediante el gestor de secretos.",
                    "Ejecutar una prueba de conexión.",
                ],
                permissions=["workflows:update", "workflow_secrets:manage"],
                tests=["Prueba de conexión", "Validar contrato de entrada/salida"],
            )
        if report.availability == "PERMISSION_DENIED":
            return GuidedConfiguration(
                code="CAPABILITY_PERMISSION_DENIED",
                requirement=f"permission:{ref}",
                title="Permiso insuficiente",
                reason="El actor no puede ejecutar esta capacidad.",
                module="rbac",
                steps=["Solicitar el permiso al administrador del tenant."],
                permissions=["admin:rbac"],
                tests=["Reintentar la validación con el permiso concedido"],
            )
        return GuidedConfiguration(
            code="CAPABILITY_NEEDS_CONFIGURATION",
            requirement=f"capability:{ref}",
            title="Configurar capacidad",
            reason="La capacidad no está ejecutable con la configuración actual.",
            module="integrations",
            marketplace_available=report.marketplace_available,
            steps=[
                "Revisar el binding del tenant.",
                "Configurar el proveedor y sus credenciales.",
                "Probar la capacidad con datos de prueba.",
            ],
            permissions=["workflows:update"],
            tests=["Validar contrato", "Probar ejecución"],
        )

    async def resolve_capability(
        self,
        capability_ref: str,
        *,
        required_fields: list[dict[str, Any]] | None = None,
    ) -> BindingReport:
        snapshot = await self._ensure_snapshot()
        descriptor = snapshot.index().get(capability_ref)
        if descriptor is None:
            return BindingReport(
                capability_ref=capability_ref,
                availability="UNAVAILABLE",
                reasons=["la capacidad no existe en el catálogo del tenant"],
            )
        availability = descriptor.availability
        binding = await resolve_binding_for_tenant(
            self.organization_id, capability_ref, workspace_id=self.workspace_id
        )
        binding_found = bool(binding.get("found"))
        binding_status = str(binding.get("status") or "")
        credential_present = bool(binding.get("credential_ref_present"))
        installed = bool(availability.installed)
        permitted = bool(availability.permitted)
        configured = bool(availability.configured)
        executable = bool(availability.executable)
        degraded = bool(
            descriptor.health_status
            and descriptor.health_status.lower() not in ("healthy", "ok", "available")
        )
        approval = bool(
            descriptor.metadata.get("requires_approval")
            or descriptor.risk_level == "critical"
        )
        status = availability.status
        if descriptor.source == "marketplace" and not installed:
            status = "NEEDS_INSTALLATION"
        elif not configured and installed:
            status = "NEEDS_CREDENTIALS" if not credential_present else "NEEDS_CONFIGURATION"
        elif not permitted:
            status = "PERMISSION_DENIED"
        elif degraded:
            status = "DEGRADED"
        elif executable and binding_found and binding_status not in ("", "active", "enabled"):
            status = "NEEDS_CONFIGURATION"
        report = BindingReport(
            capability_ref=capability_ref,
            version=descriptor.version,
            availability=status,
            executable=executable and binding_found,
            binding_found=binding_found,
            binding_id=str(binding.get("binding_id")) if binding.get("binding_id") else None,
            provider_kind=str(binding.get("provider_kind")) if binding.get("provider_kind") else None,
            binding_status=binding_status or None,
            credential_ref_present=credential_present,
            contract_version=int(descriptor.metadata.get("contract_version") or descriptor.version),
            contract_hash=descriptor.contract_hash,
            configured=configured,
            permission_denied=not permitted,
            approval_required=approval,
            degraded=degraded,
            reasons=list(availability.reasons),
            marketplace_available=descriptor.source == "marketplace",
            installed=installed,
        )
        if required_fields:
            input_schema = descriptor.input_schema or {}
            properties = input_schema.get("properties") if isinstance(input_schema, dict) else {}
            properties = properties if isinstance(properties, dict) else {}
            missing = [
                str(item.get("name"))
                for item in required_fields
                if str(item.get("name")) not in properties
            ]
            if missing and properties:
                report.availability = "INCOMPATIBLE"
                report.reasons.append("inputs incompatibles: " + ", ".join(missing[:5]))
        return report

    async def resolve_need(
        self,
        need: str,
        *,
        required_fields: list[dict[str, Any]] | None = None,
        concepts: list[str] | None = None,
        domain: str = "general",
        kinds: list[str] | None = None,
        capability_refs: list[str] | None = None,
        limit: int = 10,
    ) -> ResolutionReport:
        snapshot = await self._ensure_snapshot()
        required = [
            {"name": item} if isinstance(item, str) else dict(item)
            for item in (required_fields or [])
        ]
        requested_kinds = {str(item).lower() for item in (kinds or [])}
        non_resource_kinds = {"agent", "agents", "capability", "capabilities", "integration", "marketplace"}
        resource_only_request = bool(requested_kinds) and requested_kinds <= non_resource_kinds
        catalog_candidates = await self._catalog_candidates()
        # Una entidad aprobada de Mapping Studio representa su tabla: no se
        # ofrecen ambas como si fueran fuentes distintas.
        entity_tables = {
            str(item.metadata.get("mapped_table_id"))
            for item in catalog_candidates
            if item.kind == "catalog_entity"
            and item.metadata.get("mapped_table_id")
            and item.fields
        }
        catalog_candidates = [
            item
            for item in catalog_candidates
            if not (
                item.kind == "catalog_table"
                and str(item.metadata.get("catalog_table_id")) in entity_tables
            )
        ]
        resource_candidates: list[ResourceCandidate] = []
        for candidate in catalog_candidates:
            if requested_kinds and not any(
                kind in candidate.kind
                or kind in candidate.resource_ref
                for kind in requested_kinds
            ):
                continue
            resource_candidates.append(self._apply_field_contracts(candidate, required))

        # Knowledge OS / conectores / managed DB ya están en el snapshot canónico.
        for resource in snapshot.resources:
            if resource.kind.startswith("catalog."):
                continue
            if requested_kinds and not any(
                kind in resource.kind or kind in resource.resource_ref
                for kind in requested_kinds
            ):
                continue
            schema = resource.data_schema if isinstance(resource.data_schema, dict) else {}
            properties = schema.get("properties") if isinstance(schema, dict) else {}
            fields = []
            for name, prop in (properties or {}).items():
                raw_type = prop.get("type") if isinstance(prop, dict) else "unknown"
                fields.append(
                    ResourceField(
                        name=str(name),
                        data_type=_normalize_type(str(raw_type)),
                    )
                )
            candidate = ResourceCandidate(
                resource_ref=resource.resource_ref,
                kind=resource.kind,
                resource_class=(
                    "knowledge"
                    if resource.kind == "knowledge_base"
                    else "source"
                    if resource.kind.startswith("connector")
                    else "data"
                ),
                display_name=resource.display_name,
                description=resource.description,
                status=resource.status,
                source=dict(resource.metadata or {}),
                fields=fields,
                schema_data=schema,
                schema_source=resource.schema_source,
                contract_hash=resource.contract_hash,
                metadata=dict(resource.metadata or {}),
                executable=resource.status in ("ready", "active", "available"),
                read_only=True,
            )
            resource_candidates.append(self._apply_field_contracts(candidate, required))

        for candidate in resource_candidates:
            candidate.score = round(self._score_resource(candidate, need, required), 2)
        resource_candidates.sort(key=lambda item: (-item.score, item.resource_ref))
        resource_candidates = resource_candidates[: max(1, min(limit, 20))]

        concept_names = list(dict.fromkeys(concepts or []))
        authority = await self._authority_decisions(concept_names, domain=domain)
        resolved_authority = {
            item.concept: item.chosen for item in authority if item.status == "resolved"
        }
        ambiguous_authority = {
            item.concept: item for item in authority if item.status == "ambiguous"
        }
        for candidate in resource_candidates:
            candidate.authority = [
                item for item in candidate.authority if _active(item, datetime.now(timezone.utc))
            ]
        compatible = [
            item
            for item in resource_candidates
            if item.executable
            and not item.missing_fields
            and not item.type_mismatches
            and not item.unit_mismatches
            and not item.currency_mismatches
        ]
        selected: ResourceCandidate | None = None
        ambiguities: list[dict[str, Any]] = []
        if resolved_authority:
            authoritative = [
                item
                for item in compatible
                if all(
                    self._source_matches(item, chosen)
                    for chosen in resolved_authority.values()
                    if chosen
                )
            ]
            if len(authoritative) == 1:
                selected = authoritative[0]
            elif len(authoritative) > 1:
                ambiguities.append(
                    {
                        "code": "RESOURCE_AUTHORITY_AMBIGUOUS",
                        "message": "Varias fuentes autoritativas coinciden con el recurso.",
                        "candidates": [item.resource_ref for item in authoritative],
                    }
                )
        if selected is None and len(compatible) == 1:
            selected = compatible[0]
        elif selected is None and len(compatible) > 1:
            classes = {item.resource_class for item in compatible}
            if len(classes) > 1:
                ambiguities.append(
                    {
                        "code": "RESOURCE_CLASS_AMBIGUOUS",
                        "message": (
                            "La necesidad coincide con fuentes de datos y conocimiento; "
                            "no se sustituye una consulta transaccional por RAG."
                        ),
                        "classes": sorted(classes),
                        "candidates": [item.resource_ref for item in compatible[:10]],
                    }
                )
            else:
                ambiguities.append(
                    {
                        "code": "RESOURCE_AMBIGUOUS",
                        "message": "Hay varios recursos compatibles; falta confirmación o autoridad.",
                        "candidates": [item.resource_ref for item in compatible[:10]],
                    }
                )

        capability_candidates: list[dict[str, Any]] = []
        scored_caps, _total = search_descriptors(
            snapshot.capabilities,
            need,
            limit=5,
            source=None,
        )
        for descriptor, score in scored_caps:
            if descriptor.source == "agent":
                continue
            capability_candidates.append(
                {
                    **descriptor.compact(),
                    "score": round(score, 2),
                    "resource_candidates": [
                        item.resource_ref
                        for item in resource_candidates[:3]
                        if item.kind.startswith("catalog")
                    ],
                }
            )
        agent_candidates = _agent_candidates(snapshot, need, limit=5)
        binding_refs = list(capability_refs or [])
        for item in capability_candidates[:3]:
            ref = str(item.get("capability_ref") or "")
            if ref and ref not in binding_refs:
                binding_refs.append(ref)
        bindings = [
            await self.resolve_capability(ref, required_fields=required)
            for ref in binding_refs[:8]
        ]

        unresolved: list[dict[str, Any]] = []
        if selected is None and not resource_only_request:
            unresolved.append(
                {
                    "code": "RESOURCE_NOT_RESOLVED",
                    "message": (
                        "No hay un único recurso compatible con la necesidad y los campos "
                        "requeridos."
                    ),
                    "required_fields": [str(item.get("name") or "") for item in required],
                    "candidates": [item.resource_ref for item in resource_candidates[:10]],
                }
            )
        for candidate in resource_candidates:
            if selected is None and candidate.missing_fields and not resource_only_request:
                unresolved.append(
                    {
                        "code": "RESOURCE_FIELD_MISSING",
                        "resource_ref": candidate.resource_ref,
                        "fields": candidate.missing_fields,
                    }
                )
        for concept, decision in ambiguous_authority.items():
            unresolved.append(
                {
                    "code": "RESOURCE_AUTHORITY_AMBIGUOUS",
                    "concept": concept,
                    "message": decision.reason,
                    "candidates": decision.candidates,
                }
            )
        if concept_names:
            for decision in authority:
                if decision.status == "missing":
                    unresolved.append(
                        {
                            "code": "RESOURCE_AUTHORITY_MISSING",
                            "concept": decision.concept,
                            "message": decision.reason,
                        }
                    )

        guidance: list[GuidedConfiguration] = []
        for item in bindings:
            planned = self._guidance_for_status(item)
            if planned is not None:
                guidance.append(planned)
        if selected is None and not resource_only_request:
            guidance.append(
                GuidedConfiguration(
                    code="RESOURCE_CATALOG_REQUIRED",
                    requirement="resource:catalog",
                    title="Conectar o mapear una fuente de datos",
                    reason="No se encontró un único recurso compatible en el catálogo del tenant.",
                    module="catalog",
                    steps=[
                        "Abrir Catálogo / Mapping Studio.",
                        "Conectar la fuente de datos o registrar la entidad.",
                        "Aprobar los campos y la autoridad de la fuente.",
                        "Repetir el descubrimiento desde el Architect.",
                    ],
                    permissions=["catalog:read", "catalog:write"],
                    tests=["Verificar tabla y columnas", "Verificar autoridad única"],
                )
            )
        for decision in authority:
            if decision.status == "missing":
                guidance.append(
                    GuidedConfiguration(
                        code="RESOURCE_AUTHORITY_MISSING",
                        requirement=f"authority:{decision.concept}",
                        title="Definir autoridad de la fuente",
                        reason=f"No hay autoridad registrada para «{decision.concept}».",
                        module="catalog",
                        steps=[
                            "Abrir Mapping Studio / Autoridad.",
                            f"Registrar la fuente autoritativa para «{decision.concept}».",
                        ],
                        permissions=["catalog:write"],
                        tests=["Confirmar prioridad única", "Repetir resolución"],
                    )
                )

        trace = {
            "snapshot_hash": snapshot.snapshot_hash,
            "catalog_sources": len((await self._ensure_catalog())["sources"]),
            "catalog_tables": len((await self._ensure_catalog())["tables"]),
            "catalog_entities": len((await self._ensure_catalog())["entities"]),
            "authority_records": len((await self._ensure_catalog())["authorities"]),
            "discovered_from": "tenant_catalog+knowledge_os+bindings+marketplace",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "read_only": True,
        }
        deduped_guidance: list[GuidedConfiguration] = []
        seen_guidance: set[tuple[str, str]] = set()
        for item in guidance:
            key = (item.code, item.requirement)
            if key in seen_guidance:
                continue
            seen_guidance.add(key)
            deduped_guidance.append(item)
        return ResolutionReport(
            need=need,
            resolved=(
                selected is not None
                or (
                    resource_only_request
                    and bool(agent_candidates or capability_candidates)
                )
            )
            and not ambiguities
            and not unresolved,
            selected=selected,
            candidates=resource_candidates,
            authority=authority,
            ambiguities=ambiguities,
            unresolved=unresolved,
            bindings=bindings,
            capability_candidates=capability_candidates,
            agent_candidates=agent_candidates,
            guided_configuration=deduped_guidance,
            trace=trace,
        )

    async def inspect_resource(self, resource_ref: str) -> dict[str, Any] | None:
        for candidate in await self._catalog_candidates():
            if candidate.resource_ref == resource_ref:
                return candidate.model_dump(mode="json")
        snapshot = await self._ensure_snapshot()
        for resource in snapshot.resources:
            if resource.resource_ref == resource_ref:
                return resource.model_dump(mode="json")
        return None


def _agent_candidates(
    snapshot: CapabilitySnapshot, need: str, *, limit: int = 5
) -> list[dict[str, Any]]:
    agents = [item for item in snapshot.capabilities if item.source == "agent"]
    scored, _total = search_descriptors(agents, need, limit=limit)
    out: list[dict[str, Any]] = []
    for descriptor, score in scored:
        out.append(
            {
                **descriptor.compact(),
                "score": round(score, 2),
                "agent_id": descriptor.metadata.get("agent_id"),
                "purpose": descriptor.metadata.get("purpose"),
                "tools": descriptor.metadata.get("tools") or [],
                "knowledge_base_ids": descriptor.metadata.get("knowledge_base_ids") or [],
                "budget": descriptor.metadata.get("budget"),
                "version": descriptor.metadata.get("version") or descriptor.version,
                "executable": descriptor.availability.executable,
                "availability": descriptor.availability.model_dump(mode="json"),
            }
        )
    return out


__all__ = [
    "AuthorityDecision",
    "BindingReport",
    "BusinessResourceResolver",
    "GuidedConfiguration",
    "REPORT_SCHEMA",
    "ResolutionReport",
    "ResourceCandidate",
    "ResourceField",
]

