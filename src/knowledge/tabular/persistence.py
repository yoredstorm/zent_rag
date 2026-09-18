# =============================================================================
# Tabular ingestion — servicio de persistencia incremental
# =============================================================================
# Orquesta: fingerprint persistido → diff (lógica knowledge) → upsert scoped.
# El repositorio nunca calcula fingerprints; solo lee estado y aplica el diff.
#
# Recuperación: si la indexación semántica se interrumpió (worker caído,
# rebuild) el fingerprint NO tiene representations.semantic. En ese caso el
# diff se marca UNCHANGED pero con `needs_semantic_index=True` para que el
# engine vuelva a indexar aunque el archivo no haya cambiado.
#
# Política de chunking: `chunking_policy` (hash de la config del TabularChunker)
# se persiste junto al workbook. Si cambia (tamaño de grupos, columnas clave,
# caps...), los puntos existentes quedan obsoletos y el engine purga y
# re-indexa el documento completo aunque el contenido sea idéntico.
# =============================================================================
from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from src.core.domain.tabular import (
    TabularChangeKind,
    TabularWorkbook,
    WorkbookDiff,
)
from src.core.ports.tabular import TabularRepository
from src.knowledge.tabular.fingerprint import compute_workbook_diff


async def persist_tabular_workbook(
    repository: TabularRepository,
    workbook: TabularWorkbook,
    *,
    knowledge_base_id: UUID | None = None,
    chunking_policy: str = "",
) -> WorkbookDiff:
    """Persiste el workbook aplicando solo los cambios detectados."""
    fingerprint = await repository.get_fingerprint(
        workbook.organization_id, workbook.id
    )
    diff = compute_workbook_diff(workbook, fingerprint)
    stored_representations = dict(fingerprint.representations) if fingerprint else {}
    stored_policy = str(fingerprint.chunking_policy) if fingerprint else ""
    semantic_indexed = bool(stored_representations.get("semantic"))
    # Política ausente con representación ya indexada = versión previa sin
    # fingerprint de política: se re-indexa una vez para converger.
    policy_changed = bool(
        fingerprint is not None
        and chunking_policy
        and stored_policy != chunking_policy
        and (stored_policy or semantic_indexed)
    )
    needs_semantic_index = (
        diff.change_kind is not TabularChangeKind.UNCHANGED
        or not semantic_indexed
        or policy_changed
    )
    if diff.change_kind is not TabularChangeKind.UNCHANGED:
        await repository.upsert_workbook(
            workbook, diff, knowledge_base_id=knowledge_base_id
        )
    return replace(
        diff,
        metadata={
            **diff.metadata,
            "stored_representations": stored_representations,
            "stored_chunking_policy": stored_policy,
            "policy_changed": policy_changed,
            "needs_semantic_index": needs_semantic_index,
            "stored_materialization_policy": (
                str(fingerprint.materialization_policy) if fingerprint else ""
            ),
            "stored_materialized_tables": (
                list(fingerprint.materialized_tables) if fingerprint else []
            ),
        },
    )
