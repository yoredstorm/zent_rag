# =============================================================================
# Enrichment — identificadores exactos
# =============================================================================
# Un identificador (Byte 105, CAT31, 0x1F, &%#...) se guarda VERBATIM. No se
# normaliza, no se interpreta, no se inventa significado. La variante en
# minúsculas, si se necesita para búsqueda, es un alias con provenance.
# =============================================================================
from __future__ import annotations

import re

from src.knowledge.enrichment.contracts import EnrichmentIdentifier, RetrievalAlias
from src.knowledge.enrichment.profiling import EnrichmentContext
from src.knowledge.enrichment.versioning import POLICY_VERSION

_TYPE_MAP = {
    "byte_ref": "byte",
    "hex": "hex",
    "mask": "mask",
    "code": "code",
    "identifier": "numeric_id",
    "spec_value": "literal",
}

_EXTRA_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\bBytes?\s+\d{1,4}(?:\s*[-–]\s*\d{1,4})?\b", re.IGNORECASE), "byte"),
    (re.compile(r"\b0x[0-9A-Fa-f]{2,}\b"), "hex"),
    (re.compile(r"\b[A-Z]{2,8}\d{2,}(?:[-/][A-Z0-9]+)*\b"), "code"),
    (re.compile(r"\b[A-Z][A-Z0-9]*_\d{1,4}\b"), "code"),
)

_CONFIDENCE = {
    "byte": 0.95,
    "hex": 0.95,
    "mask": 0.9,
    "code": 0.85,
    "numeric_id": 0.8,
    "literal": 0.75,
}


def build_identifiers(
    context: EnrichmentContext,
    *,
    max_total: int = 300,
) -> tuple[EnrichmentIdentifier, ...]:
    understanding = context.understanding
    found: dict[str, EnrichmentIdentifier] = {}

    def add(value: str, kind: str, units: tuple[str, ...], confidence: float) -> None:
        cleaned = " ".join(str(value or "").split())
        if not cleaned or len(cleaned) > 64 or not units:
            return
        key = f"{kind}:{cleaned.casefold()}"
        if key in found:
            return
        found[key] = EnrichmentIdentifier(
            value=cleaned,
            identifier_type=kind,
            source_unit_ids=units,
            confidence=max(0.0, min(1.0, confidence)),
            derivation_method="deterministic",
            policy_version=POLICY_VERSION,
        )

    for literal in understanding.get("exact_literals") or ():
        value = str(literal.get("value") or "")
        kind = _TYPE_MAP.get(str(literal.get("pattern_type") or ""), "literal")
        units = context.valid_units([str(literal.get("block_id") or "")])
        add(value, kind, units, float(literal.get("confidence") or _CONFIDENCE.get(kind, 0.7)))

    # Segunda pasada: patrones adicionales sobre el texto de los bloques.
    for block in context.document.blocks:
        text = block.text or ""
        units = context.valid_units([str(block.id)])
        if not units:
            continue
        for pattern, kind in _EXTRA_PATTERNS:
            for match in pattern.finditer(text):
                add(match.group(0), kind, units, _CONFIDENCE.get(kind, 0.7))

    result = sorted(
        found.values(), key=lambda item: (-item.confidence, item.identifier_type, item.value)
    )
    return tuple(result[:max_total])


def identifier_aliases(
    identifiers: tuple[EnrichmentIdentifier, ...],
    *,
    max_total: int = 300,
) -> tuple[RetrievalAlias, ...]:
    """Variantes de búsqueda de identificadores exactos (nunca reemplazos)."""
    aliases: list[RetrievalAlias] = []
    seen: set[str] = set()
    for identifier in identifiers:
        for variant in (identifier.value.lower(), identifier.value.upper().replace(" ", "")):
            key = variant.casefold()
            if not variant or key in seen or variant == identifier.value:
                continue
            seen.add(key)
            aliases.append(
                RetrievalAlias(
                    value=variant,
                    kind="acronym" if variant.isupper() else "case",
                    target_concept_id=None,
                    source_unit_ids=identifier.source_unit_ids,
                    confidence=max(0.4, identifier.confidence - 0.2),
                    derivation_method="deterministic",
                    policy_version=POLICY_VERSION,
                )
            )
            if len(aliases) >= max_total:
                return tuple(aliases)
    return tuple(aliases)
