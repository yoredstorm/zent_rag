# =============================================================================
# Semantic Rule Compiler — fusión de reglas distribuidas
# =============================================================================
# Una regla documental puede estar repartida: política de longitud en una
# página, definición de símbolo en otra, operador de matching en una tercera.
# Fusionar es unir SEMÁNTICA COMPATIBLE, nunca pisar valores:
#
#   - familias de política con valores distintos -> NO se fusionan
#     (quedan separadas para que detect_rule_conflicts las confronte)
#   - valores iguales/ausentes -> se fusionan con provenance de TODAS las
#     piezas y evidence propio por propiedad
#   - excepciones -> se conservan, jamás se descartan
# =============================================================================
from __future__ import annotations

from typing import Any, Sequence

from src.core.domain.rule_semantics import ClaimLayer, RuleKind, VerificationState

from .model import CanonicalRule, RuleEvidence, RuleProperty, stable_id
from .verify import min_state, recompute_execution

_MERGE_FAMILIES = (
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
    "temporal.relation",
    "quantity.minimum",
    "quantity.maximum",
    "quantity.unit",
    "enumeration.allowed",
    "enumeration.prohibited",
    "formula.expression",
)

_GRAMMAR_PREFIXES = (
    "length.",
    "matching.",
)

#: Prioridad de tipo al fusionar: la regla ejecutable manda sobre la definición.
_KIND_PRIORITY: dict[str, int] = {
    RuleKind.NORMATIVE_RULE.value: 6,
    RuleKind.CONSTRAINT.value: 5,
    RuleKind.FORMULA.value: 4,
    RuleKind.EXCEPTION.value: 3,
    RuleKind.DEFINITION.value: 2,
    RuleKind.MAPPING.value: 1,
    RuleKind.REFERENCE.value: 0,
    RuleKind.PROCEDURE.value: 0,
    RuleKind.NOTE.value: 0,
    RuleKind.EXAMPLE.value: 0,
}


def _dominant_kind(left: str, right: str) -> str:
    return (
        left
        if _KIND_PRIORITY.get(left, 0) >= _KIND_PRIORITY.get(right, 0)
        else right
    )


def _canonical_value(value) -> str:
    if isinstance(value, (list, tuple, set)):
        return "|".join(sorted(str(item).lower() for item in value))
    if isinstance(value, dict):
        return "|".join(f"{key}={value[key]}" for key in sorted(value))
    return " ".join(str(value or "").lower().split())


def _policy_values(rule: CanonicalRule) -> dict[str, set[str]]:
    """Valores por DIMENSIÓN (mismo nombre base), no por familia amplia."""
    import re

    values: dict[str, set[str]] = {}
    for name, prop in rule.properties.items():
        if not prop.known:
            continue
        base = re.sub(r"\.\d+$", "", name)
        if base.startswith("matching.symbol.") or base == "observed.statement":
            continue
        if base in _MERGE_FAMILIES:
            values.setdefault(base, set()).add(_canonical_value(prop.value))
    return values


def rules_compatible(left: CanonicalRule, right: CanonicalRule) -> bool:
    """¿Dos reglas pueden fusionarse sin pisar políticas incompatibles?"""
    if left.verification_state == VerificationState.CONFLICTING.value:
        return False
    if right.verification_state == VerificationState.CONFLICTING.value:
        return False
    if left.conflicts_with or right.conflicts_with:
        return False
    # Gramáticas de campos distintos no se contaminan: si ambos declaran
    # símbolos disjuntos Y políticas completas, son patrones diferentes. Una
    # definición de símbolo se une a su gramática aunque el símbolo no se repita.
    symbols_left = {
        name
        for name in left.properties
        if name.startswith("matching.symbol.") and not name.endswith(".alphabet")
    }
    symbols_right = {
        name
        for name in right.properties
        if name.startswith("matching.symbol.") and not name.endswith(".alphabet")
    }
    if symbols_left and symbols_right and not (symbols_left & symbols_right):
        def _has_policy(rule: CanonicalRule) -> bool:
            return any(
                name in ("matching.operator", "length.policy") and prop.known
                for name, prop in rule.properties.items()
            )

        same_subject = " ".join(left.subject.lower().split()) == " ".join(
            right.subject.lower().split()
        )
        left_policy = _has_policy(left)
        right_policy = _has_policy(right)
        if (left_policy and right_policy) or (
            not same_subject and not left_policy and not right_policy
        ):
            return False
    left_values = _policy_values(left)
    right_values = _policy_values(right)
    for dimension, values in left_values.items():
        other = right_values.get(dimension)
        if other and values and other and values != other:
            return False
    return True


