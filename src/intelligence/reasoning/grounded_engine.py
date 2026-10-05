# =============================================================================
# Grounded Reasoning Engine — premisas grounded + datos del usuario → resultado
# =============================================================================
# El motor que cierra el contrato conceptual de ZENT:
#
#   QUERY SEMANTICS  (qué es cada token de la pregunta)
#        ↓
#   GROUNDING        (qué premisas exige y cuáles están respaldadas)
#        ↓
#   DERIVATION       (operación determinista sobre premisas + inputs)
#        ↓
#   ANSWERABILITY    (ANSWERABLE_DERIVED | UNANSWERABLE_MISSING_PREMISE | ...)
#
# Determinista y fail-soft: sin LLM. El LLM después EXPLICA el resultado; no
# lo decide cuando puede resolverse determinísticamente.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from src.core.domain.grounding import (
    ClaimOrigin,
    DerivedClaim,
    GroundingCategory,
    GroundingContract,
    Premise,
    resolve_grounding_mode,
)
from src.intelligence.query_semantics import (
    QuerySemanticRole,
    QuerySemantics,
    classify_query_semantics,
    detect_query_intent,
)
from src.intelligence.reasoning.derivation import (
    DerivationGraph,
    claim_from_operation,
)
from src.intelligence.reasoning.operations import (
    DEFAULT_REGISTRY,
    OperationRegistry,
    OperationResult,
    OperationStatus,
)

GROUNDED_ENGINE_VERSION = "grounded-engine-1"

#: Estados de answerability conscientes de derivación (§21).
ANSWERABLE_DIRECT = "ANSWERABLE_DIRECT"
ANSWERABLE_DERIVED = "ANSWERABLE_DERIVED"
ANSWERABLE_WITH_LIMITS = "ANSWERABLE_WITH_LIMITS"
UNANSWERABLE_MISSING_PREMISE = "UNANSWERABLE_MISSING_PREMISE"
UNANSWERABLE_CONFLICT = "UNANSWERABLE_CONFLICT"
NOT_APPLICABLE = "NOT_APPLICABLE"

_OPERATIONS_BY_INTENT: Mapping[str, tuple[str, ...]] = {
    "APPLY_RULE": ("POSITIONAL_MATCH", "ENUM_CHECK", "RANGE_CHECK", "SET_MEMBERSHIP"),
    "VALIDATE": ("POSITIONAL_MATCH", "ENUM_CHECK", "RANGE_CHECK", "SET_MEMBERSHIP"),
    "CALCULATE": ("FORMULA_EVALUATION", "ARITHMETIC", "UNIT_CONVERSION"),
    "COMPARE": ("COMPARISON", "RANGE_CHECK"),
    "TRANSFORM": ("STRING_EQUALITY",),
    "INFER": ("BOOLEAN", "COMPARISON"),
}

