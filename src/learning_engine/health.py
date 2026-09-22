# =============================================================================
# Knowledge Health — cada componente se muestra. El agregado es opcional.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field

COMPONENTS = (
    "retrievability",
    "freshness",
    "conflict_rate",
    "grounding_success",
    "failed_query_rate",
    "source_coverage",
    "parse_health",
    "structured_parse_health",
    "duplication",
)
_WARN_BELOW = 75.0


@dataclass(kw_only=True)
class KnowledgeHealth:
    components: dict[str, float]
    warnings: list[str] = field(default_factory=list)
    aggregate: float | None = None

    def to_public_dict(self) -> dict:
        return {
            "components": dict(self.components),
            "warnings": list(self.warnings),
            "aggregate": self.aggregate,
        }


def knowledge_health(
    components: dict[str, float],
    *,
    notes: dict[str, str] | None = None,
) -> KnowledgeHealth:
    """Los puntajes llegan medidos. Esta función no inventa componentes."""
    clean: dict[str, float] = {}
    warnings: list[str] = []
    notes = notes or {}
    for name in COMPONENTS:
        if name not in components:
            continue
        score = float(components[name])
        if score < 0 or score > 100:
            raise ValueError(f"{name} must be between 0 and 100")
        clean[name] = round(score, 2)
        if score < _WARN_BELOW:
            note = (notes.get(name) or "").strip()
            warnings.append(note or f"{name} {clean[name]:.0f}")
    aggregate = None
    if len(clean) >= 2:
        aggregate = round(sum(clean.values()) / len(clean), 2)
    return KnowledgeHealth(components=clean, warnings=warnings, aggregate=aggregate)
