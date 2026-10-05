# =============================================================================
# Domain — Rule semantics vocabulary (domain-agnostic)
# =============================================================================
# Vocabulario formal para reglas documentales. NO conoce ningún dominio, ningún
# símbolo concreto, ninguna frase de un fabricante.
#
# Principio rector:
#   MENCIONAR una propiedad NO establece su política.
#   "the value may be longer than the pattern" -> política asimétrica explícita.
#   "... length ..."                          -> mención: política UNKNOWN.
#
# Los clasificadores de este módulo son deterministas y puros (sin I/O, sin
# LLM). Devuelven OBSERVACIONES con el texto exacto que las soporta: el
# compilador de reglas las convierte en propiedades verificables con evidencia.
#
# Extensible: para una política nueva basta agregar una tupla a la tabla.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

RULE_SEMANTICS_VERSION = "rule-semantics-1"


# -----------------------------------------------------------------------------
# Comparaciones
# -----------------------------------------------------------------------------


class ComparisonOperator(StrEnum):
    EQ = "EQ"
    NE = "NE"
    GT = "GT"
    GTE = "GTE"
    LT = "LT"
    LTE = "LTE"
    BETWEEN = "BETWEEN"
    OUTSIDE_RANGE = "OUTSIDE_RANGE"
    UNKNOWN = "UNKNOWN"


#: Operador de comparación -> operador del registry determinista.
COMPARISON_TO_OPERATION: dict[str, str] = {
    ComparisonOperator.EQ.value: "eq",
    ComparisonOperator.NE.value: "ne",
    ComparisonOperator.GT.value: "gt",
    ComparisonOperator.GTE.value: "ge",
    ComparisonOperator.LT.value: "lt",
    ComparisonOperator.LTE.value: "le",
}


# -----------------------------------------------------------------------------
# Longitud (relaciones asimétricas)
# -----------------------------------------------------------------------------


class LengthPolicy(StrEnum):
    EXACT = "EXACT"
    VALUE_MAY_BE_LONGER = "VALUE_MAY_BE_LONGER"
    VALUE_MAY_BE_SHORTER = "VALUE_MAY_BE_SHORTER"
    PATTERN_MAY_BE_LONGER = "PATTERN_MAY_BE_LONGER"
    PATTERN_MAY_BE_SHORTER = "PATTERN_MAY_BE_SHORTER"
    MIN_LENGTH = "MIN_LENGTH"
    MAX_LENGTH = "MAX_LENGTH"
    RANGE = "RANGE"
    UNCONSTRAINED = "UNCONSTRAINED"
    UNKNOWN = "UNKNOWN"


#: Políticas que expresan restricciones numéricas de longitud.
_NUMERIC_LENGTH_POLICIES: frozenset[str] = frozenset(
    {
        LengthPolicy.MIN_LENGTH.value,
        LengthPolicy.MAX_LENGTH.value,
        LengthPolicy.RANGE.value,
    }
)

#: Políticas asimétricas: dicen en qué dirección puede diferir el largo.
_ASYMMETRIC_LENGTH_POLICIES: frozenset[str] = frozenset(
    {
        LengthPolicy.VALUE_MAY_BE_LONGER.value,
        LengthPolicy.VALUE_MAY_BE_SHORTER.value,
        LengthPolicy.PATTERN_MAY_BE_LONGER.value,
        LengthPolicy.PATTERN_MAY_BE_SHORTER.value,
    }
)


# -----------------------------------------------------------------------------
# Matching de strings/patrones
# -----------------------------------------------------------------------------


class MatchOperator(StrEnum):
    LITERAL = "LITERAL"
    WILDCARD = "WILDCARD"
    POSITIONAL = "POSITIONAL"
    PREFIX = "PREFIX"
    SUFFIX = "SUFFIX"
    CONTAINS = "CONTAINS"
    STARTS_WITH = "STARTS_WITH"
    ENDS_WITH = "ENDS_WITH"
    FIXED_POSITION = "FIXED_POSITION"
    UNKNOWN = "UNKNOWN"


# -----------------------------------------------------------------------------
# Lógica
# -----------------------------------------------------------------------------


class LogicOperator(StrEnum):
    AND = "AND"
    OR = "OR"
    NOT = "NOT"
    IMPLIES = "IMPLIES"
    ONLY_IF = "ONLY_IF"
    IF_AND_ONLY_IF = "IF_AND_ONLY_IF"
    UNLESS = "UNLESS"
    EXCEPTION = "EXCEPTION"
    DEFAULT = "DEFAULT"
    OVERRIDE = "OVERRIDE"
    PRECEDENCE = "PRECEDENCE"
    FALLBACK = "FALLBACK"


class QuantifierKind(StrEnum):
    ALL = "ALL"
    ANY = "ANY"
    NONE = "NONE"
    AT_LEAST_ONE = "AT_LEAST_ONE"
    EXACTLY_ONE = "EXACTLY_ONE"
    EXACTLY_N = "EXACTLY_N"
    UNKNOWN = "UNKNOWN"


class ModalityKind(StrEnum):
    MUST = "MUST"
    MUST_NOT = "MUST_NOT"
    SHOULD = "SHOULD"
    SHOULD_NOT = "SHOULD_NOT"
    MAY = "MAY"
    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"
    CONSTRAINT = "CONSTRAINT"
    NONE = "NONE"


#: Modalidades normativas (capaces de generar regla).
NORMATIVE_MODALITIES: frozenset[str] = frozenset(
    {
        ModalityKind.MUST.value,
        ModalityKind.MUST_NOT.value,
        ModalityKind.REQUIRED.value,
        ModalityKind.CONSTRAINT.value,
    }
)

#: Modalidad -> fuerza (mayor gana). "may" NUNCA se iguala a "must".
MODALITY_STRENGTH: dict[str, float] = {
    ModalityKind.MUST.value: 1.0,
    ModalityKind.REQUIRED.value: 1.0,
    ModalityKind.MUST_NOT.value: 1.0,
    ModalityKind.CONSTRAINT.value: 0.8,
    ModalityKind.SHOULD.value: 0.5,
    ModalityKind.SHOULD_NOT.value: 0.5,
    ModalityKind.MAY.value: 0.25,
    ModalityKind.OPTIONAL.value: 0.2,
    ModalityKind.NONE.value: 0.0,
}


