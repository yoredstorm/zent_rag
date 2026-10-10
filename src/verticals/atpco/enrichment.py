# =============================================================================
# Pack de perfil ATPCO — vocabulario de dominio, no reglas de runtime.
# =============================================================================
# El manual nombra los campos en inglés (Eff Date, Disc Date, Effective Date,
# Discontinue Date). El usuario pregunta en español. Este pack declara los
# aliases conocidos para que la cobertura y la búsqueda dirigida los usen:
# la lógica genérica solo consulta el vocabulario cargado.
#
# Se carga con:
#   RAG_KNOWLEDGE_ENRICHMENT_PROFILE_PACKS=src.verticals.atpco.enrichment
# =============================================================================
from __future__ import annotations

from src.knowledge.enrichment import EnrichmentProfilePack

#: Campos de fecha del Record 2/ATPCO tal como aparecen en el manual.
_DATE_FIELD_ALIASES = (
    "Eff Date",
    "Disc Date",
    "Effective Date",
    "Discontinue Date",
    "Date Processing",
)

ATPCO_PROFILE_PACK = EnrichmentProfilePack(
    name="atpco",
    version="1",
    description=(
        "Vocabulario ATPCO: campos de fecha del Record 2 y sinónimos en español."
    ),
    alias_map={
        "cambio de fechas": _DATE_FIELD_ALIASES,
        "cambio de fecha": _DATE_FIELD_ALIASES,
        "cambios de fechas": _DATE_FIELD_ALIASES,
        "fechas de efectividad": _DATE_FIELD_ALIASES,
        "fecha de efectividad": _DATE_FIELD_ALIASES,
        "fechas efectivas": _DATE_FIELD_ALIASES,
        "fechas de vigencia": _DATE_FIELD_ALIASES,
        "vigencia": _DATE_FIELD_ALIASES,
    },
    term_map={
        "cambio de fechas": "Effective Date",
        "cambios de fechas": "Effective Date",
        "fechas de efectividad": "Effective Date",
        "fecha de efectividad": "Effective Date",
        "vigencia": "Effective Date",
    },
    term_types={
        "eff date": "temporal_field",
        "disc date": "temporal_field",
        "effective date": "temporal_field",
        "discontinue date": "temporal_field",
        "cambio de fechas": "temporal",
    },
)

PROFILE_PACKS = (ATPCO_PROFILE_PACK,)

__all__ = ["ATPCO_PROFILE_PACK", "PROFILE_PACKS"]
