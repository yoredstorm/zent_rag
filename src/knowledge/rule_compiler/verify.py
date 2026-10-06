# =============================================================================
# Semantic Rule Compiler — verificación
# =============================================================================
# Una regla propuesta por lenguaje (o por LLM) NO se vuelve canónica por
# existir: cada propiedad inferida pasa por un gate.
#
#   1. evidencias presentes y localizables
#   2. el texto marcador existe en la evidencia
#   3. sin contradicción de negación
#   4. excepciones conservadas
#   5. alcance/sección
#   6. unidad declarada cuando la cantidad la exige
#   7. dirección preservada (asimetría)
#   8. inclusividad declarada (jamás asumida)
#   9. negación conservada en modalidad/polaridad
#  10. referencias cruzadas resueltas o declaradas
#
# Estados: PROPOSED | SUPPORTED | PARTIALLY_SUPPORTED | CONFLICTING |
#          UNSUPPORTED | UNKNOWN
#
# Solo SUPPORTED con premisas cerradas puede ejecutarse.
# =============================================================================
from __future__ import annotations

import re
from typing import Any, Sequence

from src.core.domain.rule_semantics import (
    BoundaryKind,
    ClaimLayer,
    ComparisonOperator,
    LengthPolicy,
    MatchOperator,
    RuleKind,
    VerificationState,
    analyze_language,
    asymmetric_length_policy,
    numeric_length_policy,
)

from .model import (
    CandidateRule,
    CanonicalRule,
    RuleConflict,
    RuleEvidence,
    RuleProperty,
    stable_id,
)

#: Propiedades que bloquean la ejecución si quedan UNKNOWN.
_EXECUTION_CRITICAL = (
    "matching.operator",
    "length.policy",
    "comparison.operator",
    "temporal.relation",
    "formula.expression",
)

#: Familias de política para detectar conflictos entre reglas.
_POLICY_PROPERTY_ORDER = (
    "length.policy",
    "matching.operator",
    "matching.case_sensitive",
    "matching.alphabet",
    "comparison.operator",
    "comparison.boundary",
    "temporal.relation",
    "quantity.minimum",
    "quantity.maximum",
    "quantity.unit",
    "enumeration.allowed",
    "enumeration.prohibited",
    "formula.expression",
)

#: Tipos canónicos no ejecutables por naturaleza.
_NON_EXECUTABLE_KINDS = frozenset(
    {
        RuleKind.DEFINITION.value,
        RuleKind.MAPPING.value,
        RuleKind.NOTE.value,
        RuleKind.REFERENCE.value,
        RuleKind.EXAMPLE.value,
        RuleKind.PROCEDURE.value,
    }
)


def _norm(text: str) -> str:
    return " ".join(str(text or "").split())


def _property_key(name: str) -> str:
    """`comparison.operator.1` -> `comparison.operator`."""
    return re.sub(r"\.\d+$", "", str(name or ""))


def _primary_policy(properties: dict[str, RuleProperty]) -> tuple[str, Any] | None:
    for name in _POLICY_PROPERTY_ORDER:
        prop = properties.get(name)
        if prop is not None and prop.known:
            return name, prop.value
    return None


def _evidence_map(candidate: CandidateRule) -> dict[str, RuleEvidence]:
    mapping: dict[str, RuleEvidence] = {}
    for item in candidate.evidence:
        mapping[item.evidence_id] = item
    for item in candidate.corroborating:
        mapping.setdefault(item.evidence_id, item)
    return mapping