class Polarity(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    UNKNOWN = "UNKNOWN"


class BoundaryKind(StrEnum):
    INCLUSIVE = "INCLUSIVE"
    EXCLUSIVE = "EXCLUSIVE"
    UNKNOWN = "UNKNOWN"


# -----------------------------------------------------------------------------
# Tiempo
# -----------------------------------------------------------------------------


class TemporalRelation(StrEnum):
    BEFORE = "BEFORE"
    AFTER = "AFTER"
    FROM_TO = "FROM_TO"
    EFFECTIVE_FROM = "EFFECTIVE_FROM"
    EXPIRES = "EXPIRES"
    DURATION = "DURATION"
    SIMULTANEOUS = "SIMULTANEOUS"
    UNKNOWN = "UNKNOWN"


# -----------------------------------------------------------------------------
# Clasificación documental y estado de verificación
# -----------------------------------------------------------------------------


class RuleKind(StrEnum):
    NORMATIVE_RULE = "NORMATIVE_RULE"
    DEFINITION = "DEFINITION"
    EXAMPLE = "EXAMPLE"
    NOTE = "NOTE"
    EXCEPTION = "EXCEPTION"
    PROCEDURE = "PROCEDURE"
    REFERENCE = "REFERENCE"
    FORMULA = "FORMULA"
    CONSTRAINT = "CONSTRAINT"
    MAPPING = "MAPPING"


class VerificationState(StrEnum):
    PROPOSED = "PROPOSED"
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    CONFLICTING = "CONFLICTING"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


#: Estados que permiten ejecución determinista.
EXECUTABLE_STATES: frozenset[str] = frozenset({VerificationState.SUPPORTED.value})


class ClaimLayer(StrEnum):
    """Separación estricta fuente vs interpretación vs cómputo."""

    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    DERIVED = "DERIVED"


class ExtractionMethod(StrEnum):
    DETERMINISTIC = "deterministic"
    LLM_PROPOSED = "llm_proposed"
    HUMAN = "human"
    DERIVED = "derived"


# -----------------------------------------------------------------------------
# Observaciones (salida de los clasificadores)
# -----------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class LengthObservation:
    policy: str = LengthPolicy.UNKNOWN.value
    value: int | None = None
    upper: int | None = None
    boundary: str = BoundaryKind.UNKNOWN.value
    directional: bool = False
    left_operand: str = ""
    right_operand: str = ""
    matched_text: str = ""
    explicit: bool = False
    mention_only: bool = False
    missing_premises: tuple[str, ...] = ()
    note: str = ""

    @property
    def is_policy(self) -> bool:
        return self.policy != LengthPolicy.UNKNOWN.value and not self.mention_only


@dataclass(frozen=True, kw_only=True)
class MatchObservation:
    operator: str = MatchOperator.UNKNOWN.value
    literal: bool = False
    case_sensitive: bool | None = None
    alphabet: str = ""
    prohibited_alphabet: str = ""
    fixed_position: int | None = None
    optional_positions: bool = False
    repeated_positions: bool = False
    separator: str = ""
    normalization: str = ""
    matched_text: str = ""
    explicit: bool = False


@dataclass(frozen=True, kw_only=True)
class ComparisonObservation:
    left_operand: str = ""
    operator: str = ComparisonOperator.UNKNOWN.value
    right_operand: str = ""
    boundary: str = BoundaryKind.UNKNOWN.value
    matched_text: str = ""
    explicit: bool = True
    span: tuple[int, int] = ()


@dataclass(frozen=True, kw_only=True)
class LogicObservation:
    operator: str = LogicOperator.AND.value
    matched_text: str = ""


@dataclass(frozen=True, kw_only=True)
class QuantityObservation:
    value: float | None = None
    upper: float | None = None
    unit: str = ""
    boundary: str = BoundaryKind.UNKNOWN.value
    matched_text: str = ""


@dataclass(frozen=True, kw_only=True)
class TemporalObservation:
    relation: str = TemporalRelation.UNKNOWN.value
    value: str = ""
    upper: str = ""
    unit: str = ""
    matched_text: str = ""


@dataclass(frozen=True, kw_only=True)
class ModalityObservation:
    modality: str = ModalityKind.NONE.value
    polarity: str = Polarity.UNKNOWN.value
    matched_text: str = ""

    @property
    def normative(self) -> bool:
        return self.modality in NORMATIVE_MODALITIES


@dataclass(frozen=True, kw_only=True)
class NegationObservation:
    negated: bool = False
    markers: tuple[str, ...] = ()
    matched_text: str = ""


@dataclass(frozen=True, kw_only=True)
class LanguageSignals:
    """Todas las señales lingüísticas de un enunciado, con su texto exacto."""

    modality: ModalityObservation = field(default_factory=ModalityObservation)
    negation: NegationObservation = field(default_factory=NegationObservation)
    comparisons: tuple[ComparisonObservation, ...] = ()
    length: LengthObservation = field(default_factory=LengthObservation)
    match: MatchObservation = field(default_factory=MatchObservation)
    logic: tuple[LogicObservation, ...] = ()
    quantifier: str = QuantifierKind.UNKNOWN.value
    quantities: tuple[QuantityObservation, ...] = ()
    temporal: TemporalObservation = field(default_factory=TemporalObservation)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "version": RULE_SEMANTICS_VERSION,
            "modality": self.modality.modality,
            "polarity": self.modality.polarity,
            "negated": self.negation.negated,
            "comparisons": [
                {
                    "operator": item.operator,
                    "left": item.left_operand,
                    "right": item.right_operand,
                    "boundary": item.boundary,
                    "matched_text": item.matched_text[:160],
                }
                for item in self.comparisons[:4]
            ],
            "length": {
                "policy": self.length.policy,
                "value": self.length.value,
                "upper": self.length.upper,
                "boundary": self.length.boundary,
                "directional": self.length.directional,
                "explicit": self.length.explicit,
                "mention_only": self.length.mention_only,
                "missing_premises": list(self.length.missing_premises),
            },
            "match": {
                "operator": self.match.operator,
                "case_sensitive": self.match.case_sensitive,
                "alphabet": self.match.alphabet,
                "prohibited_alphabet": self.match.prohibited_alphabet,
                "explicit": self.match.explicit,
            },
            "logic": [item.operator for item in self.logic[:6]],
            "quantifier": self.quantifier,
            "temporal": {
                "relation": self.temporal.relation,
                "value": self.temporal.value,
                "upper": self.temporal.upper,
            },
        }


# =============================================================================
# Clasificadores deterministas
# =============================================================================

_FLAGS = re.IGNORECASE | re.UNICODE

_VALUE_WORDS = ("value", "valor", "user value", "input", "entrada", "dato")
_PATTERN_WORDS = ("pattern", "patrón", "patron", "mask", "máscara", "mascara", "template", "plantilla")


def _norm(text: str) -> str:
    return " ".join(str(text or "").split())


def _snippet(text: str, match: re.Match[str]) -> str:
    start = max(0, match.start() - 40)
    end = min(len(text), match.end() + 40)
    return _norm(text[start:end])


def _first_match(text: str, patterns: tuple[re.Pattern[str], ...]) -> re.Match[str] | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match
    return None


#: Orden importa: negación deóntica antes que permiso, "may not" antes que "may".
_MODALITY_TABLE: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        ModalityKind.MUST_NOT.value,
        Polarity.NEGATIVE.value,
        re.compile(
            r"\b(must\s+not|shall\s+not|mustn'?t|ma?y\s+not|cannot|can'?t|"
            r"is\s+not\s+(?:allowed|permitted)|are\s+not\s+(?:allowed|permitted)|"
            r"not\s+permitted|prohibited|forbidden|"
            r"no\s+debe|no\s+deben|no\s+podr[aá]n?|prohibid[oa]s?|"
            r"qued[ao]\s+prohibid[oa])\b",
            _FLAGS,
        ),
    ),
    (
        ModalityKind.SHOULD_NOT.value,
        Polarity.NEGATIVE.value,
        re.compile(r"\b(should\s+not|shouldn'?t|no\s+se\s+recomienda)\b", _FLAGS),
    ),
    (
        ModalityKind.MUST.value,
        Polarity.POSITIVE.value,
        re.compile(
            r"\b(must|shall|required\s+to|is\s+required|are\s+required|has\s+to|"
            r"have\s+to|needs?\s+to|require[sd]?|"
            r"debe|deben|deber[aá]n?|obligatori[oa]|requiere|requerid[oa]|"
            r"es\s+necesario)\b",
            _FLAGS,
        ),
    ),
    (
        ModalityKind.SHOULD.value,
        Polarity.POSITIVE.value,
        re.compile(
            r"\b(should|recommended|it\s+is\s+advisable|is\s+recommended|"
            r"se\s+recomienda|recomendable|conviene)\b",
            _FLAGS,
        ),
    ),
    (
        ModalityKind.OPTIONAL.value,
        Polarity.POSITIVE.value,
        re.compile(r"\b(optional|opcional|at\s+the\s+discretion|a\s+discreci[oó]n)\b", _FLAGS),
    ),
    (
        ModalityKind.MAY.value,
        Polarity.POSITIVE.value,
        re.compile(r"\b(may|might|can|puede|pueden|podr[aá]n?)\b", _FLAGS),
    ),
)


def classify_modality(text: str) -> ModalityObservation:
    """Modalidad deóntica. "may" NUNCA se eleva a "must"."""
    raw = _norm(text)
    for modality, polarity, pattern in _MODALITY_TABLE:
        match = pattern.search(raw)
        if match:
            return ModalityObservation(
                modality=modality,
                polarity=polarity,
                matched_text=match.group(0),
            )
    return ModalityObservation()


_NEGATION_RE = re.compile(
    r"\b(not|never|no|nunca|ning[uú]n[oa]?|without|sin|except|salvo|"
    r"unless|a\s+menos\s+que|no\s+aplica|does\s+not\s+apply|cannot|"
    r"must\s+not|shall\s+not|no\s+puede|prohibido|excluded?|excluid[oa])\b",
    _FLAGS,
)


def classify_negation(text: str) -> NegationObservation:
    """Marcadores negativos: la negación no se pierde en normalización."""
    raw = _norm(text)
    markers = tuple(dict.fromkeys(match.group(0).lower() for match in _NEGATION_RE.finditer(raw)))
    return NegationObservation(
        negated=bool(markers),
        markers=markers[:8],
        matched_text="; ".join(markers[:4]),
    )


# --- Comparaciones (dirección preservada) -------------------------------------

_COMPARISON_TABLE: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        ComparisonOperator.OUTSIDE_RANGE.value,
        re.compile(
            r"\b(outside\s+(?:the\s+)?range|outside|not\s+between|"
            r"fuera\s+de\s+(?:l[ao]s?\s+)?rango|fuera\s+de|no\s+entre)\b",
            _FLAGS,
        ),
    ),
    (
        ComparisonOperator.BETWEEN.value,
        re.compile(
            r"\b(between|entre)\s+(?P<low>[^.,;\n]{1,24}?)\s+(?:and|y|–|-|a)\s+"
            r"(?P<high>[^.,;\n]{1,24})",
            _FLAGS,
        ),
    ),
    (
        ComparisonOperator.NE.value,
        re.compile(
            r"\b(not\s+equal\s+to|not\s+the\s+same\s+as|different\s+from|differs?\s+from|"
            r"distint[oa]\s+de|diferente\s+de|no\s+es\s+igual\s+a|no\s+coincide)\b",
            _FLAGS,
        ),
    ),
    (
        ComparisonOperator.GTE.value,
        re.compile(
            r"\b(at\s+least|not\s+less\s+than|greater\s+than\s+or\s+equal\s+to|"
            r"on\s+or\s+after|no\s+menos\s+de|como\s+m[ií]nimo|"
            r"mayor\s+o\s+igual\s+(?:a|que))\b",
            _FLAGS,
        ),
    ),
    (
        ComparisonOperator.LTE.value,
        re.compile(
            r"\b(at\s+most|not\s+more\s+than|less\s+than\s+or\s+equal\s+to|"
            r"up\s+to(?:\s+and\s+including)?|on\s+or\s+before|"
            r"(?:must\s+not|cannot|can'?t|shall\s+not|not)\s+exceed|"
            r"no\s+m[aá]s\s+de|como\s+m[aá]ximo|menor\s+o\s+igual\s+(?:a|que))\b",
            _FLAGS,
        ),
    ),
    (
        ComparisonOperator.GT.value,
        re.compile(
            r"\b(greater\s+than|more\s+than|exceeds?|bigger\s+than|larger\s+than|"
            r"above(?=\s+(?:\d|the\s+\d))|later\s+than|mayor\s+que|"
            r"m[aá]s\s+(?:de|que|grande\s+que))\b",
            _FLAGS,
        ),
    ),
    (
        ComparisonOperator.LT.value,
        re.compile(
            r"\b(less\s+than|fewer\s+than|below(?=\s+(?:\d|the\s+\d))|"
            r"under(?=\s+(?:\d|the\s+\d))|smaller\s+than|"
            r"earlier\s+than|prior\s+to|menor\s+que|por\s+debajo\s+de)\b",
            _FLAGS,
        ),
    ),
    (
        ComparisonOperator.EQ.value,
        re.compile(
            r"\b(equal\s+to|equals|same\s+as|identical\s+to|coincides?\s+with|"
            r"igual\s+a|igual\s+que|mismo\s+que|id[eé]ntic[oa]\s+a|coincide\s+con)\b",
            _FLAGS,
        ),
    ),
)

