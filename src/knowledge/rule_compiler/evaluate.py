# =============================================================================
# Semantic Rule Compiler — ejecución determinista de reglas canónicas
# =============================================================================
# El LLM EXPLICA; el código DECIDE cuando la regla compilada es ejecutable:
#
#   premisas grounded (CanonicalRule SUPPORTED)
#   + datos runtime del escenario
#   + operación determinista
#   = DerivedClaim
#
# Honestidad primero:
#   - regla no SUPPORTED / con conflicto -> UNDETERMINED (no se ejecuta)
#   - propiedad UNKNOWN -> UNDETERMINED + missing_premises (jamás default)
#   - entre rango inclusivo/exclusivo sin marcador -> UNDETERMINED boundary
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Sequence

from src.core.domain.rule_semantics import (
    COMPARISON_TO_OPERATION,
    COUNT_UNITS,
    BoundaryKind,
    ComparisonOperator,
    LengthPolicy,
    MatchOperator,
    TemporalRelation,
    VerificationState,
)
from src.intelligence.reasoning.operations import (
    DEFAULT_REGISTRY,
    OperationRegistry,
    OperationResult,
    OperationStatus,
)

from .model import CanonicalRule
from .pattern_bridge import pattern_semantics_from_rule
from .verify import is_pattern_relative_length

EVALUATION_VERSION = "rule-evaluation-1"

_IDENTIFIER_RE = re.compile(r"[a-z_áéíóúñ][a-z0-9_áéíóúñ]*", re.IGNORECASE)


class RuleEvaluationStatus(StrEnum):
    MATCH = "MATCH"
    NO_MATCH = "NO_MATCH"
    UNDETERMINED = "UNDETERMINED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RequirementState(StrEnum):
    SATISFIED = "SATISFIED"
    MISSING = "MISSING"
    CONFLICTING = "CONFLICTING"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(kw_only=True)
class RuleRequirement:
    """Premisa necesaria para ejecutar la regla, con estado explícito.

    Nunca convierte MISSING en default: un requisito faltante bloquea la
    ejecución y queda nombrado.
    """

    requirement_id: str
    kind: str
    state: str = RequirementState.MISSING.value
    detail: str = ""
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "requirement_id": self.requirement_id,
            "kind": self.kind,
            "state": self.state,
            "detail": self.detail[:240],
            "evidence": list(self.evidence[:8]),
        }


@dataclass(kw_only=True)
class RuleCheck:
    """Un chequeo determinista con su operación y resultado."""

    name: str
    operation: str
    status: str
    result: Any = None
    detail: str = ""
    evidence: list[str] = field(default_factory=list)
    missing_premises: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "operation": self.operation,
            "status": self.status,
            "result": self.result,
            "detail": self.detail[:240],
            "evidence": list(self.evidence[:8]),
            "missing_premises": list(self.missing_premises[:8]),
        }


