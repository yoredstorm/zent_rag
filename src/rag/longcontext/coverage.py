# =============================================================================
# Anchor / requirement coverage — señales objetivas, sin LLM
# =============================================================================
# Extiende las señales del EvidenceEvaluator: además de entidades, mide qué
# anchors exactos aparecieron (y si lo hicieron literalmente) y cuántos
# requirements quedaron sin cubrir.
# =============================================================================
from __future__ import annotations

import html
from dataclasses import dataclass, replace
from typing import Any

from src.intelligence.response.anchors import Anchor, anchor_covered
from src.rag.longcontext.requirements import RequirementCoverage, RequirementState


@dataclass(frozen=True)
class _TextItem:
    """Adapter de texto plano a la interfaz item.content usada por coverage."""

    content: str

    @property
    def metadata(self) -> dict:
        return {}


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
    #: Instancias de patrón del runtime: la instancia no exige match; su
    #: gramática se exige como premisa (requirements kind=pattern_semantics).
    runtime_patterns: tuple[str, ...] = ()
    runtime_patterns_found: tuple[str, ...] = ()
    #: Dato del escenario: aceptado siempre, separado de la cobertura documental.
    runtime_values: tuple[str, ...] = ()

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
        if self.runtime_patterns:
            payload["runtime_patterns"] = list(self.runtime_patterns)
            payload["runtime_patterns_found_in_evidence"] = list(
                self.runtime_patterns_found
            )
            payload["runtime_patterns_requires_literal_match"] = False
        if self.runtime_values:
            payload["runtime_values"] = list(self.runtime_values)
            payload["runtime_values_requires_source_match"] = False
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
    runtime_patterns: list[str] = []
    runtime_patterns_found: list[str] = []
    runtime_values: list[str] = []
    rule_requested = rule_found = field_requested = field_found = 0
    exact = True
    documentable = 0
    for anchor in resolved:
        value = str(getattr(anchor, "value", "") or "")
        role = str(getattr(anchor, "role", "") or "")
        if role == AnchorRole.RUNTIME_PATTERN.value:
            # La instancia de patrón no exige presencia literal en fuentes.
            runtime_patterns.append(value)
            needles = [
                str(needle).lower() for needle in getattr(anchor, "needles", ()) if needle
            ]
            if needles and any(needle in lowered for needle in needles):
                runtime_patterns_found.append(value)
            continue
        if role == AnchorRole.RUNTIME_VALUE.value:
            runtime_values.append(value)
            continue
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
        runtime_patterns=tuple(runtime_patterns),
        runtime_patterns_found=tuple(runtime_patterns_found),
        runtime_values=tuple(runtime_values),
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


#: Modos de generación centralizados. Ninguna capa inventa el suyo.
GENERATE_FULL = "generate_full"
GENERATE_WITH_LIMITS = "generate_with_limits"
RETRIEVE_MORE = "retrieve_more"
ABSTAIN = "abstain"