#: Frases de fórmula natural ES/EN → expresión.
_WORD_OPERATORS: tuple[tuple[str, str], ...] = (
    (r"\b(?:plus|más|mas|and)\b", "+"),
    (r"\b(?:minus|menos)\b", "-"),
    (r"\b(?:times|multiplied\s+by|por)\b", "*"),
    (r"\b(?:divided\s+by|dividido\s+(?:por|entre)|entre)\b", "/"),
)
_FORMULA_EQ_RE = re.compile(
    r"\b([a-z_áéíóúñ][a-z0-9_áéíóúñ ]{0,40}?)\s*=\s*([^=.\n;]+?[+\-*/][^=.\n;]+)",
    re.IGNORECASE,
)
_FORMULA_NATURAL_RE = re.compile(
    r"\b([a-z_áéíóúñ][a-z0-9_áéíóúñ ]{0,40}?)\s+(?:is|es)\s+"
    r"(?:calculated|calculad[ao])\s+(?:as|como)\s+([^.\n;]+)",
    re.IGNORECASE,
)
_MIN_THRESHOLD_RE = re.compile(
    r"(?:>=|≥|at\s+least|m[ií]nim[oa]s?|minim[oa]s?|minimum|"
    r"(?:edad|age)\s+m[ií]nim[ao])\s*(?:de\s+|es\s+|[:=])?\s*(\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)
_MAX_THRESHOLD_RE = re.compile(
    r"(?:<=|≤|at\s+most|m[aá]xim[oa]s?|maxim[oa]s?|maximum|"
    r"(?:edad|age)\s+m[aá]xim[ao])\s*(?:de\s+|es\s+|[:=])?\s*(\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)
_ENUM_LIST_RE = re.compile(
    r"(?:allowed|permitid[oa]s?|v[aá]lid[oa]s?|estados?\s+permitidos?|estados?|"
    r"statuses?|values?|valores?)\s*:?\s*"
    r"([A-Z][A-Z0-9_]{1,}(?:\s*,\s*[A-Z][A-Z0-9_]{1,})+)"
)
_VARIABLE_RE = re.compile(r"[a-z_áéíóúñ][a-z0-9_áéíóúñ]*", re.IGNORECASE)
#: Expresión aritmética explícita en la pregunta («3 + 3», «10 - 4»).
_ARITHMETIC_Q_RE = re.compile(
    r"(-?\d+(?:[.,]\d+)?)\s*([+\-*/])\s*(-?\d+(?:[.,]\d+)?)"
)

_MAX_EVIDENCE_CHARS = 240_000


def _item_content(item: Any) -> str:
    if isinstance(item, str):
        return item
    return str(getattr(item, "content", "") or "")


def _item_ref(item: Any, index: int) -> str:
    if isinstance(item, str):
        return f"E{index + 1}"
    return str(getattr(item, "evidence_id", "") or f"E{index + 1}")


@dataclass(frozen=True, kw_only=True)
class _FormulaPremise:
    target: str
    expression: str
    statement: str
    refs: tuple[str, ...] = ()


@dataclass(kw_only=True)
class GroundedReasoningResult:
    """Resultado del motor: semántica, premisas, derivaciones y answerability."""

    question: str
    semantics: QuerySemantics
    contract: GroundingContract
    premises: tuple[Premise, ...] = ()
    runtime_inputs: tuple[str, ...] = ()
    runtime_patterns: tuple[str, ...] = ()
    derivations: DerivationGraph = field(default_factory=DerivationGraph)
    missing_premises: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    answerability: str = NOT_APPLICABLE
    abstention_message: str = ""
    decided_by: str = "deterministic"
    version: str = GROUNDED_ENGINE_VERSION

    @property
    def has_derivation(self) -> bool:
        return self.derivations.has_supported_result

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "version": self.version,
            "answerability": self.answerability,
            "decided_by": self.decided_by,
            "intent": self.semantics.intent,
            "semantics": self.semantics.to_public_dict(),
            "query_semantics": [
                {
                    "value": obj.value,
                    "role": obj.semantic_role.lower(),
                    "evidence_required": bool(obj.evidence_required),
                }
                for obj in self.semantics.objects[:16]
            ],
            "knowledge_requirements": [
                {
                    "statement": premise.statement[:200],
                    "origin": premise.origin,
                    "evidence_refs": list(premise.evidence_refs[:4]),
                }
                for premise in self.premises[:8]
            ],
            "grounding": self.contract.to_public_dict(),
            "premises": [premise.to_public_dict() for premise in self.premises[:8]],
            "runtime_inputs": list(self.runtime_inputs[:8]),
            "runtime_patterns": list(self.runtime_patterns[:8]),
            "derivations": self.derivations.to_public_dict(),
            "missing_premises": list(self.missing_premises[:12]),
        }
        derived = self.derivations.derived_results
        if derived:
            payload["derived_result"] = derived[0].result
        if self.abstention_message:
            payload["abstention_message"] = self.abstention_message[:400]
        if self.conflicts:
            payload["conflicts"] = list(self.conflicts[:6])
        return payload


def _find_refs(statement: str, items: Sequence[Any]) -> tuple[str, ...]:
    needle = " ".join(str(statement or "").lower().split())[:80]
    if not needle:
        return ()
    refs: list[str] = []
    for index, item in enumerate(items):
        content = _item_content(item).lower()
        # Una aguja larga cae por whitespace: se compara por sus primeras palabras.
        probe = needle[:48]
        if probe and probe in content:
            refs.append(_item_ref(item, index))
    return tuple(dict.fromkeys(refs))


def _is_threshold(statement: str) -> bool:
    return bool(_MIN_THRESHOLD_RE.search(statement) or _MAX_THRESHOLD_RE.search(statement))


def _natural_to_expression(rhs: str) -> str:
    expression = str(rhs or "").strip()
    for word, symbol in _WORD_OPERATORS:
        expression = re.sub(word, f" {symbol} ", expression, flags=re.IGNORECASE)
    # «base amount» → «base_amount»: une palabras vecinas para el binder.
    expression = re.sub(r"(?<=[a-záéíóúñ])\s+(?=[a-záéíóúñ])", "_", expression, flags=re.IGNORECASE)
    expression = re.sub(r"\s+", " ", expression).strip(" _")
    return expression


def extract_formula_premises(items: Sequence[Any]) -> tuple[_FormulaPremise, ...]:
    """Fórmulas documentadas: `total = expr` o «X is calculated as …»."""
    text = "\n".join(_item_content(item) for item in items)[:_MAX_EVIDENCE_CHARS]
    formulas: list[_FormulaPremise] = []
    for match in _FORMULA_EQ_RE.finditer(text):
        target = match.group(1).strip().lower().replace(" ", "_")
        expression = match.group(2).strip()
        if _is_threshold(match.group(0)):
            continue
        formulas.append(
            _FormulaPremise(
                target=target,
                expression=expression,
                statement=match.group(0).strip()[:200],
                refs=_find_refs(match.group(0), items),
            )
        )
    for match in _FORMULA_NATURAL_RE.finditer(text):
        target = match.group(1).strip().lower().replace(" ", "_")
        expression = _natural_to_expression(match.group(2))
        if not re.search(r"[+\-*/]", expression):
            continue
        formulas.append(
            _FormulaPremise(
                target=target,
                expression=expression,
                statement=match.group(0).strip()[:200],
                refs=_find_refs(match.group(0), items),
            )
        )
    # Sin duplicados por (target, expresión).
    seen: set[tuple[str, str]] = set()
    unique: list[_FormulaPremise] = []
    for formula in formulas:
        key = (formula.target, formula.expression)
        if key in seen:
            continue
        seen.add(key)
        unique.append(formula)
    return tuple(unique)


def _bind_variables(
    expression: str, params: Mapping[str, str]
) -> tuple[dict[str, float], tuple[str, ...]]:
    """Une variables de la fórmula con parámetros del usuario (difuso, determinista)."""
    bound: dict[str, float] = {}
    missing: list[str] = []
    names = {match.group(0).lower() for match in _VARIABLE_RE.finditer(expression)}
    for name in sorted(names):
        if name in ("and", "or", "not", "e", "o", "y"):
            continue
        value = _match_param(name, params)
        if value is None:
            missing.append(name)
            continue
        bound[name] = value
    return bound, tuple(missing)


#: Alias ES/EN para unir variables de fórmula con parámetros del usuario.
_PARAM_ALIASES: dict[str, tuple[str, ...]] = {
    "price": ("precio", "valor_unitario", "unit_price"),
    "precio": ("price",),
    "amount": ("monto", "importe", "cantidad"),
    "monto": ("amount", "importe"),
    "importe": ("amount", "monto"),
    "tax_rate": ("tasa", "impuesto", "iva", "tax", "rate"),
    "rate": ("tasa", "tax_rate"),
    "tasa": ("rate", "tax_rate"),
    "tax": ("impuesto", "tax_rate"),
    "impuesto": ("tax", "tax_rate"),
    "surcharge": ("recargo", "cargo", "sobretasa"),
    "recargo": ("surcharge", "cargo"),
    "fee": ("tarifa", "cargo", "comision", "comisión"),
    "tarifa": ("fee", "rate"),
    "discount": ("descuento",),
    "descuento": ("discount",),
    "quantity": ("cantidad", "qty"),
    "cantidad": ("quantity", "qty"),
    "weight": ("peso",),
    "peso": ("weight",),
    "age": ("edad",),
    "edad": ("age",),
    "status": ("estado",),
    "estado": ("status",),
}


def _match_param(name: str, params: Mapping[str, str]) -> float | None:
    candidates = [name]
    candidates.append(name.replace("_", ""))
    candidates.extend(_PARAM_ALIASES.get(name, ()))
    for param_name, raw in params.items():
        normalized = str(param_name or "").strip().lower().replace(" ", "_")
        if not normalized:
            continue
        if (
            normalized == name
            or normalized.startswith(name)
            or name.startswith(normalized)
            or normalized.replace("_", "") == name.replace("_", "")
        ):
            return _as_number(raw)
    for variant in candidates:
        for param_name, raw in params.items():
            normalized = str(param_name or "").strip().lower().replace(" ", "_")
            if variant and (variant in normalized or normalized in variant):
                return _as_number(raw)
    return None


def _as_number(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _extract_range_premise(
    items: Sequence[Any],
) -> tuple[float | None, float | None, str, tuple[str, ...]]:
    text = "\n".join(_item_content(item) for item in items)[:_MAX_EVIDENCE_CHARS]
    minimum = None
    maximum = None
    statement = ""
    min_match = _MIN_THRESHOLD_RE.search(text)
    if min_match:
        minimum = _as_number(min_match.group(1))
        statement = text[max(0, min_match.start() - 40) : min_match.end() + 20].strip()
    max_match = _MAX_THRESHOLD_RE.search(text)
    if max_match:
        maximum = _as_number(max_match.group(1))
        if not statement:
            statement = text[max(0, max_match.start() - 40) : max_match.end() + 20].strip()
    refs = _find_refs(statement, items) if statement else ()
    return minimum, maximum, statement, refs


def _extract_enum_premise(
    items: Sequence[Any],
) -> tuple[tuple[str, ...], str, tuple[str, ...]]:
    text = "\n".join(_item_content(item) for item in items)[:_MAX_EVIDENCE_CHARS]
    match = _ENUM_LIST_RE.search(text)
    if not match:
        return (), "", ()
    options = tuple(
        part.strip() for part in match.group(1).split(",") if part.strip()
    )
    statement = match.group(0).strip()[:200]
    return options, statement, _find_refs(match.group(0), items)


def _runtime_params(semantics: QuerySemantics) -> dict[str, str]:
    params: dict[str, str] = {}
    for index, obj in enumerate(semantics.runtime_inputs):
        if obj.semantic_role != QuerySemanticRole.RUNTIME_PARAMETER.value:
            continue
        name = str(obj.cues[0]) if obj.cues else f"param_{index}"
        params[name] = obj.value
    return params


def _first_runtime_value(semantics: QuerySemantics) -> str:
    for obj in semantics.runtime_inputs:
        if obj.semantic_role in (
            QuerySemanticRole.USER_INPUT.value,
            QuerySemanticRole.USER_EXAMPLE.value,
            QuerySemanticRole.RUNTIME_VALUE.value,
        ):
            return obj.value
    # Un parámetro con letras/comodines puede ser el valor contra el patrón
    # («mi valor ASDF contra &&&F» capturado como keyword_value).
    for obj in semantics.runtime_inputs:
        value = str(obj.value or "")
        if value and any(char.isalpha() for char in value):
            return value
    return ""


def _pattern_premises(
    semantics_statements: Iterable[str],
    items: Sequence[Any],
) -> tuple[Premise, ...]:
    premises: list[Premise] = []
    for statement in semantics_statements:
        text = str(statement or "").strip()
        if not text:
            continue
        refs = _find_refs(text, items)
        premises.append(
            Premise(
                statement=text[:240],
                origin=ClaimOrigin.SOURCE.value,
                evidence_refs=refs,
                key=f"pattern:{text[:48].lower()}",
            )
        )
    return tuple(premises)


def _field_premises(
    semantics: QuerySemantics,
    items: Sequence[Any],
) -> tuple[Premise, ...]:
    """Premisas de campo documentadas («FCLAS: fare class…») para citar."""
    premises: list[Premise] = []
    for obj in semantics.field_requirements:
        value = str(obj.value or "").strip()
        if not value:
            continue
        for index, item in enumerate(items):
            content = _item_content(item)
            lowered = content.lower()
            if value.lower() not in lowered:
                continue
            sentence = next(
                (
                    part.strip()
                    for part in re.split(r"(?<=[.;\n])\s+", content)
                    if value.lower() in part.lower()
                ),
                content.strip(),
            )
            premises.append(
                Premise(
                    statement=sentence[:240],
                    origin=ClaimOrigin.SOURCE.value,
                    evidence_refs=(_item_ref(item, index),),
                    key=f"field:{value.lower()}",
                )
            )
            break
    return tuple(premises)


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value or "").strip()))