@dataclass(kw_only=True)
class RuleEvaluation:
    """Resultado determinista de aplicar una CanonicalRule a datos runtime."""

    rule_id: str
    status: str
    operation: str = ""
    result: Any = None
    checks: list[RuleCheck] = field(default_factory=list)
    missing_premises: list[str] = field(default_factory=list)
    premises_used: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    inputs: dict = field(default_factory=dict)
    reason: str = ""
    requirements: list[RuleRequirement] = field(default_factory=list)
    condition_results: list[dict] = field(default_factory=list)
    logic: str = "AND"
    exceptions_applied: list[str] = field(default_factory=list)
    version: str = EVALUATION_VERSION

    @property
    def derived(self) -> bool:
        return self.status in (
            RuleEvaluationStatus.MATCH.value,
            RuleEvaluationStatus.NO_MATCH.value,
        )

    def to_public_dict(self) -> dict:
        return {
            "version": self.version,
            "rule_id": self.rule_id,
            "status": self.status,
            "operation": self.operation,
            "result": self.result,
            "checks": [check.to_dict() for check in self.checks[:8]],
            "missing_premises": list(self.missing_premises[:12]),
            "premises_used": list(self.premises_used[:12]),
            "evidence_refs": list(self.evidence_refs[:12]),
            "inputs": {str(key)[:60]: str(value)[:120] for key, value in list(self.inputs.items())[:12]},
            "reason": self.reason[:240],
            "requirements": [item.to_dict() for item in self.requirements[:12]],
            "condition_results": [dict(item) for item in self.condition_results[:12]],
            "logic": self.logic,
            "exceptions_applied": list(self.exceptions_applied[:6]),
        }


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _as_number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    text = str(value or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if float(number).is_integer() else number


def _parse_ref_date(value: Any) -> Any:
    """Fecha de referencia/ventana -> date (ISO, d/m/Y, '15 March 2026')."""
    if value is None:
        return None
    from datetime import date, datetime

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = " ".join(str(value or "").split())
    if not text:
        return None
    for fmt in (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
        "%d.%m.%Y",
        "%d %B %Y",
        "%d %b %Y",
        "%B %d, %Y",
        "%B %Y",
    ):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.date()
        except ValueError:
            continue
    return None


def _resolve_value(name: str, values: Mapping[str, Any]) -> Any:
    """Resuelve un operando por nombre, con match exacto y por contención."""
    if not name:
        return None
    wanted = _norm(name)
    for key, value in values.items():
        if _norm(key) == wanted:
            return value
    for key, value in values.items():
        normalized = _norm(key)
        if normalized and (wanted in normalized or normalized in wanted):
            return value
    return None


def _operand_pair(
    rule: CanonicalRule,
    values: Mapping[str, Any],
    *,
    prefix: str,
) -> tuple[Any, Any, list[str]]:
    """(left, right, missing) desde propiedades comparison./length."""
    missing: list[str] = []
    left_name = ""
    right_name = ""
    for key, prop in rule.properties.items():
        if key.startswith(f"{prefix}.left") and prop.known:
            left_name = str(prop.value)
        if key.startswith(f"{prefix}.right") and prop.known:
            right_name = str(prop.value)
    left = _resolve_value(left_name, values) if left_name else values.get("value")
    right = _resolve_value(right_name, values) if right_name else values.get("pattern")
    if left is None:
        missing.append(f"operand:{left_name or 'left'}")
    if right is None:
        missing.append(f"operand:{right_name or 'right'}")
    return left, right, missing


def _extract_numbers(text: Any) -> list[float]:
    return [
        float(value.replace(',', '.'))
        for value in re.findall(r'-?\d+(?:[.,]\d+)?', str(text or ''))
    ]


def _comparison_check(
    *,
    operator: str,
    left: Any,
    right: Any,
    boundary: str,
    evidence: list[str],
    check_value: Any = None,
    bounds: Sequence[float] = (),
    registry: OperationRegistry,
) -> RuleCheck:
    if operator in (ComparisonOperator.BETWEEN.value, ComparisonOperator.OUTSIDE_RANGE.value):
        if len(bounds) < 2:
            return RuleCheck(
                name="comparison",
                operation="RANGE_CHECK",
                status=RuleEvaluationStatus.UNDETERMINED.value,
                missing_premises=["comparison_bounds"],
                detail="rango sin limites numericos",
                evidence=evidence,
            )
        if boundary == BoundaryKind.UNKNOWN.value or not boundary:
            return RuleCheck(
                name="comparison",
                operation="RANGE_CHECK",
                status=RuleEvaluationStatus.UNDETERMINED.value,
                missing_premises=["boundary"],
                detail="rango sin inclusividad declarada",
                evidence=evidence,
            )
        if check_value is None:
            return RuleCheck(
                name="comparison",
                operation="RANGE_CHECK",
                status=RuleEvaluationStatus.UNDETERMINED.value,
                missing_premises=["input:value"],
                detail="rango sin valor de escenario",
                evidence=evidence,
            )
        low, high = min(bounds[0], bounds[1]), max(bounds[0], bounds[1])
        outcome = registry.run(
            "RANGE_CHECK",
            value=_as_number(check_value),
            minimum=low,
            maximum=high,
            inclusive=boundary == BoundaryKind.INCLUSIVE.value,
        )
        if operator == ComparisonOperator.OUTSIDE_RANGE.value and outcome.ok:
            outcome = OperationResult(
                operation=outcome.operation,
                status=outcome.status,
                value=not bool(outcome.value),
                explanation=outcome.explanation + " (outside)",
                inputs=outcome.inputs,
            )
    else:
        comparison_op = COMPARISON_TO_OPERATION.get(operator)
        if comparison_op is None:
            return RuleCheck(
                name="comparison",
                operation="COMPARISON",
                status=RuleEvaluationStatus.UNDETERMINED.value,
                missing_premises=[f"comparison_operator:{operator}"],
                detail="operador no soportado",
                evidence=evidence,
            )
        missing: list[str] = []
        if left is None:
            missing.append("operand:left")
        if right is None:
            missing.append("operand:right")
        if missing:
            return RuleCheck(
                name="comparison",
                operation="COMPARISON",
                status=RuleEvaluationStatus.UNDETERMINED.value,
                missing_premises=missing,
                detail="faltan operandos de comparacion",
                evidence=evidence,
            )
        outcome = registry.run("COMPARISON", a=left, b=right, op=comparison_op)
    if not outcome.ok:
        return RuleCheck(
            name="comparison",
            operation=outcome.operation,
            status=RuleEvaluationStatus.UNDETERMINED.value,
            missing_premises=[outcome.error or "comparison_error"],
            detail=outcome.explanation or outcome.error,
            evidence=evidence,
        )
    return RuleCheck(
        name="comparison",
        operation=outcome.operation,
        status=(
            RuleEvaluationStatus.MATCH.value
            if bool(outcome.value)
            else RuleEvaluationStatus.NO_MATCH.value
        ),
        result=bool(outcome.value),
        detail=outcome.explanation,
        evidence=evidence,
    )


def _check_comparisons(
    rule: CanonicalRule,
    values: Mapping[str, Any],
    registry: OperationRegistry,
) -> list[RuleCheck]:
    """Un check por dimension de comparacion declarada (AND implicito)."""
    checks: list[RuleCheck] = []
    operators = {
        name: prop
        for name, prop in rule.properties.items()
        if re.match(r'comparison\.operator(?:\.\d+)?$', name) and prop.known
    }
    if not operators:
        return checks
    has_matching = any(
        name == 'matching.operator' and prop.known
        for name, prop in rule.properties.items()
    )
    has_quantity = any(
        name.endswith('.minimum') or name.endswith('.maximum')
        for name, prop in rule.properties.items()
        if prop.known
    )
    has_comparison_operands = any(
        name.startswith('comparison.left') or name.startswith('comparison.right')
        for name, prop in rule.properties.items()
        if prop.known
    )
    if not has_comparison_operands and has_matching:
        return checks
    for name in sorted(operators):
        prop = operators[name]
        suffix = name[len('comparison.operator') :]
        operator = str(prop.value)
        # Una política de longitud relativa al patrón ("at least the number of
        # characters referenced in the field") ya expresa la comparación de
        # magnitud: no se duplica como comparación de valores del escenario.
        if is_pattern_relative_length(rule) and operator in (
            ComparisonOperator.GT.value,
            ComparisonOperator.GTE.value,
            ComparisonOperator.LT.value,
            ComparisonOperator.LTE.value,
        ):
            continue
        left_prop = rule.properties.get(f'comparison.left{suffix}')
        right_prop = rule.properties.get(f'comparison.right{suffix}')
        boundary_prop = rule.properties.get(
            f'comparison.boundary{suffix}'
        ) or rule.properties.get('comparison.boundary')
        evidence = _property_evidence(
            rule,
            (
                f'comparison.operator{suffix}',
                f'comparison.left{suffix}',
                f'comparison.right{suffix}',
                f'comparison.boundary{suffix}',
            ),
        )
        left = _resolve_value(str(left_prop.value), values) if left_prop is not None and left_prop.known else None
        right = _resolve_value(str(right_prop.value), values) if right_prop is not None and right_prop.known else None
        bounds: list[float] = []
        if operator in (ComparisonOperator.BETWEEN.value, ComparisonOperator.OUTSIDE_RANGE.value):
            for raw in (
                left_prop.value if left_prop is not None and left_prop.known else None,
                right_prop.value if right_prop is not None and right_prop.known else None,
            ):
                bounds.extend(_extract_numbers(raw))
        if operator not in (ComparisonOperator.BETWEEN.value, ComparisonOperator.OUTSIDE_RANGE.value):
            if left is None:
                left = values.get('value')
            if right is None and right_prop is not None and right_prop.known:
                numbers = _extract_numbers(right_prop.value)
                if len(numbers) == 1:
                    right = numbers[0]
            if right is None:
                right = values.get('pattern')
            if right is None and has_quantity:
                # La dimensión de cantidad ya cubre el límite declarado.
                continue
            if left is None and right is None and has_quantity:
                continue
            if (
                isinstance(right, (int, float))
                and _as_number(left) is None
                and any(
                    name == "length.policy" and prop.known
                    for name, prop in rule.properties.items()
                )
            ):
                # Comparación numérica contra un valor no numérico cuando la
                # longitud ya define el conteo (12 characters): la longitud
                # decide; la comparación no envenena con UNDETERMINED.
                continue
        checks.append(
            _comparison_check(
                operator=operator,
                left=left,
                right=right,
                boundary=str(boundary_prop.value) if boundary_prop is not None and boundary_prop.known else '',
                evidence=evidence,
                check_value=values.get('value'),
                bounds=bounds,
                registry=registry,
            )
        )
    return checks



def _property_evidence(rule: CanonicalRule, prefixes: Sequence[str]) -> list[str]:
    refs: list[str] = []
    for key, prop in rule.properties.items():
        if any(key.startswith(prefix) for prefix in prefixes):
            refs.extend(prop.evidence)
    return list(dict.fromkeys(refs))


def _pattern_relative_length(
    rule: CanonicalRule, values: Mapping[str, Any]
) -> float | None:
    """(Longitud del patrón runtime) si la regla declara esa referencia."""
    if not is_pattern_relative_length(rule):
        return None
    pattern_value = values.get("pattern")
    if pattern_value is None:
        return None
    return float(len(str(pattern_value)))


def _check_length(
    rule: CanonicalRule,
    values: Mapping[str, Any],
    registry: OperationRegistry,
) -> RuleCheck | None:
    policy = ""
    for key, prop in rule.properties.items():
        if key == "length.policy" and prop.known:
            policy = str(prop.value)
    if not policy:
        return None
    if policy == LengthPolicy.UNKNOWN.value:
        return RuleCheck(
            name="length",
            operation="LENGTH_POLICY",
            status=RuleEvaluationStatus.UNDETERMINED.value,
            missing_premises=["length_policy"],
            detail="política de longitud UNKNOWN",
            evidence=_property_evidence(rule, ("length.policy",)),
        )
    left, right, missing = _operand_pair(rule, values, prefix="length")
    if policy in (
        LengthPolicy.VALUE_MAY_BE_LONGER.value,
        LengthPolicy.VALUE_MAY_BE_SHORTER.value,
        LengthPolicy.PATTERN_MAY_BE_LONGER.value,
        LengthPolicy.PATTERN_MAY_BE_SHORTER.value,
    ):
        if missing:
            return RuleCheck(
                name="length",
                operation="LENGTH_POLICY",
                status=RuleEvaluationStatus.UNDETERMINED.value,
                missing_premises=missing,
                detail="política asimétrica sin ambos operandos",
            )
        left_len, right_len = len(str(left)), len(str(right))
        if policy == LengthPolicy.VALUE_MAY_BE_LONGER.value:
            allowed = left_len >= right_len
        elif policy == LengthPolicy.VALUE_MAY_BE_SHORTER.value:
            allowed = left_len <= right_len
        elif policy == LengthPolicy.PATTERN_MAY_BE_LONGER.value:
            allowed = right_len >= left_len
        else:
            allowed = right_len <= left_len
        return RuleCheck(
            name="length",
            operation="LENGTH_POLICY",
            status=(
                RuleEvaluationStatus.MATCH.value
                if allowed
                else RuleEvaluationStatus.NO_MATCH.value
            ),
            result=allowed,
            detail=f"{policy}: len(left)={left_len} len(right)={right_len}",
            evidence=_property_evidence(rule, ("length.policy", "length.left", "length.right")),
        )
    if policy == LengthPolicy.UNCONSTRAINED.value:
        return RuleCheck(
            name="length",
            operation="LENGTH_POLICY",
            status=RuleEvaluationStatus.MATCH.value,
            result=True,
            detail="longitud no restringida",
            evidence=_property_evidence(rule, ("length.policy",)),
        )
    value = values.get("value")
    if value is None:
        return RuleCheck(
            name="length",
            operation="RANGE_CHECK",
            status=RuleEvaluationStatus.UNDETERMINED.value,
            missing_premises=["operand:value"],
            detail="falta el valor a medir",
        )
    length_value_prop = rule.properties.get("length.value")
    upper_prop = rule.properties.get("length.upper")
    minimum = length_value_prop.value if length_value_prop is not None and length_value_prop.known else None
    maximum = upper_prop.value if upper_prop is not None and upper_prop.known else None
    target = float(len(str(value)))
    boundary_prop = rule.properties.get("length.boundary")
    inclusive = True
    if boundary_prop is not None and boundary_prop.known:
        inclusive = str(boundary_prop.value) != BoundaryKind.EXCLUSIVE.value
    if policy == LengthPolicy.EXACT.value:
        expected = _as_number(minimum)
        if expected is None:
            # "same length": igualdad simétrica valor/patrón.
            pattern_value = values.get("pattern")
            if pattern_value is None:
                return RuleCheck(
                    name="length",
                    operation="LENGTH_POLICY",
                    status=RuleEvaluationStatus.UNDETERMINED.value,
                    missing_premises=["input:pattern"],
                    detail="EXACT sin longitud declarada ni patrón de escenario",
                )
            expected = float(len(str(pattern_value)))
        outcome = registry.run("COMPARISON", a=target, b=expected, op="eq")
    elif policy in (LengthPolicy.MIN_LENGTH.value, LengthPolicy.MAX_LENGTH.value):
        expected = _as_number(minimum)
        if expected is None:
            # "at least the number of characters referenced in the field":
            # el número de referencia es la longitud del patrón runtime.
            expected = _pattern_relative_length(rule, values)
            if expected is None:
                return RuleCheck(
                    name="length",
                    operation="LENGTH_POLICY",
                    status=RuleEvaluationStatus.UNDETERMINED.value,
                    missing_premises=["length_value", "input:pattern"],
                    detail=f"{policy} sin número declarado ni patrón de escenario",
                )
        if policy == LengthPolicy.MIN_LENGTH.value:
            outcome = registry.run(
                "COMPARISON", a=target, b=expected, op="ge" if inclusive else "gt"
            )
        else:
            outcome = registry.run(
                "COMPARISON", a=target, b=expected, op="le" if inclusive else "lt"
            )
    elif policy == LengthPolicy.RANGE.value:
        if minimum is None or maximum is None:
            return RuleCheck(
                name="length",
                operation="RANGE_CHECK",
                status=RuleEvaluationStatus.UNDETERMINED.value,
                missing_premises=["length_value", "length_upper"],
                detail="RANGE sin límites completos",
            )
        outcome = registry.run(
            "RANGE_CHECK",
            value=target,
            minimum=_as_number(minimum),
            maximum=_as_number(maximum),
            inclusive=inclusive,
        )
    else:
        return RuleCheck(
            name="length",
            operation="LENGTH_POLICY",
            status=RuleEvaluationStatus.UNDETERMINED.value,
            missing_premises=[f"length_policy:{policy}"],
            detail="política de longitud no ejecutable",
        )
    if not outcome.ok:
        return RuleCheck(
            name="length",
            operation=outcome.operation,
            status=RuleEvaluationStatus.UNDETERMINED.value,
            missing_premises=[outcome.error or "length_error"],
            detail=outcome.explanation or outcome.error,
        )
    return RuleCheck(
        name="length",
        operation=outcome.operation,
        status=(
            RuleEvaluationStatus.MATCH.value
            if bool(outcome.value)
            else RuleEvaluationStatus.NO_MATCH.value
        ),
        result=bool(outcome.value),
        detail=f"{policy}: length={int(target)} {outcome.explanation}",
        evidence=_property_evidence(rule, ("length.",)),
    )


def _check_matching(
    rule: CanonicalRule,
    values: Mapping[str, Any],
    registry: OperationRegistry,
) -> RuleCheck | None:
    operator = ""
    case_sensitive = False
    for key, prop in rule.properties.items():
        if key == "matching.operator" and prop.known:
            operator = str(prop.value)
        if key == "matching.case_sensitive" and prop.known:
            case_sensitive = bool(prop.value)
    if not operator:
        return None
    value = values.get("value")
    pattern = values.get("pattern")
    missing: list[str] = []
    if value is None:
        missing.append("input:value")
    if pattern is None:
        missing.append("input:pattern")
    if missing:
        has_other_semantics = any(
            name.startswith(("length.", "comparison.", "temporal.", "enumeration.", "quantity."))
            and prop.known
            for name, prop in rule.properties.items()
        ) or bool(rule.formula.expression)
        if has_other_semantics:
            # El chequeo de matching no aplica sin patrón; las otras
            # dimensiones ejecutables de la regla siguen decidiendo.
            return None
        return RuleCheck(
            name="matching",
            operation="POSITIONAL_MATCH",
            status=RuleEvaluationStatus.UNDETERMINED.value,
            missing_premises=missing,
            detail="matching sin valor/patrón de escenario",
        )
    if operator == MatchOperator.UNKNOWN.value:
        return RuleCheck(
            name="matching",
            operation="POSITIONAL_MATCH",
            status=RuleEvaluationStatus.UNDETERMINED.value,
            missing_premises=["matching_policy"],
            detail="política de matching UNKNOWN",
            evidence=_property_evidence(rule, ("matching.operator",)),
        )
    left = str(value)
    right = str(pattern)
    if not case_sensitive:
        left_cmp, right_cmp = left.lower(), right.lower()
    else:
        left_cmp, right_cmp = left, right
    if operator == MatchOperator.CONTAINS.value:
        matched = right_cmp in left_cmp
        outcome = OperationResult(
            operation="CONTAINS",
            status=OperationStatus.OK.value,
            value=matched,
            explanation=f"'{right}' {'in' if matched else 'not in'} '{left}'",
        )
    elif operator == MatchOperator.STARTS_WITH.value:
        matched = left_cmp.startswith(right_cmp)
        outcome = OperationResult(
            operation="STARTS_WITH",
            status=OperationStatus.OK.value,
            value=matched,
            explanation=f"'{left}' starts with '{right}' is {matched}",
        )
    elif operator == MatchOperator.ENDS_WITH.value:
        matched = left_cmp.endswith(right_cmp)
        outcome = OperationResult(
            operation="ENDS_WITH",
            status=OperationStatus.OK.value,
            value=matched,
            explanation=f"'{left}' ends with '{right}' is {matched}",
        )
    else:
        semantics = pattern_semantics_from_rule(rule)
        outcome = registry.run(
            "POSITIONAL_MATCH", value=left, pattern=right, semantics=semantics
        )
    if not outcome.ok:
        return RuleCheck(
            name="matching",
            operation=outcome.operation,
            status=RuleEvaluationStatus.UNDETERMINED.value,
            missing_premises=[item for item in str(outcome.error or "").split(", ") if item] or ["matching_semantics"],
            detail=outcome.explanation or outcome.error,
            evidence=_property_evidence(rule, ("matching.", "length.policy")),
        )
    status = str(outcome.value)
    if status in ("MATCH", "NO_MATCH"):
        mapped = (
            RuleEvaluationStatus.MATCH.value
            if status == "MATCH"
            else RuleEvaluationStatus.NO_MATCH.value
        )
    else:
        mapped = RuleEvaluationStatus.UNDETERMINED.value
    return RuleCheck(
        name="matching",
        operation=outcome.operation,
        status=mapped,
        result=status,
        detail=outcome.explanation,
        evidence=_property_evidence(rule, ("matching.", "length.policy")),
    )


def _check_enumeration(
    rule: CanonicalRule,
    values: Mapping[str, Any],
    registry: OperationRegistry,
) -> list[RuleCheck]:
    checks: list[RuleCheck] = []
    value = values.get("value")
    allowed = list(rule.enumeration.allowed)
    prohibited = list(rule.enumeration.prohibited)
    if not allowed and not prohibited:
        return checks
    if value is None:
        checks.append(
            RuleCheck(
                name="enumeration",
                operation="ENUM_CHECK",
                status=RuleEvaluationStatus.UNDETERMINED.value,
                missing_premises=["input:value"],
                detail="enumeración sin valor de escenario",
                evidence=_property_evidence(rule, ("enumeration.",)),
            )
        )
        return checks
    if allowed:
        outcome = registry.run("ENUM_CHECK", value=value, allowed=allowed)
        checks.append(
            RuleCheck(
                name="enumeration.allowed",
                operation="ENUM_CHECK",
                status=(
                    RuleEvaluationStatus.MATCH.value
                    if outcome.ok and bool(outcome.value)
                    else RuleEvaluationStatus.NO_MATCH.value
                    if outcome.ok
                    else RuleEvaluationStatus.UNDETERMINED.value
                ),
                result=bool(outcome.value) if outcome.ok else None,
                detail=outcome.explanation or outcome.error,
                evidence=_property_evidence(rule, ("enumeration.",)),
            )
        )
    if prohibited:
        outcome = registry.run("ENUM_CHECK", value=value, allowed=prohibited)
        forbidden = bool(outcome.value) if outcome.ok else None
        checks.append(
            RuleCheck(
                name="enumeration.prohibited",
                operation="ENUM_CHECK",
                status=(
                    RuleEvaluationStatus.NO_MATCH.value
                    if forbidden
                    else RuleEvaluationStatus.MATCH.value
                    if outcome.ok
                    else RuleEvaluationStatus.UNDETERMINED.value
                ),
                result=(not forbidden) if outcome.ok else None,
                detail="valor prohibido" if forbidden else (outcome.explanation or outcome.error),
                evidence=_property_evidence(rule, ("enumeration.",)),
            )
        )
    return checks


def _check_quantity(
    rule: CanonicalRule,
    values: Mapping[str, Any],
    registry: OperationRegistry,
) -> RuleCheck | None:
    minimum = maximum = None
    boundary = ""
    unit = ""
    for key, prop in rule.properties.items():
        if key.endswith(".minimum") and prop.known:
            minimum = _as_number(prop.value)
        if key.endswith(".maximum") and prop.known:
            maximum = _as_number(prop.value)
        if key.endswith(".boundary") and prop.known:
            boundary = str(prop.value)
        if key.endswith(".unit") and prop.known:
            unit = str(prop.value).strip().lower()
    if minimum is None and maximum is None:
        return None
    if unit in COUNT_UNITS:
        # La unidad es el propio dominio del conteo (caracteres/posiciones):
        # lo resuelve el chequeo de longitud, no una cantidad numérica externa.
        return None
    value = values.get("value")
    if value is None:
        return RuleCheck(
            name="quantity",
            operation="RANGE_CHECK",
            status=RuleEvaluationStatus.UNDETERMINED.value,
            missing_premises=["input:value"],
            detail="cantidad sin valor de escenario",
        )
    if not boundary or boundary == BoundaryKind.UNKNOWN.value:
        return RuleCheck(
            name="quantity",
            operation="RANGE_CHECK",
            status=RuleEvaluationStatus.UNDETERMINED.value,
            missing_premises=["boundary"],
            detail="límite sin inclusividad declarada",
        )
    outcome = registry.run(
        "RANGE_CHECK",
        value=_as_number(value),
        minimum=minimum,
        maximum=maximum,
        inclusive=boundary == BoundaryKind.INCLUSIVE.value,
    )
    if not outcome.ok:
        return RuleCheck(
            name="quantity",
            operation="RANGE_CHECK",
            status=RuleEvaluationStatus.UNDETERMINED.value,
            missing_premises=[outcome.error or "quantity_error"],
            detail=outcome.explanation or outcome.error,
        )
    return RuleCheck(
        name="quantity",
        operation="RANGE_CHECK",
        status=(
            RuleEvaluationStatus.MATCH.value
            if bool(outcome.value)
            else RuleEvaluationStatus.NO_MATCH.value
        ),
        result=bool(outcome.value),
        detail=outcome.explanation,
        evidence=_property_evidence(rule, ("quantity",)),
    )


def _check_temporal(
    rule: CanonicalRule,
    values: Mapping[str, Any],
    registry: OperationRegistry,
) -> RuleCheck | None:
    relation = rule.temporal.relation
    if relation in (TemporalRelation.UNKNOWN.value, ""):
        prop = rule.properties.get("temporal.relation")
        relation = str(prop.value) if prop is not None and prop.known else ""
    if not relation or relation == TemporalRelation.UNKNOWN.value:
        return None
    if relation in (
        TemporalRelation.EFFECTIVE_FROM.value,
        TemporalRelation.DURATION.value,
        TemporalRelation.SIMULTANEOUS.value,
    ):
        # Son metadatos de alcance/ventana: los resuelve el gate temporal de
        # `evaluate_rule`, no una comparación con el valor de runtime.
        return None
    left = values.get("value") or values.get("date")
    right = values.get("reference_date") or values.get("right") or rule.temporal.value
    missing: list[str] = []
    if left is None:
        missing.append("input:value")
    if right is None and relation in (
        TemporalRelation.BEFORE.value,
        TemporalRelation.AFTER.value,
        TemporalRelation.FROM_TO.value,
    ):
        missing.append("input:reference_date")
    if missing:
        return RuleCheck(
            name="temporal",
            operation="DATE_COMPARISON",
            status=RuleEvaluationStatus.UNDETERMINED.value,
            missing_premises=missing,
            detail="relación temporal sin fechas de escenario",
            evidence=_property_evidence(rule, ("temporal.",)),
        )
    operation = "lt" if relation == TemporalRelation.BEFORE.value else "gt"
    if relation in (TemporalRelation.EXPIRES.value,):
        operation = "le"
    # "on or before" / "on or after": el límite es inclusivo; no se pierde.
    relation_prop = rule.properties.get("temporal.relation")
    relation_text = (
        str(relation_prop.matched_text)
        if relation_prop is not None and relation_prop.known
        else ""
    )
    if re.search(r"on\s+or\s+before", relation_text, re.IGNORECASE):
        operation = "le"
    elif re.search(r"on\s+or\s+after", relation_text, re.IGNORECASE):
        operation = "ge"
    # Fecha sin año ("before 1 July"): se usa el año del valor comparado;
    # nunca se inventa un año distinto.
    if right is not None and not re.search(r"\d{4}", str(right)):
        year_match = re.search(r"(\d{4})", str(left))
        if year_match:
            right = f"{right} {year_match.group(1)}"
    if relation == TemporalRelation.FROM_TO.value:
        low, high = values.get("from"), values.get("to")
        if low is None or high is None:
            return RuleCheck(
                name="temporal",
                operation="DATE_COMPARISON",
                status=RuleEvaluationStatus.UNDETERMINED.value,
                missing_premises=["input:from", "input:to"],
                detail="ventana from/to sin límites",
            )
        lower = registry.run("DATE_COMPARISON", a=low, b=left, op="le")
        upper = registry.run("DATE_COMPARISON", a=left, b=high, op="le")
        if not (lower.ok and upper.ok):
            return RuleCheck(
                name="temporal",
                operation="DATE_COMPARISON",
                status=RuleEvaluationStatus.UNDETERMINED.value,
                missing_premises=["temporal_operands"],
                detail=lower.error or upper.error,
            )
        matched = bool(lower.value) and bool(upper.value)
    else:
        outcome = registry.run("DATE_COMPARISON", a=left, b=right, op=operation)
        if not outcome.ok:
            return RuleCheck(
                name="temporal",
                operation="DATE_COMPARISON",
                status=RuleEvaluationStatus.UNDETERMINED.value,
                missing_premises=["temporal_operands"],
                detail=outcome.error,
            )
        matched = bool(outcome.value)
    return RuleCheck(
        name="temporal",
        operation="DATE_COMPARISON",
        status=(
            RuleEvaluationStatus.MATCH.value
            if matched
            else RuleEvaluationStatus.NO_MATCH.value
        ),
        result=matched,
        detail=f"{relation}: {left} / {right}",
        evidence=_property_evidence(rule, ("temporal.",)),
    )


def _check_formula(
    rule: CanonicalRule,
    values: Mapping[str, Any],
    registry: OperationRegistry,
) -> RuleCheck | None:
    expression = rule.formula.expression
    if not expression:
        return None
    target = rule.formula.target
    variables: dict[str, Any] = {}
    missing: list[str] = []
    for name in dict.fromkeys(_IDENTIFIER_RE.findall(expression)):
        if name == target or name in ("true", "false"):
            continue
        value = _resolve_value(name, values)
        if value is None and name in rule.formula.operands:
            value = _resolve_value(str(rule.formula.operands[name]), values)
        if value is None:
            missing.append(f"input:{name}")
        else:
            variables[name] = _as_number(value) if _as_number(value) is not None else value
    if missing:
        return RuleCheck(
            name="formula",
            operation="FORMULA_EVALUATION",
            status=RuleEvaluationStatus.UNDETERMINED.value,
            missing_premises=missing,
            detail="faltan variables de la fórmula",
            evidence=_property_evidence(rule, ("formula.",)),
        )
    outcome = registry.run("FORMULA_EVALUATION", formula=expression, variables=variables)
    if not outcome.ok:
        return RuleCheck(
            name="formula",
            operation="FORMULA_EVALUATION",
            status=RuleEvaluationStatus.UNDETERMINED.value,
            missing_premises=[outcome.error or "formula_error"],
            detail=outcome.explanation or outcome.error,
        )
    return RuleCheck(
        name="formula",
        operation="FORMULA_EVALUATION",
        status=RuleEvaluationStatus.MATCH.value,
        result=outcome.value,
        detail=outcome.explanation,
        evidence=_property_evidence(rule, ("formula.",)),
    )


def _check_scoped_condition(
    rule: CanonicalRule,
    values: Mapping[str, Any],
    registry: OperationRegistry,
    prefix: str,
    *,
    label: str,
) -> RuleCheck | None:
    """Condición estructurada compilada (exception/only_if/scope) -> check.

    Soporta comparación (operator/right/boundary), igualdad de bandera
    (equals/operand) y flags booleanos (flags/expect). Sin estructura -> None:
    el llamador decide (UNDETERMINED con premisa nombrada, nunca default).
    """
    operator = ""
    right_raw: Any = None
    boundary = ""
    equals = ""
    operand = ""
    alternative_operand = ""
    flags: list[str] = []
    for key, prop in rule.properties.items():
        if not prop.known:
            continue
        if key == f"{prefix}.operator":
            operator = str(prop.value)
        elif key == f"{prefix}.right":
            right_raw = prop.value
        elif key == f"{prefix}.boundary":
            boundary = str(prop.value)
        elif key == f"{prefix}.equals":
            equals = str(prop.value)
        elif key == f"{prefix}.operand":
            operand = str(prop.value)
        elif key == f"{prefix}.alternative_operand":
            alternative_operand = str(prop.value)
        elif key == f"{prefix}.flags":
            flags = [str(item) for item in (prop.value or ())]
    evidence = _property_evidence(rule, (prefix,))

    if flags:
        resolved: dict[str, bool] = {}
        missing_flags: list[str] = []
        for flag in flags:
            value = _resolve_value(flag, values)
            if value is None:
                missing_flags.append(flag)
            else:
                resolved[flag] = bool(value)
        if missing_flags:
            return RuleCheck(
                name=label,
                operation="BOOLEAN_RULE",
                status=RuleEvaluationStatus.UNDETERMINED.value,
                missing_premises=[f"condition_flag:{flag}" for flag in missing_flags],
                detail=f"faltan flags de la condición {label}",
                evidence=evidence,
            )
        matched = all(resolved.values())
        return RuleCheck(
            name=label,
            operation="BOOLEAN_RULE",
            status=(
                RuleEvaluationStatus.MATCH.value
                if matched
                else RuleEvaluationStatus.NO_MATCH.value
            ),
            result=matched,
            detail=f"flags {resolved}",
            evidence=evidence,
        )

    if equals:
        candidate = None
        for name in (operand, alternative_operand):
            if name:
                candidate = _resolve_value(name, values)
                if candidate is not None:
                    break
        if candidate is None:
            candidate = values.get("value")
        if candidate is None:
            return RuleCheck(
                name=label,
                operation="STRING_COMPARE",
                status=RuleEvaluationStatus.UNDETERMINED.value,
                missing_premises=["condition_operand"],
                detail=f"condición {label} sin operando de escenario",
                evidence=evidence,
            )
        if isinstance(candidate, bool):
            matched = bool(candidate) == bool(equals)
        else:
            matched = str(candidate).strip().lower() == equals.strip().lower()
        return RuleCheck(
            name=label,
            operation="STRING_COMPARE",
            status=(
                RuleEvaluationStatus.MATCH.value
                if matched
                else RuleEvaluationStatus.NO_MATCH.value
            ),
            result=matched,
            detail=f"{candidate!r} == {equals!r}",
            evidence=evidence,
        )

    if not operator:
        return None
    left = values.get("value")
    right = _resolve_value(str(right_raw), values) if right_raw is not None else None
    if right is None:
        numbers = _extract_numbers(right_raw)
        if len(numbers) == 1:
            right = numbers[0]
    if left is None or right is None:
        return RuleCheck(
            name=label,
            operation="COMPARISON",
            status=RuleEvaluationStatus.UNDETERMINED.value,
            missing_premises=["condition_operand"],
            detail=f"condición {label} sin operandos de escenario",
            evidence=evidence,
        )
    if operator in (
        ComparisonOperator.BETWEEN.value,
        ComparisonOperator.OUTSIDE_RANGE.value,
    ):
        bounds = _extract_numbers(right_raw)
        return _comparison_check(
            operator=operator,
            left=left,
            right=right,
            boundary=boundary,
            evidence=evidence,
            check_value=left,
            bounds=bounds,
            registry=registry,
        )
    comparison_op = COMPARISON_TO_OPERATION.get(operator)
    if comparison_op is None:
        return RuleCheck(
            name=label,
            operation="COMPARISON",
            status=RuleEvaluationStatus.UNDETERMINED.value,
            missing_premises=[f"condition_operator:{operator}"],
            detail=f"operador de condición no soportado: {operator}",
            evidence=evidence,
        )
    outcome = registry.run("COMPARISON", a=left, b=right, op=comparison_op)
    if not outcome.ok:
        return RuleCheck(
            name=label,
            operation=outcome.operation,
            status=RuleEvaluationStatus.UNDETERMINED.value,
            missing_premises=[outcome.error or "condition_error"],
            detail=outcome.explanation or outcome.error,
            evidence=evidence,
        )
    return RuleCheck(
        name=label,
        operation=outcome.operation,
        status=(
            RuleEvaluationStatus.MATCH.value
            if bool(outcome.value)
            else RuleEvaluationStatus.NO_MATCH.value
        ),
        result=bool(outcome.value),
        detail=outcome.explanation,
        evidence=evidence,
    )


def _requirements_for(
    rule: CanonicalRule,
    checks: Sequence[RuleCheck],
    *,
    extra: Sequence[RuleRequirement] = (),
) -> list[RuleRequirement]:
    """Estado explícito por premisa: nunca MISSING convertido en default."""
    requirements: list[RuleRequirement] = []
    for check in checks:
        if check.status == RuleEvaluationStatus.MATCH.value:
            state = RequirementState.SATISFIED.value
        elif check.status == RuleEvaluationStatus.NO_MATCH.value:
            state = RequirementState.SATISFIED.value
        elif check.status == RuleEvaluationStatus.UNDETERMINED.value:
            state = RequirementState.MISSING.value
        else:
            state = RequirementState.NOT_APPLICABLE.value
        requirements.append(
            RuleRequirement(
                requirement_id=f"check:{check.name}",
                kind=check.name,
                state=state,
                detail=check.detail or check.operation,
                evidence=list(check.evidence),
            )
        )
    requirements.extend(extra)
    if rule.conflicts_with:
        requirements.append(
            RuleRequirement(
                requirement_id="conflict",
                kind="conflict",
                state=RequirementState.CONFLICTING.value,
                detail="reglas contradictorias: no se ejecuta ninguna",
                evidence=list(rule.evidence_ids())[:4],
            )
        )
    return requirements


def evaluate_rule(
    rule: CanonicalRule,
    values: Mapping[str, Any] | None = None,
    *,
    registry: OperationRegistry | None = None,
) -> RuleEvaluation:
    """Aplica una CanonicalRule verificada a datos runtime (determinista)."""
    registry = registry or DEFAULT_REGISTRY
    runtime_values = dict(values or {})
    evidence_refs = list(rule.evidence_ids())
    premises_used = [
        prop.matched_text
        for prop in rule.properties.values()
        if prop.known and prop.matched_text
    ][:8]

    # Una regla reemplazada por otra (override/supersede) no se aplica.
    if rule.supersedes and not rule.executable:
        return RuleEvaluation(
            rule_id=rule.rule_id,
            status=RuleEvaluationStatus.NOT_APPLICABLE.value,
            missing_premises=[],
            evidence_refs=evidence_refs,
            inputs=runtime_values,
            premises_used=premises_used,
            reason="superseded_by:" + ",".join(rule.supersedes[:3]),
            requirements=_requirements_for(rule, ()),
        )

    if not rule.executable or rule.verification_state != VerificationState.SUPPORTED.value:
        return RuleEvaluation(
            rule_id=rule.rule_id,
            status=RuleEvaluationStatus.UNDETERMINED.value,
            missing_premises=list(
                dict.fromkeys([*rule.missing_premises, *(["conflict"] if rule.conflicts_with else [])])
            ),
            evidence_refs=evidence_refs,
            inputs=runtime_values,
            premises_used=premises_used,
            reason=f"regla no ejecutable ({rule.verification_state})",
            requirements=_requirements_for(rule, ()),
        )

    # Aplicabilidad de gramática: una regla que declara símbolos de patrón solo
    # aplica a patrones que USAN alguno de esos símbolos. Una regla de otro
    # patrón no puede decidir MATCH/NO_MATCH sobre el patrón del escenario.
    pattern_value = runtime_values.get("pattern")
    declared_symbols = {
        name[len("matching.symbol.") :]
        for name, prop in rule.properties.items()
        if name.startswith("matching.symbol.")
        and not name.endswith(".alphabet")
        and not name.endswith(".unmerged")
        and prop.known
    }
    if (
        pattern_value is not None
        and declared_symbols
        and not any(str(symbol) in str(pattern_value) for symbol in declared_symbols)
    ):
        return RuleEvaluation(
            rule_id=rule.rule_id,
            status=RuleEvaluationStatus.NOT_APPLICABLE.value,
            result="NOT_APPLICABLE",
            evidence_refs=evidence_refs,
            inputs=runtime_values,
            premises_used=premises_used,
            reason="pattern_does_not_use_declared_symbols",
            requirements=_requirements_for(rule, ()),
        )

    # --- Ventana de vigencia: la fecha runtime selecciona la versión --------
    reference_date = runtime_values.get("reference_date") or runtime_values.get("date")
    if rule.relations.get("TEMPORAL_CHOICE") and not reference_date:
        return RuleEvaluation(
            rule_id=rule.rule_id,
            status=RuleEvaluationStatus.UNDETERMINED.value,
            missing_premises=["temporal_scope"],
            evidence_refs=evidence_refs,
            inputs=runtime_values,
            premises_used=premises_used,
            reason="faltan premisas: temporal_scope (no se elige versión sin fecha)",
            requirements=_requirements_for(rule, ()),
        )
    if reference_date:
        reference_parsed = _parse_ref_date(reference_date)
        if reference_parsed is not None:
            start = (
                _parse_ref_date(rule.scope.effective_from)
                if rule.scope.effective_from
                else None
            )
            end = (
                _parse_ref_date(rule.scope.effective_to)
                if rule.scope.effective_to
                else None
            )
            outside = (start is not None and reference_parsed < start) or (
                end is not None and reference_parsed > end
            )
            if outside:
                return RuleEvaluation(
                    rule_id=rule.rule_id,
                    status=RuleEvaluationStatus.NOT_APPLICABLE.value,
                    result="NOT_APPLICABLE",
                    evidence_refs=evidence_refs,
                    inputs=runtime_values,
                    premises_used=premises_used,
                    reason="outside_effective_window",
                    requirements=_requirements_for(rule, ()),
                    logic="TEMPORAL",
                )

    # --- Alcance específico ("For products marked FINAL") -------------------
    scope_checks: list[RuleCheck] = []
    scope_indices = sorted(
        {
            name.split(".")[2]
            for name in rule.properties
            if name.startswith("scope.condition.")
            and len(name.split(".")) > 3
            and name.split(".")[2].isdigit()
        }
    )
    for scope_index in scope_indices:
        check = _check_scoped_condition(
            rule,
            runtime_values,
            registry,
            f"scope.condition.{scope_index}",
            label=f"scope:{scope_index}",
        )
        if check is None:
            continue
        scope_checks.append(check)
        if check.status == RuleEvaluationStatus.NO_MATCH.value:
            return RuleEvaluation(
                rule_id=rule.rule_id,
                status=RuleEvaluationStatus.NOT_APPLICABLE.value,
                operation=check.operation,
                result="NOT_APPLICABLE",
                checks=[check],
                evidence_refs=evidence_refs,
                inputs=runtime_values,
                premises_used=premises_used,
                reason="scope_not_matched",
                requirements=_requirements_for(rule, [check]),
                condition_results=[
                    {"condition_id": check.name, "result": check.status}
                ],
                logic="SCOPE",
            )
        if check.status == RuleEvaluationStatus.UNDETERMINED.value:
            missing_scope = list(check.missing_premises or ["scope_condition"])
            return RuleEvaluation(
                rule_id=rule.rule_id,
                status=RuleEvaluationStatus.UNDETERMINED.value,
                operation=check.operation,
                checks=[check],
                missing_premises=missing_scope,
                evidence_refs=evidence_refs,
                inputs=runtime_values,
                premises_used=premises_used,
                reason="faltan premisas: " + ", ".join(missing_scope[:4]),
                requirements=_requirements_for(rule, [check]),
                condition_results=[
                    {"condition_id": check.name, "result": check.status}
                ],
                logic="SCOPE",
            )

    # --- Condiciones only_if / excepciones (antes de ejecutar el cuerpo) ----
    logic_prop = rule.properties.get("logic.operators")
    logic_ops = (
        list(logic_prop.value)
        if logic_prop is not None and logic_prop.known and isinstance(logic_prop.value, list)
        else []
    )
    condition_checks: list[RuleCheck] = []
    only_if = _check_scoped_condition(
        rule, runtime_values, registry, "condition.only_if", label="only_if"
    )
    if only_if is not None:
        condition_checks.append(only_if)
        if only_if.status == RuleEvaluationStatus.NO_MATCH.value:
            modality = str(rule.modality or "")
            if modality in ("MAY", "OPTIONAL"):
                # "may be enabled only if": condición falsa -> no permitido.
                return RuleEvaluation(
                    rule_id=rule.rule_id,
                    status=RuleEvaluationStatus.NO_MATCH.value,
                    operation=only_if.operation,
                    result=False,
                    checks=[only_if],
                    evidence_refs=evidence_refs,
                    inputs=runtime_values,
                    premises_used=premises_used,
                    reason="permission_not_granted",
                    requirements=_requirements_for(rule, [only_if]),
                    condition_results=[
                        {"condition_id": "condition:only_if", "result": only_if.status}
                    ],
                    logic="ONLY_IF",
                )
            return RuleEvaluation(
                rule_id=rule.rule_id,
                status=RuleEvaluationStatus.NOT_APPLICABLE.value,
                operation=only_if.operation,
                result="NOT_APPLICABLE",
                checks=[only_if],
                evidence_refs=evidence_refs,
                inputs=runtime_values,
                premises_used=premises_used,
                reason="condition_not_met",
                requirements=_requirements_for(rule, [only_if]),
                condition_results=[
                    {"condition_id": "condition:only_if", "result": only_if.status}
                ],
                logic="ONLY_IF",
            )
        if only_if.status == RuleEvaluationStatus.UNDETERMINED.value:
            missing_condition = list(only_if.missing_premises or ["condition_only_if"])
            return RuleEvaluation(
                rule_id=rule.rule_id,
                status=RuleEvaluationStatus.UNDETERMINED.value,
                operation=only_if.operation,
                checks=[only_if],
                missing_premises=missing_condition,
                evidence_refs=evidence_refs,
                inputs=runtime_values,
                premises_used=premises_used,
                reason="faltan premisas: " + ", ".join(missing_condition[:4]),
                requirements=_requirements_for(rule, [only_if]),
                condition_results=[
                    {"condition_id": "condition:only_if", "result": only_if.status}
                ],
                logic="ONLY_IF",
            )

    exception_checks: list[RuleCheck] = []
    for index, exception_text in enumerate(rule.exceptions):
        check = _check_scoped_condition(
            rule,
            runtime_values,
            registry,
            f"exception.condition.{index}",
            label=f"exception:{index}",
        )
        if check is None:
            check = RuleCheck(
                name=f"exception:{index}",
                operation="EXCEPTION_CONDITION",
                status=RuleEvaluationStatus.UNDETERMINED.value,
                missing_premises=["exception_condition"],
                detail="; ".join(str(exception_text).split())[:160],
            )
        exception_checks.append(check)
        if check.status == RuleEvaluationStatus.MATCH.value:
            return RuleEvaluation(
                rule_id=rule.rule_id,
                status=RuleEvaluationStatus.NOT_APPLICABLE.value,
                operation=check.operation,
                result="NOT_APPLICABLE",
                checks=[*condition_checks, *exception_checks],
                evidence_refs=evidence_refs,
                inputs=runtime_values,
                premises_used=premises_used,
                reason="exception_applied",
                requirements=_requirements_for(rule, [*condition_checks, *exception_checks]),
                condition_results=[
                    {"condition_id": f"exception:{index}", "result": check.status}
                ],
                logic="UNLESS",
                exceptions_applied=[str(exception_text)[:240]],
            )
    pending_exceptions = [
        check
        for check in exception_checks
        if check.status == RuleEvaluationStatus.UNDETERMINED.value
    ]
    if pending_exceptions:
        missing = [
            value
            for check in pending_exceptions
            for value in (check.missing_premises or ["exception_condition"])
        ]
        return RuleEvaluation(
            rule_id=rule.rule_id,
            status=RuleEvaluationStatus.UNDETERMINED.value,
            checks=[*condition_checks, *exception_checks],
            missing_premises=list(dict.fromkeys(missing))[:8],
            evidence_refs=evidence_refs,
            inputs=runtime_values,
            premises_used=premises_used,
            reason="faltan premisas: exception_condition",
            requirements=_requirements_for(rule, [*condition_checks, *exception_checks]),
            condition_results=[
                {"condition_id": check.name, "result": check.status}
                for check in exception_checks
            ],
            logic="UNLESS",
        )

    checks: list[RuleCheck] = []
    matching = _check_matching(rule, runtime_values, registry)
    if matching is not None:
        checks.append(matching)
    length = _check_length(rule, runtime_values, registry)
    if length is not None:
        checks.append(length)
    checks.extend(_check_comparisons(rule, runtime_values, registry))
    checks.extend(_check_enumeration(rule, runtime_values, registry))
    quantity = _check_quantity(rule, runtime_values, registry)
    if quantity is not None:
        checks.append(quantity)
    temporal = _check_temporal(rule, runtime_values, registry)
    if temporal is not None:
        checks.append(temporal)
    formula = _check_formula(rule, runtime_values, registry)
    if formula is not None:
        checks.append(formula)

    condition_results = [
        {"condition_id": f"check:{check.name}", "result": check.status, "operation": check.operation}
        for check in [*scope_checks, *condition_checks, *exception_checks, *checks]
    ]
    connector = "OR" if ("OR" in logic_ops and "AND" not in logic_ops) else "AND"

    if not checks:
        condition_only = bool(condition_checks) and all(
            check.status == RuleEvaluationStatus.MATCH.value
            for check in condition_checks
        )
        scope_only = bool(scope_checks) and all(
            check.status == RuleEvaluationStatus.MATCH.value for check in scope_checks
        )
        if condition_only or scope_only:
            primary = condition_checks[0] if condition_checks else scope_checks[0]
            return RuleEvaluation(
                rule_id=rule.rule_id,
                status=RuleEvaluationStatus.MATCH.value,
                operation=primary.operation,
                result=True,
                checks=[*scope_checks, *condition_checks, *exception_checks],
                evidence_refs=evidence_refs,
                inputs=runtime_values,
                premises_used=premises_used,
                reason=(
                    "conditions_satisfied"
                    if condition_only
                    else "scope_condition_satisfied"
                ),
                requirements=_requirements_for(
                    rule, [*scope_checks, *condition_checks, *exception_checks]
                ),
                condition_results=condition_results,
                logic="CONDITION_ONLY",
            )
        return RuleEvaluation(
            rule_id=rule.rule_id,
            status=RuleEvaluationStatus.NOT_APPLICABLE.value,
            missing_premises=["executable_semantics"],
            evidence_refs=evidence_refs,
            inputs=runtime_values,
            premises_used=premises_used,
            reason="la regla no declara semántica ejecutable para estos datos",
            requirements=_requirements_for(rule, [*condition_checks, *exception_checks]),
            condition_results=condition_results,
            logic=connector,
        )

    missing: list[str] = []
    for check in checks:
        missing.extend(check.missing_premises)
    matched_checks = [check for check in checks if check.status == RuleEvaluationStatus.MATCH.value]
    no_match = [check for check in checks if check.status == RuleEvaluationStatus.NO_MATCH.value]
    undetermined = [check for check in checks if check.status == RuleEvaluationStatus.UNDETERMINED.value]
    if connector == "OR":
        if matched_checks:
            status = RuleEvaluationStatus.MATCH.value
            result: Any = True
            reason = "derived_from_canonical_rule (OR)"
        elif undetermined:
            status = RuleEvaluationStatus.UNDETERMINED.value
            result = None
            reason = "faltan premisas: " + ", ".join(list(dict.fromkeys(missing))[:4])
        else:
            status = RuleEvaluationStatus.NO_MATCH.value
            result = False
            reason = "no cumple ninguna rama: " + "; ".join(check.name for check in no_match)
    elif no_match:
        status = RuleEvaluationStatus.NO_MATCH.value
        result = False
        reason = "no cumple: " + "; ".join(check.name for check in no_match)
    elif undetermined:
        status = RuleEvaluationStatus.UNDETERMINED.value
        result = None
        reason = "faltan premisas: " + ", ".join(list(dict.fromkeys(missing))[:4])
    else:
        status = RuleEvaluationStatus.MATCH.value
        result = True
        reason = "derived_from_canonical_rule"
    result_checks = [check for check in checks if check.result is not None]
    primary_operation = checks[0].operation
    for check in checks:
        if check.name == "matching":
            primary_operation = check.operation
            break
    # MATCH: el resultado es el valor del último check SATISFECHO (preserva
    # valores de fórmula/medida); NUNCA el valor de un check NO_MATCH ajeno a
    # la rama OR que decidió. Antes, un check NO_MATCH posterior invertía el
    # resultado (MATCH con result=False).
    if status == RuleEvaluationStatus.MATCH.value:
        matched_results = [
            check.result
            for check in result_checks
            if check.status == RuleEvaluationStatus.MATCH.value and check.result is not None
        ]
        final_result: Any = matched_results[-1] if matched_results else True
    else:
        final_result = result
    return RuleEvaluation(
        rule_id=rule.rule_id,
        status=status,
        operation=primary_operation,
        result=final_result,
        checks=[*scope_checks, *condition_checks, *checks],
        missing_premises=list(dict.fromkeys(missing))[:16],
        premises_used=premises_used,
        evidence_refs=evidence_refs,
        inputs=runtime_values,
        reason=reason,
        requirements=_requirements_for(rule, [*condition_checks, *checks]),
        condition_results=condition_results,
        logic=connector,
        version=EVALUATION_VERSION,
    )


def evaluate_rules(
    rules: Sequence[CanonicalRule],
    values: Mapping[str, Any] | None = None,
    *,
    registry: OperationRegistry | None = None,
    merge: bool = True,
) -> list[RuleEvaluation]:
    """Evalúa reglas compatibles (fragmentos distribuidos unidos) una vez.

    Las reglas en conflicto no se fusionan ni se ejecutan en silencio.
    """
    if merge:
        from .merge import merge_distributed_rules

        rules = merge_distributed_rules(rules)
    return [evaluate_rule(rule, values, registry=registry) for rule in rules]


def rule_premises(rule: CanonicalRule) -> list[Any]:
    """Premisas grounded de la regla (para DerivedClaim/observabilidad)."""
    from src.core.domain.grounding import ClaimOrigin, Premise

    premises: list[Premise] = []
    seen: set[str] = set()
    for name, prop in rule.properties.items():
        if not prop.known:
            continue
        key = f"{name}:{str(prop.value)[:80]}"
        if key in seen:
            continue
        seen.add(key)
        statement = prop.matched_text or f"{name}={prop.value}"
        premises.append(
            Premise(
                statement=f"{rule.rule_id} {name}={str(prop.value)[:120]}",
                origin=ClaimOrigin.SOURCE.value,
                evidence_refs=tuple(prop.evidence),
                key=key[:160],
            )
        )
        if prop.matched_text and prop.matched_text != statement:
            premises.append(
                Premise(
                    statement=prop.matched_text[:240],
                    origin=ClaimOrigin.SOURCE.value,
                    evidence_refs=tuple(prop.evidence),
                    key=f"text:{key}"[:160],
                )
            )
    return premises


__all__ = [
    "EVALUATION_VERSION",
    "RequirementState",
    "RuleCheck",
    "RuleEvaluation",
    "RuleEvaluationStatus",
    "RuleRequirement",
    "evaluate_rule",
    "evaluate_rules",
    "rule_premises",
]
