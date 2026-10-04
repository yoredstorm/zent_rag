# =============================================================================
# Representation Fingerprint — identidad auditable de la representación
# =============================================================================
# `content_hash` responde "¿cambió el texto?". El fingerprint responde
# "¿cambió ALGO que afecta cómo esta fuente queda representada para retrieval?":
# parser, reconstrucción, understanding, enrichment, chunking, modelo de
# embeddings, dimensiones, sparse encoding, representación de padres.
#
#   content unchanged + representation unchanged -> skip
#   content unchanged + representation changed   -> re-materialize / re-index
#   content changed                              -> update normal
#
# Determinista: mismo contenido + misma config => mismo fingerprint.
# Se persiste en metadata (structured_documents) y en el payload de cada punto.
# =============================================================================
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum

from src.core.domain.knowledge_v2 import StructuredDocument

from .versions import (
    COMPILER_REPRESENTATION_VERSION,
    CONTENT_REPRESENTATION_VERSION,
    CONTEXTUALIZATION_VERSION,
    EMBEDDING_REPRESENTATION_VERSION,
    FABRIC_REPRESENTATION_VERSION,
    PARENT_REPRESENTATION_VERSION,
    REPRESENTATION_SCHEMA_VERSION,
    RETRIEVAL_REPRESENTATION_VERSION,
    SPARSE_ENCODING_VERSION,
)

FINGERPRINT_SCHEMA_VERSION = "1"

# Clave donde el fingerprint vigente del índice vive dentro de la metadata del
# StructuredDocument (JSONB). El fingerprint que usó el último index exitoso.
INDEXED_FINGERPRINT_KEY = "indexed_representation_fingerprint"
# Descriptor completo indexado (componentes), para calcular la RAZÓN del cambio
# sin repartir comparaciones por el repositorio.
INDEXED_DESCRIPTOR_KEY = "indexed_representation_descriptor"
# Marca que un operador/CLI invalidó la representación (reason=manual).
INVALIDATED_BY_KEY = "representation_invalidated_by"

# Razones canónicas de re-index (Phase 14: cardinalidad controlada).
REINDEX_REASONS = (
    "content_changed",
    "parser_changed",
    "reconstruction_changed",
    "understanding_changed",
    "enrichment_version_changed",
    "chunking_changed",
    "contextualization_changed",
    "embedding_model_changed",
    "embedding_dimension_changed",
    "sparse_changed",
    "parent_representation_changed",
    "compiler_changed",
    "fabric_changed",
    "embedding_representation_changed",
    "semantic_pipeline_changed",
    "missing_index",
    "manual",
    "nutrition_action",
    "representation_changed",
)

# Orden de evaluación: contenido primero; luego lo que cambia la identidad de
# la representación (modelo antes que versiones de pipeline).
_REASON_CHECKS: tuple[tuple[str, str], ...] = (
    ("embedding_model", "embedding_model_changed"),
    ("embedding_dimensions", "embedding_dimension_changed"),
    ("parser_version", "parser_changed"),
    ("reconstruction_version", "reconstruction_changed"),
    ("understanding_version", "understanding_changed"),
    ("enrichment_version", "enrichment_version_changed"),
    ("chunking_version", "chunking_changed"),
    ("contextualization_version", "contextualization_changed"),
    ("sparse_encoding_version", "sparse_changed"),
    ("parent_representation_version", "parent_representation_changed"),
    ("compiler_representation_version", "compiler_changed"),
    ("fabric_representation_version", "fabric_changed"),
    ("semantic_window_policy", "semantic_pipeline_changed"),
    ("semantic_state", "semantic_pipeline_changed"),
    ("stitcher", "semantic_pipeline_changed"),
    ("regional_model", "semantic_pipeline_changed"),
    ("global_model", "semantic_pipeline_changed"),
    ("embedding_representation", "embedding_representation_changed"),
    ("embedding_representation_version", "embedding_representation_changed"),
    ("content_representation_version", "contextualization_changed"),
    ("retrieval_representation_version", "contextualization_changed"),
)


class RepresentationDecision(StrEnum):
    """Decisión de materialización derivada del fingerprint."""

    CREATE = "create"      # no había índice previo
    SKIP = "skip"          # contenido y representación idénticos
    UPDATE = "update"      # cambió el contenido (flujo normal)
    REINDEX = "reindex"    # contenido igual, representación distinta