def is_grammar_fragment(rule: CanonicalRule) -> bool:
    """Fragmento de gramática de matching: símbolo, longitud, operador."""
    if rule.kind == RuleKind.EXAMPLE.value:
        return False
    return any(
        name.startswith(_GRAMMAR_PREFIXES)
        for name, prop in rule.properties.items()
        if prop.known
    )


def _evidence_key(evidence: RuleEvidence) -> str:
    return evidence.evidence_id or evidence.unit_id or evidence.locator.get("locator", "")


def _alphabet_generality(value: Any) -> int:
    """Generalidad de un alfabeto: la definición general manda sobre el ejemplo."""
    return {
        "": 0,
        "letter": 1,
        "digit": 1,
        "space": 1,
        "literal": 1,
        "alphanumeric": 2,
        "any_char": 3,
    }.get(str(value or "").strip().lower(), 0)


def _symbol_generality(name: str, prop: RuleProperty) -> int:
    """Generalidad de una propiedad de símbolo (definición o alfabeto)."""
    if name.endswith(".alphabet"):
        return _alphabet_generality(prop.value)
    text = str(prop.value or "").lower()
    if any(
        marker in text
        for marker in (
            "any character",
            "cualquier car",
            "any position",
            "cualquier posici",
        )
    ):
        return 3
    if any(
        marker in text
        for marker in (
            "alphanumeric",
            "alfanum",
            "letter or digit",
            "letra o d",
            "or alpha",
            "alpha or",
            "letter or",
        )
    ):
        return 2
    if any(
        marker in text
        for marker in ("number", "digit", "numeric", "letter", "alpha", "letra")
    ):
        return 1
    return 0