#: Captura del operando derecho de una comparación ("minimum of 5 days").
_OPERAND_RIGHT_RE = re.compile(
    r"(?:(?:of|de|que|than|a)\s+)?\s*"
    r"(?P<number>-?\d+(?:[.,]\d+)?)(?:\s*(?P<unit>%|[a-záéíóúñ]{1,12}))?",
    _FLAGS,
)

#: Palabras que NO son unidades tras un número.
_UNIT_STOPWORDS = frozenset(
    {
        "and", "y", "or", "o", "the", "el", "la", "los", "las", "de", "del", "que",
        "unless", "except", "only", "when", "if", "salvo", "para", "con", "sin",
        "aplica", "aplica.", "require", "requires", "required", "must", "shall",
        "should", "may", "can",
    }
)

#: Captura del operando derecho nominal ("earlier than the departure date").
_OPERAND_PHRASE_RE = re.compile(
    r"\s*(?:(?:the|a|an|el|la|los|las)\s+)?"
    r"(?P<phrase>[a-záéíóúñ][\wáéíóúñ-]*(?:\s+[\wáéíóúñ-]+){0,5})",
    _FLAGS,
)

_OPERAND_PHRASE_STOPWORDS = frozenset(
    {
        "are", "is", "must", "shall", "may", "can", "when", "under", "que",
        "and", "or", "y", "o", "but", "pero", "with", "con", "for", "para",
        "than", "to", "of", "de", "del", "the",
    }
)


def _clean_operand_phrase(raw: str) -> str:
    words = _norm(raw).split()
    while words and words[-1].lower() in _OPERAND_PHRASE_STOPWORDS:
        words.pop()
    return " ".join(words)[:80]


_LEFT_MODAL_TAIL = frozenset(
    {
        "must", "shall", "may", "can", "cannot", "not", "is", "are", "be",
        "debe", "deben", "puede", "pueden", "ser", "es", "son", "the", "a",
        "an", "el", "la", "los", "las", "que", "y", "and", "or", "o",
    }
)


def _capture_left_operand(raw: str, start: int) -> str:
    """Operando izquierdo nominal: el sujeto antes del operador."""
    prefix = raw[:start]
    cut = max(prefix.rfind("."), prefix.rfind(";"), prefix.rfind(","))
    chunk = prefix[cut + 1 :] if cut >= 0 else prefix
    words = chunk.strip().split()
    while words and words[-1].lower() in _LEFT_MODAL_TAIL:
        words.pop()
    text = " ".join(words).strip()
    return text[-80:]


def classify_comparison(text: str) -> tuple[ComparisonObservation, ...]:
    """Operadores de comparación con left/right preservados.

    La asimetría es obligatoria: "A may be longer than B" produce GT(A, B),
    jamás un difuso "distinta longitud".
    """
    raw = _norm(text)
    observations: list[ComparisonObservation] = []
    seen: set[tuple[str, str]] = set()
    for operator, pattern in _COMPARISON_TABLE:
        match = pattern.search(raw)
        if not match:
            continue
        left = ""
        right = ""
        groups = match.groupdict() or {}
        if "low" in groups and match.group("low"):
            left = _norm(match.group("low"))
        if not left:
            left = _capture_left_operand(raw, match.start())
        if "right" in groups and match.group("right"):
            right = _norm(match.group("right"))
        elif "high" in groups and match.group("high"):
            right = _norm(match.group("high"))
        if not right:
            after = raw[match.end() :]
            right_match = _OPERAND_RIGHT_RE.match(" " + after.strip())
            if right_match:
                number = _norm(right_match.group("number"))
                unit = _norm(right_match.group("unit") or "")
                right = number
                if unit and unit.lower() not in _UNIT_STOPWORDS:
                    right = f"{number} {unit}"
            elif operator in (
                ComparisonOperator.GT.value,
                ComparisonOperator.GTE.value,
                ComparisonOperator.LT.value,
                ComparisonOperator.LTE.value,
                ComparisonOperator.EQ.value,
                ComparisonOperator.NE.value,
            ):
                # Relación entre operandos nominales: "X earlier than Y".
                phrase_match = _OPERAND_PHRASE_RE.match(" " + after.strip())
                if phrase_match:
                    right = _clean_operand_phrase(
                        phrase_match.group("phrase")
                    )
        key = (operator, right)
        if key in seen:
            continue
        seen.add(key)
        boundary = BoundaryKind.UNKNOWN.value
        if operator in (
            ComparisonOperator.GTE.value,
            ComparisonOperator.LTE.value,
        ):
            # "at least"/"at most"/"or equal"/"on or before" son inclusivos.
            boundary = BoundaryKind.INCLUSIVE.value
            if re.search(r"\bup\s+to\b", match.group(0), _FLAGS) and not re.search(
                r"including|inclusive", match.group(0), _FLAGS
            ):
                # "up to" sin marcador explícito: la inclusividad NO se asume.
                boundary = BoundaryKind.UNKNOWN.value
        explicit_boundary = classify_boundary(raw)
        if operator == ComparisonOperator.BETWEEN.value and explicit_boundary != BoundaryKind.UNKNOWN.value:
            boundary = explicit_boundary
        if explicit_boundary == BoundaryKind.EXCLUSIVE.value and operator != ComparisonOperator.LT.value:
            boundary = BoundaryKind.EXCLUSIVE.value
        observations.append(
            ComparisonObservation(
                left_operand=left,
                operator=operator,
                right_operand=right,
                boundary=boundary,
                matched_text=match.group(0).strip(),
                span=(match.start(), match.end()),
            )
        )
    # "must not exceed": LTE manda; se elimina el GT que la misma palabra
    # habría producido (la negación no se pierde).
    not_exceed_rights = {
        obs.right_operand
        for obs in observations
        if obs.operator == ComparisonOperator.LTE.value
        and re.search(r"\bnot\s+exceed|no\s+exced|no\s+debe\s+exceder", obs.matched_text, _FLAGS)
    }
    if not_exceed_rights:
        observations = [
            obs
            for obs in observations
            if not (
                obs.operator == ComparisonOperator.GT.value
                and obs.right_operand in not_exceed_rights
            )
        ]
    # "less than or equal to" no debe degradarse a "less than" (y viceversa):
    # la observación inclusiva manda sobre la exclusiva con el mismo operando.
    inclusive_rights: dict[str, str] = {}
    for obs in observations:
        if obs.operator == ComparisonOperator.LTE.value and re.search(
            r"or\s+equal|including|inclusive|at\s+most|not\s+more|"
            r"no\s+m[aá]s|como\s+m[aá]ximo|on\s+or\s+before|not\s+exceed",
            obs.matched_text,
            _FLAGS,
        ):
            inclusive_rights[obs.right_operand] = ComparisonOperator.LTE.value
        if obs.operator == ComparisonOperator.GTE.value and re.search(
            r"or\s+equal|at\s+least|not\s+less|no\s+menos|como\s+m[ií]nimo|"
            r"on\s+or\s+after",
            obs.matched_text,
            _FLAGS,
        ):
            inclusive_rights[obs.right_operand] = ComparisonOperator.GTE.value
    if inclusive_rights:
        observations = [
            obs
            for obs in observations
            if not (
                obs.right_operand in inclusive_rights
                and (
                    (
                        inclusive_rights[obs.right_operand]
                        == ComparisonOperator.LTE.value
                        and obs.operator == ComparisonOperator.LT.value
                    )
                    or (
                        inclusive_rights[obs.right_operand]
                        == ComparisonOperator.GTE.value
                        and obs.operator == ComparisonOperator.GT.value
                    )
                )
            )
        ]
    # "than or equal to": EQ/LT/GT parciales nacidos del mismo modificador no
    # son comparaciones adicionales (la inclusiva ya los representa). Se usa el
    # span exacto, no la ventana de contexto.
    inclusive_spans = [
        (span_match.start(), span_match.end())
        for span_match in re.finditer(
            r"(?:less|greater)\s+than\s+or\s+equal\s+to|on\s+or\s+before|"
            r"on\s+or\s+after|up\s+to(?:\s+and\s+including)?|at\s+(?:least|most)|"
            r"not\s+more\s+than|not\s+less\s+than|no\s+m[aá]s\s+de|"
            r"no\s+menos\s+de|como\s+m[aá]ximo|como\s+m[ií]nimo",
            raw,
            _FLAGS,
        )
    ]
    if inclusive_spans:
        partial = {
            ComparisonOperator.EQ.value,
            ComparisonOperator.LT.value,
            ComparisonOperator.GT.value,
        }
        observations = [
            obs
            for obs in observations
            if not (
                obs.operator in partial
                and obs.span
                and any(
                    obs.span[0] >= span[0] and obs.span[1] <= span[1]
                    for span in inclusive_spans
                )
            )
        ]
    return tuple(observations)