def missing_premise_message(missing: Sequence[str]) -> str:
    """Abstención correcta: nombra la PREMISA faltante, no el dato del usuario."""
    messages: list[str] = []
    for item in missing:
        text = str(item)
        if text.startswith("definition:symbol:"):
            symbol = text.rsplit(":", 1)[-1]
            messages.append(
                f"falta en las fuentes la definición necesaria del símbolo «{symbol}»"
            )
        elif text.startswith("semantics:symbol:"):
            symbol = text.rsplit(":", 1)[-1]
            messages.append(
                f"la semántica del símbolo «{symbol}» no es concluyente en las fuentes"
            )
        elif text == "matching_policy":
            messages.append(
                "falta en las fuentes la semántica de aplicación del patrón "
                "(posición/literalidad)"
            )
        elif text == "positional_semantics":
            messages.append(
                "falta en las fuentes la semántica posicional del patrón"
            )
        elif text == "literal_semantics":
            messages.append(
                "falta en las fuentes la coincidencia de caracteres literales"
            )
        elif text == "length_semantics":
            messages.append(
                "falta en las fuentes la política de longitud del patrón"
            )
        elif text.startswith("definition:policy:"):
            policy = text.rsplit(":", 1)[-1]
            messages.append(
                f"falta en las fuentes la definición de la política {policy}"
            )
        elif text.startswith("no_rule_valid_at:"):
            date_value = text.split(":", 1)[1]
            messages.append(
                f"no hay una regla vigente en las fuentes para la fecha {date_value}"
            )
        elif text.startswith("input:"):
            messages.append(f"falta el dato «{text.split(':', 1)[1]}» para calcular")
        else:
            messages.append(text)
    return " y ".join(dict.fromkeys(messages))[:400]


# -----------------------------------------------------------------------------
# Reglas booleanas, porcentajes, políticas referenciadas, temporalidad y strings
# -----------------------------------------------------------------------------