def merge_rule_pair(left: CanonicalRule, right: CanonicalRule) -> CanonicalRule:
    """Union de semántica compatible, evidencia y excepciones."""
    properties: dict[str, RuleProperty] = {}
    for name, prop in left.properties.items():
        if name in ("observed.statement", "modality", "polarity"):
            continue
        properties[name] = prop
    for name, prop in right.properties.items():
        if name in ("observed.statement", "modality", "polarity"):
            continue
        existing = properties.get(name)
        if existing is None:
            properties[name] = prop
            continue
        if _canonical_value(existing.value) == _canonical_value(prop.value):
            merged_evidence = list(dict.fromkeys([*existing.evidence, *prop.evidence]))
            properties[name] = RuleProperty(
                name=existing.name,
                value=existing.value,
                value_kind=existing.value_kind,
                layer=existing.layer,
                state=min_state(existing.state, prop.state),
                evidence=merged_evidence,
                method=existing.method,
                confidence=max(existing.confidence, prop.confidence),
                explicit=existing.explicit or prop.explicit,
                matched_text=existing.matched_text or prop.matched_text,
                missing_premises=list(
                    dict.fromkeys([*existing.missing_premises, *prop.missing_premises])
                ),
                note=existing.note or prop.note,
            )
        elif name.startswith("matching.symbol.") and (
            name.endswith(".alphabet")
            or "." not in name[len("matching.symbol.") :]
        ):
            # Dos definiciones del MISMO símbolo: la más general manda
            # (alfanumérico sobre dígito/letra). La desplazada queda visible
            # como `.superseded` para auditoría, nunca como decisión.
            if _symbol_generality(name, prop) > _symbol_generality(name, existing):
                properties[name] = prop
                properties[f"{name}.superseded"] = existing
            else:
                properties[f"{name}.superseded"] = prop
        elif existing.explicit and prop.explicit and existing.value != prop.value:
            # Valores incompatibles no se fusionan en silencio.
            properties[f"{name}.unmerged"] = prop
    provenance: list[RuleEvidence] = []
    seen: set[str] = set()
    for evidence in [*left.provenance, *right.provenance]:
        key = _evidence_key(evidence)
        if key in seen:
            continue
        seen.add(key)
        provenance.append(evidence)
    corroborating: list[RuleEvidence] = []
    seen_corroborating: set[str] = set()
    for evidence in [*left.corroborating, *right.corroborating]:
        key = _evidence_key(evidence)
        if key in seen_corroborating:
            continue
        seen_corroborating.add(key)
        corroborating.append(evidence)

    statements = []
    for statement in (left.statement, right.statement):
        text = " ".join(statement.split())
        if text and text not in statements:
            statements.append(text)
    merged_statement = " | ".join(statements)[:2000]

    # Modalidad/polaridad: gana la fuerza declarada, con evidencia unida.
    from src.core.domain.rule_semantics import MODALITY_STRENGTH

    modality_sources = [
        (left.modality, left.properties.get("modality")),
        (right.modality, right.properties.get("modality")),
    ]
    merged_modality = max(
        (left.modality, right.modality),
        key=lambda value: MODALITY_STRENGTH.get(value, 0.0),
    )
    modality_evidence: list[str] = []
    polarity_value = (
        left.polarity if left.modality == merged_modality else right.polarity
    )
    for _modality_value, prop in modality_sources:
        if prop is not None:
            modality_evidence.extend(prop.evidence)
    left_modality_prop = left.properties.get("modality")
    right_modality_prop = right.properties.get("modality")
    left_polarity_prop = left.properties.get("polarity")
    right_polarity_prop = right.properties.get("polarity")
    properties["modality"] = RuleProperty(
        name="modality",
        value=merged_modality,
        state=min_state(
            left_modality_prop.state
            if left_modality_prop
            else VerificationState.SUPPORTED.value,
            right_modality_prop.state
            if right_modality_prop
            else VerificationState.SUPPORTED.value,
        ),
        evidence=list(dict.fromkeys(modality_evidence)),
        confidence=max(left.confidence, right.confidence),
        note="modalidades unidas: gana la más fuerte"
        if left.modality != right.modality
        else "",
    )
    if polarity_value != "UNKNOWN":
        properties["polarity"] = RuleProperty(
            name="polarity",
            value=polarity_value,
            state=min_state(
                left_polarity_prop.state
                if left_polarity_prop
                else VerificationState.SUPPORTED.value,
                right_polarity_prop.state
                if right_polarity_prop
                else VerificationState.SUPPORTED.value,
            ),
            evidence=list(dict.fromkeys(modality_evidence)),
            confidence=max(left.confidence, right.confidence),
        )

    observed_states = [
        prop.state
        for prop in (
            left.properties.get("observed.statement"),
            right.properties.get("observed.statement"),
        )
        if prop is not None
    ]
    observed_evidence: list[str] = []
    for prop in (
        left.properties.get("observed.statement"),
        right.properties.get("observed.statement"),
    ):
        if prop is not None:
            observed_evidence.extend(prop.evidence)
    properties["observed.statement"] = RuleProperty(
        name="observed.statement",
        value=merged_statement,
        layer=ClaimLayer.OBSERVED.value,
        state=min_state(observed_states[0], observed_states[1])
        if len(observed_states) > 1
        else (observed_states[0] if observed_states else VerificationState.SUPPORTED.value),
        evidence=list(dict.fromkeys(observed_evidence)),
        explicit=True,
    )
    merged_id = stable_id(
        "rule",
        "merged",
        "|".join(sorted([left.rule_id, right.rule_id])),
    )
    return CanonicalRule(
        rule_id=merged_id,
        statement=merged_statement,
        subject=left.subject or right.subject,
        kind=_dominant_kind(left.kind, right.kind),
        modality=left.modality if left.modality != "NONE" else right.modality,
        polarity=left.polarity if left.polarity != "UNKNOWN" else right.polarity,
        operator=left.operator or right.operator,
        arguments=[*left.arguments, *right.arguments][:16],
        properties=properties,
        conditions=list(dict.fromkeys([*left.conditions, *right.conditions]))[:24],
        consequences=list(dict.fromkeys([*left.consequences, *right.consequences]))[:24],
        exceptions=list(dict.fromkeys([*left.exceptions, *right.exceptions]))[:24],
        scope=left.scope if left.scope.section_path else right.scope,
        temporal=left.temporal if left.temporal.relation != "UNKNOWN" else right.temporal,
        formula=left.formula if left.formula.expression else right.formula,
        enumeration=(
            left.enumeration
            if (left.enumeration.allowed or left.enumeration.prohibited)
            else right.enumeration
        ),
        provenance=provenance[:48],
        corroborating=corroborating[:16],
        relations={
            **dict(left.relations),
            **dict(right.relations),
            "MERGED_FROM": list(
                dict.fromkeys(
                    [
                        *left.relations.get("MERGED_FROM", []),
                        *right.relations.get("MERGED_FROM", []),
                        left.rule_id,
                        right.rule_id,
                    ]
                )
            ),
        },
        confidence=max(left.confidence, right.confidence),
        extraction_method=left.extraction_method,
        verification_state=min_state(left.verification_state, right.verification_state),
        executable=False,
        ambiguities=list(dict.fromkeys([*left.ambiguities, *right.ambiguities]))[:24],
        missing_premises=list(
            dict.fromkeys([*left.missing_premises, *right.missing_premises])
        )[:24],
        conflicts_with=[],
        supersedes=list(dict.fromkeys([*left.supersedes, *right.supersedes])),
    )


