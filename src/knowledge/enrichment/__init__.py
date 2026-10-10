# =============================================================================
# Knowledge OS — Semantic Enrichment Layer
# =============================================================================
# ENRIQUECIMIENTO ≠ EVIDENCIA.
#
# Esta capa recibe un StructuredDocument ya reconstruido/entendido y produce
# señal DERIVADA: conceptos, aliases, acrónimos, identificadores, términos de
# dominio, qualifiers temporales, referencias, reglas posibles, aliases de
# retrieval y preguntas sintéticas.
#
# Nada de lo generado es canónico ni evidencia. Todo lleva:
#   derived=true, canonical=false, source_unit_ids, derivation_method,
#   confidence, policy_version.
#
# Orden obligatorio: determinista -> estructural -> estadístico -> heurística
# de dominio -> (opcional, acotado) modelo semántico. Sin LLM por defecto.
# =============================================================================
from __future__ import annotations

from .contracts import (
    DomainTerm,
    EnrichmentIdentifier,
    EnrichmentQuality,
    EnrichmentStatistics,
    PossibleRule,
    RetrievalAlias,
    SemanticConcept,
    SemanticEnrichmentResult,
    SemanticReference,
    SemanticTypeTag,
    SyntheticQuestion,
    TemporalQualifier,
)
from .pipeline import enrich_document
from .profiling import (
    EnrichmentProfilePack,
    active_profile_packs,
    expand_aliases,
    register_profile_pack,
)
from .versioning import (
    ENRICHMENT_SCHEMA_VERSION,
    ENRICHMENT_VERSION,
    POLICY_VERSION,
)

__all__ = [
    "ENRICHMENT_SCHEMA_VERSION",
    "ENRICHMENT_VERSION",
    "POLICY_VERSION",
    "DomainTerm",
    "EnrichmentIdentifier",
    "EnrichmentProfilePack",
    "EnrichmentQuality",
    "EnrichmentStatistics",
    "PossibleRule",
    "RetrievalAlias",
    "SemanticConcept",
    "SemanticEnrichmentResult",
    "SemanticReference",
    "SemanticTypeTag",
    "SyntheticQuestion",
    "TemporalQualifier",
    "active_profile_packs",
    "enrich_document",
    "expand_aliases",
    "register_profile_pack",
]