# --- Longitud ----------------------------------------------------------------

_LENGTH_MENTION_RE = re.compile(
    r"\b(length|longitud|tama[nñ]o|number\s+of\s+(?:characters|positions|digits|"
    r"letters)|cantidad\s+de\s+(?:caracteres|posiciones|d[ií]gitos|letras))\b",
    _FLAGS,
)

#: Números en palabras (EN/ES) para longitudes declaradas en lenguaje natural.
_NUMBER_WORDS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12,
    "trece": 13, "catorce": 14, "quince": 15, "dieciséis": 16, "dieciseis": 16,
    "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
}

_NUMBER_TOKEN = r"(?P<n>\d+|" + "|".join(_NUMBER_WORDS) + r")"


def _parse_number_token(raw: str) -> int | None:
    text = _norm(raw or "").lower()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    return _NUMBER_WORDS.get(text)

_EXACT_LENGTH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:same|equal|identical)\s+(?:number\s+of\s+)?"
        r"(?:length|characters?|positions?|digits?|letters?)\b",
        _FLAGS,
    ),
    re.compile(
        rf"\b(?:must|shall|has\s+to|have\s+to|debe|deben)\s+"
        rf"(?:have|be|contain|tener|contener)\s+exactly\s+{_NUMBER_TOKEN}\s+"
        r"(?:characters?|positions?|digits?|letras?|caracteres?|posiciones?|d[ií]gitos?)\b",
        _FLAGS,
    ),
    re.compile(
        rf"\b(?:must|shall|debe|deben|requiere)\s+(?:have|be\s+of|tener|ser\s+de)\s+"
        rf"(?:a\s+)?(?:length|longitud)\s+of\s+{_NUMBER_TOKEN}\b",
        _FLAGS,
    ),
    re.compile(
        rf"\b(?:debe|deben|deber[aá]n?)\s+(?:tener|contener|ser\s+de)\s+"
        rf"{_NUMBER_TOKEN}\s+(?:caracteres?|posiciones?|d[ií]gitos?|letras?)\b",
        _FLAGS,
    ),
    re.compile(
        rf"\bexactly\s+{_NUMBER_TOKEN}\s+"
        r"(?:characters?|positions?|digits?|letters?|caracteres?|posiciones?|d[ií]gitos?|letras?)\b",
        _FLAGS,
    ),
    re.compile(
        rf"\bexactamente\s+{_NUMBER_TOKEN}\s+"
        r"(?:caracteres?|posiciones?|d[ií]gitos?|letras?)\b",
        _FLAGS,
    ),
    re.compile(r"\bfixed[- ]length\b|\blongitud\s+(?:fija|exacta)\b", _FLAGS),
    re.compile(r"\b(?:misma|igual)\s+longitud\b|\bmismo\s+n[uú]mero\s+de\s+(?:caracteres|posiciones)\b", _FLAGS),
)

_ASYMMETRIC_LENGTH_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "longer",
        "",
        re.compile(
            r"(?P<left>[a-z0-9áéíóúñ_&*#%?.]+(?:\s+[a-z0-9áéíóúñ_&*#%?.()]{1,20}){0,3}?)\s+"
            r"(?:may|can|might|is\s+allowed\s+to|are\s+allowed\s+to|puede|pueden|"
            r"podr[aá]n?)\s+(?:be|contain|have|tener|contener)\s+"
            r"(?P<more>more|m[aá]s)\s+(?:characters?|positions?|digits?|letters?|"
            r"caracteres?|posiciones?|d[ií]gitos?|letras?|long|large|largo|larga)\s+"
            r"(?:than|que)\s+(?P<right>[a-z0-9áéíóúñ_&*#%?.]+(?:\s+[a-z0-9áéíóúñ_&*#%?.()]{1,20}){0,3})",
            _FLAGS,
        ),
    ),
    (
        "shorter",
        "",
        re.compile(
            r"(?P<left>[a-z0-9áéíóúñ_&*#%?.]+(?:\s+[a-z0-9áéíóúñ_&*#%?.()]{1,20}){0,3}?)\s+"
            r"(?:may|can|might|is\s+allowed\s+to|are\s+allowed\s+to|puede|pueden|"
            r"podr[aá]n?)\s+(?:be|contain|have|tener|contener)\s+"
            r"(?P<fewer>fewer|less|menos)\s+(?:characters?|positions?|digits?|letters?|"
            r"caracteres?|posiciones?|d[ií]gitos?|letras?|long|large|larg[oa])\s+"
            r"(?:than|que)\s+(?P<right>[a-z0-9áéíóúñ_&*#%?.]+(?:\s+[a-z0-9áéíóúñ_&*#%?.()]{1,20}){0,3})",
            _FLAGS,
        ),
    ),
    (
        "longer",
        "pattern",
        re.compile(
            r"(?P<left>pattern|patr[oó]n|m[aá]scara|mask|template|plantilla)\s+"
            r"(?:may|can|might|puede|podr[aá])\s+(?:be|contain|have|tener|contener)\s+"
            r"(?P<more>more|m[aá]s)\s+(?:characters?|positions?|caracteres?|posiciones?|"
            r"long|larg[oa])\s+(?:than|que)\s+"
            r"(?P<right>value|valor|input|entrada|dato)\b",
            _FLAGS,
        ),
    ),
    (
        "shorter",
        "pattern",
        re.compile(
            r"(?P<left>pattern|patr[oó]n|m[aá]scara|mask|template|plantilla)\s+"
            r"(?:may|can|might|puede|podr[aá])\s+(?:be|contain|have|tener|contener)\s+"
            r"(?P<fewer>fewer|less|menos)\s+(?:characters?|positions?|caracteres?|posiciones?|"
            r"long|cort[ao])\s+(?:than|que)\s+"
            r"(?P<right>value|valor|input|entrada|dato)\b",
            _FLAGS,
        ),
    ),
    (
        "longer",
        "",
        re.compile(
            r"(?P<left>[a-z0-9áéíóúñ_&*#%?.]+(?:\s+[a-z0-9áéíóúñ_&*#%?.()]{1,20}){0,3}?)\s+"
            r"(?:may|can|might|puede|pueden|podr[aá]n?)\s+(?:be|ser)\s+"
            r"(?:longer|larg[oa])\s+(?:than|que)\s+"
            r"(?P<right>[a-z0-9áéíóúñ_&*#%?.]+(?:\s+[a-z0-9áéíóúñ_&*#%?.()]{1,20}){0,3})",
            _FLAGS,
        ),
    ),
    (
        "shorter",
        "",
        re.compile(
            r"(?P<left>[a-z0-9áéíóúñ_&*#%?.]+(?:\s+[a-z0-9áéíóúñ_&*#%?.()]{1,20}){0,3}?)\s+"
            r"(?:may|can|might|puede|pueden|podr[aá]n?)\s+(?:be|ser)\s+"
            r"(?:shorter|cort[ao])\s+(?:than|que)\s+"
            r"(?P<right>[a-z0-9áéíóúñ_&*#%?.]+(?:\s+[a-z0-9áéíóúñ_&*#%?.()]{1,20}){0,3})",
            _FLAGS,
        ),
    ),
)

_MIN_LENGTH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        rf"\b(?:at\s+least|no\s+fewer\s+than|no\s+less\s+than|minimum(?:\s+(?:of|length))?)\s+"
        rf"{_NUMBER_TOKEN}\b",
        _FLAGS,
    ),
    re.compile(
        rf"\b(?:m[ií]nimo(?:\s+de)?|al\s+menos|como\s+m[ií]nimo|no\s+menos\s+de)\s+"
        rf"{_NUMBER_TOKEN}\b",
        _FLAGS,
    ),
)

_MAX_LENGTH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        rf"\b(?:at\s+most|no\s+more\s+than|not\s+more\s+than|maximum(?:\s+(?:of|length))?)\s+"
        rf"{_NUMBER_TOKEN}\b",
        _FLAGS,
    ),
    re.compile(
        rf"\b(?:m[aá]ximo(?:\s+de)?|como\s+m[aá]ximo|no\s+m[aá]s\s+de)\s+"
        rf"{_NUMBER_TOKEN}\b",
        _FLAGS,
    ),
)

