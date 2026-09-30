# =============================================================================
# Anchor / requirement coverage — señales objetivas, sin LLM
# =============================================================================
# Extiende las señales del EvidenceEvaluator: además de entidades, mide qué
# anchors exactos aparecieron (y si lo hicieron literalmente) y cuántos
# requirements quedaron sin cubrir.
# =============================================================================
from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any

from src.intelligence.response.anchors import Anchor, anchor_covered
from src.rag.longcontext.requirements import RequirementCoverage, RequirementState


@dataclass(frozen=True, kw_only=True)
class AnchorCoverage:
    requested: int
    found: int
    coverage: float
    exact: bool
    found_values: tuple[str, ...] = ()
    missing_values: tuple[str, ...] = ()
    #: Valores de ejemplo del usuario: no exigen match en fuentes.
    examples: tuple[str, ...] = ()
    examples_found: tuple[str, ...] = ()
    rule_requested: int = 0
    rule_found: int = 0
    field_requested: int = 0
    field_found: int = 0

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "requested": self.requested,
            "found": self.found,
            "coverage": round(self.coverage, 4),
            "anchor_exact_match": self.exact,
            "found_values": list(self.found_values),
            "missing_values": list(self.missing_values),
        }
        if self.rule_requested or self.field_requested:
            payload["rule_requested"] = self.rule_requested
            payload["rule_found"] = self.rule_found
            payload["field_requested"] = self.field_requested
            payload["field_found"] = self.field_found
        if self.examples:
            payload["examples"] = list(self.examples)
            payload["examples_found_in_evidence"] = list(self.examples_found)
            payload["examples_requires_source_match"] = False
        return payload


def anchor_coverage(
    anchors: list[Anchor] | tuple[Anchor, ...],
    items: list[Any] | tuple[Any, ...],
) -> AnchorCoverage:
    """Cobertura role-aware: documentables cuentan; ejemplos se reportan aparte.

    Un anchor de ejemplo («QNNF0SME») que no aparece en la documentación NO
    baja la cobertura: es la entrada sobre la que se aplica la regla.
    """
    from src.rag.longcontext.roles import (
        AnchorRole,
        assign_roles,
        is_documentable,
    )

    resolved = assign_roles("", list(anchors or ()))
    if not resolved:
        return AnchorCoverage(requested=0, found=0, coverage=0.0, exact=False)
    texts = [
        html.unescape(str(getattr(item, "content", "") or ""))
        for item in items
    ]
    joined = "\n".join(texts)
    lowered = joined.lower()

    found_values: list[str] = []
    missing_values: list[str] = []
    examples: list[str] = []
    examples_found: list[str] = []
    rule_requested = rule_found = field_requested = field_found = 0
    exact = True
    documentable = 0
    for anchor in resolved:
        value = str(getattr(anchor, "value", "") or "")
        role = str(getattr(anchor, "role", "") or "")
        if role == AnchorRole.EXAMPLE_VALUE.value:
            examples.append(value)
            needles = [
                str(needle).lower() for needle in getattr(anchor, "needles", ()) if needle
            ]
            if needles and any(needle in lowered for needle in needles):
                examples_found.append(value)
            continue
        if not is_documentable(role):
            continue
        documentable += 1
        if role == AnchorRole.RULE_ANCHOR.value:
            rule_requested += 1
        if role == AnchorRole.FIELD_ANCHOR.value:
            field_requested += 1
        if anchor_covered(anchor, joined):
            found_values.append(value)
            if role == AnchorRole.RULE_ANCHOR.value:
                rule_found += 1
            if role == AnchorRole.FIELD_ANCHOR.value:
                field_found += 1
            needles = [
                str(needle) for needle in getattr(anchor, "needles", ()) if needle
            ]
            if needles and not any(
                str(needle).strip().lower() in lowered for needle in needles
            ):
                exact = False
        else:
            missing_values.append(value)
            exact = False
    return AnchorCoverage(
        requested=documentable,
        found=len(found_values),
        coverage=(len(found_values) / documentable) if documentable else 0.0,
        exact=exact and bool(found_values) and documentable == len(found_values),
        found_values=tuple(found_values),
        missing_values=tuple(missing_values),
        examples=tuple(examples),
        examples_found=tuple(examples_found),
        rule_requested=rule_requested,
        rule_found=rule_found,
        field_requested=field_requested,
        field_found=field_found,
    )


def requirement_coverage(
    requirements: list[Any] | tuple[Any, ...],
    items: list[Any] | tuple[Any, ...],
    *,
    conflicting_needles: set[str] | None = None,
) -> RequirementCoverage:
    from src.rag.longcontext.requirements import evaluate_requirements

    return evaluate_requirements(
        requirements, items, conflicting_needles=conflicting_needles
    )


def apply_coverage_to_quality(
    quality: Any,
    *,
    anchors: AnchorCoverage | None = None,
    requirements: RequirementCoverage | None = None,
) -> Any:
    """Vuelca coverage en EvidenceQuality (campos opcionales ya existentes)."""
    if quality is None:
        return quality
    try:
        if anchors is not None and (anchors.requested or anchors.examples):
            quality.anchor_coverage = anchors.coverage
            quality.anchor_exact_match = anchors.exact
            quality.anchors_requested = anchors.found_values + anchors.missing_values
            quality.anchors_found = anchors.found_values
            quality.anchors_missing = anchors.missing_values
            if anchors.examples:
                quality.examples = anchors.examples
                quality.examples_found = anchors.examples_found
        if requirements is not None and requirements.requested:
            quality.requirement_coverage = requirements.coverage
            quality.requirements_requested = requirements.requested
            quality.requirements_found = requirements.found + requirements.partial
            quality.requirements_missing = tuple(
                requirement.description for requirement in requirements.unanswered
            )
            quality.requirements_states = tuple(
                (requirement.id, requirement.state)
                for requirement in requirements.requirements
            )
    except AttributeError:
        return quality
    return quality


def requirements_satisfied(
    coverage: RequirementCoverage | None,
    minimum: float,
) -> bool:
    """¿La cobertura alcanza el piso del perfil? Sin requirements, no bloquea.

    Los valores de ejemplo del usuario (kind example / role example_value) no
    bloquean: la documentación debe probar la regla, no el ejemplo concreto.
    """
    if coverage is None or coverage.requested == 0:
        return True
    if coverage.conflicting:
        return False
    if coverage.documentable_requested == 0:
        return True
    blocking = [
        requirement
        for requirement in coverage.requirements
        if requirement.documentable
        and not requirement.soft
        and requirement.kind not in ("structural", "example")
        and requirement.role not in ("example_value", "example")
    ]
    if not blocking:
        return True
    # Cada parte dura (anchor, entidad, cláusula corta) debe estar cubierta:
    # encontrar FCLAS no responde «¿cómo funciona FCLAS?».
    for requirement in blocking:
        if requirement.state in (
            RequirementState.MISSING.value,
            RequirementState.CONFLICTING.value,
        ):
            return False
    if coverage.all_hard_found:
        return True
    return coverage.coverage >= max(0.0, float(minimum))


__all__ = [
    "AnchorCoverage",
    "anchor_coverage",
    "apply_coverage_to_quality",
    "requirement_coverage",
    "requirements_satisfied",
]