#: «if active and verified then eligible» / «active AND verified -> eligible»
_BOOL_RULE_ARROW_RE = re.compile(
    r"(?:if\s+)?([A-Za-zÁÉÍÓÚÑÜáéíóúñü][A-Za-z0-9ÁÉÍÓÚÑÜáéíóúñü_\s]{2,80}?)\s*"
    r"(?:->|→|=>|then|,?\s*entonces)\s*"
    r"([A-Za-zÁÉÍÓÚÑÜáéíóúñü][A-Za-z0-9ÁÉÍÓÚÑÜáéíóúñü_\s]{2,40})",
    re.IGNORECASE,
)
#: «eligible when active and verified» / «es elegible si está activo y verificado»
_BOOL_RULE_WHEN_RE = re.compile(
    r"([A-Za-zÁÉÍÓÚÑÜáéíóúñü][A-Za-z0-9ÁÉÍÓÚÑÜáéíóúñü_\s]{2,40}?)\s+"
    r"(?:when|if|cuando|si)\s+"
    r"([A-Za-zÁÉÍÓÚÑÜáéíóúñü][A-Za-z0-9ÁÉÍÓÚÑÜáéíóúñü_\s]{2,80})",
    re.IGNORECASE,
)
_BOOL_ALIASES: dict[str, tuple[str, ...]] = {
    "active": ("activo", "activa", "habilitado", "enabled"),
    "activo": ("active", "activa"),
    "verified": ("verificado", "verificada", "confirmado"),
    "verificado": ("verified",),
    "eligible": ("elegible", "califica", "apto"),
    "elegible": ("eligible",),
}

#: «tax rate = 18%», «IVA: 21 %», «tasa de impuesto 19%»
_PERCENT_RE = re.compile(
    r"(tax\s*rate|tax_rate|impuesto|iva|tasa(?:\s+de\s+impuesto)?|rate)\s*"
    r"(?:=|:)?\s*(\d+(?:[.,]\d+)?)\s*%",
    re.IGNORECASE,
)

#: «status must follow policy X», «según la política X»
_POLICY_REF_RE = re.compile(
    r"(?:must\s+follow|follow|according\s+to|seg[uú]n|de\s+acuerdo\s+(?:a|con)|"
    r"sigue|conforme\s+a|debe\s+seguir)\s+(?:the\s+|la\s+|el\s+)?"
    r"(?:policy|pol[ií]tica|rule|regla|norma)\s+([A-Z][A-Z0-9_-]{0,})",
    re.IGNORECASE,
)

#: «effective from 2026-01-01», «válida desde 01/01/2026»
_DATE_FROM_RE = re.compile(
    r"(?:effective|valid|v[aá]lid[ao]|in\s+effect|vigente)\s*"
    r"(?:from|after|desde|a\s+partir\s+de|el)?\s*"
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})",
    re.IGNORECASE,
)
#: «until 2025-12-31», «hasta el 31/12/2025»
_DATE_UNTIL_RE = re.compile(
    r"(?:until|through|hasta|antes\s+de|expira\s+el?)\s*"
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})",
    re.IGNORECASE,
)

#: «abc es igual a ABC», «X same as Y»
_EQUALITY_Q_RE = re.compile(
    r"([A-Za-z0-9_.-]{2,30})\s+(?:es\s+)?(?:igual\s+a|same\s+as|equivale\s+a)\s+"
    r"([A-Za-z0-9_.-]{2,30})",
    re.IGNORECASE,
)
_CASE_INSENSITIVE_RE = re.compile(
    r"case[\s-]*insensitive|ignora\s+may[uú]sculas|sin\s+distinguir\s+may[uú]sculas|"
    r"no\s+distingue\s+may[uú]sculas",
    re.IGNORECASE,
)
_CASE_SENSITIVE_RE = re.compile(
    r"case[\s-]*sensitive|distingue\s+may[uú]sculas|sensible\s+a\s+may[uú]sculas",
    re.IGNORECASE,
)
_UPPERCASE_RE = re.compile(
    r"(?:convert|transform|normaliz\w*|pasa\w*)\s+(?:to\s+)?uppercase|"
    r"may[uú]sculas\s+antes|en\s+may[uú]sculas",
    re.IGNORECASE,
)
_TAX_TOTAL_RE = re.compile(
    r"(?:total|monto|precio\s+final|importe|final\s+price|price\s+with)",
    re.IGNORECASE,
)
_TAX_WORD_RE = re.compile(r"(?:impuesto|iva|tax)", re.IGNORECASE)


@dataclass(frozen=True, kw_only=True)
class _RangeCandidate:
    minimum: float | None = None
    maximum: float | None = None
    statement: str = ""
    refs: tuple[str, ...] = ()
    valid_from: str = ""
    valid_until: str = ""


@dataclass(frozen=True, kw_only=True)
class _BooleanRule:
    conditions: tuple[str, ...]
    consequent: str
    statement: str
    refs: tuple[str, ...] = ()


def _as_bool(value: Any) -> bool | None:
    text = str(value or "").strip().lower()
    if text in ("true", "sí", "si", "yes", "1", "verdadero"):
        return True
    if text in ("false", "no", "0", "falso"):
        return False
    return None


def _normalize_name(name: str) -> str:
    text = str(name or "").strip().lower()
    for source, target in (
        ("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n"),
    ):
        text = text.replace(source, target)
    return re.sub(r"\s+", "_", text)


def _match_bool_param(condition: str, params: Mapping[str, str]) -> str | None:
    name = _normalize_name(condition)
    candidates = [name, *(_BOOL_ALIASES.get(name, ()))]
    for param_name in params:
        normalized = _normalize_name(param_name)
        if any(
            normalized == candidate
            or normalized.startswith(candidate)
            or candidate.startswith(normalized)
            or candidate in normalized
            or normalized in candidate
            for candidate in candidates
            if candidate
        ):
            return param_name
    return None


def _split_conditions(raw: str) -> list[str]:
    parts = re.split(
        r"\s*(?:,|;|\band\b|\by\b|&&)\s*", str(raw or ""), flags=re.IGNORECASE
    )
    cleaned = []
    for part in parts:
        stripped = re.sub(
            r"^(?:if|si|est[aá]|is|es)\s+",
            "",
            str(part or "").strip(),
            flags=re.IGNORECASE,
        )
        name = _normalize_name(stripped)
        if 2 <= len(name) <= 40 and re.match(r"^[a-z0-9_]+$", name):
            cleaned.append(name)
    return cleaned


