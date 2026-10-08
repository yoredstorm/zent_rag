# =============================================================================
# Operation Compatibility — el ranking no decide qué operación es correcta
# =============================================================================
# Principio:
#
#   EL RANKING NO DECIDE QUÉ OPERACIÓN ES CORRECTA.
#
# Antes:  all candidates -> score -> winner
# Ahora:  all candidates -> source scope -> semantic compatibility
#         -> operation compatibility -> premise compatibility -> executability
#         -> ranking -> winner
#
# Una CanonicalRule NO puede ganar solo porque menciona el símbolo `&` de la
# consulta: mencionar un símbolo no es lo mismo que definir su semántica ni que
# ejecutarla. Una consulta con un patrón de runtime (`&&&F`) aplicado a un valor
# (`ABCFGEGE`) exige la familia MATCHING (POSITIONAL_MATCH/MATCH); una regla
# COMPARISON/RANGE/FORMULA no es compatible por mera cercanía léxica y queda
# FUERA del pass decisivo (no es un conflicto documental: es un candidato de
# retrieval incompatible).
#
# Este módulo concentra:
#   1. QueryOperationRequirements (derivado de QuerySemantics, sin dominio);
#   2. OperationCompatibilityResult (contrato auditable por candidata);
#   3. la matriz de compatibilidad de operaciones;
#   4. OperationInputValidator (tipos semánticos antes del registry);
#   5. telemetría determinista del gate (score ANTES/después).
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

OPERATION_COMPATIBILITY_VERSION = "operation-compatibility-1"

#: Alfabeto de comodines de máscara (mismo que el índice de reglas y anchors).
RUNTIME_MASK_SYMBOLS = frozenset("&*?%#$@!~^")

#: Familias de operación (vocabulario del contrato, no de dominio).
FAMILY_ANY = "ANY"
FAMILY_MATCHING = "MATCHING"
FAMILY_COMPARISON = "COMPARISON"
FAMILY_RANGE = "RANGE"
FAMILY_DATE = "DATE"
FAMILY_FORMULA = "FORMULA"
FAMILY_ARITHMETIC = "ARITHMETIC"
FAMILY_ENUM = "ENUM"
FAMILY_BOOLEAN = "BOOLEAN"

#: Capacidades que una regla puede ofrecer (derivadas de su gramática).
CAP_MASK_MATCH = "MASK_MATCH"
CAP_POSITIONAL_SYMBOL_SEMANTICS = "POSITIONAL_SYMBOL_SEMANTICS"
CAP_LENGTH_POLICY = "LENGTH_POLICY"
CAP_COMPARISON = "COMPARISON"
CAP_RANGE = "RANGE"
CAP_DATE = "DATE"
CAP_FORMULA = "FORMULA"
CAP_ARITHMETIC = "ARITHMETIC"
CAP_ENUM = "ENUM"
CAP_BOOLEAN = "BOOLEAN"

#: Niveles de uso de un símbolo por parte de la regla (mencionar != ejecutar).
SYMBOL_MENTIONED = "mentioned"
SYMBOL_DEFINED = "defined"
SYMBOL_EXECUTABLE = "executable"

#: Elegibilidad de una candidata frente a la query.
ELIGIBLE = "ELIGIBLE"
OPERATION_INCOMPATIBLE = "OPERATION_INCOMPATIBLE"
OPERAND_TYPE_INCOMPATIBLE = "OPERAND_TYPE_INCOMPATIBLE"
MISSING_RUNTIME_SYMBOL_SEMANTICS = "MISSING_RUNTIME_SYMBOL_SEMANTICS"
NO_EXECUTABLE_FAMILY = "NO_EXECUTABLE_FAMILY"

#: Operaciones de máscara (patrón posicional), no de comparación.
_MASK_MATCH_OPERATORS = frozenset(
    {"POSITIONAL", "FIXED_POSITION", "PREFIX", "SUFFIX", "WILDCARD", "LITERAL"}
)
_ORDERING_COMPARISON_OPERATORS = frozenset({"GT", "GTE", "LT", "LTE"})
_RANGE_COMPARISON_OPERATORS = frozenset({"BETWEEN", "OUTSIDE_RANGE"})

#: Familias de ejecución permitidas por familia de query (matriz central).
_ALLOWED_FAMILIES: dict[str, frozenset[str]] = {
    FAMILY_MATCHING: frozenset({FAMILY_MATCHING}),
    FAMILY_COMPARISON: frozenset({FAMILY_COMPARISON, FAMILY_RANGE}),
    FAMILY_RANGE: frozenset({FAMILY_RANGE, FAMILY_COMPARISON}),
    # Una regla temporal puede ejecutarse vía rango/comparación de fecha; pero
    # la familia DATE también admite ventanas resueltas por el gate temporal.
    FAMILY_DATE: frozenset({FAMILY_DATE, FAMILY_RANGE, FAMILY_COMPARISON}),
    FAMILY_FORMULA: frozenset({FAMILY_FORMULA, FAMILY_ARITHMETIC}),
    FAMILY_ENUM: frozenset({FAMILY_ENUM, FAMILY_BOOLEAN}),
    FAMILY_BOOLEAN: frozenset(
        {FAMILY_BOOLEAN, FAMILY_ENUM, FAMILY_RANGE, FAMILY_COMPARISON, FAMILY_DATE}
    ),
}