def _verify_property(
    candidate: CandidateRule,
    prop: RuleProperty,
    evidence: dict[str, RuleEvidence],
    *,
    statement_text: str,
) -> RuleProperty:
    """Verifica UNA propiedad; devuelve copia con estado y premisas."""
    state = VerificationState.SUPPORTED.value
    notes: list[str] = []
    missing = list(dict.fromkeys(prop.missing_premises))

    # 1-2. Evidencia presente y marcador verificable.
    if not prop.evidence:
        state = VerificationState.UNSUPPORTED.value
        notes.append("propiedad sin evidencia")
    else:
        known = [ref for ref in prop.evidence if ref in evidence]
        if not known:
            state = VerificationState.UNSUPPORTED.value
            notes.append("evidencia referenciada inexistente")
        else:
            prop = RuleProperty(
                name=prop.name,
                value=prop.value,
                value_kind=prop.value_kind,
                layer=prop.layer,
                state=prop.state,
                evidence=list(dict.fromkeys(prop.evidence)),
                method=prop.method,
                confidence=prop.confidence,
                explicit=prop.explicit,
                matched_text=prop.matched_text,
                missing_premises=list(prop.missing_premises),
                note=prop.note,
            )
            joined = _norm(" ".join(evidence[ref].excerpt for ref in known))
            marker = _norm(prop.matched_text)
            if marker and marker.lower() not in joined.lower() and prop.layer != ClaimLayer.OBSERVED.value:
                state = VerificationState.PARTIALLY_SUPPORTED.value
                notes.append("marcador no verificable en la evidencia")

    # 3/9. Contradicción y negación (solo si la negación toca al marcador).
    if state != VerificationState.UNSUPPORTED.value:
        signals = analyze_language(statement_text)
        name = _property_key(prop.name)
        # La negación solo baja la fuerza si modifica DIRECTAMENTE al operador
        # ("not equal"), no si aparece en la ventana de contexto ("unless ...
        # greater than").
        negated_marker = bool(
            re.search(
                r"\b(?:not|no|never|nunca|sin)\s+\w{0,12}\s*"
                r"(?:greater|less|equal|between|outside|mayor|menor|igual|entre)\b",
                prop.matched_text,
                re.IGNORECASE,
            )
        )
        if name == "comparison.operator":
            operator = str(prop.value or "")
            if negated_marker and operator in (
                ComparisonOperator.EQ.value,
                ComparisonOperator.GT.value,
                ComparisonOperator.GTE.value,
                ComparisonOperator.BETWEEN.value,
            ):
                # La negación léxica de la cláusula baja la fuerza, no se descarta.
                state = VerificationState.PARTIALLY_SUPPORTED.value
                notes.append("negación en la cláusula; operador no confirmado")
        if name == "matching.operator" and str(prop.value or "") == MatchOperator.UNKNOWN.value:
            state = VerificationState.PARTIALLY_SUPPORTED.value
        if str(prop.value or "") == LengthPolicy.UNKNOWN.value:
            state = VerificationState.PARTIALLY_SUPPORTED.value
            if "length_policy" not in missing:
                missing.append("length_policy")

    # 5. Alcance/sección: propiedad cuya evidencia no tiene locator no es dura.
    if state == VerificationState.SUPPORTED.value and prop.evidence:
        first = evidence.get(prop.evidence[0])
        if first is not None and not first.locator and len(candidate.evidence) > 1:
            state = VerificationState.PARTIALLY_SUPPORTED.value
            notes.append("evidencia sin locator físico")

    # 6. Unidades: la ausencia ya viene declarada como missing premise.
    if any(value.startswith("unit:") for value in missing):
        state = min_state(state, VerificationState.PARTIALLY_SUPPORTED.value)

    # 7. Dirección: comparación con GT/GTE/LT/LTE exige operando derecho o queda parcial.
    name = _property_key(prop.name)
    if name == "comparison.operator" and str(prop.value or "") in (
        ComparisonOperator.GT.value,
        ComparisonOperator.GTE.value,
        ComparisonOperator.LT.value,
        ComparisonOperator.LTE.value,
    ):
        has_right = any(
            key.startswith("comparison.right") and value.known
            for key, value in candidate.properties.items()
        )
        if not has_right:
            state = min_state(state, VerificationState.PARTIALLY_SUPPORTED.value)
            if "comparison.right_operand" not in missing:
                missing.append("comparison.right_operand")
            notes.append("dirección sin operando derecho explícito")

    # 8. Inclusividad: rango sin marcador no se asume inclusivo.
    if (
        name in ("query.boundary", "quantity.boundary", "comparison.boundary")
        and str(prop.value or "") == BoundaryKind.UNKNOWN.value
    ):
        state = min_state(state, VerificationState.PARTIALLY_SUPPORTED.value)
        if "boundary" not in missing:
            missing.append("boundary")

    prop.state = state
    prop.missing_premises = list(dict.fromkeys(missing))
    if notes:
        prop.note = (prop.note + "; " if prop.note else "") + "; ".join(notes)
    return prop