@dataclass(frozen=True, kw_only=True)
class RepresentationDescriptor:
    """Componentes que definen la identidad de la representación de retrieval."""

    content_hash: str
    parser_version: str = ""
    structure_schema_version: str = ""
    reconstruction_version: str = ""
    understanding_version: str = ""
    enrichment_version: str = ""
    compiler_representation_version: str = COMPILER_REPRESENTATION_VERSION
    chunking_version: str = ""
    contextualization_version: str = CONTEXTUALIZATION_VERSION
    sparse_encoding_version: str = SPARSE_ENCODING_VERSION
    content_representation_version: str = CONTENT_REPRESENTATION_VERSION
    retrieval_representation_version: str = RETRIEVAL_REPRESENTATION_VERSION
    embedding_provider: str = ""
    embedding_model: str = ""
    embedding_dimensions: int = 0
    parent_representation_version: str = PARENT_REPRESENTATION_VERSION
    fabric_representation_version: str = FABRIC_REPRESENTATION_VERSION
    #: Fase 29: versiones de la pipeline semántica (ventana/estado/stitch/
    #: regional/global). Un cambio invalida representación y reindexa.
    semantic_window_policy: str = ""
    semantic_state: str = ""
    stitcher: str = ""
    regional_model: str = ""
    global_model: str = ""
    embedding_representation: str = "content"
    embedding_representation_version: str = EMBEDDING_REPRESENTATION_VERSION
    schema_version: str = REPRESENTATION_SCHEMA_VERSION

    def as_fields(self) -> dict[str, object]:
        return {key: value for key, value in asdict(self).items() if value not in (None, "")}

    def to_payload(self) -> dict[str, object]:
        """Payload auditable (fingerprint + componentes). Nunca incluye texto."""
        fields = self.as_fields()
        fields["fingerprint"] = compute_fingerprint(self)
        return fields

    @property
    def fingerprint(self) -> str:
        return compute_fingerprint(self)


def compute_fingerprint(descriptor: RepresentationDescriptor) -> str:
    """SHA256 canónico de los componentes (orden estable, sin texto fuente)."""
    payload = json.dumps(
        descriptor.as_fields(), sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def descriptor_for_document(
    document: StructuredDocument,
    *,
    embedding_provider: str = "",
    embedding_model: str = "",
    embedding_dimensions: int = 0,
    enrichment_version: str | None = None,
) -> RepresentationDescriptor:
    """Lee las versiones reales del documento entendido, no constantes ciegas."""
    understanding = document.metadata.get("understanding") or {}
    reconstruction = document.metadata.get("semantic_reconstruction") or {}
    enrichment = document.metadata.get("enrichment") or {}
    semantic = _semantic_pipeline_versions()
    return RepresentationDescriptor(
        content_hash=str(document.content_hash or ""),
        parser_version=str(
            understanding.get("parser_version")
            or reconstruction.get("parser_version")
            or ""
        ),
        structure_schema_version=str(understanding.get("schema_version") or ""),
        reconstruction_version=str(reconstruction.get("schema_version") or ""),
        understanding_version=str(
            understanding.get("understanding_schema_version") or ""
        ),
        enrichment_version=str(
            enrichment_version
            or enrichment.get("enrichment_version")
            or ""
        ),
        chunking_version=str(understanding.get("chunking_version") or ""),
        semantic_window_policy=str(semantic.get("window_plan_version") or ""),
        semantic_state=str(semantic.get("state_version") or ""),
        stitcher=str(semantic.get("stitch_version") or ""),
        regional_model=str(semantic.get("regional_version") or ""),
        global_model=str(semantic.get("global_version") or ""),
        embedding_provider=str(embedding_provider or ""),
        embedding_model=str(embedding_model or ""),
        embedding_dimensions=int(embedding_dimensions or 0),
    )


def _semantic_pipeline_versions() -> dict:
    """Versiones de la pipeline semántica (lazy: evita ciclo de imports)."""
    try:
        from src.knowledge.semantic.service import semantic_versions

        return dict(semantic_versions())
    except Exception:  # noqa: BLE001 — sin semantic, fingerprint estable
        return {}


def representation_decision(
    previous_fingerprint: str | None,
    current_fingerprint: str,
    *,
    content_changed: bool,
) -> RepresentationDecision:
    """Matriz de decisión explícita (§7 y §21 del brief)."""
    if not previous_fingerprint:
        return RepresentationDecision.CREATE
    if content_changed:
        return RepresentationDecision.UPDATE
    if previous_fingerprint != current_fingerprint:
        return RepresentationDecision.REINDEX
    return RepresentationDecision.SKIP


def change_reason(
    previous_descriptor: dict | None,
    current_descriptor: dict,
    *,
    content_changed: bool = False,
    invalidated_by: str | None = None,
) -> str:
    """Razón legible y acotada del re-index (Phase 14).

    Compara el descriptor indexado con el vigente. Nunca inventa: si no hay
    descriptor previo, `missing_index` (o `manual` si un operador invalidó).
    """
    if invalidated_by in ("manual", "nutrition_action"):
        return invalidated_by
    if not previous_descriptor:
        return "missing_index"
    if content_changed or (
        previous_descriptor.get("content_hash") != current_descriptor.get("content_hash")
    ):
        return "content_changed"
    for key, reason in _REASON_CHECKS:
        if previous_descriptor.get(key) != current_descriptor.get(key):
            return reason
    if previous_descriptor.get("fingerprint") != current_descriptor.get("fingerprint"):
        return "representation_changed"
    return "unchanged"