#: Familia de query -> operaciones deterministas esperadas (telemetría).
_EXPECTED_OPERATIONS: dict[str, tuple[str, ...]] = {
    FAMILY_MATCHING: ("POSITIONAL_MATCH", "MATCH"),
    FAMILY_COMPARISON: ("COMPARISON", "RANGE_CHECK"),
    FAMILY_RANGE: ("RANGE_CHECK", "COMPARISON"),
    FAMILY_DATE: ("DATE_COMPARE", "DATE_COMPARISON", "RANGE_CHECK"),
    FAMILY_FORMULA: ("FORMULA_EVALUATION", "ARITHMETIC"),
    FAMILY_ENUM: ("ENUM_CHECK", "SET_MEMBERSHIP"),
    FAMILY_BOOLEAN: ("BOOLEAN", "BOOLEAN_RULE"),
}

#: Operación determinista -> familia (para verificar envelopes ya construidos).
_OPERATION_FAMILIES: dict[str, str] = {
    "POSITIONAL_MATCH": FAMILY_MATCHING,
    "MATCH": FAMILY_MATCHING,
    "STRING_EQUALITY": FAMILY_MATCHING,
    "STRING_COMPARE": FAMILY_COMPARISON,
    "CONTAINS": FAMILY_MATCHING,
    "STARTS_WITH": FAMILY_MATCHING,
    "ENDS_WITH": FAMILY_MATCHING,
    "LENGTH_POLICY": FAMILY_MATCHING,
    "COMPARISON": FAMILY_COMPARISON,
    "NUMERIC_COMPARE": FAMILY_COMPARISON,
    "RANGE_CHECK": FAMILY_RANGE,
    "QUANTITY_CHECK": FAMILY_RANGE,
    "DATE_COMPARE": FAMILY_DATE,
    "DATE_COMPARISON": FAMILY_DATE,
    "DATE_RANGE": FAMILY_DATE,
    "FORMULA": FAMILY_FORMULA,
    "FORMULA_EVALUATION": FAMILY_FORMULA,
    "ARITHMETIC": FAMILY_ARITHMETIC,
    "UNIT_CONVERSION": FAMILY_ARITHMETIC,
    "ENUM_CHECK": FAMILY_ENUM,
    "SET_MEMBERSHIP": FAMILY_ENUM,
    "SET_RELATION": FAMILY_ENUM,
    "BOOLEAN": FAMILY_BOOLEAN,
    "BOOLEAN_RULE": FAMILY_BOOLEAN,
    "ELIGIBILITY": FAMILY_BOOLEAN,
}

#: Señales genéricas (ES/EN) de familia cuando QuerySemantics no basta.
_RANGE_QUERY_RE = re.compile(
    r"\b(?:rango|range|umbral|threshold|m[ií]nim[ao]|m[aá]xim[ao]|\bmin\b|\bmax\b|"
    r"at\s+least|at\s+most|greater\s+than|less\s+than|\bentre\b|\bbetween\b|"
    r"no\s+m[aá]s\s+de|al\s+menos|como\s+m[aá]ximo)\b",
    re.IGNORECASE,
)
_ENUM_QUERY_RE = re.compile(
    r"\b(?:enum|estados?\s+(?:permitidos?|v[aá]lidos?)|"
    r"valores?\s+(?:permitidos?|v[aá]lidos?)|allowed\s+(?:values|statuses)|"
    r"one\s+of|uno\s+de\s+los)\b",
    re.IGNORECASE,
)
_ENUM_PERMISSION_RE = re.compile(
    r"\b(?:permitid\w*|prohibid\w*|allowed|forbidden)\b", re.IGNORECASE
)
_UPPER_TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9_-]{1,}\b")
_DATE_QUERY_RE = re.compile(
    r"\b(?:vigente|effective|v[aá]lid[ao]\s+(?:en|desde|hasta|from|until)|"
    r"fecha\s+de\s+(?:vigencia|aplicaci[oó]n)|date\s+of\s+effect|"
    r"a\s+partir\s+de\s+la\s+fecha)\b",
    re.IGNORECASE,
)
_BOOLEAN_QUERY_RE = re.compile(
    r"\b(?:si\s+.{2,80}\s+entonces|if\s+.{2,80}\s+then|"
    r"cuando\s+.{2,80}\s+(?:aplica|se\s+cumple)|"
    r"condiciones?\s+(?:se\s+cumplen|se\s+verifican))\b",
    re.IGNORECASE,
)
_MASK_TOKEN_RE = re.compile(r"[A-Za-z0-9&*?%#$@!~^]{2,}")
_DECISION_VERB_QUERY_RE = re.compile(
    r"\b(?:cumpl\w*|valid\w*|verific\w*|comprob\w*|chequ\w*|check\w*|confirm\w*|"
    r"satisfac\w*|aprob\w*|permitid\w*|allowed|prohibid\w*|forbidden|elegib\w*|"
    r"eligible)\b",
    re.IGNORECASE,
)
_DATE_TOKEN_RE = re.compile(r"(\d{4}-\d{2}-\d{2}|\d{1,2}[/.]\d{1,2}[/.]\d{4})")


def _maskish(text: str) -> bool:
    """¿El texto (token) es una máscara? `?` final solo no cuenta (puntuación)."""
    stripped = text[:-1] if text.endswith("?") else text
    if any(char in RUNTIME_MASK_SYMBOLS and char != "?" for char in stripped):
        return True
    return bool(text) and all(char in RUNTIME_MASK_SYMBOLS for char in text)