_STATE_ORDER = {
    VerificationState.UNSUPPORTED.value: 0,
    VerificationState.UNKNOWN.value: 1,
    VerificationState.PARTIALLY_SUPPORTED.value: 2,
    VerificationState.CONFLICTING.value: 3,
    VerificationState.PROPOSED.value: 4,
    VerificationState.SUPPORTED.value: 5,
}


def min_state(left: str, right: str) -> str:
    return left if _STATE_ORDER.get(left, 0) <= _STATE_ORDER.get(right, 0) else right


def is_pattern_relative_length(rule: CanonicalRule) -> bool:
    """¿La política de longitud se mide contra la longitud del patrón?

    Políticas como "at least the number of characters referenced in the field
    (additional characters may follow)" no declaran número: el valor runtime se
    compara contra la longitud del patrón. Se exige señal explícita (operandos
    direccionales o nota declarada); jamás se asume.
    """
    for name, prop in (getattr(rule, "properties", {}) or {}).items():
        if not getattr(prop, "known", False):
            continue
        value = str(getattr(prop, "value", "") or "").lower()
        if name.endswith("right_operand") and value == "pattern":
            return True
        if name.endswith("left_operand") and value == "value":
            return True
        note = str(getattr(prop, "note", "") or "").lower()
        if "additional characters may follow" in note:
            return True
        if "length referenced by the pattern" in note:
            return True
    return False


def _required_execution_missing(rule: CanonicalRule) -> list[str]:
    """Premisas que impiden ejecución determinista (UNKNOWN no se ejecuta)."""
    missing: list[str] = []
    for name in _EXECUTION_CRITICAL:
        prop = rule.properties.get(name)
        if prop is None:
            continue
        if not prop.known:
            missing.append(name)
            continue
        if name == "matching.operator" and str(prop.value) == MatchOperator.UNKNOWN.value:
            missing.append("matching_policy")
        if name == "length.policy":
            policy = str(prop.value)
            if policy == LengthPolicy.UNKNOWN.value:
                missing.append("length_policy")
            elif numeric_length_policy(policy) and prop.value is not None:
                value_prop = rule.properties.get("length.value")
                upper_prop = rule.properties.get("length.upper")
                # Longitud relativa al patrón ("at least the number referenced
                # in the field"): no exige número; se mide contra el patrón.
                pattern_relative = is_pattern_relative_length(rule)
                if (value_prop is None or not value_prop.known) and not pattern_relative:
                    missing.append("length_value")
                if (
                    policy == LengthPolicy.RANGE.value
                    and (upper_prop is None or not upper_prop.known)
                    and not pattern_relative
                ):
                    missing.append("length_upper")
            elif asymmetric_length_policy(policy):
                has_roles = any(
                    key.startswith("length.left") for key in rule.properties
                ) and any(key.startswith("length.right") for key in rule.properties)
                has_matching = any(
                    key == "matching.operator" and prop.known
                    for key, prop in rule.properties.items()
                )
                if not has_roles and not has_matching:
                    missing.append("length_operand_role")
        if name == "comparison.operator":
            policy = str(prop.value)
            if policy in (ComparisonOperator.BETWEEN.value, ComparisonOperator.OUTSIDE_RANGE.value):
                boundary = next(
                    (
                        item
                        for key, item in rule.properties.items()
                        if key.startswith("comparison.boundary") and item.known
                    ),
                    None,
                )
                if boundary is None:
                    missing.append("boundary")
        if name == "formula.expression":
            target = rule.properties.get("formula.target")
            if target is None or not target.known:
                missing.append("formula_target")
    if rule.verification_state == VerificationState.CONFLICTING.value:
        missing.append("conflict")
    # ¿La regla declara ALGUNA semántica ejecutable? Una definición de símbolo
    # aislada no alcanza: sin política de matching/longitud/comparación no hay
    # decisión determinista posible.
    capable = False
    for name, prop in rule.properties.items():
        if not prop.known:
            continue
        if (
            name == "matching.operator"
            or name.startswith("length.")
            and name != "length.boundary"
            or name.startswith("comparison.operator")
            or name == "temporal.relation"
            or name == "formula.expression"
            or name.startswith("condition.only_if.")
            or name.startswith("scope.condition.")
            or name.startswith("exception.condition.")
            or name.startswith("quantity")
            and (name.endswith(".minimum") or name.endswith(".maximum"))
            or name in ("enumeration.allowed", "enumeration.prohibited")
        ):
            capable = True
            break
    if not capable and "executable_semantics" not in missing:
        missing.append("executable_semantics")
    return list(dict.fromkeys(missing))