@dataclass(frozen=True, kw_only=True)
class EvidenceState:
    """Estado ÚNICO de evidencia del run: una sola verdad para el coverage.

    Todas las capas (prompt, disclaimers, agent runtime, evaluator, engine)
    consumen esto en lugar de recalcular anchors/entidades por su cuenta.
    Los EXAMPLE_VALUE no exigen match en fuentes: nunca aparecen en missing.
    """

    question: str
    documentable_anchors: tuple[Any, ...] = ()
    example_values: tuple[Any, ...] = ()
    #: Instancias de patrón del runtime («me viene &&&F»): instancia no literal,
    #: semántica documentada sí.
    runtime_patterns: tuple[Any, ...] = ()
    #: Valores de runtime que no son ejemplos ni patrones.
    runtime_values: tuple[Any, ...] = ()
    entities: tuple[Any, ...] = ()
    anchor_coverage: AnchorCoverage | None = None
    requirements: RequirementCoverage | None = None
    missing_anchors: tuple[str, ...] = ()
    missing_entities: tuple[str, ...] = ()
    missing_requirements: tuple[str, ...] = ()
    #: Premisas del dominio que faltan (semántica de símbolos, matching, etc.):
    #: se nombran como premisas, nunca como «el valor del usuario no aparece».
    missing_premises: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    #: Entidades que SÍ aparecieron (para el bloque canónico del prompt).
    entities_found: tuple[str, ...] = ()
    #: Señales del evaluador/JEV (opcional): score, conflicts, etc.
    quality: Any | None = None
    #: Por qué se detuvo la investigación (stop_reason del engine, si hubo).
    stop_reason: str = ""
    #: ¿Quedan estrategias de retrieval legítimas? Lo decide el engine/runtime.
    retrieval_available: bool = False
    #: Decisión única derivada del estado (no la inventa cada runtime).
    generation_mode: str = GENERATE_FULL
    decision_reason: str = ""
    #: Fuentes que sostienen la decisión (evidencia usada, no candidatos).
    evidence_sources: tuple[dict[str, Any], ...] = ()

    @property
    def missing_documentable_evidence(self) -> tuple[str, ...]:
        """Faltantes DOCUMENTABLES. Un EXAMPLE_VALUE jamás entra acá."""
        return tuple(
            dict.fromkeys(
                [
                    *self.missing_anchors,
                    *self.missing_entities,
                    *self.missing_requirements,
                ]
            )
        )

    @property
    def domain_requirement_coverage(self) -> float:
        """Cobertura de PREMISAS del dominio (separada del dato del usuario)."""
        if self.requirements is not None and self.requirements.requested:
            return self.requirements.domain_requirement_coverage
        if self.anchor_coverage is not None:
            return self.anchor_coverage.coverage
        return 0.0

    @property
    def runtime_input_coverage(self) -> float:
        """Cobertura del ESCENARIO: el dato del usuario se acepta, no se busca."""
        if self.requirements is not None and self.requirements.runtime_requirements:
            return self.requirements.runtime_input_coverage
        if self.example_values or self.runtime_values or self.runtime_patterns:
            return 1.0
        return 0.0

    @property
    def evidence_complete(self) -> bool:
        return not (self.missing_documentable_evidence or self.conflicts)

    @property
    def coverage(self) -> float:
        return self.domain_requirement_coverage

    def to_public_dict(self) -> dict[str, Any]:
        found_anchors = set(self.anchor_coverage.found_values) if self.anchor_coverage else set()
        found_examples = set(self.anchor_coverage.examples_found) if self.anchor_coverage else set()
        runtime_pattern_values = {
            str(getattr(anchor, "value", "")) for anchor in self.runtime_patterns
        }
        anchors_payload: list[dict[str, Any]] = []
        for anchor in (
            *self.documentable_anchors,
            *self.example_values,
            *self.runtime_patterns,
            *self.runtime_values,
        ):
            role = str(getattr(anchor, "role", "") or "")
            value = str(getattr(anchor, "value", ""))
            runtime = role in ("example_value", "runtime_pattern", "runtime_value")
            anchors_payload.append(
                {
                    "value": value,
                    "role": role,
                    "found": value in (found_examples if role == "example_value" else found_anchors),
                    "requires_source_match": not runtime,
                    "requires_semantics": role == "runtime_pattern",
                }
            )
        payload: dict[str, Any] = {
            "authority": "canonical_evidence_engine",
            "legacy_coverage": "disabled",
            "anchors": anchors_payload,
            "documentable_anchors": [
                str(getattr(anchor, "value", "")) for anchor in self.documentable_anchors
            ],
            "example_values": [
                str(getattr(anchor, "value", "")) for anchor in self.example_values
            ],
            "runtime_patterns": [
                str(getattr(anchor, "value", "")) for anchor in self.runtime_patterns
            ],
            "runtime_values": [
                str(getattr(anchor, "value", "")) for anchor in self.runtime_values
            ],
            "examples_requires_source_match": False,
            "runtime_values_requires_source_match": False,
            "entities": [
                str(getattr(entity, "label", entity)) for entity in self.entities
            ],
            "entities_found": list(self.entities_found),
            "missing_anchors": list(self.missing_anchors),
            "missing_entities": list(self.missing_entities),
            "missing_requirements": list(self.missing_requirements),
            "missing_premises": list(self.missing_premises),
            "missing_documentable_evidence": list(self.missing_documentable_evidence),
            "conflicts": list(self.conflicts),
            "complete": self.evidence_complete,
            "evidence_complete": self.evidence_complete,
            "coverage": round(self.coverage, 4),
            "domain_requirement_coverage": round(self.domain_requirement_coverage, 4),
            "runtime_input_coverage": round(self.runtime_input_coverage, 4),
            "stop_reason": self.stop_reason or None,
            "retrieval_available": self.retrieval_available,
            "generation_mode": self.generation_mode,
            "decision_reason": self.decision_reason or None,
        }
        if self.evidence_sources:
            payload["evidence_sources"] = [dict(item) for item in self.evidence_sources[:12]]
        if self.quality is not None and hasattr(self.quality, "to_public_dict"):
            payload["quality"] = self.quality.to_public_dict()
        return payload


