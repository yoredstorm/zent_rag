# =============================================================================
# Deterministic operations registry — operaciones permitidas, sin eval libre
# =============================================================================
# El LLM decide libremente el resultado cuando la operación es determinista:
# eso no es razonamiento, es una fuente de alucinación. Acá viven las
# operaciones seguras que el runtime puede ejecutar sobre premisas grounded y
# datos del usuario:
#
#   ARITHMETIC, COMPARISON, BOOLEAN, SET_MEMBERSHIP, STRING_EQUALITY,
#   POSITIONAL_MATCH, RANGE_CHECK, ENUM_CHECK, DATE_COMPARISON,
#   DATE_ARITHMETIC, UNIT_CONVERSION, FORMULA_EVALUATION.
#
# NUNCA se ejecuta Python arbitrario: las expresiones se parsean con `ast` y
# sólo se evalúan nodos de una whitelist numérica/booleana.
# =============================================================================
from __future__ import annotations

import ast
import operator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any, Callable, Mapping

OPERATIONS_VERSION = "operations-1"


class OperationType(StrEnum):
    ARITHMETIC = "ARITHMETIC"
    COMPARISON = "COMPARISON"
    BOOLEAN = "BOOLEAN"
    SET_MEMBERSHIP = "SET_MEMBERSHIP"
    STRING_EQUALITY = "STRING_EQUALITY"
    STRING_COMPARE = "STRING_COMPARE"
    NUMERIC_COMPARE = "NUMERIC_COMPARE"
    POSITIONAL_MATCH = "POSITIONAL_MATCH"
    RANGE_CHECK = "RANGE_CHECK"
    ENUM_CHECK = "ENUM_CHECK"
    DATE_COMPARISON = "DATE_COMPARISON"
    DATE_RANGE = "DATE_RANGE"
    DATE_ARITHMETIC = "DATE_ARITHMETIC"
    UNIT_CONVERSION = "UNIT_CONVERSION"
    FORMULA_EVALUATION = "FORMULA_EVALUATION"
    BOOLEAN_RULE = "BOOLEAN_RULE"
    SET_RELATION = "SET_RELATION"


#: Operaciones que el motor determinista sabe ejecutar.
REGISTERED_OPERATIONS: tuple[str, ...] = tuple(op.value for op in OperationType)


class OperationStatus(StrEnum):
    OK = "OK"
    ERROR = "ERROR"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True, kw_only=True)
class OperationResult:
    operation: str
    status: str
    value: Any = None
    explanation: str = ""
    inputs: tuple[str, ...] = ()
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == OperationStatus.OK.value

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "status": self.status,
            "value": self.value,
            "explanation": self.explanation[:300],
            "inputs": list(self.inputs[:8]),
            "error": self.error[:200],
        }