def is_runtime_mask(value: Any) -> bool:
    """¿El valor es una máscara de runtime (contiene comodines)?

    Un valor numérico nunca es máscara; un string con comodines sí. No exige
    que TODOS los caracteres sean comodines (`W&&2M` es una máscara). Un `?`
    final aislado es puntuación, no máscara (`ABCD?`).
    """
    text = str(value or "")
    if not text:
        return False
    if _numeric_like(text):
        return False
    return _maskish(text)


def _numeric_like(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    text = str(value or "").strip().replace(",", ".")
    if not text:
        return False
    try:
        float(text)
    except ValueError:
        return False
    return True


def mask_symbols_in(value: Any) -> tuple[str, ...]:
    """Símbolos de máscara presentes en un valor (ordenados, únicos)."""
    return tuple(
        sorted({char for char in str(value or "") if char in RUNTIME_MASK_SYMBOLS})
    )


def question_mask_token(question: Any) -> str:
    """Primer token con comodines de la pregunta ('' si no hay).

    `¿ABCFGEGE cumple el patrón &&&F?` -> `&&&F` (el `?` final es puntuación).
    `cumple?` NO es una máscara.
    """
    for match in _MASK_TOKEN_RE.finditer(str(question or "")):
        token = match.group(0)
        if not _maskish(token):
            continue
        if token.endswith("?") and any(
            char in RUNTIME_MASK_SYMBOLS and char != "?" for char in token[:-1]
        ):
            token = token[:-1]
        return token
    return ""


def operation_family_for_operation(operation: Any) -> str:
    """Familia de una operación determinista ('' si se desconoce)."""
    return _OPERATION_FAMILIES.get(str(operation or "").upper(), "")


def allowed_families(operation_family: str) -> frozenset[str]:
    return _ALLOWED_FAMILIES.get(str(operation_family or ""), frozenset())


def expected_operations(operation_family: str) -> tuple[str, ...]:
    """Operaciones deterministas esperadas para la familia de la query."""
    return _EXPECTED_OPERATIONS.get(str(operation_family or ""), ())


# -----------------------------------------------------------------------------
# Query requirements (derivados de QuerySemantics; sin hardcode de dominio)
# -----------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class QueryOperationRequirements:
    """Qué exige la OPERACIÓN de la consulta (no qué documento menciona)."""

    query_intent: str = ""
    operation_family: str = FAMILY_ANY
    runtime_patterns: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    positional: bool = False
    requires_length_policy: bool = False
    required_capabilities: tuple[str, ...] = ()
    #: True cuando la familia está definida y una candidata incompatible NO
    #: puede entrar al pass decisivo. False = ANY (sin gate, ranking histórico).
    enforced: bool = False

    @property
    def runtime_pattern(self) -> bool:
        return bool(self.runtime_patterns)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "version": OPERATION_COMPATIBILITY_VERSION,
            "query_intent": self.query_intent,
            "operation_family": self.operation_family,
            "expected_operations": list(
                expected_operations(self.operation_family)[:4]
            ),
            "runtime_pattern": self.runtime_pattern,
            "runtime_patterns": list(self.runtime_patterns[:8]),
            "symbols": list(self.symbols[:8]),
            "positional": bool(self.positional),
            "requires_length_policy": bool(self.requires_length_policy),
            "required_capabilities": list(self.required_capabilities[:8]),
            "enforced": bool(self.enforced),
        }


def _semantics_values(semantics: Any) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    """(patrones, valores runtime, intent) de un objeto o dict público."""
    if semantics is None:
        return (), (), ""
    if isinstance(semantics, Mapping):
        patterns = tuple(
            str(value)
            for value in semantics.get("runtime_patterns") or ()
            if str(value or "").strip()
        )
        values = tuple(
            str(value)
            for value in semantics.get("runtime_inputs") or ()
            if str(value or "").strip()
        )
        intent = str(semantics.get("intent") or "")
        return patterns, values, intent
    patterns = tuple(
        str(getattr(obj, "value", "") or "")
        for obj in (getattr(semantics, "runtime_patterns", ()) or ())
        if str(getattr(obj, "value", "") or "").strip()
    )
    values = tuple(
        str(getattr(obj, "value", "") or "")
        for obj in (getattr(semantics, "runtime_inputs", ()) or ())
        if str(getattr(obj, "value", "") or "").strip()
    )
    intent = str(getattr(semantics, "intent", "") or "")
    return patterns, values, intent


