# =============================================================================
# Company Discovery — loaders Postgres (acceso a las señales ya existentes)
# =============================================================================
# Solo lectura, tenant-scoped, siempre con LIMIT. Devuelven filas como dict
# para que los extractores sean puros y testeables sin base de datos.
# Si una señal no existe (tabla ausente en una versión vieja), el loader
# devuelve vacío: el descubrimiento es fail-soft, nunca rompe el runtime.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)


async def _rows(sql: str, params: dict) -> list[dict]:
    session = await get_async_session()
    try:
        result = await session.execute(text(sql), params)
        return [dict(row._mapping) for row in result.fetchall()]
    except Exception as exc:  # noqa: BLE001 - señal ausente: descubrir vacío
        logger.warning("company discovery loader failed", error=str(exc)[:200])
        return []
    finally:
        await session.close()


async def load_catalog_tables(
    organization_id: UUID, limit: int = 200
) -> list[dict]:
    return await _rows(
        """
        SELECT t.id, t.source_id, t.schema_name, t.table_name, t.table_comment,
               s.name AS source_name, s.engine, s.connector_id
        FROM catalog_tables t
        LEFT JOIN catalog_sources s ON s.id = t.source_id
        WHERE t.organization_id = :oid AND t.removed_at IS NULL
        ORDER BY t.schema_name, t.table_name
        LIMIT :limit
        """,
        {"oid": str(organization_id), "limit": limit},
    )


async def load_catalog_columns(
    organization_id: UUID, limit: int = 1000
) -> list[dict]:
    return await _rows(
        """
        SELECT c.id, c.table_id, c.column_name, c.data_type, c.is_primary_key,
               c.nullable, c.column_comment
        FROM catalog_columns c
        WHERE c.organization_id = :oid
        ORDER BY c.table_id, c.ordinal_position
        LIMIT :limit
        """,
        {"oid": str(organization_id), "limit": limit},
    )


async def load_catalog_entities(organization_id: UUID, limit: int = 200) -> list[dict]:
    return await _rows(
        """
        SELECT e.id, e.name, e.display_name, e.description, e.provenance,
               e.confidence, e.mapped_table_id, e.status
        FROM catalog_entities e
        WHERE e.organization_id = :oid AND e.status <> 'deprecated'
        ORDER BY e.name
        LIMIT :limit
        """,
        {"oid": str(organization_id), "limit": limit},
    )


async def load_catalog_fields(organization_id: UUID, limit: int = 500) -> list[dict]:
    return await _rows(
        """
        SELECT f.id, f.entity_id, f.name, f.description, f.provenance,
               f.confidence, f.mapped_column_id, f.synonyms, f.status,
               f.mapping_type, f.role
        FROM catalog_fields f
        WHERE f.organization_id = :oid AND f.status <> 'rejected'
        ORDER BY f.name
        LIMIT :limit
        """,
        {"oid": str(organization_id), "limit": limit},
    )


async def load_catalog_enum_values(
    organization_id: UUID, limit: int = 500
) -> list[dict]:
    return await _rows(
        """
        SELECT ev.id, ev.column_id, ev.value, ev.documented_meaning,
               ev.occurrence_count, ev.status
        FROM catalog_enum_values ev
        WHERE ev.organization_id = :oid
        ORDER BY ev.occurrence_count DESC
        LIMIT :limit
        """,
        {"oid": str(organization_id), "limit": limit},
    )


async def load_catalog_column_identifiers(
    organization_id: UUID, column_ids: list[UUID]
) -> list[dict]:
    if not column_ids:
        return []
    return await _rows(
        """
        SELECT c.id, c.column_name, t.schema_name, t.table_name
        FROM catalog_columns c
        JOIN catalog_tables t ON t.id = c.table_id AND t.organization_id = c.organization_id
        WHERE c.organization_id = :oid AND c.id = ANY(:ids)
        """,
        {"oid": str(organization_id), "ids": [str(item) for item in column_ids]},
    )


async def load_tabular_tables(organization_id: UUID, limit: int = 200) -> list[dict]:
    return await _rows(
        """
        SELECT t.id, t.name, t.title, t.workbook_id, w.filename
        FROM tabular_tables t
        LEFT JOIN tabular_workbooks w
          ON w.id = t.workbook_id AND w.organization_id = t.organization_id
        WHERE t.organization_id = :oid
        ORDER BY w.filename, t.name
        LIMIT :limit
        """,
        {"oid": str(organization_id), "limit": limit},
    )


async def load_tabular_columns(organization_id: UUID, limit: int = 1000) -> list[dict]:
    return await _rows(
        """
        SELECT c.id, c.table_id, c.original_name, c.normalized_name,
               c.inferred_type, c.semantic_type, c.aliases
        FROM tabular_columns c
        WHERE c.organization_id = :oid
        ORDER BY c.table_id, c.physical_index
        LIMIT :limit
        """,
        {"oid": str(organization_id), "limit": limit},
    )


async def load_workflows(organization_id: UUID, limit: int = 100) -> list[dict]:
    return await _rows(
        """
        SELECT id, name, description, trigger_type, trigger_config, status,
               graph, steps, workspace_id
        FROM workflows
        WHERE organization_id = :oid
        ORDER BY created_at DESC
        LIMIT :limit
        """,
        {"oid": str(organization_id), "limit": limit},
    )


async def load_agents(organization_id: UUID, limit: int = 100) -> list[dict]:
    return await _rows(
        """
        SELECT id, name, description, tools, config_json, is_active
        FROM agents
        WHERE organization_id = :oid AND is_active = TRUE
        ORDER BY created_at DESC
        LIMIT :limit
        """,
        {"oid": str(organization_id), "limit": limit},
    )