def _extract_boolean_rules(items: Sequence[Any]) -> tuple[_BooleanRule, ...]:
    """Reglas «condiciones AND → consecuencia» documentadas."""
    text = "\n".join(_item_content(item) for item in items)[:_MAX_EVIDENCE_CHARS]
    rules: list[_BooleanRule] = []
    for match in _BOOL_RULE_ARROW_RE.finditer(text):
        conditions = _split_conditions(match.group(1))
        if not conditions:
            continue
        rules.append(
            _BooleanRule(
                conditions=tuple(conditions),
                consequent=_normalize_name(match.group(2)),
                statement=match.group(0).strip()[:200],
                refs=_find_refs(match.group(0), items),
            )
        )
    for match in _BOOL_RULE_WHEN_RE.finditer(text):
        if "→" in match.group(0) or "->" in match.group(0):
            continue
        conditions_raw = match.group(2)
        conditions = _split_conditions(conditions_raw)
        if not conditions:
            continue
        if not (
            any(condition in _BOOL_ALIASES for condition in conditions)
            or re.search(r"\band\b|\by\b|,", conditions_raw, re.IGNORECASE)
        ):
            continue
        rules.append(
            _BooleanRule(
                conditions=tuple(conditions),
                consequent=_normalize_name(match.group(1)),
                statement=match.group(0).strip()[:200],
                refs=_find_refs(match.group(0), items),
            )
        )
    seen: set[tuple[str, str]] = set()
    unique: list[_BooleanRule] = []
    for rule in rules:
        key = (rule.consequent, "|".join(rule.conditions))
        if key in seen:
            continue
        seen.add(key)
        unique.append(rule)
    return tuple(unique)


def _extract_percent_premises(
    items: Sequence[Any],
) -> tuple[tuple[str, float, str, tuple[str, ...]], ...]:
    """(nombre, tasa decimal, statement, refs) de porcentajes documentados."""
    text = "\n".join(_item_content(item) for item in items)[:_MAX_EVIDENCE_CHARS]
    found: list[tuple[str, float, str, tuple[str, ...]]] = []
    for match in _PERCENT_RE.finditer(text):
        name = _normalize_name(match.group(1))
        value = _as_number(match.group(2))
        if value is None:
            continue
        found.append(
            (
                name,
                value / 100.0,
                match.group(0).strip()[:200],
                _find_refs(match.group(0), items),
            )
        )
    return tuple(found)


def _extract_policy_reference(items: Sequence[Any]) -> tuple[str, str, tuple[str, ...]]:
    """Referencia a una política/regla NO definida en la evidencia."""
    text = "\n".join(_item_content(item) for item in items)[:_MAX_EVIDENCE_CHARS]
    for match in _POLICY_REF_RE.finditer(text):
        name = match.group(1)
        occurrences = len(re.findall(re.escape(name), text))
        defined = occurrences > 1 or bool(
            re.search(
                rf"{re.escape(name)}\s*(?:=|:|defines|define|means|significa|establece)",
                text,
                re.IGNORECASE,
            )
        )
        if not defined:
            return (
                f"definition:policy:{name}",
                match.group(0).strip()[:200],
                _find_refs(match.group(0), items),
            )
    return "", "", ()


def _parse_date_any(value: Any) -> str:
    from datetime import datetime as _dt

    text = str(value or "").strip()
    for fmt_in in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return _dt.strptime(text, fmt_in).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _date_in_scope(date_value: str, candidate: _RangeCandidate) -> bool:
    day = _parse_date_any(date_value)
    if not day:
        return False
    if candidate.valid_from and day < _parse_date_any(candidate.valid_from):
        return False
    if candidate.valid_until and day > _parse_date_any(candidate.valid_until):
        return False
    return True


def _date_param(semantics: QuerySemantics) -> str:
    for obj in semantics.runtime_inputs:
        if obj.semantic_type == "date" or (
            obj.cues and str(obj.cues[0]).lower() in ("date", "fecha")
        ):
            return obj.value
    return ""


def _extract_range_candidates(items: Sequence[Any]) -> tuple[_RangeCandidate, ...]:
    """Umbrales documentados, con vigencia temporal cuando el texto la declara."""
    text = "\n".join(_item_content(item) for item in items)[:_MAX_EVIDENCE_CHARS]
    sentences = re.split(r"(?<=[.;\n])\s+", text)
    candidates: list[_RangeCandidate] = []
    for sentence in sentences:
        min_match = _MIN_THRESHOLD_RE.search(sentence)
        max_match = _MAX_THRESHOLD_RE.search(sentence)
        if not min_match and not max_match:
            continue
        from_match = _DATE_FROM_RE.search(sentence)
        until_match = _DATE_UNTIL_RE.search(sentence)
        candidates.append(
            _RangeCandidate(
                minimum=_as_number(min_match.group(1)) if min_match else None,
                maximum=_as_number(max_match.group(1)) if max_match else None,
                statement=sentence.strip()[:240],
                refs=_find_refs(sentence.strip()[:120], items),
                valid_from=from_match.group(1) if from_match else "",
                valid_until=until_match.group(1) if until_match else "",
            )
        )
    return tuple(candidates)


def _string_policy_premise(
    items: Sequence[Any],
) -> tuple[str, str, tuple[str, ...]]:
    """Política de strings documentada, con statement y refs reales."""
    text = "\n".join(_item_content(item) for item in items)[:_MAX_EVIDENCE_CHARS]
    for regex, policy in (
        (_CASE_INSENSITIVE_RE, "case_insensitive"),
        (_UPPERCASE_RE, "uppercase"),
        (_CASE_SENSITIVE_RE, "case_sensitive"),
    ):
        match = regex.search(text)
        if match:
            return policy, match.group(0).strip()[:120], _find_refs(match.group(0), items)
    return "", "", ()


def _string_policy(items: Sequence[Any]) -> str:
    return _string_policy_premise(items)[0]