def derive_query_operation_requirements(
    *,
    question: str = "",
    semantics: Any = None,
    semantics_public: Mapping[str, Any] | None = None,
    symbols: Sequence[str] = (),
    runtime_patterns: Sequence[str] = (),
    intent: str = "",
    required_semantics: Sequence[str] = (),
) -> QueryOperationRequirements:
    """Deriva la familia/capacidades requeridas por la consulta.

    Sin patrón de runtime y sin intención concluyente devuelve ANY (sin gate):
    el comportamiento histórico de ranking se conserva. Con patrón de runtime
    exige MATCHING (máscara posicional sobre un valor), sin importar si el
    clasificador la etiquetó como COMPARE/VALIDATE/APPLY_RULE.
    """
    sem = semantics if semantics is not None else semantics_public
    sem_patterns, sem_values, sem_intent = _semantics_values(sem)

    resolved_intent = str(intent or sem_intent or "").upper()
    text = str(question or "")
    if not text and not isinstance(sem, Mapping) and sem is not None:
        text = str(getattr(sem, "question", "") or "")
    if not resolved_intent and text:
        try:
            from src.intelligence.query_semantics import classify_query_semantics

            classified = classify_query_semantics(text)
            resolved_intent = str(getattr(classified, "intent", "") or "").upper()
            if not sem_patterns:
                sem_patterns, sem_values, _ = _semantics_values(classified)
        except Exception:  # noqa: BLE001 — sin clasificador no se fuerza familia
            resolved_intent = ""

    patterns = tuple(
        dict.fromkeys(
            [
                *(str(value) for value in runtime_patterns if str(value or "").strip()),
                *(value for value in sem_patterns if value),
            ]
        )
    )
    if not patterns and text:
        token = question_mask_token(text)
        if token:
            patterns = (token,)

    symbol_set = {
        str(symbol)
        for symbol in symbols
        if str(symbol or "") and str(symbol) in RUNTIME_MASK_SYMBOLS
    }
    for pattern in patterns:
        symbol_set.update(mask_symbols_in(pattern))
    resolved_symbols = tuple(sorted(symbol_set))

    requirements = set(str(item) for item in required_semantics if item)
    positional = bool(patterns) or "positional_semantics" in requirements
    requires_length = "length_semantics" in requirements or bool(
        re.search(r"\b(?:longitud|length|caracteres|characters)\b", text, re.IGNORECASE)
    )

    has_numbers = any(_numeric_like(value) for value in sem_values)
    has_decision_verb = bool(_DECISION_VERB_QUERY_RE.search(text))
    has_digit = bool(re.search(r"\d", text))
    has_date_token = bool(_DATE_TOKEN_RE.search(text))

    family = FAMILY_ANY
    if patterns and resolved_symbols:
        family = FAMILY_MATCHING
    elif resolved_intent == "CALCULATE":
        family = FAMILY_FORMULA
    elif resolved_intent == "COMPARE":
        family = (
            FAMILY_RANGE
            if _RANGE_QUERY_RE.search(text) or has_numbers
            else FAMILY_COMPARISON
        )
    elif _DATE_QUERY_RE.search(text) and (has_decision_verb or has_date_token):
        family = FAMILY_DATE
    elif _ENUM_QUERY_RE.search(text) and has_decision_verb:
        family = FAMILY_ENUM
    elif (
        _ENUM_PERMISSION_RE.search(text)
        and _UPPER_TOKEN_RE.search(text)
        and has_decision_verb
    ):
        # Membresía sobre un valor concreto («¿el estado ACTIVE está
        # permitido?»): hace falta un valor, no una pregunta de listado.
        family = FAMILY_ENUM
    elif _RANGE_QUERY_RE.search(text) and (has_decision_verb or has_digit):
        # La señal de rango sola no alcanza: «¿cuál es el rango permitido?»
        # es una pregunta de dato, no una verificación de umbral.
        family = FAMILY_RANGE
    elif _BOOLEAN_QUERY_RE.search(text):
        family = FAMILY_BOOLEAN

    capabilities: list[str] = []
    if family == FAMILY_MATCHING:
        capabilities.extend([CAP_MASK_MATCH, CAP_POSITIONAL_SYMBOL_SEMANTICS])
        if requires_length:
            capabilities.append(CAP_LENGTH_POLICY)
    elif family in (FAMILY_COMPARISON, FAMILY_RANGE):
        capabilities.extend([CAP_COMPARISON, CAP_RANGE])
    elif family == FAMILY_DATE:
        capabilities.append(CAP_DATE)
    elif family == FAMILY_FORMULA:
        capabilities.append(CAP_FORMULA)
    elif family == FAMILY_ENUM:
        capabilities.append(CAP_ENUM)

    return QueryOperationRequirements(
        query_intent=resolved_intent,
        operation_family=family,
        runtime_patterns=patterns,
        symbols=resolved_symbols,
        positional=positional,
        requires_length_policy=requires_length,
        required_capabilities=tuple(dict.fromkeys(capabilities)),
        enforced=family != FAMILY_ANY,
    )


# -----------------------------------------------------------------------------
# Perfil de capacidades de una CanonicalRule
# -----------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class RuleCapabilityProfile:
    """Qué puede EJECUTAR una regla (no qué menciona)."""

    operator: str = ""
    families: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    symbol_usage: Mapping[str, str] = field(default_factory=dict)

    def usage_of(self, symbols: Iterable[str]) -> tuple[tuple[str, ...], ...]:
        mentioned: list[str] = []
        defined: list[str] = []
        executable: list[str] = []
        for symbol in symbols:
            level = self.symbol_usage.get(str(symbol))
            if level == SYMBOL_EXECUTABLE:
                executable.append(str(symbol))
            elif level == SYMBOL_DEFINED:
                defined.append(str(symbol))
            elif level == SYMBOL_MENTIONED:
                mentioned.append(str(symbol))
        return (
            tuple(sorted(mentioned)),
            tuple(sorted(defined)),
            tuple(sorted(executable)),
        )


def _known(prop: Any) -> bool:
    return bool(getattr(prop, "known", False))