def verify_candidate(candidate: CandidateRule) -> CanonicalRule:
    """CandidateRule -> CanonicalRule con verificación por propiedad."""
    evidence = _evidence_map(candidate)
    properties: dict[str, RuleProperty] = {}
    for name, prop in candidate.properties.items():
        properties[name] = _verify_property(
            candidate, prop, evidence, statement_text=candidate.statement
        )

    states = [prop.state for prop in properties.values()]
    conflicts = [state for state in states if state == VerificationState.CONFLICTING.value]
    supported = [state for state in states if state == VerificationState.SUPPORTED.value]
    unsupported = [state for state in states if state == VerificationState.UNSUPPORTED.value]
    if conflicts:
        verification_state = VerificationState.CONFLICTING.value
    elif not states:
        verification_state = VerificationState.UNKNOWN.value
    elif unsupported and not supported:
        verification_state = VerificationState.UNSUPPORTED.value
    elif supported and len(supported) == len(states):
        verification_state = VerificationState.SUPPORTED.value
    elif supported:
        verification_state = VerificationState.PARTIALLY_SUPPORTED.value
    else:
        verification_state = VerificationState.UNKNOWN.value

    # Excepciones: si la fuente declara excepción, no bloquea; se conserva.
    if candidate.exceptions:
        properties.setdefault(
            "exception.count",
            RuleProperty(
                name="exception.count",
                value=len(candidate.exceptions),
                evidence=[],
                state=VerificationState.SUPPORTED.value,
                note="excepciones conservadas",
            ),
        )

    rule = CanonicalRule(
        rule_id=stable_id(
            "rule",
            candidate.subject.lower(),
            candidate.statement.lower()[:400],
            candidate.kind,
            candidate.operator,
        ),
        statement=candidate.statement,
        subject=candidate.subject,
        kind=candidate.kind,
        modality=candidate.modality,
        polarity=candidate.polarity,
        operator=candidate.operator,
        arguments=list(candidate.arguments),
        properties=properties,
        conditions=list(candidate.conditions),
        consequences=list(candidate.consequences),
        exceptions=list(candidate.exceptions),
        scope=candidate.scope,
        temporal=candidate.temporal,
        formula=candidate.formula,
        enumeration=candidate.enumeration,
        provenance=list(candidate.evidence),
        corroborating=list(candidate.corroborating),
        relations=dict(candidate.relations),
        confidence=candidate.confidence,
        extraction_method=candidate.extraction_method,
        verification_state=verification_state,
        ambiguities=list(candidate.ambiguities),
        missing_premises=list(candidate.missing_premises),
    )
    missing = _required_execution_missing(rule)
    for value in missing:
        if value not in rule.missing_premises:
            rule.missing_premises.append(value)
    executable = (
        verification_state == VerificationState.SUPPORTED.value
        and rule.kind not in _NON_EXECUTABLE_KINDS
        and not rule.missing_premises
    )
    if rule.kind == RuleKind.FORMULA.value:
        executable = bool(rule.formula.expression) and executable
    rule.executable = bool(executable)
    return rule