_RANGE_LENGTH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(rf"\bbetween\s+{_NUMBER_TOKEN}\s+and\s+(?P<m>\d+)\b", _FLAGS),
    re.compile(rf"\bentre\s+{_NUMBER_TOKEN}\s+y\s+(?P<m>\d+)\b", _FLAGS),
)

# --- Marcos de paráfrasis de longitud (léxico + roles, no frases fijas) ------
# Cada marco combina slots: sujeto (value/pattern), permiso, cantidad extra,
# unidad y relación posicional. El objetivo es que variantes lingüísticas
# produzcan la MISMA relación canónica sin listar la frase completa.

_VALUE_SIDE = (
    r"(?:value|input|code|product\s+code|string|serial(?:\s+identifier)?|"
    r"password|identifier|valor|entrada|c[oó]digo|contrase[nñ]a|identificador)"
)
_PATTERN_SIDE = (
    r"(?:pattern|mask|tile|template|matched\s+(?:portion|part|tile)|"
    r"pattern\s+positions?|m[aá]scara|patr[oó]n|plantilla)"
)
_LENGTH_UNITS = (
    r"(?:characters?|chars?|digits?|letters?|positions?|"
    r"caracteres?|posiciones?|d[ií]gitos?|letras?)"
)
_PERMISSION = (
    r"(?:may|can|might|could|is|are|puede|pueden|podr[aá]n?)"
)
_EXTRA = (
    r"(?:additional|extra|more|further|leading|trailing|filler|"
    r"adicionales?|extras?|m[aá]s|relleno)"
)

_LENGTH_FRAMES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        LengthPolicy.VALUE_MAY_BE_LONGER.value,
        re.compile(
            rf"\b{_VALUE_SIDE}\b[^.;]{{0,40}}?\b{_PERMISSION}\b[^.;]{{0,30}}?"
            rf"\b(?:contain|carry|have|include|be)\b[^.;]{{0,40}}?\b{_EXTRA}\b"
            rf"[^.;]{{0,30}}?\b{_LENGTH_UNITS}\b[^.;]{{0,40}}?"
            rf"\b(?:beyond|after|outside|in\s+front\s+of)\b[^.;]{{0,30}}?"
            rf"\b{_PATTERN_SIDE}\b",
            _FLAGS,
        ),
    ),
    (
        LengthPolicy.VALUE_MAY_BE_LONGER.value,
        re.compile(
            rf"\b(?P<extra>additional|extra|more|leading|trailing|filler)\b"
            rf"[^.;]{{0,30}}?\b{_LENGTH_UNITS}?\b[^.;]{{0,30}}?"
            rf"\b(?:are|is|son|est[aá]n?)\b\s*"
            rf"(?:permitted|allowed|accepted|permitid[oa]s?|aceptad[oa]s?)\b"
            rf"[^.;]{{0,40}}?\b(?:after|before|beyond|in\s+front\s+of)\b"
            rf"[^.;]{{0,30}}?\b(?:the\s+)?{_PATTERN_SIDE}\b",
            _FLAGS,
        ),
    ),
    (
        LengthPolicy.VALUE_MAY_BE_LONGER.value,
        re.compile(
            rf"\b(?:additional|extra|more|leading|trailing|filler)\b"
            rf"[^.;]{{0,30}}?\b{_LENGTH_UNITS}?\b[^.;]{{0,40}}?"
            rf"\b(?:are|is|son|est[aá]n?)\b\s*"
            rf"(?:permitted|allowed|accepted|permitid[oa]s?|aceptad[oa]s?)\b",
            _FLAGS,
        ),
    ),
    (
        LengthPolicy.VALUE_MAY_BE_LONGER.value,
        re.compile(
            rf"\b{_VALUE_SIDE}\b[^.;]{{0,40}}?\b{_PERMISSION}\b\s+"
            rf"(?:be|ser)\s+(?:longer|larg[oa])\s+(?:than|que)\s+"
            rf"\b{_PATTERN_SIDE}\b",
            _FLAGS,
        ),
    ),
    (
        LengthPolicy.PATTERN_MAY_BE_LONGER.value,
        re.compile(
            rf"\b{_PATTERN_SIDE}\b[^.;]{{0,40}}?\b{_PERMISSION}\b\s+"
            rf"(?:be|ser)\s+(?:longer|larg[oa])\s+(?:than|que)\s+"
            rf"\b{_VALUE_SIDE}\b",
            _FLAGS,
        ),
    ),
    (
        LengthPolicy.VALUE_MAY_BE_SHORTER.value,
        re.compile(
            rf"\b{_VALUE_SIDE}\b[^.;]{{0,40}}?\b{_PERMISSION}\b\s+"
            rf"(?:be|ser)\s+(?:shorter|cort[ao])\s+(?:than|que)\s+"
            rf"\b{_PATTERN_SIDE}\b",
            _FLAGS,
        ),
    ),
    (
        LengthPolicy.VALUE_MAY_BE_LONGER.value,
        re.compile(
            rf"\b{_VALUE_SIDE}\b[^.;]{{0,40}}?\b{_PERMISSION}\b[^.;]{{0,30}}?"
            rf"\b(?:carry|contain|have|include|be)\b[^.;]{{0,30}}?\b{_EXTRA}\b"
            rf"[^.;]{{0,30}}?\b(?:in\s+front\s+of|before|leading)\b[^.;]{{0,30}}?"
            rf"\b(?:the\s+)?{_PATTERN_SIDE}\b",
            _FLAGS,
        ),
    ),
)
_UNCONSTRAINED_LENGTH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:any\s+length|length\s+is\s+not\s+(?:restricted|constrained|limited)|"
        r"unrestricted\s+length|regardless\s+of\s+length)\b",
        _FLAGS,
    ),
    re.compile(
        r"\b(?:cualquier\s+longitud|longitud\s+(?:libre|sin\s+restricci[oó]n)|"
        r"sin\s+restricci[oó]n\s+de\s+longitud|independientemente\s+de\s+la\s+longitud)\b",
        _FLAGS,
    ),
)


def match_length_frame(text: str) -> LengthObservation | None:
    """Marco de paráfrasis -> política de longitud direccional (o None)."""
    raw = _norm(text)
    if not raw:
        return None
    for policy, pattern in _LENGTH_FRAMES:
        match = pattern.search(raw)
        if not match:
            continue
        if policy == LengthPolicy.PATTERN_MAY_BE_LONGER.value:
            left, right = "pattern", "value"
        else:
            left, right = "value", "pattern"
        return LengthObservation(
            policy=policy,
            directional=True,
            left_operand=left,
            right_operand=right,
            matched_text=_snippet(raw, match),
            explicit=True,
        )
    return None


def _operand_role(text: str) -> str:
    lowered = _norm(text).lower()
    if any(word in lowered for word in _VALUE_WORDS):
        return "value"
    if any(word in lowered for word in _PATTERN_WORDS):
        return "pattern"
    return ""