def reason_over_evidence(
    *,
    question: str,
    evidence_items: Sequence[Any] = (),
    contract: GroundingContract | None = None,
    operations: OperationRegistry | None = None,
) -> GroundedReasoningResult:
    """Motor determinista: semántica → premisas → derivación → answerability."""
    items = list(evidence_items or ())
    resolved_contract = contract or GroundingContract(
        mode=resolve_grounding_mode(),
        allowed_operations=tuple(_OPERATIONS_BY_INTENT.get("APPLY_RULE", ())),
    )
    registry = operations or DEFAULT_REGISTRY
    semantics = classify_query_semantics(question)
    intent = semantics.intent or detect_query_intent(question)[0]

    runtime_inputs = _unique(
        obj.value for obj in semantics.runtime_inputs
    )
    runtime_patterns = _unique(obj.value for obj in semantics.runtime_patterns)

    premises: list[Premise] = []
    conflicts: list[str] = []
    missing: list[str] = []
    claims: list[DerivedClaim] = []
    inferences = []
    operations_used: list[str] = []

    formulas = extract_formula_premises(items)
    params = _runtime_params(semantics)
    percent_premises = _extract_percent_premises(items)
    boolean_rules = _extract_boolean_rules(items)
    policy_key, policy_statement, policy_refs = _extract_policy_reference(items)
    range_candidates = _extract_range_candidates(items)
    user_date = _date_param(semantics)
    equality_match = _EQUALITY_Q_RE.search(str(question or ""))
    (
        string_policy,
        string_policy_statement,
        string_policy_refs,
    ) = _string_policy_premise(items)
    _pattern_intents = ("APPLY_RULE", "VALIDATE", "COMPARE")
    _formula_intents = (
        "CALCULATE",
        "LOOKUP",
        "APPLY_RULE",
        "VALIDATE",
        "COMPARE",
        "INFER",
    )
    _range_intents = ("VALIDATE", "COMPARE", "APPLY_RULE", "LOOKUP")

    # ------------------------------------------------------------------
    # 1. Patrón de runtime: la instancia no exige match literal; su gramática sí.
    # ------------------------------------------------------------------
    if runtime_patterns and intent in _pattern_intents:
        from src.rag.longcontext.pattern import (
            WILDCARD_SYMBOLS,
            analyze_pattern_instance,
            extract_pattern_semantics,
            missing_pattern_premises,
            positional_match,
        )

        pattern_value = runtime_patterns[0]
        value = _first_runtime_value(semantics)
        pattern_semantics = extract_pattern_semantics(items)
        defined_symbols = tuple(pattern_semantics.symbol_definitions.keys())
        instance = analyze_pattern_instance(
            pattern_value,
            symbols=defined_symbols if defined_symbols else WILDCARD_SYMBOLS,
        )
        if not value:
            missing = ["input:value"]
        else:
            missing = list(
                missing_pattern_premises(
                    instance, pattern_semantics, value_length=len(value)
                )
            )
        premises.extend(
            _pattern_premises(
                [
                    *(definition.statement for definition in pattern_semantics.symbol_definitions.values()),
                    *pattern_semantics.statements,
                ],
                items,
            )
        )
        # El campo nombrado por la pregunta, si está documentado, también es una
        # premisa citada (cross-source: regla en A, gramática en B).
        premises.extend(_field_premises(semantics, items))
        if not missing:
            result = positional_match(value, instance, pattern_semantics)
            if result.status == "UNDETERMINED":
                missing = list(result.missing_premises)
            else:
                operations_used.append("POSITIONAL_MATCH")
                claim = claim_from_operation(
                    statement=(
                        f"«{value}» "
                        f"{'cumple' if result.status == 'MATCH' else 'no cumple'} "
                        f"el patrón «{pattern_value}»"
                    ),
                    operation=OperationResult(
                        operation="POSITIONAL_MATCH",
                        status=OperationStatus.OK.value,
                        value=result.status,
                        explanation=result.reason,
                        inputs=(value, pattern_value),
                    ),
                    premises=tuple(premises),
                    user_inputs=(value, pattern_value),
                    evidence_refs=_unique(
                        ref for premise in premises for ref in premise.evidence_refs
                    ),
                    contract=resolved_contract,
                    claim_type=GroundingCategory.DERIVED_CLAIM.value,
                    confidence=0.9 if result.status == "MATCH" else 0.85,
                )
                claims.append(claim)

    # ------------------------------------------------------------------
    # 2. Total con impuesto: tasa documentada + precio del usuario.
    # ------------------------------------------------------------------
    elif (
        _TAX_TOTAL_RE.search(str(question or ""))
        and _TAX_WORD_RE.search(str(question or ""))
        and percent_premises
        and params
    ):
        rate_name, rate_value, rate_statement, rate_refs = percent_premises[0]
        numeric_params = [
            (name, value)
            for name, value in params.items()
            if _as_number(value) is not None
        ]
        if numeric_params:
            price_name, price_raw = numeric_params[0]
            price_value = _as_number(price_raw)
            premises.append(
                Premise(
                    statement=rate_statement,
                    origin=ClaimOrigin.SOURCE.value,
                    evidence_refs=rate_refs,
                    key=f"percent:{rate_name}",
                )
            )
            premises.append(
                Premise(
                    statement=f"user-provided value: {price_name}={price_raw}",
                    origin=ClaimOrigin.USER.value,
                    key=f"input:{price_name}",
                )
            )
            result = registry.run(
                "FORMULA_EVALUATION",
                formula=f"{price_name} * (1 + {rate_name})",
                variables={price_name: price_value, rate_name: rate_value},
            )
            if result.status == OperationStatus.OK.value:
                operations_used.append("FORMULA_EVALUATION")
                claim = claim_from_operation(
                    statement=(
                        f"aplicando la tasa documentada {rate_value * 100:g}% "
                        f"sobre {price_name}={price_raw} resulta {result.value}"
                    ),
                    operation=result,
                    premises=tuple(premises),
                    user_inputs=(f"{price_name}={price_raw}",),
                    evidence_refs=rate_refs,
                    contract=resolved_contract,
                    claim_type=GroundingCategory.DERIVED_CLAIM.value,
                    confidence=0.9,
                )
                claims.append(claim)
            else:
                conflicts.append(result.error or "cálculo de impuesto no ejecutable")

    # ------------------------------------------------------------------
    # 3. Cálculo: fórmula documentada + parámetros del usuario.
    # ------------------------------------------------------------------
    elif formulas and params and intent in _formula_intents:
        # Dos fórmulas distintas para el mismo target son un conflicto: no se
        # elige una arbitrariamente.
        by_target: dict[str, set[str]] = {}
        for candidate_formula in formulas:
            by_target.setdefault(candidate_formula.target, set()).add(
                candidate_formula.expression
            )
        conflicting_targets = [
            target for target, expressions in by_target.items() if len(expressions) > 1
        ]
        if conflicting_targets:
            conflicts.append(
                "conflicting_formulas:" + ",".join(sorted(conflicting_targets))
            )
        else:
            formula = formulas[0]
            premises.append(
                Premise(
                    statement=formula.statement,
                    origin=ClaimOrigin.SOURCE.value,
                    evidence_refs=formula.refs,
                    key=f"formula:{formula.target}",
                )
            )
            bound, unbound = _bind_variables(formula.expression, params)
            # El TARGET de la fórmula es el resultado, no una entrada requerida.
            unbound = tuple(name for name in unbound if name != formula.target)
            if unbound:
                missing = [f"input:{name}" for name in unbound]
            else:
                result = registry.run(
                    "FORMULA_EVALUATION",
                    formula=formula.expression,
                    variables=bound,
                )
                if result.status == OperationStatus.OK.value:
                    operations_used.append("FORMULA_EVALUATION")
                    premises.append(
                        Premise(
                            statement="user-provided values: "
                            + ", ".join(
                                f"{key}={value}" for key, value in sorted(bound.items())
                            ),
                            origin=ClaimOrigin.USER.value,
                            key="user_inputs",
                        )
                    )
                    claim = claim_from_operation(
                        statement=(
                            f"aplicando la fórmula documentada «{formula.expression}» "
                            f"resulta {result.value}"
                        ),
                        operation=result,
                        premises=tuple(premises),
                        user_inputs=tuple(
                            f"{key}={value}" for key, value in sorted(bound.items())
                        ),
                        evidence_refs=formula.refs,
                        contract=resolved_contract,
                        claim_type=GroundingCategory.DERIVED_CLAIM.value,
                        confidence=0.9,
                    )
                    claims.append(claim)
                else:
                    conflicts.append(result.error or "formula no ejecutable")
    elif _ARITHMETIC_Q_RE.search(str(question or "")) and intent in (
        "CALCULATE",
        "LOOKUP",
        "INFER",
    ):
        # Operación general permitida (P0.15): 3 + 3 = 6 aunque «3 + 3 = 6» no
        # esté escrito en la fuente. No exige evidencia: es capacidad del motor.
        match = _ARITHMETIC_Q_RE.search(str(question or ""))
        expression = (
            f"{match.group(1).replace(',', '.')} {match.group(2)} "
            f"{match.group(3).replace(',', '.')}"
        )
        result = registry.run("ARITHMETIC", expression=expression)
        if result.status == OperationStatus.OK.value:
            operations_used.append("ARITHMETIC")
            claim = claim_from_operation(
                statement=f"la operación {expression} da {result.value}",
                operation=result,
                user_inputs=(expression,),
                contract=resolved_contract,
                confidence=0.95,
            )
            claims.append(claim)
        else:
            conflicts.append(result.error or "operación aritmética no ejecutable")
    # ------------------------------------------------------------------
    # 4. Lógica booleana documentada: condiciones AND → consecuencia.
    # ------------------------------------------------------------------
    elif boolean_rules and intent in _formula_intents:
        rule = boolean_rules[0]
        bool_params = {
            name: value for name, value in params.items() if _as_bool(value) is not None
        }
        condition_values: dict[str, bool] = {}
        missing_conditions: list[str] = []
        for condition in rule.conditions:
            param_name = _match_bool_param(condition, bool_params)
            if param_name is None:
                missing_conditions.append(condition)
            else:
                condition_values[condition] = bool(_as_bool(bool_params[param_name]))
        if missing_conditions:
            missing = [f"input:{condition}" for condition in missing_conditions]
        else:
            premises.append(
                Premise(
                    statement=rule.statement,
                    origin=ClaimOrigin.SOURCE.value,
                    evidence_refs=rule.refs,
                    key="boolean_rule",
                )
            )
            premises.append(
                Premise(
                    statement="user-provided values: "
                    + ", ".join(
                        f"{name}={value}" for name, value in sorted(bool_params.items())
                    ),
                    origin=ClaimOrigin.USER.value,
                    key="user_inputs",
                )
            )
            result_bool = all(condition_values.values())
            operations_used.append("BOOLEAN")
            claim = claim_from_operation(
                statement=(
                    f"con {', '.join(f'{c}={v}' for c, v in condition_values.items())} "
                    f"{'se cumple' if result_bool else 'no se cumple'}: "
                    f"{rule.consequent}"
                ),
                operation=OperationResult(
                    operation="BOOLEAN",
                    status=OperationStatus.OK.value,
                    value=result_bool,
                    explanation=f"conditions {condition_values}",
                    inputs=tuple(sorted(condition_values)),
                ),
                premises=tuple(premises),
                user_inputs=tuple(f"{name}={value}" for name, value in sorted(bool_params.items())),
                evidence_refs=rule.refs,
                contract=resolved_contract,
                claim_type=GroundingCategory.DERIVED_CLAIM.value,
                confidence=0.9,
            )
            claims.append(claim)
    # ------------------------------------------------------------------
    # 5. Igualdad/transformación de strings con política documentada.
    # ------------------------------------------------------------------
    elif equality_match and string_policy:
        left, right = equality_match.group(1), equality_match.group(2)
        policy = string_policy
        if policy:
            case_sensitive = policy == "case_sensitive"
            if policy == "uppercase":
                left_cmp, right_cmp = left.upper(), right.upper()
            else:
                left_cmp, right_cmp = left, right
            result = registry.run(
                "STRING_EQUALITY",
                a=left_cmp,
                b=right_cmp,
                case_sensitive=case_sensitive,
            )
            if result.status == OperationStatus.OK.value:
                operations_used.append("STRING_EQUALITY")
                premises.append(
                    Premise(
                        statement=(
                            string_policy_statement
                            or f"documented string policy: {policy}"
                        ),
                        origin=ClaimOrigin.SOURCE.value,
                        evidence_refs=string_policy_refs,
                        key="string_policy",
                    )
                )
                claim = claim_from_operation(
                    statement=(
                        f"«{left}» {'coincide con' if result.value else 'no coincide con'} "
                        f"«{right}» según la política documentada"
                    ),
                    operation=result,
                    premises=tuple(premises),
                    user_inputs=(left, right),
                    evidence_refs=string_policy_refs,
                    contract=resolved_contract,
                    claim_type=GroundingCategory.DERIVED_CLAIM.value,
                    confidence=0.85,
                )
                claims.append(claim)
    elif formulas and not params and intent == "CALCULATE":
        # Sin datos del usuario no hay cálculo: no se inventan entradas.
        missing = ["input:formula_variables"]

    # ------------------------------------------------------------------
    # 6. Validación por rango/umbral temporal, conflicto o enum documentado.
    # ------------------------------------------------------------------
    elif intent in _range_intents:
        numeric = [
            (name, _as_number(value))
            for name, value in params.items()
            if _as_number(value) is not None
        ]
        options, enum_statement, enum_refs = _extract_enum_premise(items)
        status_values = [
            (name, value)
            for name, value in params.items()
            if value and not str(value)[0].isdigit()
        ]
        selected: _RangeCandidate | None = None
        if range_candidates:
            dated = [
                candidate
                for candidate in range_candidates
                if candidate.valid_from or candidate.valid_until
            ]
            if user_date and dated:
                selected = next(
                    (
                        candidate
                        for candidate in dated
                        if _date_in_scope(user_date, candidate)
                    ),
                    None,
                )
                if selected is None:
                    missing = [f"no_rule_valid_at:{user_date}"]
            else:
                distinct_min = {
                    candidate.minimum
                    for candidate in range_candidates
                    if candidate.minimum is not None
                }
                distinct_max = {
                    candidate.maximum
                    for candidate in range_candidates
                    if candidate.maximum is not None
                }
                if len(distinct_min) > 1 or len(distinct_max) > 1:
                    conflicts.append("conflicting_range_rules")
                else:
                    selected = range_candidates[0]
        if selected is not None and not conflicts and numeric:
            premises.append(
                Premise(
                    statement=selected.statement[:240],
                    origin=ClaimOrigin.SOURCE.value,
                    evidence_refs=selected.refs,
                    key="threshold",
                )
            )
            name, value = numeric[0]
            result = registry.run(
                "RANGE_CHECK",
                value=value,
                minimum=selected.minimum,
                maximum=selected.maximum,
            )
            if result.status == OperationStatus.OK.value:
                operations_used.append("RANGE_CHECK")
                premises.append(
                    Premise(
                        statement=f"user-provided value: {name}={value}",
                        origin=ClaimOrigin.USER.value,
                        key=f"input:{name}",
                    )
                )
                inside = bool(result.value)
                claim = claim_from_operation(
                    statement=(
                        f"el valor {value} {'cumple' if inside else 'no cumple'} "
                        f"el rango documentado"
                    ),
                    operation=result,
                    premises=tuple(premises),
                    user_inputs=(f"{name}={value}",),
                    evidence_refs=selected.refs,
                    contract=resolved_contract,
                    confidence=0.9,
                )
                claims.append(claim)
        elif options and status_values and not conflicts:
            premises.append(
                Premise(
                    statement=enum_statement[:240],
                    origin=ClaimOrigin.SOURCE.value,
                    evidence_refs=enum_refs,
                    key="allowed_values",
                )
            )
            name, value = status_values[0]
            result = registry.run("ENUM_CHECK", value=value, allowed=options)
            if result.status == OperationStatus.OK.value:
                operations_used.append("ENUM_CHECK")
                premises.append(
                    Premise(
                        statement=f"user-provided value: {name}={value}",
                        origin=ClaimOrigin.USER.value,
                        key=f"input:{name}",
                    )
                )
                allowed = bool(result.value)
                claim = claim_from_operation(
                    statement=(
                        f"el valor «{value}» {'está permitido' if allowed else 'no está permitido'} "
                        f"según los valores documentados"
                    ),
                    operation=result,
                    premises=tuple(premises),
                    user_inputs=(f"{name}={value}",),
                    evidence_refs=enum_refs,
                    contract=resolved_contract,
                    confidence=0.9,
                )
                claims.append(claim)

    # ------------------------------------------------------------------
    # 7. Política referenciada y no definida: premisa faltante explícita.
    # ------------------------------------------------------------------
    if not claims and policy_key and not conflicts:
        premises.append(
            Premise(
                statement=policy_statement,
                origin=ClaimOrigin.SOURCE.value,
                evidence_refs=policy_refs,
                key="policy_reference",
            )
        )
        missing.append(policy_key)

    # ------------------------------------------------------------------
    # 4. Answerability consciente de la derivación.
    # ------------------------------------------------------------------
    supported = [claim for claim in claims if claim.supported]
    if conflicts:
        answerability = UNANSWERABLE_CONFLICT
    elif supported:
        answerability = ANSWERABLE_DERIVED
    elif missing:
        answerability = UNANSWERABLE_MISSING_PREMISE
    elif runtime_patterns or runtime_inputs:
        answerability = ANSWERABLE_WITH_LIMITS if premises else NOT_APPLICABLE
    else:
        answerability = NOT_APPLICABLE

    graph = DerivationGraph(
        claims=tuple(claims),
        inferences=tuple(inferences),
        missing_premises=tuple(dict.fromkeys(missing)),
        conflicts=tuple(dict.fromkeys(conflicts)),
        operations_used=tuple(dict.fromkeys(operations_used)),
    )
    return GroundedReasoningResult(
        question=str(question or ""),
        semantics=semantics,
        contract=resolved_contract,
        premises=tuple(premises),
        runtime_inputs=runtime_inputs,
        runtime_patterns=runtime_patterns,
        derivations=graph,
        missing_premises=graph.missing_premises,
        conflicts=graph.conflicts,
        answerability=answerability,
        abstention_message=(
            missing_premise_message(missing) if answerability == UNANSWERABLE_MISSING_PREMISE else ""
        ),
    )