def rule_capability_profile(rule: Any) -> RuleCapabilityProfile:
    """Extrae familias/capacidades/símbolos ejecutables de una CanonicalRule."""
    from src.knowledge.rule_compiler.index import rule_symbol_usage

    properties = dict(getattr(rule, "properties", {}) or {})
    known = {
        str(name): prop
        for name, prop in properties.items()
        if _known(prop)
    }
    symbol_usage = dict(rule_symbol_usage(rule))

    operator = str(getattr(rule, "operator", "") or "")
    matching_operator = str(
        getattr(known.get("matching.operator"), "value", "") or ""
    ).upper()
    comparison_operators = [
        str(getattr(prop, "value", "") or "").upper()
        for name, prop in known.items()
        if re.match(r"comparison\.operator(?:\.\d+)?$", name)
    ]
    has_matching = bool(matching_operator) or bool(symbol_usage)
    has_comparison = bool(comparison_operators) or any(
        name.startswith(("comparison.left", "comparison.right")) for name in known
    )
    has_range = any(
        op in _RANGE_COMPARISON_OPERATORS for op in comparison_operators
    ) or any(
        name.endswith((".minimum", ".maximum")) for name in known
    )
    temporal_relation = str(
        getattr(getattr(rule, "temporal", None), "relation", "") or ""
    ).upper()
    has_date = temporal_relation not in ("", "UNKNOWN") or (
        "temporal.relation" in known
    )
    has_formula = bool(str(getattr(getattr(rule, "formula", None), "expression", "") or ""))
    enumeration = getattr(rule, "enumeration", None)
    has_enum = bool(
        list(getattr(enumeration, "allowed", ()) or ())
        or list(getattr(enumeration, "prohibited", ()) or ())
        or "enumeration.allowed" in known
    )
    has_boolean = any(
        name.startswith(("logic.operators", "condition.only_if", "condition.flags"))
        for name in known
    )
    has_length = "length.policy" in known

    families: list[str] = []
    if has_matching or has_length:
        families.append(FAMILY_MATCHING)
    if has_comparison:
        families.append(FAMILY_COMPARISON)
    if has_range:
        families.append(FAMILY_RANGE)
    if has_date:
        families.append(FAMILY_DATE)
    if has_formula:
        families.append(FAMILY_FORMULA)
    if has_enum:
        families.append(FAMILY_ENUM)
    if has_boolean and not families:
        families.append(FAMILY_BOOLEAN)

    capabilities: list[str] = []
    has_symbol_semantics = any(
        level in (SYMBOL_DEFINED, SYMBOL_EXECUTABLE)
        for level in symbol_usage.values()
    )
    if matching_operator in _MASK_MATCH_OPERATORS or has_symbol_semantics:
        capabilities.append(CAP_MASK_MATCH)
    if has_symbol_semantics:
        capabilities.append(CAP_POSITIONAL_SYMBOL_SEMANTICS)
    if has_length:
        capabilities.append(CAP_LENGTH_POLICY)
    if has_comparison:
        capabilities.append(CAP_COMPARISON)
    if has_range:
        capabilities.append(CAP_RANGE)
    if has_date:
        capabilities.append(CAP_DATE)
    if has_formula:
        capabilities.append(CAP_FORMULA)
    if has_enum:
        capabilities.append(CAP_ENUM)
    if has_boolean:
        capabilities.append(CAP_BOOLEAN)

    return RuleCapabilityProfile(
        operator=operator,
        families=tuple(dict.fromkeys(families)),
        capabilities=tuple(dict.fromkeys(capabilities)),
        symbol_usage=symbol_usage,
    )


# -----------------------------------------------------------------------------
# Resultado por candidata + matriz de compatibilidad
# -----------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class OperationCompatibilityResult:
    """Contrato explícito: por qué una candidata es (in)compatible con la query."""

    candidate_rule_id: str
    query_intent: str = ""
    query_runtime_patterns: tuple[str, ...] = ()
    query_symbols: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    candidate_operator: str = ""
    candidate_capabilities: tuple[str, ...] = ()
    candidate_families: tuple[str, ...] = ()
    compatible: bool = True
    eligibility: str = ELIGIBLE
    hard_reasons: tuple[str, ...] = ()
    soft_reasons: tuple[str, ...] = ()
    symbol_mentioned: tuple[str, ...] = ()
    symbol_defined: tuple[str, ...] = ()
    symbol_executable: tuple[str, ...] = ()
    score_before: float = 0.0
    score_after: float = 0.0

    @property
    def rejected(self) -> bool:
        return not self.compatible

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "version": OPERATION_COMPATIBILITY_VERSION,
            "candidate_rule_id": self.candidate_rule_id,
            "query_intent": self.query_intent,
            "query_runtime_patterns": list(self.query_runtime_patterns[:4]),
            "query_symbols": list(self.query_symbols[:8]),
            "required_capabilities": list(self.required_capabilities[:8]),
            "candidate_operator": self.candidate_operator,
            "candidate_capabilities": list(self.candidate_capabilities[:10]),
            "candidate_families": list(self.candidate_families[:6]),
            "compatible": bool(self.compatible),
            "eligibility": self.eligibility,
            "hard_reasons": list(self.hard_reasons[:6]),
            "soft_reasons": list(self.soft_reasons[:6]),
            "symbol_mentioned": list(self.symbol_mentioned[:8]),
            "symbol_defined": list(self.symbol_defined[:8]),
            "symbol_executable": list(self.symbol_executable[:8]),
            "score_before": round(float(self.score_before), 4),
            "score_after": round(float(self.score_after), 4),
        }