def recompute_execution(rule: CanonicalRule) -> CanonicalRule:
    """Recalcula premisas faltantes y ejecutabilidad tras un merge/edición.

    Solo SUPPORTED con premisas cerradas ejecuta. Una propiedad UNKNOWN o un
    conflicto bloquean la ejecución y quedan nombrados en missing_premises.
    """
    missing: list[str] = [
        value
        for value in rule.missing_premises
        if value not in ("conflict", "executable_semantics")
    ]
    for prop in rule.properties.values():
        for value in prop.missing_premises:
            if value not in missing:
                missing.append(value)
    for value in _required_execution_missing(rule):
        if value not in missing:
            missing.append(value)
    rule.missing_premises = list(dict.fromkeys(missing))[:24]
    rule.executable = bool(
        rule.verification_state == VerificationState.SUPPORTED.value
        and rule.kind not in _NON_EXECUTABLE_KINDS
        and not rule.missing_premises
    )
    if rule.kind == RuleKind.FORMULA.value:
        rule.executable = bool(rule.formula.expression) and rule.executable
    return rule


# -----------------------------------------------------------------------------
# Conflictos entre reglas
# -----------------------------------------------------------------------------


def _canonical_value(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return "|".join(sorted(str(item).lower() for item in value))
    if isinstance(value, dict):
        return "|".join(f"{key}={value[key]}" for key in sorted(value))
    return " ".join(str(value or "").lower().split())


#: Dimensiones comparables: mismo nombre base -> mismo eje semántico. Evita
#: falsos conflictos entre dimensiones distintas (alphabet vs operator).
_COMPARABLE_DIMENSIONS: frozenset[str] = frozenset(
    {
        "length.policy",
        "length.value",
        "length.upper",
        "length.boundary",
        "matching.operator",
        "matching.literal",
        "matching.case_sensitive",
        "matching.alphabet",
        "matching.prohibited_alphabet",
        "matching.fixed_position",
        "comparison.operator",
        "comparison.boundary",
        "temporal.relation",
        "quantity.minimum",
        "quantity.maximum",
        "quantity.unit",
        "enumeration.allowed",
        "enumeration.prohibited",
        "formula.expression",
    }
)


def _comparable_props(rule: CanonicalRule) -> dict[str, RuleProperty]:
    props: dict[str, RuleProperty] = {}
    for name, prop in rule.properties.items():
        if not prop.known:
            continue
        base = _property_key(name)
        if base in _COMPARABLE_DIMENSIONS:
            props.setdefault(base, prop)
    return props


def _resolution_for(
    rule_a: CanonicalRule,
    rule_b: CanonicalRule,
    *,
    property_name: str,
) -> tuple[str | None, str]:
    """Resolución SOLO con base declarada: versión, vigencia, prioridad, scope."""
    # 1b. Vigencia declarada en una sola regla: la fecha runtime decide; el
    # compilador NO elige una versión en silencio (conflicto temporal).
    if rule_a.scope.effective_from or rule_b.scope.effective_from:
        return None, "temporal"
    # 1. Vigencia explícita posterior.
    if rule_a.scope.effective_from and rule_b.scope.effective_from:
        if rule_a.scope.effective_from > rule_b.scope.effective_from:
            return rule_a.rule_id, "effective_from posterior"
        if rule_b.scope.effective_from > rule_a.scope.effective_from:
            return rule_b.rule_id, "effective_from posterior"
    # 2. version_label declarado.
    if rule_a.scope.version_label and rule_b.scope.version_label:
        if rule_a.scope.version_label != rule_b.scope.version_label:
            if rule_a.scope.version_label > rule_b.scope.version_label:
                return rule_a.rule_id, "version_label mayor"
            return rule_b.rule_id, "version_label mayor"
    # 3. supersede explícito por statement.
    a_signals = analyze_language(rule_a.statement)
    b_signals = analyze_language(rule_b.statement)
    a_supersedes = {item.operator for item in a_signals.logic} & {"OVERRIDE", "PRECEDENCE"}
    b_supersedes = {item.operator for item in b_signals.logic} & {"OVERRIDE", "PRECEDENCE"}
    if a_supersedes and not b_supersedes:
        return rule_a.rule_id, "override/precedence explícito"
    if b_supersedes and not a_supersedes:
        return rule_b.rule_id, "override/precedence explícito"
    # 4. prioridad numérica explícita.
    if rule_a.scope.priority is not None and rule_b.scope.priority is not None:
        if rule_a.scope.priority != rule_b.scope.priority:
            winner = rule_a if rule_a.scope.priority > rule_b.scope.priority else rule_b
            return winner.rule_id, "priority explícita"
    # 5. especificidad de alcance (más contexto de sección gana).
    a_specificity = (len(rule_a.scope.section_path), len(rule_a.provenance))
    b_specificity = (len(rule_b.scope.section_path), len(rule_b.provenance))
    if a_specificity != b_specificity and (a_specificity[0] != b_specificity[0]):
        winner = rule_a if a_specificity > b_specificity else rule_b
        return winner.rule_id, "mayor especificidad de alcance"
    return None, ""


def detect_rule_conflicts(rules: Sequence[CanonicalRule]) -> tuple[list[RuleConflict], list[CanonicalRule]]:
    """Detecta y clasifica conflictos por DIMENSIÓN; muta estados de reglas."""
    conflicts: list[RuleConflict] = []
    by_subject: dict[str, list[CanonicalRule]] = {}
    for rule in rules:
        if rule.kind == RuleKind.EXAMPLE.value:
            continue
        subject_key = " ".join(rule.subject.lower().split())[:160]
        if not subject_key:
            continue
        by_subject.setdefault(subject_key, []).append(rule)

    for subject_key, group in by_subject.items():
        if len(group) < 2:
            continue
        for index, rule_a in enumerate(group):
            for rule_b in group[index + 1 :]:
                props_a = _comparable_props(rule_a)
                props_b = _comparable_props(rule_b)
                for dimension, prop_a in props_a.items():
                    prop_b = props_b.get(dimension)
                    if prop_b is None:
                        continue
                    raw_a, raw_b = prop_a.value, prop_b.value
                    if _canonical_value(raw_a) == _canonical_value(raw_b):
                        continue
                    # Una excepción declarada explica la diferencia: no es conflicto.
                    if rule_a.exceptions or rule_b.exceptions:
                        continue
                    resolution, basis = _resolution_for(
                        rule_a, rule_b, property_name=dimension
                    )
                    conflict = RuleConflict(
                        conflict_id=stable_id(
                            "conflict", subject_key, dimension, rule_a.rule_id, rule_b.rule_id
                        ),
                        property_name=dimension,
                        rule_a_id=rule_a.rule_id,
                        rule_b_id=rule_b.rule_id,
                        value_a=raw_a,
                        value_b=raw_b,
                        reason=f"dimensión {dimension} incompatible para '{subject_key[:80]}'",
                        resolution=resolution,
                        resolution_basis=basis,
                        evidence=list(
                            dict.fromkeys(
                                [*rule_a.evidence_ids(), *rule_b.evidence_ids()]
                            )
                        ),
                        materiality="HIGH"
                        if dimension
                        in (
                            "length.policy",
                            "comparison.operator",
                            "enumeration.allowed",
                            "enumeration.prohibited",
                        )
                        else "MEDIUM",
                    )
                    conflicts.append(conflict)
                    if basis == "temporal":
                        # Conflicto de versiones: ambas quedan ejecutables y la
                        # fecha runtime selecciona. Sin fecha, evaluación
                        # devuelve UNDETERMINED (nunca elección arbitraria).
                        for rule in (rule_a, rule_b):
                            other = rule_b.rule_id if rule is rule_a else rule_a.rule_id
                            choices = rule.relations.setdefault("TEMPORAL_CHOICE", [])
                            if other not in choices:
                                choices.append(other)
                        continue
                    if resolution is None:
                        for rule in (rule_a, rule_b):
                            other = rule_b.rule_id if rule is rule_a else rule_a.rule_id
                            if other not in rule.conflicts_with:
                                rule.conflicts_with.append(other)
                            rule.verification_state = VerificationState.CONFLICTING.value
                            rule.executable = False
                            if "conflict" not in rule.missing_premises:
                                rule.missing_premises.append("conflict")
                    else:
                        loser = rule_b if resolution == rule_a.rule_id else rule_a
                        winner = rule_a if resolution == rule_a.rule_id else rule_b
                        if winner.rule_id not in loser.supersedes:
                            loser.supersedes.append(winner.rule_id)
                        loser.executable = False
    return conflicts, list(rules)

__all__ = [
    "detect_rule_conflicts",
    "is_pattern_relative_length",
    "min_state",
    "recompute_execution",
    "verify_candidate",
]
