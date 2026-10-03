# =============================================================================
# Semantic Reconstruction Layer — Database Source Adapter
# =============================================================================
# Una base de datos no se convierte en miles de frases. Se reconstruye como
# schema -> table -> column -> data type, PK/FK, constraints, relaciones,
# patrones de valores y metadata. El resultado alimenta al mismo Knowledge
# Compiler universal.
# =============================================================================
from __future__ import annotations

from typing import Any

from src.core.domain.knowledge_v2 import StructuredDocument

from ..contracts import (
    ElementKind,
    RawElement,
    RawExtraction,
    RawTable,
    SourceKind,
    SourceProvenance,
    element_uuid,
)
from .base import SourceAdapter


class DatabaseSourceAdapter(SourceAdapter):
    kind = SourceKind.DATABASE.value
    description = "Base de datos: schema, tabla, columna, PK/FK, constraints, patrones"

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
        schema = _database_schema(document)
        if not schema:
            extraction.warnings.append("database schema metadata unavailable")
            return extraction

        database = str(schema.get("database") or document.metadata.get("database") or "")
        position = 0

        def add(element: RawElement) -> None:
            nonlocal position
            position += 1
            extraction.elements.append(element)

        for schema_entry in schema.get("schemas") or ():
            schema_name = str(schema_entry.get("name") or "public")
            add(
                RawElement(
                    id=element_uuid(document.id, position, f"schema:{schema_name}"),
                    kind=ElementKind.SCHEMA.value,
                    text=schema_name,
                    order=position,
                    depth=0,
                    provenance=SourceProvenance(
                        source_kind=self.kind,
                        adapter=self.name,
                        source_id=document.source_id,
                        document_id=document.id,
                        document_title=document.title,
                        database=database or None,
                        schema=schema_name,
                        excerpt=schema_name,
                    ),
                    confidence=0.95,
                    attributes={"table_count": len(schema_entry.get("tables") or ())},
                )
            )
            for table in schema_entry.get("tables") or ():
                self._add_table(
                    document, extraction, add, database, schema_name, table
                )

        extraction.stats = {
            "schemas": len(schema.get("schemas") or ()),
            "tables": _count(schema, "tables"),
            "columns": _count(schema, "columns"),
            "elements": len(extraction.elements),
        }
        return extraction

    def _add_table(
        self,
        document: StructuredDocument,
        extraction: RawExtraction,
        add,
        database: str,
        schema_name: str,
        table: dict[str, Any],
    ) -> None:
        table_name = str(table.get("name") or table.get("table") or "table")
        reference = f"{schema_name}.{table_name}"
        columns = list(table.get("columns") or ())
        primary_keys = [
            str(column.get("name"))
            for column in columns
            if column.get("primary_key") or column.get("is_primary_key")
        ]
        foreign_keys = [
            {
                "column": str(column.get("name")),
                "references_table": str(
                    column.get("references_table")
                    or (column.get("references") or {}).get("table")
                    or column.get("fk_table")
                    or ""
                ),
                "references_column": str(
                    column.get("references_column")
                    or (column.get("references") or {}).get("column")
                    or column.get("fk_column")
                    or ""
                ),
            }
            for column in columns
            if column.get("foreign_key")
            or column.get("is_foreign_key")
            or column.get("references")
            or column.get("fk_table")
        ]
        table_id = element_uuid(document.id, len(extraction.elements), f"table:{reference}")
        add(
            RawElement(
                id=table_id,
                kind=ElementKind.TABLE.value,
                text=reference,
                order=len(extraction.elements),
                depth=1,
                provenance=SourceProvenance(
                    source_kind=SourceKind.DATABASE.value,
                    adapter=self.name,
                    source_id=document.source_id,
                    document_id=document.id,
                    document_title=document.title,
                    database=database or None,
                    schema=schema_name,
                    table=reference,
                    excerpt=str(table.get("description") or reference),
                ),
                confidence=0.95,
                attributes={
                    "description": table.get("description"),
                    "row_count": table.get("row_count"),
                    "primary_key": primary_keys,
                    "foreign_keys": foreign_keys,
                    "constraints": list(table.get("constraints") or ())[:50],
                    "indexes": list(table.get("indexes") or ())[:50],
                },
            )
        )
        extraction.tables.append(
            RawTable(
                id=str(table_id),
                name=reference,
                headers=tuple(str(column.get("name")) for column in columns),
                rows=(),
                provenance=SourceProvenance(
                    source_kind=SourceKind.DATABASE.value,
                    adapter=self.name,
                    source_id=document.source_id,
                    document_id=document.id,
                    document_title=document.title,
                    database=database or None,
                    schema=schema_name,
                    table=reference,
                ),
                confidence=0.95,
                metadata={
                    "database": database,
                    "schema": schema_name,
                    "primary_key": primary_keys,
                    "foreign_keys": foreign_keys,
                    "row_count": table.get("row_count"),
                    "sample_values": table.get("sample_values") or {},
                },
            )
        )
        for column in columns:
            name = str(column.get("name") or "")
            if not name:
                continue
            add(
                RawElement(
                    id=element_uuid(document.id, len(extraction.elements), f"column:{reference}.{name}"),
                    kind=ElementKind.FIELD.value,
                    text=name,
                    order=len(extraction.elements),
                    depth=2,
                    parent_id=table_id,
                    provenance=SourceProvenance(
                        source_kind=SourceKind.DATABASE.value,
                        adapter=self.name,
                        source_id=document.source_id,
                        document_id=document.id,
                        document_title=document.title,
                        database=database or None,
                        schema=schema_name,
                        table=reference,
                        column=name,
                        excerpt=str(column.get("description") or name),
                    ),
                    confidence=0.95,
                    attributes={
                        "data_type": column.get("data_type") or column.get("type"),
                        "nullable": bool(column.get("nullable", column.get("is_nullable", True))),
                        "primary_key": bool(
                            column.get("primary_key") or column.get("is_primary_key")
                        ),
                        "foreign_key": bool(
                            column.get("foreign_key")
                            or column.get("is_foreign_key")
                            or column.get("references")
                            or column.get("fk_table")
                        ),
                        "references_table": column.get("references_table")
                        or (column.get("references") or {}).get("table")
                        or column.get("fk_table"),
                        "references_column": column.get("references_column")
                        or (column.get("references") or {}).get("column")
                        or column.get("fk_column"),
                        "description": column.get("description"),
                        "sample_values": list(column.get("sample_values") or ())[:5],
                        "unique": bool(column.get("unique", False)),
                    },
                )
            )


def _database_schema(document: StructuredDocument) -> dict[str, Any] | None:
    for key in ("database_schema", "schema", "database"):
        value = document.metadata.get(key)
        if isinstance(value, dict) and ("schemas" in value or "tables" in value):
            if "schemas" not in value:
                value = {"schemas": [{"name": value.get("schema_name", "public"), "tables": value.get("tables", [])}]}
            return value
    tables = document.metadata.get("tables")
    if isinstance(tables, list) and tables:
        return {"schemas": [{"name": "public", "tables": tables}]}
    return None


def _count(schema: dict[str, Any], child: str) -> int:
    total = 0
    for schema_entry in schema.get("schemas") or ():
        for table in schema_entry.get("tables") or ():
            if child == "tables":
                total += 1
            elif child == "columns":
                total += len(table.get("columns") or ())
    return total


__all__ = ["DatabaseSourceAdapter"]
