# =============================================================================
# Rule Backfill — documentos indexados antes del Semantic Rule Compiler
# =============================================================================
# El índice de reglas no existía cuando se ingestaron documentos viejos: sus
# chunks no traen `canonical_rule_ids` y el Rule Lane no tiene representación
# recuperable. Este backfill:
#
#   1. DETECTA documentos sin reglas indexadas (idempotente);
#   2. RECOMPILA reglas desde el StructuredDocument / semantic units existentes
#      (no re-parsea bytes crudos ni exige al usuario borrar la KB);
#   3. PERSISTE CanonicalRules (misma autoridad de siempre);
#   4. AGREGA canonical_rule_ids / canonical_rule_objects al payload del índice
#      SIN regenerar embeddings;
#   5. REGISTRA cuántas reglas nuevas/actualizadas encontró.
#
# Reingesta completa sigue disponible (knowledge_reprocess) para cuando cambia
# el parser; este backfill es para el cambio de compilador de reglas.
# =============================================================================
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from src.core.domain.knowledge_v2 import (
    DocumentSection,
    DocumentTable,
    StructuredBlock,
    StructuredBlockKind,
    StructuredContentType,
    StructuredDocument,
)
from src.infrastructure.observability.logging_config import get_logger
from src.knowledge.rule_compiler.index import RULE_INDEX_VERSION

logger = get_logger(__name__)

RULE_BACKFILL_VERSION = "rule-backfill-1"


@dataclass(kw_only=True)
class RuleBackfillReport:
    documents_scanned: int = 0
    documents_needing_backfill: int = 0
    documents_backfilled: int = 0
    documents_skipped: int = 0
    rules_persisted: int = 0
    rules_created: int = 0
    rules_reinforced: int = 0
    canonical_rules: int = 0
    payloads_updated: int = 0
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False
    version: str = RULE_BACKFILL_VERSION

    def to_public_dict(self) -> dict:
        return {
            "version": self.version,
            "dry_run": self.dry_run,
            "documents_scanned": self.documents_scanned,
            "documents_needing_backfill": self.documents_needing_backfill,
            "documents_backfilled": self.documents_backfilled,
            "documents_skipped": self.documents_skipped,
            "rules_persisted": self.rules_persisted,
            "rules_created": self.rules_created,
            "rules_reinforced": self.rules_reinforced,
            "canonical_rules": self.canonical_rules,
            "payloads_updated": self.payloads_updated,
            "errors": self.errors[:8],
        }


def document_needs_rule_backfill(
    metadata: dict | None,
    *,
    rules_indexed: bool = False,
    rule_index_version: str = RULE_INDEX_VERSION,
) -> bool:
    """¿El documento fue indexado antes del Semantic Rule Compiler?

    Idempotente: un documento con la versión de índice vigente (o con reglas ya
    indexadas en knowledge_canonical_objects) NO se reprocesa.
    """
    data = metadata or {}
    if str(data.get("rule_index_version") or "") == rule_index_version:
        return False
    if str(data.get("rule_backfill_version") or "") == RULE_BACKFILL_VERSION:
        return False
    return not rules_indexed


async def find_backfill_candidates(
    organization_id: UUID,
    *,
    document_id: UUID | None = None,
    source_id: UUID | None = None,
    knowledge_base_id: UUID | None = None,
    limit: int = 500,
) -> list[dict]:
    """Documentos del tenant que necesitan backfill (scoped, sin cross-tenant)."""
    from sqlalchemy import text as sql_text

    from src.infrastructure.postgres.session import get_async_session

    where = [
        "sd.organization_id = :org",
        "NOT (COALESCE(sd.metadata->>'rule_index_version', '') = :version)",
        "NOT (COALESCE(sd.metadata->>'rule_backfill_version', '') = :backfill_version)",
        "NOT EXISTS ("
        "  SELECT 1 FROM knowledge_canonical_objects k"
        "  WHERE k.organization_id = sd.organization_id"
        "    AND k.kind = 'business_rule'"
        "    AND k.metadata->>'document_id' = sd.id::text"
        "    AND k.metadata->>'retrieval_index_version' = :version"
        ")",
    ]
    params: dict = {
        "org": organization_id,
        "version": RULE_INDEX_VERSION,
        "backfill_version": RULE_BACKFILL_VERSION,
        "limit": max(1, int(limit)),
    }
    if document_id is not None:
        where.append("sd.id = :document_id")
        params["document_id"] = document_id
    if source_id is not None:
        where.append("sd.source_id = :source_id")
        params["source_id"] = source_id
    if knowledge_base_id is not None:
        where.append("sd.knowledge_base_id = :kb_id")
        params["kb_id"] = knowledge_base_id

    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                sql_text(
                    "SELECT sd.id, sd.organization_id, sd.workspace_id, sd.source_id, "
                    "sd.title, sd.metadata "
                    "FROM structured_documents sd WHERE "
                    + " AND ".join(where)
                    + " ORDER BY sd.updated_at ASC LIMIT :limit"
                ),
                params,
            )
        ).all()
    finally:
        await session.close()
    return [
        {
            "id": row.id,
            "organization_id": row.organization_id,
            "workspace_id": row.workspace_id,
            "source_id": row.source_id,
            "title": row.title,
            "metadata": row.metadata if isinstance(row.metadata, dict) else {},
        }
        for row in rows
    ]