def capability_score_bonus(
    profile: RuleCapabilityProfile,
    requirements: QueryOperationRequirements,
    *,
    query_symbols: Sequence[str] | None = None,
) -> float:
    """Bonus de ranking por capacidad (posterior al gate de compatibilidad).

    Prioridad del pass decisivo: capacidad exacta de operación > símbolos
    exactos ejecutables > gramática ejecutable > premisas > provenance >
    verificación > relevancia léxica.
    """
    symbols = tuple(query_symbols) if query_symbols is not None else requirements.symbols
    bonus = 0.0
    if requirements.operation_family != FAMILY_ANY:
        if requirements.operation_family in profile.families:
            bonus += 6.0
    _, defined, executable = profile.usage_of(symbols)
    if executable:
        bonus += 4.0
    elif defined:
        bonus += 2.0
    if CAP_MASK_MATCH in profile.capabilities:
        bonus += 2.0
    if CAP_LENGTH_POLICY in profile.capabilities:
        bonus += 1.0
    return bonus


def evaluate_operation_compatibility(
    rule: Any,
    requirements: QueryOperationRequirements,
    *,
    score_before: float = 0.0,
) -> OperationCompatibilityResult:
    """Aplica la matriz de compatibilidad a una candidata concreta.

    - Query MATCHING + regla sin semántica de matching => OPERATION_INCOMPATIBLE
      (o MISSING_RUNTIME_SYMBOL_SEMANTICS si declara matching de OTRO símbolo).
    - Símbolo mencionado en statement/props NO cuenta como semántica ejecutable.
    - COMPARISON/RANGE/DATE/FORMULA/ARITHMETIC no califican para una máscara
      runtime: la excepción exigiría evidencia explícita y demostrable de que el
      patrón es un operador de orden (no existe en el modelo actual).
    """
    profile = rule_capability_profile(rule)
    mentioned, defined, executable = profile.usage_of(requirements.symbols)
    query_symbols = tuple(requirements.symbols)

    compatible = True
    eligibility = ELIGIBLE
    hard: list[str] = []
    soft: list[str] = []

    if requirements.enforced:
        if requirements.operation_family == FAMILY_MATCHING:
            has_symbol_semantics = any(
                level in (SYMBOL_DEFINED, SYMBOL_EXECUTABLE)
                for level in profile.symbol_usage.values()
            )
            has_matching_semantics = (
                CAP_MASK_MATCH in profile.capabilities or has_symbol_semantics
            )
            if not has_matching_semantics:
                if profile.families:
                    compatible = False
                    eligibility = OPERATION_INCOMPATIBLE
                    hard.append(OPERATION_INCOMPATIBLE)
                else:
                    compatible = False
                    eligibility = MISSING_RUNTIME_SYMBOL_SEMANTICS
                    hard.append(MISSING_RUNTIME_SYMBOL_SEMANTICS)
            elif query_symbols and not (set(defined) | set(executable)):
                compatible = False
                eligibility = MISSING_RUNTIME_SYMBOL_SEMANTICS
                hard.append(MISSING_RUNTIME_SYMBOL_SEMANTICS)
            if compatible and mentioned and not (set(defined) | set(executable)):
                soft.append("SYMBOL_MENTIONED_WITHOUT_SEMANTICS")
        else:
            allowed = allowed_families(requirements.operation_family)
            if profile.families:
                if not (set(profile.families) & allowed):
                    compatible = False
                    eligibility = OPERATION_INCOMPATIBLE
                    hard.append(OPERATION_INCOMPATIBLE)
            else:
                compatible = False
                eligibility = NO_EXECUTABLE_FAMILY
                soft.append(NO_EXECUTABLE_FAMILY)

    missing_capabilities = [
        capability
        for capability in requirements.required_capabilities
        if capability not in profile.capabilities
    ]
    for capability in missing_capabilities:
        if capability == CAP_LENGTH_POLICY:
            # La política de longitud puede recuperarla Premise Closure: no
            # excluye por sí sola (solo baja prioridad).
            soft.append("MISSING_LENGTH_POLICY")
        elif capability == CAP_POSITIONAL_SYMBOL_SEMANTICS and requirements.enforced:
            if not (set(defined) | set(executable)):
                if compatible:
                    compatible = False
                    eligibility = MISSING_RUNTIME_SYMBOL_SEMANTICS
                    hard.append(MISSING_RUNTIME_SYMBOL_SEMANTICS)
        elif capability == CAP_MASK_MATCH and requirements.enforced:
            if CAP_MASK_MATCH not in profile.capabilities:
                if compatible:
                    compatible = False
                    eligibility = OPERATION_INCOMPATIBLE
                    hard.append(OPERATION_INCOMPATIBLE)

    score_after = float(score_before)
    if compatible:
        score_after += capability_score_bonus(profile, requirements)

    return OperationCompatibilityResult(
        candidate_rule_id=str(getattr(rule, "rule_id", "") or ""),
        query_intent=requirements.query_intent,
        query_runtime_patterns=requirements.runtime_patterns,
        query_symbols=query_symbols,
        required_capabilities=requirements.required_capabilities,
        candidate_operator=profile.operator,
        candidate_capabilities=profile.capabilities,
        candidate_families=profile.families,
        compatible=compatible,
        eligibility=eligibility,
        hard_reasons=tuple(dict.fromkeys(hard)),
        soft_reasons=tuple(dict.fromkeys(soft)),
        symbol_mentioned=mentioned,
        symbol_defined=defined,
        symbol_executable=executable,
        score_before=float(score_before),
        score_after=score_after,
    )


