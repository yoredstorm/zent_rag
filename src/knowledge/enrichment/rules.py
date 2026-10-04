# =============================================================================
# Enrichment — reglas posibles (candidatos, NUNCA canónicas)
# =============================================================================
# Detecta la forma lingüística de una regla (if/then, must/shall/required).
# El Knowledge Compiler decide después, con evidencia, si es una regla real.
# Esta capa solo propone candidatos trazables.
# =============================================================================
from __future__ import annotations

import re
from uuid import UUID, uuid5

from src.knowledge.enrichment.contracts import PossibleRule
from src.knowledge.enrichment.normalize import collapse, normalize_key
from src.knowledge.enrichment.profiling import EnrichmentContext
from src.knowledge.enrichment.versioning import ENRICHMENT_NAMESPACE, POLICY_VERSION

_NS = UUID(ENRICHMENT_NAMESPACE)

_CONDITIONAL = re.compile(
    r"\b(if|when|cuando|si)\b\s+(.{4,220}?)\s*(?:,|\bthen\b|=>|entonces|→)\s*(.{4,220})",
    re.IGNORECASE,
)
_OBLIGATION = re.compile(
    r"\b(must|shall|debe|deber[aá]|required|obligatorio|no\s+puede|prohibido)\b\s*(.{4,220})",
    re.IGNORECASE,
)


def build_possible_rules(
    context: EnrichmentContext,
    *,
    max_total: int = 80,
) -> tuple[PossibleRule, ...]:
    found: dict[str, PossibleRule] = {}

    def add(statement: str, condition: str, consequence: str, units: tuple[str, ...], confidence: float) -> None:
        cleaned = collapse(statement)[:400]
        if not cleaned or not units:
            return
        key = normalize_key(cleaned)[:160]
        if key in found:
            return
        rule_key = str(uuid5(_NS, f"possible-rule:{key}"))
        found[key] = PossibleRule(
            rule_key=rule_key,
            statement=cleaned,
            condition=collapse(condition)[:240],
            consequence=collapse(consequence)[:240],
            language=context.document.language,
            source_unit_ids=units,
            confidence=max(0.0, min(1.0, confidence)),
            derivation_method="deterministic",
            policy_version=POLICY_VERSION,
        )

    for block in context.document.blocks:
        text = collapse(block.text or "")
        if not text:
            continue
        units = context.valid_units([str(block.id)])
        if not units:
            continue
        for match in _CONDITIONAL.finditer(text):
            add(
                match.group(0),
                condition=match.group(2),
                consequence=match.group(3),
                units=units,
                confidence=0.7,
            )
        for match in _OBLIGATION.finditer(text):
            add(
                match.group(0),
                condition="",
                consequence=match.group(2),
                units=units,
                confidence=0.62,
            )
        if len(found) >= max_total:
            break

    result = sorted(found.values(), key=lambda item: (-item.confidence, item.statement.casefold()))
    return tuple(result[:max_total])