def _normalize_number(value: Any) -> Any:
    """Colapsa ruido de punto flotante (55.00000000000001 -> 55)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        rounded = round(value, 10)
        if abs(rounded - round(rounded)) < 1e-9:
            return int(round(rounded))
        return rounded
    return value


def _error(operation: str, message: str, *, inputs: tuple[str, ...] = ()) -> OperationResult:
    return OperationResult(
        operation=operation,
        status=OperationStatus.ERROR.value,
        error=message,
        inputs=inputs,
    )


# -----------------------------------------------------------------------------
# Expresiones seguras (ast whitelist)
# -----------------------------------------------------------------------------

_BIN_OPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
}
_COMPARE_OPS: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}

_MAX_POW_EXPONENT = 64


class UnsafeExpression(ValueError):
    """La expresión usa nodos fuera de la whitelist."""


def _eval_node(node: ast.AST, variables: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, variables)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, bool, str)):
            return node.value
        raise UnsafeExpression("constant type not allowed")
    if isinstance(node, ast.Name):
        name = node.id
        if name in variables:
            return variables[name]
        if name in ("True", "False"):
            return name == "True"
        raise UnsafeExpression(f"unknown name: {name}")
    if isinstance(node, ast.BinOp):
        handler = _BIN_OPS.get(type(node.op))
        if handler is None:
            raise UnsafeExpression("binary operator not allowed")
        left = _eval_node(node.left, variables)
        right = _eval_node(node.right, variables)
        if isinstance(node.op, ast.Pow) and isinstance(right, (int, float)) and right > _MAX_POW_EXPONENT:
            raise UnsafeExpression("exponent too large")
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right in (0, 0.0):
            raise UnsafeExpression("division by zero")
        return handler(left, right)
    if isinstance(node, ast.UnaryOp):
        handler = _UNARY_OPS.get(type(node.op))
        if handler is None:
            raise UnsafeExpression("unary operator not allowed")
        return handler(_eval_node(node.operand, variables))
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, variables)
        for op_node, comparator in zip(node.ops, node.comparators):
            handler = _COMPARE_OPS.get(type(op_node))
            if handler is None:
                raise UnsafeExpression("comparison operator not allowed")
            right = _eval_node(comparator, variables)
            if not handler(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.BoolOp):
        values = [_eval_node(value, variables) for value in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
        raise UnsafeExpression("boolean operator not allowed")
    raise UnsafeExpression(f"node not allowed: {type(node).__name__}")


def evaluate_expression(expression: str, variables: Mapping[str, Any] | None = None) -> Any:
    """Evalúa una expresión aritmética/booleana con nodos whitelisted."""
    text = str(expression or "").strip()
    if not text:
        raise UnsafeExpression("empty expression")
    # Acepta «total = precio * (1 + tasa)»: la fórmula documental trae igual.
    if "=" in text and not any(op in text for op in ("==", ">=", "<=", "!=")):
        text = text.split("=", 1)[1].strip()
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpression(f"syntax error: {exc.msg}") from exc
    return _eval_node(tree, dict(variables or {}))


def _coerce_number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            number = float(value.replace(",", "."))
        except ValueError:
            return None
        return int(number) if number.is_integer() else number
    return None


# -----------------------------------------------------------------------------
# Operaciones
# -----------------------------------------------------------------------------


def run_arithmetic(
    expression: str | None = None,
    *,
    variables: Mapping[str, Any] | None = None,
    a: Any = None,
    b: Any = None,
    op: str = "add",
) -> OperationResult:
    operation = OperationType.ARITHMETIC.value
    try:
        if expression is not None:
            value = _normalize_number(evaluate_expression(expression, variables))
            return OperationResult(
                operation=operation,
                status=OperationStatus.OK.value,
                value=value,
                explanation=f"evaluated {expression}",
                inputs=tuple(sorted((variables or {}).keys())),
            )
        left, right = _coerce_number(a), _coerce_number(b)
        if left is None or right is None:
            return _error(operation, "non-numeric operand")
        handlers = {
            "add": operator.add,
            "sub": operator.sub,
            "mul": operator.mul,
            "div": operator.truediv,
            "mod": operator.mod,
        }
        handler = handlers.get(str(op))
        if handler is None:
            return _error(operation, f"unknown arithmetic op: {op}")
        if str(op) == "div" and right == 0:
            return _error(operation, "division by zero")
        value = _normalize_number(handler(left, right))
        return OperationResult(
            operation=operation,
            status=OperationStatus.OK.value,
            value=value,
            explanation=f"{left} {op} {right} = {value}",
            inputs=(str(a), str(b)),
        )
    except UnsafeExpression as exc:
        return _error(operation, str(exc))


def run_comparison(
    a: Any,
    b: Any,
    *,
    op: str = "ge",
    case_sensitive: bool = False,
) -> OperationResult:
    operation = OperationType.COMPARISON.value
    left, right = _coerce_number(a), _coerce_number(b)
    if left is None or right is None:
        if not isinstance(a, str) or not isinstance(b, str):
            return _error(operation, "incomparable operands")
        left = a if case_sensitive else str(a).lower()
        right = b if case_sensitive else str(b).lower()
    handlers: dict[str, Callable[[Any, Any], bool]] = {
        "eq": operator.eq,
        "ne": operator.ne,
        "lt": operator.lt,
        "le": operator.le,
        "gt": operator.gt,
        "ge": operator.ge,
    }
    symbols = {"eq": "==", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}
    handler = handlers.get(str(op))
    if handler is None:
        return _error(operation, f"unknown comparison op: {op}")
    result = bool(handler(left, right))
    return OperationResult(
        operation=operation,
        status=OperationStatus.OK.value,
        value=result,
        explanation=f"{left} {symbols[str(op)]} {right} is {result}",
        inputs=(str(a), str(b)),
    )


def run_boolean(
    expression: str,
    *,
    variables: Mapping[str, Any] | None = None,
) -> OperationResult:
    operation = OperationType.BOOLEAN.value
    try:
        value = bool(evaluate_expression(expression, variables))
        return OperationResult(
            operation=operation,
            status=OperationStatus.OK.value,
            value=value,
            explanation=f"boolean({expression}) = {value}",
            inputs=tuple(sorted((variables or {}).keys())),
        )
    except UnsafeExpression as exc:
        return _error(operation, str(exc))


def run_set_membership(value: Any, options: Any) -> OperationResult:
    operation = OperationType.SET_MEMBERSHIP.value
    if isinstance(options, str):
        options = [part.strip() for part in options.split(",") if part.strip()]
    try:
        normalized = [str(item).strip().lower() for item in options]
    except TypeError:
        return _error(operation, "options not iterable")
    result = str(value).strip().lower() in normalized
    return OperationResult(
        operation=operation,
        status=OperationStatus.OK.value,
        value=result,
        explanation=f"{value} in {{{', '.join(str(item) for item in options[:8])}}} is {result}",
        inputs=(str(value),),
    )


def run_string_equality(a: Any, b: Any, *, case_sensitive: bool = False) -> OperationResult:
    operation = OperationType.STRING_EQUALITY.value
    left = str(a)
    right = str(b)
    result = left == right if case_sensitive else left.lower() == right.lower()
    return OperationResult(
        operation=operation,
        status=OperationStatus.OK.value,
        value=result,
        explanation=f"'{left}' {'==' if result else '!='} '{right}'",
        inputs=(left, right),
    )


def run_string_compare(
    a: Any,
    b: Any,
    *,
    op: str = "eq",
    case_sensitive: bool = False,
) -> OperationResult:
    """Comparación de strings con orden y sensibilidad a mayúsculas."""
    operation = OperationType.STRING_COMPARE.value
    left = str(a)
    right = str(b)
    if not case_sensitive:
        left, right = left.lower(), right.lower()
    handlers: dict[str, Callable[[Any, Any], bool]] = {
        "eq": operator.eq,
        "ne": operator.ne,
        "lt": operator.lt,
        "le": operator.le,
        "gt": operator.gt,
        "ge": operator.ge,
    }
    handler = handlers.get(str(op))
    if handler is None:
        return _error(operation, f"unknown string op: {op}")
    result = bool(handler(left, right))
    return OperationResult(
        operation=operation,
        status=OperationStatus.OK.value,
        value=result,
        explanation=f"'{left}' {str(op)} '{right}' is {result}",
        inputs=(str(a), str(b)),
    )


def run_numeric_compare(
    a: Any,
    b: Any,
    *,
    op: str = "ge",
) -> OperationResult:
    """Comparación numérica estricta: no compara strings como números."""
    operation = OperationType.NUMERIC_COMPARE.value
    left, right = _coerce_number(a), _coerce_number(b)
    if left is None or right is None:
        return _error(operation, "non-numeric operand")
    return run_comparison(left, right, op=op)


def run_date_range(
    value: Any,
    *,
    start: Any = None,
    end: Any = None,
    inclusive: bool = True,
) -> OperationResult:
    """Pertenencia a una ventana temporal [start, end]."""
    operation = OperationType.DATE_RANGE.value
    target = _parse_date(value)
    if target is None:
        return _error(operation, "unparseable date")
    low = _parse_date(start) if start is not None else None
    high = _parse_date(end) if end is not None else None
    if start is not None and low is None:
        return _error(operation, "unparseable range start")
    if end is not None and high is None:
        return _error(operation, "unparseable range end")
    if inclusive:
        result = (low is None or target >= low) and (high is None or target <= high)
    else:
        result = (low is None or target > low) and (high is None or target < high)
    return OperationResult(
        operation=operation,
        status=OperationStatus.OK.value,
        value=bool(result),
        explanation=(
            f"{target.isoformat()} in "
            f"[{low.isoformat() if low else '-inf'}, {high.isoformat() if high else '+inf'}] "
            f"inclusive={inclusive}"
        ),
        inputs=(str(value),),
    )


def run_set_relation(
    a: Any,
    b: Any,
    *,
    relation: str = "subset",
) -> OperationResult:
    """Relación entre conjuntos: subset | superset | disjoint | intersects | equal."""
    operation = OperationType.SET_RELATION.value

    def _as_set(value: Any) -> set[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            return {part.strip() for part in value.split(",") if part.strip()}
        try:
            return {str(item).strip() for item in value}
        except TypeError:
            return None

    left, right = _as_set(a), _as_set(b)
    if left is None or right is None:
        return _error(operation, "set operands not iterable")
    handlers: dict[str, Callable[[set], bool]] = {
        "subset": lambda: left <= right,
        "superset": lambda: left >= right,
        "disjoint": lambda: left.isdisjoint(right),
        "intersects": lambda: bool(left & right),
        "equal": lambda: left == right,
    }
    handler = handlers.get(str(relation))
    if handler is None:
        return _error(operation, f"unknown set relation: {relation}")
    result = bool(handler())
    return OperationResult(
        operation=operation,
        status=OperationStatus.OK.value,
        value=result,
        explanation=f"|A|={len(left)} |B|={len(right)} {relation} is {result}",
        inputs=(str(a), str(b)),
    )


def run_range_check(
    value: Any,
    *,
    minimum: Any = None,
    maximum: Any = None,
    inclusive: bool = True,
) -> OperationResult:
    operation = OperationType.RANGE_CHECK.value
    number = _coerce_number(value)
    low = _coerce_number(minimum) if minimum is not None else None
    high = _coerce_number(maximum) if maximum is not None else None
    if number is None or (minimum is not None and low is None) or (maximum is not None and high is None):
        return _error(operation, "non-numeric range operands")
    if low is not None and high is not None and low > high:
        low, high = high, low
    if inclusive:
        result = (low is None or number >= low) and (high is None or number <= high)
    else:
        result = (low is None or number > low) and (high is None or number < high)
    bounds = f"[{low if low is not None else '-inf'}, {high if high is not None else '+inf'}]"
    return OperationResult(
        operation=operation,
        status=OperationStatus.OK.value,
        value=bool(result),
        explanation=f"{number} in {bounds} is {result}",
        inputs=(str(value),),
    )


def run_enum_check(value: Any, allowed: Any, *, case_sensitive: bool = False) -> OperationResult:
    operation = OperationType.ENUM_CHECK.value
    if isinstance(allowed, str):
        allowed = [part.strip() for part in allowed.split(",") if part.strip()]
    try:
        options = [str(item).strip() for item in allowed]
    except TypeError:
        return _error(operation, "allowed values not iterable")
    candidate = str(value).strip()
    if case_sensitive:
        result = candidate in options
    else:
        result = candidate.lower() in [option.lower() for option in options]
    return OperationResult(
        operation=operation,
        status=OperationStatus.OK.value,
        value=bool(result),
        explanation=f"'{candidate}' {'is in' if result else 'is not in'} allowed values",
        inputs=(candidate,),
    )


def run_date_comparison(a: Any, b: Any, *, op: str = "le") -> OperationResult:
    operation = OperationType.DATE_COMPARISON.value
    left, right = _parse_date(a), _parse_date(b)
    if left is None or right is None:
        return _error(operation, "unparseable date")
    handlers: dict[str, Callable[[Any, Any], bool]] = {
        "eq": operator.eq,
        "ne": operator.ne,
        "lt": operator.lt,
        "le": operator.le,
        "gt": operator.gt,
        "ge": operator.ge,
    }
    symbols = {"eq": "==", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}
    handler = handlers.get(str(op))
    if handler is None:
        return _error(operation, f"unknown comparison op: {op}")
    result = bool(handler(left, right))
    return OperationResult(
        operation=operation,
        status=OperationStatus.OK.value,
        value=result,
        explanation=f"{left.isoformat()} {symbols[str(op)]} {right.isoformat()} is {result}",
        inputs=(str(a), str(b)),
    )


def run_date_arithmetic(value: Any, *, days: int = 0, weeks: int = 0, months: int = 0) -> OperationResult:
    operation = OperationType.DATE_ARITHMETIC.value
    base = _parse_date(value)
    if base is None:
        return _error(operation, "unparseable date")
    result = base + timedelta(days=int(days) + 7 * int(weeks))
    if months:
        month_index = result.month - 1 + int(months)
        year = result.year + month_index // 12
        month = month_index % 12 + 1
        day = min(result.day, _days_in_month(year, month))
        result = date(year, month, day)
    return OperationResult(
        operation=operation,
        status=OperationStatus.OK.value,
        value=result.isoformat(),
        explanation=f"{base.isoformat()} + {days}d {weeks}w {months}m = {result.isoformat()}",
        inputs=(str(value),),
    )


def run_unit_conversion(value: Any, *, from_unit: str, to_unit: str) -> OperationResult:
    operation = OperationType.UNIT_CONVERSION.value
    number = _coerce_number(value)
    if number is None:
        return _error(operation, "non-numeric value")
    factor = _UNIT_FACTORS.get((from_unit.lower(), to_unit.lower()))
    if factor is None:
        # Temperaturas: conversiones afines.
        temperature = _TEMPERATURE_CONVERSIONS.get((from_unit.lower(), to_unit.lower()))
        if temperature is None:
            return _error(operation, f"unsupported conversion {from_unit}->{to_unit}")
        result = temperature(float(number))
    else:
        result = float(number) * factor
        if float(result).is_integer():
            result = int(result)
    return OperationResult(
        operation=operation,
        status=OperationStatus.OK.value,
        value=result,
        explanation=f"{number} {from_unit} = {result} {to_unit}",
        inputs=(str(value),),
    )


def run_formula(
    formula: str,
    *,
    variables: Mapping[str, Any] | None = None,
) -> OperationResult:
    operation = OperationType.FORMULA_EVALUATION.value
    try:
        value = _normalize_number(evaluate_expression(formula, variables))
        return OperationResult(
            operation=operation,
            status=OperationStatus.OK.value,
            value=value,
            explanation=f"{formula.strip()} with {sorted((variables or {}).keys())} = {value}",
            inputs=tuple(sorted((variables or {}).keys())),
        )
    except UnsafeExpression as exc:
        return _error(operation, str(exc))


def run_positional_match(
    value: Any,
    pattern: Any,
    semantics: Any,
    **kwargs: Any,
) -> OperationResult:
    operation = OperationType.POSITIONAL_MATCH.value
    try:
        from src.rag.longcontext.pattern import positional_match

        result = positional_match(str(value), str(pattern), semantics, **kwargs)
        return OperationResult(
            operation=operation,
            status=OperationStatus.OK.value if result.derived else OperationStatus.UNSUPPORTED.value,
            value=result.status,
            explanation=result.reason,
            inputs=(str(value), str(pattern)),
            error="" if result.derived else ", ".join(result.missing_premises),
        )
    except Exception as exc:  # noqa: BLE001 — el registry nunca lanza
        return _error(operation, str(exc)[:200])


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
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
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)).day


#: Factores multiplicativos directos (unidades base: metro, gramo, segundo, litro).
_UNIT_FACTORS: dict[tuple[str, str], float] = {
    ("km", "m"): 1000.0,
    ("m", "km"): 0.001,
    ("m", "cm"): 100.0,
    ("cm", "m"): 0.01,
    ("in", "cm"): 2.54,
    ("cm", "in"): 1 / 2.54,
    ("ft", "m"): 0.3048,
    ("m", "ft"): 1 / 0.3048,
    ("mi", "km"): 1.609344,
    ("km", "mi"): 1 / 1.609344,
    ("kg", "g"): 1000.0,
    ("g", "kg"): 0.001,
    ("lb", "kg"): 0.45359237,
    ("kg", "lb"): 1 / 0.45359237,
    ("oz", "g"): 28.349523125,
    ("g", "oz"): 1 / 28.349523125,
    ("l", "ml"): 1000.0,
    ("ml", "l"): 0.001,
    ("gal", "l"): 3.785411784,
    ("l", "gal"): 1 / 3.785411784,
    ("h", "min"): 60.0,
    ("min", "s"): 60.0,
    ("h", "s"): 3600.0,
}

#: Conversiones afines de temperatura: (desde, hasta) -> fn.
_TEMPERATURE_CONVERSIONS: dict[tuple[str, str], Callable[[float], float]] = {
    ("c", "f"): lambda c: c * 9 / 5 + 32,
    ("f", "c"): lambda f: (f - 32) * 5 / 9,
    ("c", "k"): lambda c: c + 273.15,
    ("k", "c"): lambda k: k - 273.15,
    ("f", "k"): lambda f: (f - 32) * 5 / 9 + 273.15,
    ("k", "f"): lambda k: (k - 273.15) * 9 / 5 + 32,
}


class OperationRegistry:
    """Registry seguro: el runtime sólo ejecuta operaciones registradas."""

    def __init__(self, *, enabled: bool = True) -> None:
        self._enabled = bool(enabled)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def available(self) -> tuple[str, ...]:
        return REGISTERED_OPERATIONS if self._enabled else ()

    def allows(self, operation: str) -> bool:
        return self._enabled and str(operation).upper() in REGISTERED_OPERATIONS

    def run(self, operation: str, **kwargs: Any) -> OperationResult:
        name = str(operation or "").upper()
        if not self.allows(name):
            return OperationResult(
                operation=name,
                status=OperationStatus.UNSUPPORTED.value,
                error="operation not registered or disabled",
            )
        if name == OperationType.ARITHMETIC.value:
            return run_arithmetic(
                kwargs.get("expression"),
                variables=kwargs.get("variables"),
                a=kwargs.get("a"),
                b=kwargs.get("b"),
                op=str(kwargs.get("op") or "add"),
            )
        if name == OperationType.COMPARISON.value:
            return run_comparison(
                kwargs.get("a"), kwargs.get("b"), op=str(kwargs.get("op") or "ge")
            )
        if name == OperationType.BOOLEAN.value:
            return run_boolean(str(kwargs.get("expression") or ""), variables=kwargs.get("variables"))
        if name == OperationType.SET_MEMBERSHIP.value:
            return run_set_membership(kwargs.get("value"), kwargs.get("options") or ())
        if name == OperationType.STRING_EQUALITY.value:
            return run_string_equality(
                kwargs.get("a"),
                kwargs.get("b"),
                case_sensitive=bool(kwargs.get("case_sensitive", False)),
            )
        if name == OperationType.STRING_COMPARE.value:
            return run_string_compare(
                kwargs.get("a"),
                kwargs.get("b"),
                op=str(kwargs.get("op") or "eq"),
                case_sensitive=bool(kwargs.get("case_sensitive", False)),
            )
        if name == OperationType.NUMERIC_COMPARE.value:
            return run_numeric_compare(
                kwargs.get("a"), kwargs.get("b"), op=str(kwargs.get("op") or "ge")
            )
        if name == OperationType.DATE_RANGE.value:
            return run_date_range(
                kwargs.get("value"),
                start=kwargs.get("start"),
                end=kwargs.get("end"),
                inclusive=bool(kwargs.get("inclusive", True)),
            )
        if name == OperationType.BOOLEAN_RULE.value:
            outcome = run_boolean(
                str(kwargs.get("expression") or ""),
                variables=kwargs.get("variables"),
            )
            return OperationResult(
                operation=OperationType.BOOLEAN_RULE.value,
                status=outcome.status,
                value=outcome.value,
                explanation=outcome.explanation,
                inputs=outcome.inputs,
                error=outcome.error,
            )
        if name == OperationType.SET_RELATION.value:
            return run_set_relation(
                kwargs.get("a"),
                kwargs.get("b"),
                relation=str(kwargs.get("relation") or "subset"),
            )
        if name == OperationType.POSITIONAL_MATCH.value:
            return run_positional_match(
                kwargs.get("value"), kwargs.get("pattern"), kwargs.get("semantics")
            )
        if name == OperationType.RANGE_CHECK.value:
            return run_range_check(
                kwargs.get("value"),
                minimum=kwargs.get("minimum"),
                maximum=kwargs.get("maximum"),
                inclusive=bool(kwargs.get("inclusive", True)),
            )
        if name == OperationType.ENUM_CHECK.value:
            return run_enum_check(kwargs.get("value"), kwargs.get("allowed") or ())
        if name == OperationType.DATE_COMPARISON.value:
            return run_date_comparison(
                kwargs.get("a"), kwargs.get("b"), op=str(kwargs.get("op") or "le")
            )
        if name == OperationType.DATE_ARITHMETIC.value:
            return run_date_arithmetic(
                kwargs.get("value"),
                days=int(kwargs.get("days") or 0),
                weeks=int(kwargs.get("weeks") or 0),
                months=int(kwargs.get("months") or 0),
            )
        if name == OperationType.UNIT_CONVERSION.value:
            return run_unit_conversion(
                kwargs.get("value"),
                from_unit=str(kwargs.get("from_unit") or ""),
                to_unit=str(kwargs.get("to_unit") or ""),
            )
        if name == OperationType.FORMULA_EVALUATION.value:
            return run_formula(str(kwargs.get("formula") or ""), variables=kwargs.get("variables"))
        return OperationResult(
            operation=name,
            status=OperationStatus.UNSUPPORTED.value,
            error="operation not implemented",
        )


#: Instancia compartida (barata, sin estado mutable).
DEFAULT_REGISTRY = OperationRegistry()


__all__ = [
    "DEFAULT_REGISTRY",
    "OPERATIONS_VERSION",
    "REGISTERED_OPERATIONS",
    "OperationRegistry",
    "OperationResult",
    "OperationStatus",
    "OperationType",
    "UnsafeExpression",
    "evaluate_expression",
    "run_arithmetic",
    "run_boolean",
    "run_comparison",
    "run_date_arithmetic",
    "run_date_comparison",
    "run_date_range",
    "run_enum_check",
    "run_formula",
    "run_numeric_compare",
    "run_positional_match",
    "run_range_check",
    "run_set_membership",
    "run_set_relation",
    "run_string_compare",
    "run_string_equality",
    "run_unit_conversion",
]