# -----------------------------------------------------------------------------
# Gate + telemetría
# -----------------------------------------------------------------------------


@dataclass(kw_only=True)
class RuleCompatibilityGate:
    """Resultado del gate sobre una lista de candidatas (orden preservado)."""

    requirements: QueryOperationRequirements
    applied: bool = False
    compatible: list[Any] = field(default_factory=list)
    rejected: list[Any] = field(default_factory=list)
    results: list[OperationCompatibilityResult] = field(default_factory=list)

    def result_for(self, rule: Any) -> OperationCompatibilityResult | None:
        rule_id = str(getattr(rule, "rule_id", "") or "")
        for result in self.results:
            if result.candidate_rule_id == rule_id:
                return result
        return None

    def ranked_compatible(self) -> list[Any]:
        """Compatibles ordenadas por score después del gate (determinista)."""
        by_id: dict[str, Any] = {}
        for rule in self.compatible:
            by_id.setdefault(str(getattr(rule, "rule_id", "") or ""), rule)
        ordered = sorted(
            (result for result in self.results if result.compatible),
            key=lambda item: (-item.score_after, item.candidate_rule_id),
        )
        return [
            by_id[result.candidate_rule_id]
            for result in ordered
            if result.candidate_rule_id in by_id
        ]

    def winner_id(self) -> str:
        ranked = self.ranked_compatible()
        return str(getattr(ranked[0], "rule_id", "") or "") if ranked else ""

    def to_public_dict(self) -> dict[str, Any]:
        rejected_reasons: dict[str, int] = {}
        for result in self.results:
            if result.compatible:
                continue
            reason = result.hard_reasons[0] if result.hard_reasons else result.eligibility
            rejected_reasons[reason] = rejected_reasons.get(reason, 0) + 1
        return {
            "version": OPERATION_COMPATIBILITY_VERSION,
            "applied": bool(self.applied),
            "query_operation": self.requirements.operation_family,
            "expected_operations": list(
                expected_operations(self.requirements.operation_family)[:4]
            ),
            "query": self.requirements.to_public_dict(),
            "candidates": len(self.results),
            "compatible": len(self.compatible),
            "rejected": len(self.rejected),
            "top_rejected_reasons": [
                {"reason": reason, "count": count}
                for reason, count in sorted(
                    rejected_reasons.items(), key=lambda item: (-item[1], item[0])
                )[:6]
            ],
            "winner_rule_id": self.winner_id(),
            "scores": [
                {
                    "rule_id": result.candidate_rule_id,
                    "score_before": round(result.score_before, 4),
                    "score_after": round(result.score_after, 4),
                    "eligible": bool(result.compatible),
                    "eligibility": result.eligibility,
                    "hard_reasons": list(result.hard_reasons[:3]),
                    "soft_reasons": list(result.soft_reasons[:3]),
                }
                for result in self.results[:24]
            ],
            "rules": [result.to_public_dict() for result in self.results[:24]],
        }


def gate_rules_for_requirements(
    rules: Sequence[Any],
    requirements: QueryOperationRequirements,
    *,
    scores: Mapping[str, float] | None = None,
) -> RuleCompatibilityGate:
    """Evalúa compatibilidad de TODAS las candidatas y separa elegibles."""
    score_map = {str(key): float(value) for key, value in (scores or {}).items()}
    gate = RuleCompatibilityGate(requirements=requirements, applied=bool(requirements.enforced))
    for rule in rules or ():
        rule_id = str(getattr(rule, "rule_id", "") or "")
        result = evaluate_operation_compatibility(
            rule, requirements, score_before=score_map.get(rule_id, 0.0)
        )
        gate.results.append(result)
        (gate.compatible if result.compatible else gate.rejected).append(rule)
    return gate