def classify_length_policy(text: str) -> LengthObservation:
    """Política de longitud explícita; mención sin política -> UNKNOWN.

    Nunca convierte "length" en EXACT. La dirección
    (VALUE_MAY_BE_LONGER vs PATTERN_MAY_BE_LONGER) se preserva.
    """
    raw = _norm(text)
    if not raw:
        return LengthObservation()

    for pattern in _EXACT_LENGTH_PATTERNS:
        match = pattern.search(raw)
        if match:
            value = _parse_number_token(match.groupdict().get("n") or "")
            return LengthObservation(
                policy=LengthPolicy.EXACT.value,
                value=value,
                boundary=BoundaryKind.INCLUSIVE.value,
                matched_text=_snippet(raw, match),
                explicit=True,
            )

    for direction, forced, pattern in _ASYMMETRIC_LENGTH_PATTERNS:
        match = pattern.search(raw)
        if not match:
            continue
        left = _norm(match.group("left"))
        right = _norm(match.group("right"))
        if forced == "pattern":
            policy = (
                LengthPolicy.PATTERN_MAY_BE_LONGER.value
                if direction == "longer"
                else LengthPolicy.PATTERN_MAY_BE_SHORTER.value
            )
        else:
            left_role = _operand_role(left)
            right_role = _operand_role(right)
            if left_role == "value" and right_role == "pattern":
                policy = (
                    LengthPolicy.VALUE_MAY_BE_LONGER.value
                    if direction == "longer"
                    else LengthPolicy.VALUE_MAY_BE_SHORTER.value
                )
            elif left_role == "pattern" and right_role == "value":
                policy = (
                    LengthPolicy.PATTERN_MAY_BE_LONGER.value
                    if direction == "longer"
                    else LengthPolicy.PATTERN_MAY_BE_SHORTER.value
                )
            else:
                return LengthObservation(
                    policy=LengthPolicy.UNKNOWN.value,
                    directional=False,
                    left_operand=left,
                    right_operand=right,
                    matched_text=_snippet(raw, match),
                    explicit=True,
                    mention_only=False,
                    missing_premises=("length_operand_role",),
                    note="dirección declarada sin operandos identificables",
                )
        return LengthObservation(
            policy=policy,
            directional=True,
            left_operand=left,
            right_operand=right,
            matched_text=_snippet(raw, match),
            explicit=True,
        )

    # Las políticas numéricas de longitud SOLO aplican con contexto de longitud
    # explícito ("maximum length of 5", "at least 3 characters"): un "máximo de
    # 5 días" es una cantidad, no una política de longitud.
    has_length_context = bool(
        _LENGTH_MENTION_RE.search(raw)
        or re.search(
            r"\b(characters?|positions?|digits?|letters?|caracteres?|posiciones?|"
            r"d[ií]gitos?|letras?)\b",
            raw,
            _FLAGS,
        )
    )
    if not has_length_context:
        # Marcos de paráfrasis sin unidad explícita ("can be longer than").
        frame = match_length_frame(raw)
        if frame is not None:
            return frame
        mention = _LENGTH_MENTION_RE.search(raw)
        if mention:
            return LengthObservation(
                policy=LengthPolicy.UNKNOWN.value,
                mention_only=True,
                matched_text=_snippet(raw, mention),
                explicit=False,
                missing_premises=("length_policy",),
                note="se menciona longitud sin establecer política",
            )
        return LengthObservation()

    range_match = _first_match(raw, _RANGE_LENGTH_PATTERNS)
    if range_match:
        low = _parse_number_token(range_match.group("n"))
        high = int(range_match.group("m"))
        if low is not None:
            return LengthObservation(
                policy=LengthPolicy.RANGE.value,
                value=min(low, high),
                upper=max(low, high),
                boundary=BoundaryKind.INCLUSIVE.value,
                matched_text=_snippet(raw, range_match),
                explicit=True,
            )

    min_match = _first_match(raw, _MIN_LENGTH_PATTERNS)
    if min_match:
        value = _parse_number_token(min_match.group("n"))
        if value is not None:
            return LengthObservation(
                policy=LengthPolicy.MIN_LENGTH.value,
                value=value,
                boundary=BoundaryKind.INCLUSIVE.value,
                matched_text=_snippet(raw, min_match),
                explicit=True,
            )

    max_match = _first_match(raw, _MAX_LENGTH_PATTERNS)
    if max_match:
        value = _parse_number_token(max_match.group("n"))
        if value is not None:
            return LengthObservation(
                policy=LengthPolicy.MAX_LENGTH.value,
                value=value,
                boundary=BoundaryKind.INCLUSIVE.value,
                matched_text=_snippet(raw, max_match),
                explicit=True,
            )

    # Marcos de paráfrasis: recién DESPUÉS de las políticas numéricas, para que
    # "no more than 12 characters" sea MAX_LENGTH y no "más caracteres".
    frame = match_length_frame(raw)
    if frame is not None:
        return frame

    if _first_match(raw, _UNCONSTRAINED_LENGTH_PATTERNS):
        match = _first_match(raw, _UNCONSTRAINED_LENGTH_PATTERNS)
        return LengthObservation(
            policy=LengthPolicy.UNCONSTRAINED.value,
            matched_text=_snippet(raw, match) if match else "",
            explicit=True,
        )

    mention = _LENGTH_MENTION_RE.search(raw)
    if mention:
        return LengthObservation(
            policy=LengthPolicy.UNKNOWN.value,
            mention_only=True,
            matched_text=_snippet(raw, mention),
            explicit=False,
            missing_premises=("length_policy",),
            note="se menciona longitud sin establecer política",
        )
    return LengthObservation()


# --- Matching ---------------------------------------------------------------

_MATCH_TABLE: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        MatchOperator.FIXED_POSITION.value,
        re.compile(
            r"\b(?:in|at|en)\s+(?:the\s+)?(?:position|posici[oó]n)\s+(?P<n>\d+)\b",
            _FLAGS,
        ),
    ),
    (
        MatchOperator.POSITIONAL.value,
        re.compile(
            r"(?:positional|posicional|matching\s+is\s+positional|"
            r"left[\s-]*to[\s-]*right|de\s+izquierda\s+a\s+derecha|same\s+position|"
            r"misma\s+posici[oó]n|by\s+position|por\s+posici[oó]n|in\s+order|en\s+orden)",
            _FLAGS,
        ),
    ),
    (
        MatchOperator.PREFIX.value,
        re.compile(
            r"(?:prefix|prefijo|at\s+the\s+(?:start|beginning)|al\s+(?:inicio|principio)|"
            r"from\s+the\s+(?:start|beginning)|desde\s+el\s+(?:inicio|principio)|"
            r"left[- ]?most|m[aá]s\s+a\s+la\s+izquierda|"
            r"from\s+the\s+left|comienza\s+(?:al|en\s+el)\s+inicio)",
            _FLAGS,
        ),
    ),
    (
        MatchOperator.SUFFIX.value,
        re.compile(
            r"(?:suffix|sufijo|at\s+the\s+end|al\s+final|from\s+the\s+end|"
            r"desde\s+el\s+final|right[- ]?most|m[aá]s\s+a\s+la\s+derecha|"
            r"from\s+the\s+right(?:\s+edge)?|starts?\s+from\s+the\s+right|"
            r"right\s+edge|desde\s+la\s+derecha)",
            _FLAGS,
        ),
    ),
    (
        MatchOperator.STARTS_WITH.value,
        re.compile(r"\b(starts?\s+with|begins?\s+with|comienza\s+con|empieza\s+con)\b", _FLAGS),
    ),
    (
        MatchOperator.ENDS_WITH.value,
        re.compile(r"\b(ends?\s+with|finishes?\s+with|termina\s+con|finaliza\s+con)\b", _FLAGS),
    ),
    (
        MatchOperator.CONTAINS.value,
        re.compile(r"\b(contains?|includes?|contiene|incluye|contengan)\b", _FLAGS),
    ),
    (
        MatchOperator.LITERAL.value,
        re.compile(
            r"(?:literal(?:ly)?|exact(?:ly)?|fixed\s+character|car[aá]cter\s+fijo|"
            r"must\s+match|coincidencia\s+exacta|debe\s+coincidir)",
            _FLAGS,
        ),
    ),
    (
        MatchOperator.WILDCARD.value,
        re.compile(
            r"\b(wildcards?|comod[ií]n(?:es)?)\b",
            _FLAGS,
        ),
    ),
)

_ALPHABET_TABLE: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "alphanumeric",
        re.compile(
            r"\b(alpha[- ]?numeric|alfanum[eé]ric[oa]s?|letter\s+or\s+digit|"
            r"letra\s+o\s+d[ií]gito)\b",
            _FLAGS,
        ),
    ),
    ("digit", re.compile(r"\b(digits?|numeric|num[eé]ric[oa]s?|d[ií]gitos?)\b", _FLAGS)),
    ("letter", re.compile(r"\b(letters?|alphabetic|alfab[eé]tic[oa]s?|letras?)\b", _FLAGS)),
    ("space", re.compile(r"\b(spaces?|blanks?|espacios?|en\s+blanco)\b", _FLAGS)),
    (
        "any_char",
        re.compile(
            r"\b(any\s+character|cualquier\s+car[aá]cter|any\s+position|"
            r"cualquier\s+posici[oó]n)\b",
            _FLAGS,
        ),
    ),
)

_PROHIBITED_ALPHABET_RE = re.compile(
    r"\b(?:must\s+not|cannot|may\s+not|is\s+not\s+allowed\s+to|no\s+puede|"
    r"prohibido\s+(?:el\s+uso\s+de)?|sin)\s+"
    r"(?:contain|include|use|tener|contener|incluir|usar)?\s*"
    r"(?P<what>[a-záéíóúñ][a-záéíóúñ\s]{2,40})",
    _FLAGS,
)