async def load_structured_document(
    organization_id: UUID, document_id: UUID
) -> StructuredDocument | None:
    """Reconstruye el StructuredDocument persistido (blocks + sections + tables).

    No toca bytes crudos: usa el modelo estructurado ya guardado, que es la
    entrada canónica del Knowledge Compiler.
    """
    from sqlalchemy import text as sql_text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        doc_row = (
            await session.execute(
                sql_text(
                    "SELECT id, organization_id, workspace_id, source_id, external_id, "
                    "title, content_hash, mime_type, document_type, language, metadata "
                    "FROM structured_documents "
                    "WHERE id = :did AND organization_id = :oid"
                ),
                {"did": document_id, "oid": organization_id},
            )
        ).first()
        if doc_row is None:
            return None
        block_rows = (
            await session.execute(
                sql_text(
                    "SELECT id, node_type, kind, content_type, text, order_index, "
                    "page_number, section_path, parent_id, depth, heading, page_start, "
                    "page_end, char_start, char_end, bbox, language, token_count, "
                    "content_hash, metadata "
                    "FROM structured_blocks "
                    "WHERE document_id = :did AND organization_id = :oid "
                    "ORDER BY order_index, id"
                ),
                {"did": document_id, "oid": organization_id},
            )
        ).all()
    finally:
        await session.close()

    blocks: list[StructuredBlock] = []
    sections: list[DocumentSection] = []
    tables: list[DocumentTable] = []
    for row in block_rows:
        node_type = str(getattr(row, "node_type", "") or "")
        if node_type == "block":
            blocks.append(_block_from_row(row, organization_id))
        elif node_type == "section":
            sections.append(_section_from_row(row, organization_id, document_id))
        elif node_type == "table":
            tables.append(_table_from_row(row, organization_id, document_id))

    return StructuredDocument(
        id=doc_row.id,
        organization_id=doc_row.organization_id,
        workspace_id=doc_row.workspace_id,
        source_id=doc_row.source_id,
        external_id=str(doc_row.external_id or ""),
        title=str(doc_row.title or ""),
        content_hash=str(doc_row.content_hash or ""),
        mime_type=doc_row.mime_type,
        document_type=doc_row.document_type,
        language=doc_row.language,
        blocks=tuple(blocks),
        sections=tuple(sections),
        tables=tuple(tables),
        metadata=doc_row.metadata if isinstance(doc_row.metadata, dict) else {},
    )


def _block_from_row(row, organization_id: UUID) -> StructuredBlock:
    metadata = row.metadata if isinstance(row.metadata, dict) else {}
    kind = _parse_enum(StructuredBlockKind, row.kind, StructuredBlockKind.PARAGRAPH)
    content_type = _parse_enum(
        StructuredContentType, row.content_type, StructuredContentType.TEXT
    )
    return StructuredBlock(
        id=row.id,
        kind=kind,
        text=str(row.text or ""),
        order=int(row.order_index or 0),
        page=row.page_number,
        heading_path=tuple(str(item) for item in (row.section_path or ())),
        content_type=content_type,
        language=row.language,
        token_count=int(row.token_count or 0),
        content_hash=row.content_hash,
        metadata=metadata,
    )


def _section_from_row(row, organization_id: UUID, document_id: UUID) -> DocumentSection:
    metadata = row.metadata if isinstance(row.metadata, dict) else {}
    return DocumentSection(
        id=row.id,
        document_id=document_id,
        organization_id=organization_id,
        section_path=tuple(str(item) for item in (row.section_path or ())),
        heading=str(row.heading or ""),
        depth=int(row.depth or 0),
        parent_id=row.parent_id,
        order=int(row.order_index or 0),
        page_start=row.page_start,
        page_end=row.page_end,
        text=str(row.text or ""),
        language=row.language,
        token_count=int(row.token_count or 0),
        content_hash=row.content_hash,
        metadata=metadata,
    )


def _table_from_row(row, organization_id: UUID, document_id: UUID) -> DocumentTable:
    metadata = row.metadata if isinstance(row.metadata, dict) else {}
    headers = tuple(str(item) for item in (metadata.get("headers") or ()))
    rows = tuple(
        tuple(str(cell) for cell in row_values)
        for row_values in (metadata.get("rows") or ())
    )
    return DocumentTable(
        id=row.id,
        document_id=document_id,
        organization_id=organization_id,
        caption=str(row.heading or ""),
        headers=headers,
        rows=rows,
        page=row.page_number,
        token_count=int(row.token_count or 0),
        content_hash=row.content_hash,
        metadata=metadata,
    )


