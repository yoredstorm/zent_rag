# =============================================================================
# Enrichment — términos de dominio y unidades
# =============================================================================
# Las unidades («%», «USD», «días», «MB») se enlazan al número que acompañan.
# Los térmimos de dominio salen de los packs (vocabulario extensible) o de
# vocabulario técnico genérico. Nunca se interpreta el valor: se etiqueta.
# =============================================================================
from __future__ import annotations

import re

from src.knowledge.enrichment.contracts import DomainTerm, SemanticTypeTag
from src.knowledge.enrichment.normalize import collapse, normalize_key
from src.knowledge.enrichment.profiling import EnrichmentContext
from src.knowledge.enrichment.versioning import POLICY_VERSION

_UNIT = re.compile(
    r"\b(\d+(?:[.,]\d+)?)\s*"
    r"(%|USD|EUR|GBP|JPY|MXN|COP|BRL|CLP|ARS|"
    r"kg|g|mg|km|cm|mm|m2|m3|MB|GB|TB|KB|bytes?|B|"
    r"d[ií]as?|horas?|min(?:utos?)?|seg(?:undos?)?|"
    r"years?|months?|weeks?|days?|hours?)\b",
    re.IGNORECASE,
)
_SYMBOL_CURRENCY = re.compile(r"([$€£])\s*(\d+(?:[.,]\d+)?)")
_UNIT_KIND = {
    "%": "percentage",
    "usd": "currency", "eur": "currency", "gbp": "currency", "jpy": "currency",
    "mxn": "currency", "cop": "currency", "brl": "currency", "clp": "currency",
    "ars": "currency",
    "kg": "mass", "g": "mass", "mg": "mass",
    "km": "distance", "cm": "distance", "mm": "distance", "m2": "area", "m3": "volume",
    "mb": "digital", "gb": "digital", "tb": "digital", "kb": "digital",
    "b": "digital", "byte": "digital", "bytes": "digital",
}


def _unit_kind(unit: str) -> str:
    key = normalize_key(unit)
    if key in _UNIT_KIND:
        return _UNIT_KIND[key]
    if key.endswith("as") or key.endswith("s"):
        return "duration"
    return "unit"


def build_domain_terms(
    context: EnrichmentContext,
    *,
    max_total: int = 200,
) -> tuple[DomainTerm, ...]:
    found: dict[str, DomainTerm] = {}

    def add(term: str, semantic_type: str, units: tuple[str, ...], confidence: float) -> None:
        cleaned = collapse(term)
        if not cleaned or not units:
            return
        key = f"{semantic_type}:{normalize_key(cleaned)}"
        if key in found:
            return
        found[key] = DomainTerm(
            term=cleaned,
            semantic_type=semantic_type,
            source_unit_ids=units,
            confidence=max(0.0, min(1.0, confidence)),
            derivation_method="deterministic",
            policy_version=POLICY_VERSION,
        )

    for block in context.document.blocks:
        text = block.text or ""
        units = context.valid_units([str(block.id)])
        if not units:
            continue
        for match in _UNIT.finditer(text):
            amount, unit = match.group(1), match.group(2)
            add(f"{amount} {unit}", f"unit:{_unit_kind(unit)}", units, 0.85)
        for match in _SYMBOL_CURRENCY.finditer(text):
            symbol, amount = match.group(1), match.group(2)
            add(f"{symbol}{amount}", "unit:currency", units, 0.8)

    # Términos del vocabulario de packs (status, carrier, ...).
    for block in context.document.blocks:
        units = context.valid_units([str(block.id)])
        if not units:
            continue
        for token in set(re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-z0-9_\-]{2,30}", block.text or "")):
            for pack in context.packs:
                semantic_type = pack.semantic_type(token)
                if semantic_type:
                    add(token, semantic_type, units, 0.65)
                    break
            if len(found) >= max_total:
                break
        if len(found) >= max_total:
            break

    result = sorted(found.values(), key=lambda item: (item.semantic_type, item.term.casefold()))
    return tuple(result[:max_total])


def build_semantic_types(
    concepts,
    domain_terms,
    *,
    max_total: int = 300,
) -> tuple[SemanticTypeTag, ...]:
    """Etiquetas de tipo por nombre (conceptos + términos de dominio)."""
    found: dict[str, SemanticTypeTag] = {}

    def add(name: str, semantic_type: str, units: tuple[str, ...], confidence: float, derivation: str) -> None:
        cleaned = collapse(name)
        if not cleaned:
            return
        key = f"{semantic_type}:{normalize_key(cleaned)}"
        existing = found.get(key)
        if existing is not None:
            return
        found[key] = SemanticTypeTag(
            name=cleaned,
            semantic_type=semantic_type,
            source_unit_ids=units,
            confidence=max(0.0, min(1.0, confidence)),
            derivation_method=derivation,
            policy_version=POLICY_VERSION,
        )

    for concept in concepts:
        add(concept.canonical_name, concept.semantic_type, concept.source_unit_ids, concept.confidence, "deterministic")
    for term in domain_terms:
        add(term.term, term.semantic_type, term.source_unit_ids, term.confidence, "deterministic")

    result = sorted(found.values(), key=lambda item: (item.semantic_type, item.name.casefold()))
    return tuple(result[:max_total])
