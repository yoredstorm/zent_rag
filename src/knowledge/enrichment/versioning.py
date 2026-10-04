# =============================================================================
# Enrichment — versiones de política y esquema
# =============================================================================
# La versión entra en el representation_fingerprint y en cada item persistido.
# Subirla invalida re-enrichment + re-materialización de retrieval, no la
# evidencia.
# =============================================================================
from __future__ import annotations

ENRICHMENT_VERSION = "1"
ENRICHMENT_SCHEMA_VERSION = "1"

# Política determinista-primero: ningún item sin provenance puede existir.
POLICY_VERSION = "deterministic-first-1"

# Namespace estable de ids derivados de conceptos (no confundir con ids
# canónicos del compilador: concept_id es de enrichment, no de knowledge).
ENRICHMENT_NAMESPACE = "9f4a1c7e-2d5b-4e8a-b3c6-7d9e0f1a2b34"