async def load_successful_sql(organization_id: UUID, limit: int = 200) -> list[dict]:
    """SQL exitoso: señal de uso real (question + SQL + tablas + actor)."""
    return await _rows(
        """
        SELECT id, question, generated_sql, tables, user_id, status, created_at
        FROM sql_audit_logs
        WHERE organization_id = :oid AND status = 'success'
        ORDER BY created_at DESC
        LIMIT :limit
        """,
        {"oid": str(organization_id), "limit": limit},
    )


async def load_verified_queries(organization_id: UUID, limit: int = 100) -> list[dict]:
    return await _rows(
        """
        SELECT id, canonical_question, question_variants, verified_sql,
               table_dependencies, column_dependencies, concept_dependencies,
               status
        FROM verified_queries
        WHERE organization_id = :oid AND status = 'VERIFIED'
        ORDER BY last_verified_at DESC NULLS LAST
        LIMIT :limit
        """,
        {"oid": str(organization_id), "limit": limit},
    )


async def load_workflow_run_steps(
    organization_id: UUID, limit: int = 500
) -> list[dict]:
    """Secuencia observada de pasos: base de procesos OBSERVED (§9/§10).

    workflow_run_steps no tiene organization_id: el scoping de tenant entra
    por el join con workflow_runs.
    """
    return await _rows(
        """
        SELECT s.run_id, s.step_index, s.node_id, s.node_type, s.status,
               r.workflow_id, r.status AS run_status, w.name AS workflow_name
        FROM workflow_run_steps s
        JOIN workflow_runs r ON r.id = s.run_id
        LEFT JOIN workflows w ON w.id = r.workflow_id
        WHERE r.organization_id = :oid AND s.node_id IS NOT NULL
        ORDER BY s.run_id, s.step_index
        LIMIT :limit
        """,
        {"oid": str(organization_id), "limit": limit},
    )


async def load_structured_documents(
    organization_id: UUID, limit: int = 100
) -> list[dict]:
    return await _rows(
        """
        SELECT id, title, document_type, source_id, mime_type, page_count,
               metadata, created_at
        FROM structured_documents
        WHERE organization_id = :oid
        ORDER BY created_at DESC
        LIMIT :limit
        """,
        {"oid": str(organization_id), "limit": limit},
    )


async def load_document_blocks(
    organization_id: UUID, document_ids: list[UUID], limit: int = 800
) -> list[dict]:
    if not document_ids:
        return []
    return await _rows(
        """
        SELECT id, document_id, node_type, kind, text, order_index,
               section_path, page_number
        FROM structured_blocks
        WHERE organization_id = :oid AND document_id = ANY(:ids)
          AND node_type IN ('block', 'section', 'table')
        ORDER BY document_id, order_index
        LIMIT :limit
        """,
        {"oid": str(organization_id), "ids": [str(d) for d in document_ids], "limit": limit},
    )


async def load_document_versions(
    organization_id: UUID, limit: int = 200
) -> list[dict]:
    return await _rows(
        """
        SELECT v.id, v.document_id, v.version, v.change_kind,
               v.previous_version_id, v.created_at, d.title
        FROM structured_document_versions v
        LEFT JOIN structured_documents d
          ON d.id = v.document_id AND d.organization_id = v.organization_id
        WHERE v.organization_id = :oid
        ORDER BY v.document_id, v.version
        LIMIT :limit
        """,
        {"oid": str(organization_id), "limit": limit},
    )


async def load_claim_conflicts(organization_id: UUID, limit: int = 100) -> list[dict]:
    """Claims con mismo sujeto+predicado y objeto distinto: conflicto real."""
    return await _rows(
        """
        SELECT normalized_subject, normalized_predicate,
               array_agg(DISTINCT normalized_object) AS objects,
               COUNT(*) AS claims,
               array_agg(DISTINCT id) AS claim_ids
        FROM claim_ledger
        WHERE organization_id = :oid
          AND normalized_object IS NOT NULL
        GROUP BY normalized_subject, normalized_predicate
        HAVING COUNT(DISTINCT normalized_object) > 1
        ORDER BY COUNT(*) DESC
        LIMIT :limit
        """,
        {"oid": str(organization_id), "limit": limit},
    )


async def load_authoritative_sql_signals(
    organization_id: UUID, limit: int = 100
) -> list[dict]:
    """Candidatos a fuente de verdad: columnas usadas en ejecuciones exitosas."""
    return await _rows(
        """
        SELECT (c->>'concept') AS concept,
               (c->>'column') AS column_name,
               MIN((c->>'table')) AS table_name,
               COUNT(DISTINCT q.id) AS runs,
               COUNT(DISTINCT q.user_id) AS actors
        FROM verified_queries q
        CROSS JOIN LATERAL jsonb_array_elements(q.column_dependencies) AS c
        WHERE q.organization_id = :oid AND q.status = 'VERIFIED'
        GROUP BY 1, 2
        HAVING COUNT(DISTINCT q.id) >= 2
        ORDER BY COUNT(DISTINCT q.id) DESC
        LIMIT :limit
        """,
        {"oid": str(organization_id), "limit": limit},
    )


async def organizations_due_for_discovery(limit: int = 50) -> list[UUID]:
    """Organizaciones con actividad reciente que justifica descubrir."""
    rows = await _rows(
        """
        SELECT organization_id FROM (
            SELECT organization_id FROM company_entities
            UNION
            SELECT organization_id FROM company_discovery_candidates
            UNION
            SELECT organization_id FROM catalog_sources
            UNION
            SELECT organization_id FROM structured_documents
        ) AS active
        LIMIT :limit
        """,
        {"limit": limit},
    )
    return [row["organization_id"] for row in rows]