def classify_match(text: str) -> MatchObservation:
    """Operador de matching + case + alfabeto, con su texto exacto."""
    raw = _norm(text)
    operator = MatchOperator.UNKNOWN.value
    matched_text = ""
    fixed_position: int | None = None
    # "may contain more characters than" / paráfrasis de longitud / política
    # numérica explícita: no es matching por contains.
    length_like = (
        any(pattern.search(raw) for _, _, pattern in _ASYMMETRIC_LENGTH_PATTERNS)
        or match_length_frame(raw) is not None
        or classify_length_policy(raw).is_policy
    )
    for candidate, pattern in _MATCH_TABLE:
        if candidate == MatchOperator.CONTAINS.value and length_like:
            continue
        match = pattern.search(raw)
        if match:
            operator = candidate
            matched_text = _snippet(raw, match)
            if candidate == MatchOperator.FIXED_POSITION.value:
                fixed_position = int(match.group("n"))
            break

    alphabet = ""
    for kind, pattern in _ALPHABET_TABLE:
        match = pattern.search(raw)
        if match:
            alphabet = kind
            matched_text = matched_text or _snippet(raw, match)
            break

    prohibited = ""
    prohibited_match = _PROHIBITED_ALPHABET_RE.search(raw)
    if prohibited_match:
        candidate_objects = _norm(prohibited_match.group("what")).lower()
        if re.search(
            r"\b(spaces?|blanks?|special\s+characters?|letters?|digits?|punctuation|"
            r"symbols?|accents?|diacritics?|espacios?|caracteres\s+especiales|letras?|"
            r"d[ií]gitos?|s[ií]mbolos?|puntuaci[oó]n|acentos?)\b",
            candidate_objects,
        ):
            prohibited = candidate_objects[:60]

    case_sensitive: bool | None = None
    case_match = re.search(
        r"\b(case[- ]sensitive|case\s+matters|distingue\s+may[uú]sculas(?:\s+y\s+min[uú]sculas)?)\b",
        raw,
        _FLAGS,
    )
    if case_match:
        case_sensitive = True
        matched_text = matched_text or _snippet(raw, case_match)
    else:
        case_match = re.search(
            r"\b(case[- ]insensitive|case\s+insensitive|ignores?\s+case|"
            r"no\s+distingue\s+may[uú]sculas)\b",
            raw,
            _FLAGS,
        )
        if case_match:
            case_sensitive = False
            matched_text = matched_text or _snippet(raw, case_match)

    literal = bool(
        re.search(
            r"(?:literal(?:ly)?|exact(?:ly)?|fixed\s+character|car[aá]cter\s+fijo|"
            r"must\s+match|coincidencia\s+exacta|debe\s+coincidir)",
            raw,
            _FLAGS,
        )
    )

    optional_positions_match = re.search(
        r"\b(optional|opcional(?:es)?)\s+(?:positions?|posiciones?)\b", raw, _FLAGS
    )
    repeated_positions_match = re.search(
        r"\b(repeat(?:ed)?|repetid[ao]s?)\s+(?:positions?|posiciones?|"
        r"characters?|caracteres?)\b",
        raw,
        _FLAGS,
    )
    separator_match = re.search(
        r"\b(separator|separador|hyphen|gu[ií]on|dash|space|espacio)\b", raw, _FLAGS
    )
    normalization_match = re.search(
        r"\b(uppercase|upper[- ]case|may[uú]sculas|normaliz\w*|trim(?:med)?|"
        r"strip(?:ped)?)\b",
        raw,
        _FLAGS,
    )

    return MatchObservation(
        operator=operator,
        literal=literal,
        case_sensitive=case_sensitive,
        alphabet=alphabet,
        prohibited_alphabet=prohibited,
        fixed_position=fixed_position,
        optional_positions=bool(optional_positions_match),
        repeated_positions=bool(repeated_positions_match),
        separator=(separator_match.group(0).lower() if separator_match else ""),
        normalization=(
            normalization_match.group(0).lower() if normalization_match else ""
        ),
        matched_text=matched_text,
        explicit=operator != MatchOperator.UNKNOWN.value or bool(alphabet),
    )


# --- Lógica -----------------------------------------------------------------

_LOGIC_TABLE: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        LogicOperator.IF_AND_ONLY_IF.value,
        re.compile(r"\b(if\s+and\s+only\s+if|si\s+y\s+solo\s+si|ssi)\b", _FLAGS),
    ),
    (
        LogicOperator.ONLY_IF.value,
        re.compile(r"\b(only\s+if|only\s+when|solo\s+si|solamente\s+si|s[oó]lo\s+cuando|únicamente\s+si)\b", _FLAGS),
    ),
    (
        LogicOperator.UNLESS.value,
        re.compile(
            r"\b(unless|except\s+(?:when|if|where|for)|salvo\s+que|excepto\s+(?:cuando|si|para)|"
            r"a\s+menos\s+que|no\s+aplica\s+(?:cuando|si|para))\b",
            _FLAGS,
        ),
    ),
    (
        LogicOperator.OVERRIDE.value,
        re.compile(r"\b(overrides?|prevalece\s+sobre|tiene\s+prioridad\s+sobre|override)\b", _FLAGS),
    ),
    (
        LogicOperator.PRECEDENCE.value,
        re.compile(r"\b(precedence|prioridad|en\s+caso\s+de\s+conflicto|takes?\s+precedence)\b", _FLAGS),
    ),
    (
        LogicOperator.DEFAULT.value,
        re.compile(r"\b(by\s+default|defaults?\s+to|por\s+defecto|salvo\s+indicaci[oó]n\s+contraria)\b", _FLAGS),
    ),
    (
        LogicOperator.FALLBACK.value,
        re.compile(r"\b(fallback|si\s+no\s+aplica|en\s+su\s+defecto|otherwise)\b", _FLAGS),
    ),
    (
        LogicOperator.IMPLIES.value,
        re.compile(r"\b(implies|implica|therefore|por\s+lo\s+tanto)\b", _FLAGS),
    ),
    (
        LogicOperator.NOT.value,
        re.compile(r"\b(\bnot\b|\bno\b|\bnunca\b|never)\b", _FLAGS),
    ),
    (
        LogicOperator.AND.value,
        re.compile(r"\b(and|y|as[ií]\s+como|adem[aá]s\s+de)\b", _FLAGS),
    ),
    (
        LogicOperator.OR.value,
        re.compile(r"\b(or|o|either|u)\b", _FLAGS),
    ),
)


def classify_logic(text: str) -> tuple[LogicObservation, ...]:
    """Conectores lógicos presentes, con su texto exacto."""
    raw = _norm(text)
    found: list[LogicObservation] = []
    for operator, pattern in _LOGIC_TABLE:
        match = pattern.search(raw)
        if match:
            found.append(
                LogicObservation(
                    operator=operator,
                    matched_text=_snippet(raw, match),
                )
            )
    return tuple(found)


_QUANTIFIER_TABLE: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        QuantifierKind.EXACTLY_ONE.value,
        re.compile(r"\b(exactly\s+one|exactamente\s+uno?|uno\s+y\s+solo\s+uno)\b", _FLAGS),
    ),
    (
        QuantifierKind.EXACTLY_N.value,
        re.compile(r"\bexactly\s+\d+\b|\bexactamente\s+\d+\b", _FLAGS),
    ),
    (
        QuantifierKind.AT_LEAST_ONE.value,
        re.compile(
            r"\b(at\s+least\s+one|al\s+menos\s+uno?|como\s+m[ií]nimo\s+uno?)\b",
            _FLAGS,
        ),
    ),
    (QuantifierKind.NONE.value, re.compile(r"\b(no\s+one|none|ning[uú]n[oa]?|nadie)\b", _FLAGS)),
    (QuantifierKind.ALL.value, re.compile(r"\b(all|every|each|todos?|cada|toda?s?)\b", _FLAGS)),
    (QuantifierKind.ANY.value, re.compile(r"\b(any|some|cualquier|cualquiera|algun[oa]?)\b", _FLAGS)),
)


def classify_quantifier(text: str) -> str:
    raw = _norm(text)
    for kind, pattern in _QUANTIFIER_TABLE:
        if pattern.search(raw):
            return kind
    return QuantifierKind.UNKNOWN.value


# --- Cantidades/rangos -------------------------------------------------------

_QUANTITY_RE = re.compile(
    r"\b(?P<min>at\s+least|minimum(?:\s+of)?|no\s+less\s+than|al\s+menos|m[ií]nimo(?:\s+de)?)"
    r"(?:\s+[a-záéíóúñ]{2,15}){0,3}\s+(?P<n>-?\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>%|[a-záéíóúñ]{1,12})?",
    _FLAGS,
)
_QUANTITY_MAX_RE = re.compile(
    r"\b(?P<max>at\s+most|maximum(?:\s+of)?|no\s+more\s+than|como\s+m[aá]ximo|m[aá]ximo(?:\s+de)?)"
    r"(?:\s+[a-záéíóúñ]{2,15}){0,3}\s+(?P<n>-?\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>%|[a-záéíóúñ]{1,12})?",
    _FLAGS,
)
_QUANTITY_RANGE_RE = re.compile(
    r"\b(?:between|entre)\s+(?P<n>-?\d+(?:[.,]\d+)?)\s*(?:and|y)\s*"
    r"(?P<m>-?\d+(?:[.,]\d+)?)\s*(?P<unit>%|[a-záéíóúñ]{1,12})?",
    _FLAGS,
)

#: Unidades que son en realidad el dominio del conteo (no exigen unidad externa).
COUNT_UNITS = frozenset(
    {
        "characters", "character", "positions", "position", "digits", "digit",
        "letters", "letter", "caracteres", "carácter", "posiciones", "posición",
        "dígitos", "dígito", "letras", "letra",
    }
)


def _clean_unit(raw: str) -> str:
    unit = _norm(raw or "").lower()
    return "" if unit in _UNIT_STOPWORDS else unit


def classify_quantities(text: str) -> tuple[QuantityObservation, ...]:
    """Rangos/cantidades numéricas con límites y unidad declarados."""
    raw = _norm(text)
    found: list[QuantityObservation] = []
    range_match = _QUANTITY_RANGE_RE.search(raw)
    if range_match:
        range_boundary = classify_boundary(raw)
        found.append(
            QuantityObservation(
                value=float(range_match.group("n").replace(",", ".")),
                upper=float(range_match.group("m").replace(",", ".")),
                unit=_clean_unit(range_match.group("unit")),
                boundary=range_boundary,
                matched_text=_snippet(raw, range_match),
            )
        )
    min_match = _QUANTITY_RE.search(raw)
    if min_match:
        found.append(
            QuantityObservation(
                value=float(min_match.group("n").replace(",", ".")),
                unit=_clean_unit(min_match.group("unit")),
                boundary=BoundaryKind.INCLUSIVE.value,
                matched_text=_snippet(raw, min_match),
            )
        )
    max_match = _QUANTITY_MAX_RE.search(raw)
    if max_match:
        found.append(
            QuantityObservation(
                upper=float(max_match.group("n").replace(",", ".")),
                unit=_clean_unit(max_match.group("unit")),
                boundary=BoundaryKind.INCLUSIVE.value,
                matched_text=_snippet(raw, max_match),
            )
        )
    return tuple(found)


