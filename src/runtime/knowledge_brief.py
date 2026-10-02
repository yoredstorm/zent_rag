# =============================================================================
# Knowledge Brief — representación progresiva para el prompt (S7, C3).
# =============================================================================
# Facts -> Relations -> Rules -> Critical excerpts -> Supporting excerpts.
# Cada línea conserva refs (kn: canónico, ev: evidencia). Presupuesto
# determinista por sección con arrastre; lo que no entra se declara truncado.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field

from src.runtime.evidence_assembly import EvidencePackage, EvidenceUnit

_SECTION_ORDER = (
    "facts",
    "relations",
    "rules",
    "critical_excerpts",
    "supporting_excerpts",
)
_SECTION_LABELS = {
    "facts": "Facts",
    "relations": "Relations",
    "rules": "Rules",
    "critical_excerpts": "Critical excerpts",
    "supporting_excerpts": "Supporting excerpts",
}
_BUDGET_SHARE = {
    "facts": 0.25,
    "relations": 0.15,
    "rules": 0.10,
    "critical_excerpts": 0.30,
    "supporting_excerpts": 0.20,
}
_ITEM_LIMITS = {
    "facts": 240,
    "relations": 200,
    "rules": 240,
    "critical_excerpts": 600,
    "supporting_excerpts": 600,
}


def _unit_section(unit: EvidenceUnit) -> str:
    if unit.kind == "fact":
        return "facts"
    if unit.kind == "relation":
        return "relations"
    if unit.kind == "rule":
        return "rules"
    if unit.kind == "excerpt":
        return "critical_excerpts" if unit.critical else "supporting_excerpts"
    return "supporting_excerpts"


def _refs_suffix(unit: EvidenceUnit) -> str:
    parts: list[str] = []
    for canonical_id in unit.canonical_ids[:1]:
        parts.append(f"kn:{canonical_id[:8]}")
    for evidence_id in unit.evidence_ids[:2]:
        parts.append(f"ev:{evidence_id}")
    if unit.validity:
        parts.append(f"vigencia:{unit.validity}")
    return " · ".join(parts)


@dataclass(frozen=True)
class BriefItem:
    text: str
    refs: dict = field(default_factory=dict)

    def to_public_dict(self) -> dict:
        return {"text": self.text, "refs": dict(self.refs)}


@dataclass(frozen=True)
class BriefSection:
    kind: str
    items: tuple[BriefItem, ...] = ()
    chars: int = 0
    truncated: int = 0

    def to_public_dict(self, *, max_items: int = 8) -> dict:
        return {
            "kind": self.kind,
            "count": len(self.items),
            "chars": self.chars,
            "truncated": self.truncated,
            "items": [
                item.to_public_dict() for item in self.items[: max(0, max_items)]
            ],
        }


@dataclass(frozen=True)
class KnowledgeBrief:
    sections: tuple[BriefSection, ...] = ()
    chars: int = 0
    budget_chars: int = 0

    def render_text(self) -> str:
        blocks: list[str] = []
        for section in self.sections:
            if not section.items:
                continue
            lines = "\n".join(f"- {item.text}" for item in section.items)
            blocks.append(f"[{_SECTION_LABELS[section.kind]}]\n{lines}")
        return "\n\n".join(blocks)

    def to_public_dict(self) -> dict:
        return {
            "chars": self.chars,
            "budget_chars": self.budget_chars,
            "sections": [section.to_public_dict() for section in self.sections],
        }


def build_knowledge_brief(
    package: EvidencePackage, *, budget_chars: int = 8_000
) -> KnowledgeBrief:
    """Brief determinista: estructurado primero, excerpts después."""
    budget = max(0, int(budget_chars))
    buckets: dict[str, list[EvidenceUnit]] = {kind: [] for kind in _SECTION_ORDER}
    for unit in package.units:
        buckets[_unit_section(unit)].append(unit)

    sections: list[BriefSection] = []
    leftover = 0
    used_total = 0
    for kind in _SECTION_ORDER:
        capacity = int(budget * _BUDGET_SHARE[kind]) + leftover
        used = 0
        truncated = 0
        items: list[BriefItem] = []
        limit = _ITEM_LIMITS[kind]
        for unit in buckets[kind]:
            raw = unit.text
            cut = len(raw) > limit
            text = raw[: limit - 1].rstrip() + "…" if cut else raw
            suffix = _refs_suffix(unit)
            line = f"{text} ({suffix})" if suffix else text
            if used + len(line) > capacity:
                truncated += 1
                continue
            if cut:
                truncated += 1
            items.append(
                BriefItem(
                    text=line,
                    refs={
                        **unit.refs,
                        "unit_id": unit.unit_id,
                        "evidence_ids": list(unit.evidence_ids),
                        "canonical_ids": list(unit.canonical_ids),
                    },
                )
            )
            used += len(line)
        leftover = max(0, capacity - used)
        used_total += used
        sections.append(
            BriefSection(
                kind=kind, items=tuple(items), chars=used, truncated=truncated
            )
        )
    return KnowledgeBrief(
        sections=tuple(sections), chars=used_total, budget_chars=budget
    )