def observe_grounded_result(result: Any) -> None:
    """Métricas del motor grounded (fail-soft: nunca rompe el run)."""
    try:
        import src.infrastructure.observability.metrics as m

        public = (
            result.to_public_dict()
            if hasattr(result, "to_public_dict")
            else dict(result or {})
        )
        if not isinstance(public, dict):
            return
        answerability = str(public.get("answerability") or "NOT_APPLICABLE")
        m.grounding_answerability_total.labels(answerability=answerability).inc()
        semantics = (
            public.get("semantics") if isinstance(public.get("semantics"), dict) else {}
        )
        for obj in semantics.get("objects") or ():
            if not isinstance(obj, dict):
                continue
            role = str(obj.get("semantic_role") or "")
            if role:
                m.grounding_query_role_total.labels(role=role).inc()
        derivations = (
            public.get("derivations")
            if isinstance(public.get("derivations"), dict)
            else {}
        )
        for claim in derivations.get("claims") or ():
            if not isinstance(claim, dict):
                continue
            m.grounding_derived_claims_total.labels(
                operation=str(claim.get("operation") or ""),
                verification_status=str(claim.get("verification_status") or ""),
            ).inc()
        for premise in public.get("missing_premises") or ():
            kind = str(premise).split(":", 1)[0] or "other"
            m.grounding_missing_premise_total.labels(premise=kind).inc()
    except Exception:  # noqa: BLE001 — la observabilidad nunca rompe el run
        pass


__all__ = [
    "ANSWERABLE_DERIVED",
    "ANSWERABLE_DIRECT",
    "ANSWERABLE_WITH_LIMITS",
    "GROUNDED_ENGINE_VERSION",
    "GroundedReasoningResult",
    "NOT_APPLICABLE",
    "UNANSWERABLE_CONFLICT",
    "UNANSWERABLE_MISSING_PREMISE",
    "extract_formula_premises",
    "missing_premise_message",
    "observe_grounded_result",
    "reason_over_evidence",
]