# --- Tiempo -----------------------------------------------------------------

_TEMPORAL_TABLE: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        TemporalRelation.EFFECTIVE_FROM.value,
        re.compile(
            r"\b(effective\s+(?:from|as\s+of)\b|effective\s+(?=[a-záéíóúñ]+\s+\d{4})|"
            r"valid\s+from|vigente\s+(?:desde|a\s+partir)|v[aá]lid[oa]\s+desde)\b",
            _FLAGS,
        ),
    ),
    (
        TemporalRelation.EXPIRES.value,
        re.compile(
            r"\b(expires?|expiration|valid\s+(?:to|until)|hasta\s+el|vence|"
            r"vencimiento|vigencia\s+hasta)\b",
            _FLAGS,
        ),
    ),
    (
        TemporalRelation.FROM_TO.value,
        re.compile(r"\b(from\s+.+?\s+to\s+|desde\s+.+?\s+hasta\s+)\b", _FLAGS),
    ),
    (
        TemporalRelation.DURATION.value,
        re.compile(
            r"\b(within|dentro\s+de|no\s+m[aá]s\s+de|durante)\s+\d+\s*"
            r"(days?|d[ií]as?|weeks?|semanas?|months?|meses?|hours?|horas?)\b",
            _FLAGS,
        ),
    ),
    (
        TemporalRelation.SIMULTANEOUS.value,
        re.compile(r"\b(simultaneous(?:ly)?|at\s+the\s+same\s+time|simult[aá]neamente|al\s+mismo\s+tiempo)\b", _FLAGS),
    ),
    (
        TemporalRelation.BEFORE.value,
        re.compile(
            r"\b(?:before|prior\s+to|on\s+or\s+before|antes\s+de|previo\s+a)\s+"
            r"(?=\d|the\s+\d|el\s+\d|"
            r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
            r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
            r"dec(?:ember)?|enero|febrero|marzo|abril|mayo|junio|julio|"
            r"agosto|septiembre|octubre|noviembre|diciembre)",
            _FLAGS,
        ),
    ),
    (
        TemporalRelation.AFTER.value,
        re.compile(
            r"\b(?:after|on\s+or\s+after|posterior\s+a|despu[eé]s\s+de)\s+"
            r"(?=\d|the\s+\d|el\s+\d|"
            r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
            r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
            r"dec(?:ember)?|enero|febrero|marzo|abril|mayo|junio|julio|"
            r"agosto|septiembre|octubre|noviembre|diciembre)",
            _FLAGS,
        ),
    ),
)

_MONTHS = (
    r"january|february|march|april|may|june|july|august|september|october|"
    r"november|december|enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
    r"septiembre|octubre|noviembre|diciembre"
)

_DATE_LIKE_RE = re.compile(
    r"(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{4}-\d{2}-\d{2}|"
    rf"\d{{1,2}}\s+(?:de\s+)?(?:{_MONTHS})(?:\s+\d{{4}})?|"
    rf"(?:{_MONTHS})\s+\d{{1,2}},?\s+\d{{4}}|"
    rf"(?:{_MONTHS})\s+\d{{4}})",
    _FLAGS,
)


def classify_temporal(text: str) -> TemporalObservation:
    """Relación temporal con su texto exacto (el parseo de fecha viene aparte)."""
    raw = _norm(text)
    for relation, pattern in _TEMPORAL_TABLE:
        match = pattern.search(raw)
        if not match:
            continue
        value = ""
        date_match = _DATE_LIKE_RE.search(raw)
        if date_match:
            value = date_match.group(0)
        return TemporalObservation(
            relation=relation,
            value=value,
            matched_text=_snippet(raw, match),
        )
    return TemporalObservation()


def classify_boundary(text: str) -> str:
    """Inclusividad declarada. Sin marcador -> UNKNOWN (jamás se asume)."""
    raw = _norm(text)
    if re.search(r"\b(inclusive|inclusively|including|or\s+less|or\s+more|"
                 r"inclusive|incluyendo|inclusive|hasta\s+e\s+incluyendo)\b", raw, _FLAGS):
        return BoundaryKind.INCLUSIVE.value
    if re.search(r"\b(exclusive|exclusively|not\s+including|excluding|"
                 r"excluyente|sin\s+incluir|no\s+incluye)\b", raw, _FLAGS):
        return BoundaryKind.EXCLUSIVE.value
    return BoundaryKind.UNKNOWN.value


# -----------------------------------------------------------------------------
# API principal
# -----------------------------------------------------------------------------


def analyze_language(text: str) -> LanguageSignals:
    """Todas las señales lingüísticas de un enunciado, en una pasada."""
    raw = _norm(text)
    if not raw:
        return LanguageSignals()
    length = classify_length_policy(raw)
    modality = classify_modality(raw)
    if modality.modality == ModalityKind.MUST_NOT.value and length.policy != LengthPolicy.UNKNOWN.value:
        # "must not exceed the maximum" ya es negación; la política se conserva.
        pass
    return LanguageSignals(
        modality=modality,
        negation=classify_negation(raw),
        comparisons=classify_comparison(raw),
        length=length,
        match=classify_match(raw),
        logic=classify_logic(raw),
        quantifier=classify_quantifier(raw),
        quantities=classify_quantities(raw),
        temporal=classify_temporal(raw),
    )


def is_normative(text: str, *, min_length: int = 0) -> bool:
    """¿El enunciado tiene fuerza normativa propia?"""
    if min_length and len(_norm(text)) < min_length:
        return False
    signals = analyze_language(text)
    if signals.modality.normative:
        return True
    logic = {item.operator for item in signals.logic}
    return bool(
        logic
        & {
            LogicOperator.ONLY_IF.value,
            LogicOperator.IF_AND_ONLY_IF.value,
            LogicOperator.UNLESS.value,
        }
    )


def is_example(text: str) -> bool:
    """Marcadores de ejemplo: no es regla por sí solo."""
    raw = _norm(text)
    return bool(
        re.search(
            r"\b(for\s+example|e\.g\.|example|examples?|por\s+ejemplo|ejemplo|"
            r"such\s+as|tales?\s+como|illustration|ilustraci[oó]n)\b",
            raw,
            _FLAGS,
        )
    )


def is_definition(text: str) -> bool:
    raw = _norm(text)
    return bool(
        re.search(
            r"\b(means|represents?|is\s+defined\s+as|defined\s+as|stands?\s+for|"
            r"denotes?|significa|representa|se\s+define\s+como|equivale\s+a|"
            r"corresponde\s+a|es\s+el|es\s+la)\b",
            raw,
            _FLAGS,
        )
    )


def operator_for_symbol(symbol: str) -> str | None:
    """Símbolo textual de comparación ('>=') -> operador canónico."""
    mapping = {
        "=": ComparisonOperator.EQ.value,
        "==": ComparisonOperator.EQ.value,
        "!=": ComparisonOperator.NE.value,
        "<>": ComparisonOperator.NE.value,
        ">": ComparisonOperator.GT.value,
        ">=": ComparisonOperator.GTE.value,
        "=>": ComparisonOperator.GTE.value,
        "<": ComparisonOperator.LT.value,
        "<=": ComparisonOperator.LTE.value,
        "=<": ComparisonOperator.LTE.value,
    }
    return mapping.get(str(symbol or "").strip())


def numeric_length_policy(policy: str) -> bool:
    return str(policy or "") in _NUMERIC_LENGTH_POLICIES


def asymmetric_length_policy(policy: str) -> bool:
    return str(policy or "") in _ASYMMETRIC_LENGTH_POLICIES


__all__ = [
    "BoundaryKind",
    "ClaimLayer",
    "ComparisonOperator",
    "ComparisonObservation",
    "COMPARISON_TO_OPERATION",
    "COUNT_UNITS",
    "EXECUTABLE_STATES",
    "ExtractionMethod",
    "LanguageSignals",
    "LengthObservation",
    "LengthPolicy",
    "LogicObservation",
    "LogicOperator",
    "MatchObservation",
    "MatchOperator",
    "ModalityKind",
    "ModalityObservation",
    "MODALITY_STRENGTH",
    "NORMATIVE_MODALITIES",
    "NegationObservation",
    "Polarity",
    "QuantifierKind",
    "QuantityObservation",
    "RuleKind",
    "RULE_SEMANTICS_VERSION",
    "TemporalObservation",
    "TemporalRelation",
    "VerificationState",
    "analyze_language",
    "asymmetric_length_policy",
    "classify_boundary",
    "classify_comparison",
    "classify_length_policy",
    "classify_logic",
    "classify_match",
    "classify_modality",
    "classify_negation",
    "classify_quantifier",
    "classify_quantities",
    "classify_temporal",
    "is_definition",
    "is_example",
    "is_normative",
    "numeric_length_policy",
    "operator_for_symbol",
]
