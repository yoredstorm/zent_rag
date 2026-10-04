# =============================================================================
# Knowledge OS — Representation Layer
# =============================================================================
# La representación de retrieval es un artefacto versionado y auditable:
#
#   content/evidence  (inmutable, recuperable)
#   content_representation   (lo que se embebe para el chunk hijo)
#   retrieval_representation (conceptos + aliases + preguntas, futuro multivec)
#   parent_representation    (resumen semántico del padre, sin truncar)
#
# Nada de esta capa es evidencia: es derivado, con provenance hacia unidades.
# =============================================================================
from __future__ import annotations

from .dependencies import (
    REASON_TO_ARTIFACT,
    ArtifactKind,
    InvalidationPlan,
    downstream_of,
    invalidation_plan,
    plan_for_reason,
)
from .fingerprint import (
    FINGERPRINT_SCHEMA_VERSION,
    INDEXED_DESCRIPTOR_KEY,
    INDEXED_FINGERPRINT_KEY,
    INVALIDATED_BY_KEY,
    REINDEX_REASONS,
    RepresentationDecision,
    RepresentationDescriptor,
    change_reason,
    compute_fingerprint,
    descriptor_for_document,
    representation_decision,
)
from .parent import (
    ParentSemanticRepresentation,
    build_parent_representation,
)
from .retrieval import (
    ContentRepresentation,
    RetrievalRepresentation,
    RetrievalRepresentationBuilder,
)
from .versions import (
    COMPILER_REPRESENTATION_VERSION,
    CONTENT_REPRESENTATION_VERSION,
    EMBEDDING_REPRESENTATION_VERSION,
    FABRIC_REPRESENTATION_VERSION,
    PARENT_REPRESENTATION_VERSION,
    REPRESENTATION_SCHEMA_VERSION,
    RETRIEVAL_REPRESENTATION_VERSION,
    SPARSE_ENCODING_VERSION,
)

__all__ = [
    "COMPILER_REPRESENTATION_VERSION",
    "CONTENT_REPRESENTATION_VERSION",
    "EMBEDDING_REPRESENTATION_VERSION",
    "FABRIC_REPRESENTATION_VERSION",
    "FINGERPRINT_SCHEMA_VERSION",
    "INDEXED_DESCRIPTOR_KEY",
    "INDEXED_FINGERPRINT_KEY",
    "INVALIDATED_BY_KEY",
    "PARENT_REPRESENTATION_VERSION",
    "REASON_TO_ARTIFACT",
    "REINDEX_REASONS",
    "REPRESENTATION_SCHEMA_VERSION",
    "RETRIEVAL_REPRESENTATION_VERSION",
    "SPARSE_ENCODING_VERSION",
    "ArtifactKind",
    "ContentRepresentation",
    "InvalidationPlan",
    "ParentSemanticRepresentation",
    "RepresentationDecision",
    "RepresentationDescriptor",
    "RetrievalRepresentation",
    "RetrievalRepresentationBuilder",
    "build_parent_representation",
    "change_reason",
    "compute_fingerprint",
    "descriptor_for_document",
    "downstream_of",
    "invalidation_plan",
    "plan_for_reason",
    "representation_decision",
]