def decide_generation_mode(
    state: EvidenceState,
    *,
    retrieval_available: bool = False,
) -> tuple[str, str]:
    """UNA decisión de grounding, derivada del estado (prohibido duplicarla).

    - requirements completos y sin conflictos → GENERATE_FULL
    - falta evidencia documentable y quedan estrategias → RETRIEVE_MORE
    - falta evidencia y ya no hay estrategias → GENERATE_WITH_LIMITS
    - falta evidencia, retrieval agotado y nada recuperado → ABSTAIN (policy)
    """
    if state.evidence_complete:
        return GENERATE_FULL, "requirements complete; no conflicts"
    if retrieval_available:
        return RETRIEVE_MORE, "missing documentable evidence; retrieval available"
    if not state.documentable_anchors and not state.entities and not state.requirements:
        return ABSTAIN, "no evidence requested and nothing retrieved"
    return GENERATE_WITH_LIMITS, "retrieval exhausted; answer with limits"


def build_evidence_state(
    question: str,
    items: Any,
    *,
    anchors: list[Any] | tuple[Any, ...] | None = None,
    entities: list[Any] | tuple[Any, ...] | None = None,
    conflicting: int = 0,
    quality: Any | None = None,
    stop_reason: str = "",
    retrieval_available: bool = False,
    evidence_sources: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
) -> EvidenceState:
    """Construye el estado canónico. `items` = chunks o texto plano.

    Único lugar donde se decide qué falta y en qué modo se genera. Los
    consumidores (prompt, disclaimers, runtime, flow) NO recalculan nada.
    """
    from src.rag.longcontext.requirements import build_requirements, evaluate_requirements
    from src.rag.longcontext.views import build_query_views

    if isinstance(items, str):
        evidence_texts: list[str] = [items]
        evidence_items: list[Any] = [_TextItem(items)]
    else:
        evidence_items = list(items or ())
        if evidence_items and isinstance(evidence_items[0], str):
            evidence_items = [_TextItem(str(item)) for item in evidence_items]
        evidence_texts = evidence_items

    views = build_query_views(question) if anchors is None else None
    resolved_anchors = list(anchors) if anchors is not None else list(views.anchors or ())
    resolved_entities = (
        list(entities)
        if entities is not None
        else list(getattr(views, "entities", ()) or ())
    )
    from src.rag.longcontext.roles import AnchorRole, assign_roles, is_documentable

    resolved_anchors = assign_roles(question, resolved_anchors)
    documentable = [
        anchor
        for anchor in resolved_anchors
        if is_documentable(str(getattr(anchor, "role", "")))
    ]
    examples = [
        anchor
        for anchor in resolved_anchors
        if str(getattr(anchor, "role", "")) == AnchorRole.EXAMPLE_VALUE.value
    ]
    runtime_patterns = [
        anchor
        for anchor in resolved_anchors
        if str(getattr(anchor, "role", "")) == AnchorRole.RUNTIME_PATTERN.value
    ]
    runtime_values = [
        anchor
        for anchor in resolved_anchors
        if str(getattr(anchor, "role", ""))
        in (AnchorRole.RUNTIME_VALUE.value, AnchorRole.OPTIONAL_CONTEXT.value)
    ]
    # El valor del escenario que se aplica contra un patrón/rango: primer valor
    # de runtime no-paramétrico disponible (el patrón se evalúa aparte).
    runtime_value = ""
    for anchor in (*examples, *runtime_values):
        candidate = str(getattr(anchor, "value", "") or "")
        if candidate:
            runtime_value = candidate
            break

    anchor_cov = anchor_coverage(resolved_anchors, evidence_items)
    requirements = build_requirements(
        question,
        resolved_anchors,
        resolved_entities,
        examples=[str(getattr(anchor, "value", "")) for anchor in examples],
        runtime_value=runtime_value,
    )
    requirement_cov = evaluate_requirements(requirements, evidence_items)

    missing_anchors = tuple(anchor_cov.missing_values)
    entity_label_by_needle: dict[str, str] = {}
    for entity in resolved_entities:
        for variant in getattr(entity, "variants", ()) or ():
            value = str(variant).strip().lower()
            if value:
                entity_label_by_needle[value] = str(getattr(entity, "label", variant))
    missing_entities = tuple(
        entity_label_by_needle.get(
            str(requirement.needles[0]).strip().lower()
            if requirement.needles
            else requirement.description,
            requirement.needles[0] if requirement.needles else requirement.description,
        )
        for requirement in requirement_cov.unanswered
        if requirement.kind == "entity"
    )
    missing_requirements = tuple(
        requirement.description for requirement in requirement_cov.unanswered
    )
    # Premisas del dominio faltantes: claves semánticas (definition:symbol:&,
    # matching_policy, length_semantics...). NUNCA el valor del usuario ni la
    # instancia del patrón como exigencia literal.
    missing_premises_list: list[str] = []
    _pattern_semantics_for_missing = None
    for requirement in requirement_cov.unanswered:
        if requirement.kind == "pattern_semantics":
            from src.rag.longcontext.pattern import (
                analyze_pattern_instance,
                extract_pattern_semantics,
                missing_pattern_premises,
            )

            if _pattern_semantics_for_missing is None:
                _pattern_semantics_for_missing = extract_pattern_semantics(
                    evidence_items
                )
            missing_premises_list.extend(
                missing_pattern_premises(
                    analyze_pattern_instance(requirement.pattern),
                    _pattern_semantics_for_missing,
                    value_length=(
                        len(requirement.value) if requirement.value else None
                    ),
                )
            )
        elif requirement.kind == "pattern_policy":
            key = requirement.description.rsplit(": ", 1)[-1]
            if key:
                missing_premises_list.append(key)
    missing_premises = tuple(dict.fromkeys(missing_premises_list))
    entities_found = tuple(
        requirement.needles[0] if requirement.needles else requirement.description
        for requirement in requirement_cov.requirements
        if requirement.kind == "entity"
        and requirement.state == RequirementState.FOUND.value
    )
    conflicts: list[str] = []
    if requirement_cov.conflicting:
        conflicts.append(f"{requirement_cov.conflicting} requirement(s) en conflicto")
    if conflicting:
        conflicts.append(f"{conflicting} fragmento(s) en conflicto")
    state = EvidenceState(
        question=question,
        documentable_anchors=tuple(documentable),
        example_values=tuple(examples),
        runtime_patterns=tuple(runtime_patterns),
        runtime_values=tuple(runtime_values),
        entities=tuple(resolved_entities),
        anchor_coverage=anchor_cov,
        requirements=requirement_cov,
        missing_anchors=missing_anchors,
        missing_entities=missing_entities,
        missing_requirements=missing_requirements,
        missing_premises=missing_premises,
        conflicts=tuple(conflicts),
        entities_found=entities_found,
        quality=quality,
        stop_reason=stop_reason,
        retrieval_available=bool(retrieval_available),
        evidence_sources=tuple(dict(item) for item in evidence_sources or ()),
    )
    mode, reason = decide_generation_mode(
        state, retrieval_available=bool(retrieval_available)
    )
    return replace(state, generation_mode=mode, decision_reason=reason)


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
    "ABSTAIN",
    "AnchorCoverage",
    "EvidenceState",
    "GENERATE_FULL",
    "GENERATE_WITH_LIMITS",
    "RETRIEVE_MORE",
    "anchor_coverage",
    "apply_coverage_to_quality",
    "build_evidence_state",
    "decide_generation_mode",
    "requirement_coverage",
    "requirements_satisfied",
]