def operation_compatibility_for_rules(
    rules: Sequence[Any],
    requirements: QueryOperationRequirements,
    *,
    scores: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Vista pública del gate (telemetría del stage `operation_compatibility`)."""
    return gate_rules_for_requirements(rules, requirements, scores=scores).to_public_dict()


# -----------------------------------------------------------------------------
# OperationInputValidator — tipos semánticos antes del registry determinista
# -----------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class OperationInputValidation:
    """Resultado de validar los operandos de una operación determinista."""

    valid: bool = True
    reasons: tuple[str, ...] = ()
    detail: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "valid": bool(self.valid),
            "reasons": list(self.reasons[:4]),
            "detail": self.detail[:200],
        }


def validate_operation_inputs(
    operation: str,
    *,
    operands: Mapping[str, Any] | None = None,
    runtime_patterns: Sequence[str] = (),
) -> OperationInputValidation:
    """Valida tipos semánticos ANTES de ejecutar la operación determinista.

    - COMPARISON/NUMERIC_COMPARE: operandos ordenables; una máscara de runtime
      NO es un escalar ordenable (`ABCFGEGE >= &&&F` jamás se evalúa lexical).
    - RANGE_CHECK: valor y límites numéricos.
    - DATE_*: operandos parseables como fecha (fail-closed si no).
    """
    values = dict(operands or {})
    name = str(operation or "").upper()
    patterns = {str(item) for item in runtime_patterns if str(item or "").strip()}

    if name in ("COMPARISON", "NUMERIC_COMPARE", "STRING_COMPARE"):
        op = str(values.get("op") or "").lower()
        left = values.get("a")
        right = values.get("b")
        for label, operand in (("left", left), ("right", right)):
            if is_runtime_mask(operand):
                return OperationInputValidation(
                    valid=False,
                    reasons=(OPERAND_TYPE_INCOMPATIBLE,),
                    detail=(
                        f"{label} operand is a runtime pattern mask: "
                        f"{str(operand)[:60]}"
                    ),
                )
            if str(operand or "") in patterns and patterns:
                return OperationInputValidation(
                    valid=False,
                    reasons=(OPERAND_TYPE_INCOMPATIBLE,),
                    detail=f"{label} operand is a runtime pattern: {str(operand)[:60]}",
                )
        if name == "COMPARISON" and op in ("gt", "ge", "lt", "le"):
            if not (_numeric_like(left) and _numeric_like(right)):
                return OperationInputValidation(
                    valid=False,
                    reasons=(OPERAND_TYPE_INCOMPATIBLE,),
                    detail=(
                        "ordered comparison requires ordered scalars: "
                        f"{str(left)[:40]} {op} {str(right)[:40]}"
                    ),
                )
        return OperationInputValidation()

    if name == "RANGE_CHECK":
        value = values.get("value")
        if value is not None and not _numeric_like(value):
            return OperationInputValidation(
                valid=False,
                reasons=(OPERAND_TYPE_INCOMPATIBLE,),
                detail=f"range value is not numeric: {str(value)[:40]}",
            )
        return OperationInputValidation()

    if name in ("DATE_COMPARISON", "DATE_COMPARE", "DATE_RANGE"):
        for label in ("a", "b", "from", "to"):
            operand = values.get(label)
            if operand is None:
                continue
            if not _looks_like_date(operand):
                return OperationInputValidation(
                    valid=False,
                    reasons=(OPERAND_TYPE_INCOMPATIBLE,),
                    detail=f"{label} operand is not a date: {str(operand)[:40]}",
                )
        return OperationInputValidation()

    return OperationInputValidation()


_DATE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4}|"
    r"\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{1,2},?\s+\d{4}|\w+\s+\d{4})"
)


def _looks_like_date(value: Any) -> bool:
    """Fecha parseable ISO/d-m-Y/natural ES-EN (validación de tipo, no de valor)."""
    if value is None:
        return False
    from datetime import date, datetime

    if isinstance(value, (date, datetime)):
        return True
    text = " ".join(str(value or "").split())
    if not text:
        return False
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
            datetime.strptime(text, fmt)
            return True
        except ValueError:
            continue
    return bool(_DATE_RE.fullmatch(text))


def validate_comparison_operands(
    left: Any, right: Any, *, op: str = ""
) -> OperationInputValidation:
    """Atajo para el chequeo de comparación del rule compiler."""
    return validate_operation_inputs(
        "COMPARISON", operands={"a": left, "b": right, "op": op}
    )


def envelope_operation_compatible(
    operation: str,
    requirements: QueryOperationRequirements,
) -> tuple[bool, str]:
    """Invariante AUTHORITATIVE_OPERATION_COMPATIBILITY para un envelope.

    Devuelve (compatible, razón). Una operación cuya familia no está permitida
    por la query NO puede sostener un DecisionEnvelope autoritativo.
    """
    if not requirements.enforced:
        return True, ""
    family = operation_family_for_operation(operation)
    if not family:
        # Operación genérica/desconocida (p.ej. RULE_EVALUATION de una regla de
        # dominio): no hay base para declararla incompatible.
        return True, ""
    if family in allowed_families(requirements.operation_family):
        return True, ""
    return False, OPERATION_INCOMPATIBLE


__all__ = [
    "CAP_ARITHMETIC",
    "CAP_BOOLEAN",
    "CAP_COMPARISON",
    "CAP_DATE",
    "CAP_ENUM",
    "CAP_FORMULA",
    "CAP_LENGTH_POLICY",
    "CAP_MASK_MATCH",
    "CAP_POSITIONAL_SYMBOL_SEMANTICS",
    "CAP_RANGE",
    "ELIGIBLE",
    "FAMILY_ANY",
    "FAMILY_ARITHMETIC",
    "FAMILY_BOOLEAN",
    "FAMILY_COMPARISON",
    "FAMILY_DATE",
    "FAMILY_ENUM",
    "FAMILY_FORMULA",
    "FAMILY_MATCHING",
    "FAMILY_RANGE",
    "MISSING_RUNTIME_SYMBOL_SEMANTICS",
    "NO_EXECUTABLE_FAMILY",
    "OPERAND_TYPE_INCOMPATIBLE",
    "OPERATION_COMPATIBILITY_VERSION",
    "OPERATION_INCOMPATIBLE",
    "OperationCompatibilityResult",
    "OperationInputValidation",
    "QueryOperationRequirements",
    "RUNTIME_MASK_SYMBOLS",
    "RuleCapabilityProfile",
    "RuleCompatibilityGate",
    "SYMBOL_DEFINED",
    "SYMBOL_EXECUTABLE",
    "SYMBOL_MENTIONED",
    "allowed_families",
    "capability_score_bonus",
    "derive_query_operation_requirements",
    "envelope_operation_compatible",
    "evaluate_operation_compatibility",
    "expected_operations",
    "gate_rules_for_requirements",
    "is_runtime_mask",
    "mask_symbols_in",
    "operation_compatibility_for_rules",
    "operation_family_for_operation",
    "question_mask_token",
    "rule_capability_profile",
    "validate_comparison_operands",
    "validate_operation_inputs",
]
