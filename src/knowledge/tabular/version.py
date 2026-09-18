# =============================================================================
# Tabular ingestion — versión del pipeline derivado
# =============================================================================
# Se incluye en `workbook.metadata.pipeline_version` y en el fingerprint
# persistido: cuando cambia el parser/detector/heurística, un re-sync del mismo
# archivo (mismo content_hash) fuerza el reproceso de la representación derivada
# en lugar de saltarse todo por "unchanged".
#
# Subir esta versión al cambiar lógica de detección/schema/chunking.
# =============================================================================
from __future__ import annotations

TABULAR_PIPELINE_VERSION = "1.3"