def merge_distributed_rules(
    rules: Sequence[CanonicalRule],
    *,
    grammar_only: bool = True,
) -> list[CanonicalRule]:
    """Fusiona fragmentos de regla compatibles; el resto queda intacto.

    ``grammar_only=True`` fusiona fragmentos de gramática (matching/length),
    que es donde la distribución entre páginas es estructural. Otras familias
    se evalúan por separado.

    Entre varios clústeres compatibles se prefiere el de operador de MÁSCARA
    (POSITIONAL/FIXED_POSITION/...): una política de longitud pertenece a la
    gramática del patrón, no a una regla de comparación de campos.
    """
    rules = list(rules)
    fragments = [
        rule for rule in rules if (not grammar_only or is_grammar_fragment(rule))
    ]
    fragment_ids = {id(rule) for rule in fragments}
    others = [rule for rule in rules if id(rule) not in fragment_ids]
    clusters: list[CanonicalRule] = []
    for rule in fragments:
        best_index = -1
        best_score: tuple[int, int, int] | None = None
        for index, cluster in enumerate(clusters):
            if not rules_compatible(cluster, rule):
                continue
            score = _cluster_preference(cluster, rule)
            if best_score is None or score > best_score:
                best_score = score
                best_index = index
        if best_index >= 0:
            clusters[best_index] = merge_rule_pair(clusters[best_index], rule)
        else:
            clusters.append(rule)
    result: list[CanonicalRule] = []
    for cluster in [*clusters, *others]:
        recompute_execution(cluster)
        result.append(cluster)
    return result


#: Operadores que describen la gramática del patrón (máscara), no comparación.
_MASK_OPERATORS = frozenset({"POSITIONAL", "FIXED_POSITION", "PREFIX", "SUFFIX"})


def _rule_symbols(rule: CanonicalRule) -> set[str]:
    return {
        name[len("matching.symbol.") :]
        for name in rule.properties
        if name.startswith("matching.symbol.") and not name.endswith(".alphabet")
    }


def _cluster_preference(
    cluster: CanonicalRule, fragment: CanonicalRule
) -> tuple[int, int, int]:
    operator_prop = cluster.properties.get("matching.operator")
    operator = (
        str(operator_prop.value or "").upper()
        if operator_prop is not None and operator_prop.known
        else ""
    )
    mask = 1 if operator in _MASK_OPERATORS else 0
    overlap = len(_rule_symbols(cluster) & _rule_symbols(fragment))
    return (mask, overlap, len(cluster.properties))


__all__ = [
    "is_grammar_fragment",
    "merge_distributed_rules",
    "merge_rule_pair",
    "rules_compatible",
]