def _parse_enum(enum_cls, value, default):
    try:
        return enum_cls(str(value))
    except (ValueError, TypeError):
        return default


async def _mark_document_backfilled(
    organization_id: UUID, document_id: UUID
) -> None:
    """Marca idempotencia en el documento estructurado (no toca embeddings)."""
    from sqlalchemy import text as sql_text

    from src.infrastructure.postgres.session import get_async_session

    marker = {
        "rule_index_version": RULE_INDEX_VERSION,
        "rule_backfill_version": RULE_BACKFILL_VERSION,
        "rule_backfilled_at": datetime.now(timezone.utc).isoformat(),
    }
    session = await get_async_session()
    try:
        await session.execute(
            sql_text(
                "UPDATE structured_documents "
                "SET metadata = metadata || CAST(:marker AS jsonb) "
                "WHERE id = :did AND organization_id = :oid"
            ),
            {
                "marker": json.dumps(marker),
                "did": document_id,
                "oid": organization_id,
            },
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def backfill_documents(
    organization_id: UUID,
    *,
    document_id: UUID | None = None,
    source_id: UUID | None = None,
    knowledge_base_id: UUID | None = None,
    limit: int = 500,
    dry_run: bool = False,
    compiler=None,
    vector_store=None,
) -> RuleBackfillReport:
    """Backfill idempotente por tenant / KB / fuente / documento.

    `compiler` y `vector_store` son inyectables para tests; en producción se
    usan el KnowledgeCompiler y el vector store reales.
    """
    report = RuleBackfillReport(dry_run=dry_run)
    candidates = await find_backfill_candidates(
        organization_id,
        document_id=document_id,
        source_id=source_id,
        knowledge_base_id=knowledge_base_id,
        limit=limit,
    )
    report.documents_scanned = len(candidates)
    report.documents_needing_backfill = len(candidates)
    if dry_run:
        return report

    if compiler is None:
        from src.knowledge.compiler.pipeline import KnowledgeCompiler

        compiler = KnowledgeCompiler()
    if vector_store is None:
        try:
            from src.api.deps import get_vector_store

            vector_store = get_vector_store()
        except Exception as exc:  # noqa: BLE001 — sin store no se actualiza payload
            logger.warning("Rule backfill: vector store unavailable", error=str(exc)[:160])
            vector_store = None

    for candidate in candidates:
        doc_uuid = candidate["id"]
        try:
            document = await load_structured_document(organization_id, doc_uuid)
            if document is None:
                report.documents_skipped += 1
                continue
            result = await compiler.compile_document(
                document,
                workspace_id=candidate.get("workspace_id"),
                persist=True,
            )
            persisted = getattr(result, "persisted", {}) or {}
            report.rules_persisted += int(persisted.get("rules") or 0)
            report.rules_created += int(persisted.get("rules_created") or 0)
            report.rules_reinforced += int(persisted.get("rules_reinforced") or 0)
            report.canonical_rules += int(persisted.get("canonical_rules") or 0)

            rule_ids = persisted.get("canonical_rule_ids") or {}
            rule_objects = persisted.get("canonical_rule_objects") or {}
            rule_fingerprints = persisted.get("canonical_rule_fingerprints") or {}
            if vector_store is not None and (rule_ids or rule_objects):
                updater = getattr(vector_store, "update_document_payload", None)
                if callable(updater):
                    await updater(
                        organization_id,
                        doc_uuid,
                        {
                            "compiled_status": str(
                                persisted.get("status") or "completed"
                            ),
                            "canonical_rule_ids": dict(list(rule_ids.items())[:64]),
                            "canonical_rule_objects": dict(
                                list(rule_objects.items())[:64]
                            ),
                            "canonical_rule_fingerprints": dict(
                                list(rule_fingerprints.items())[:64]
                            ),
                            "rule_index_version": str(
                                persisted.get("rule_index_version")
                                or RULE_INDEX_VERSION
                            ),
                            "compiled_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    report.payloads_updated += 1
            await _mark_document_backfilled(organization_id, doc_uuid)
            report.documents_backfilled += 1
        except Exception as exc:  # noqa: BLE001 — un documento no frena el backfill
            report.errors.append(f"{doc_uuid}: {str(exc)[:160]}")
            logger.warning(
                "Rule backfill document failed",
                document_id=str(doc_uuid),
                error=str(exc)[:200],
            )
    return report


__all__ = [
    "RULE_BACKFILL_VERSION",
    "RuleBackfillReport",
    "backfill_documents",
    "document_needs_rule_backfill",
    "find_backfill_candidates",
    "load_structured_document",
]
