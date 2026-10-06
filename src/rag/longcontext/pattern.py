# =============================================================================
# Pattern grammar — instancia de patrón vs gramática documentada (§5, §6, §14)
# =============================================================================
# El error que esto corrige: exigir que el documento contenga la máscara
# concreta «&&&F». La documentación debe definir la GRAMÁTICA:
#
#   «& representa una posición alfanumérica»
#   «el matching es posicional, de izquierda a derecha»
#   «el carácter literal debe coincidir en su posición»
#
# Con esa gramática, una instancia del usuario («&&&F», «AAA-###») se
# INTERPRETA y se aplica: el patrón concreto no exige presencia literal; sus
# SEMÁNTICAS sí. Genérico: sirve para fare basis, códigos de producto,
# edades/rangos y cualquier lenguaje de comodines.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable, Sequence

from src.core.domain.rule_semantics import (
    BoundaryKind,
    LengthPolicy,
    classify_length_policy,
    numeric_length_policy,
)

PATTERN_VERSION = "pattern-grammar-2"

#: Alfabeto de comodines soportado (ampliable por alias documental).
WILDCARD_SYMBOLS: tuple[str, ...] = ("&", "*", "?", "%", "#", "$", "@", "!", "~", "^")

_SYMBOL_ALIASES: dict[str, tuple[str, ...]] = {
    "&": ("&", "ampersand", "ampersan", "y comercial", "et"),
    "*": ("*", "asterisk", "asterisco", "star"),
    "?": ("?", "question mark", "signo de interrogaci[oó]n", "question-mark"),
    "%": ("%", "percent", "porcentaje", "percentage"),
    "#": ("#", "hash", "number sign", "numeral", "almohadilla"),
    "$": ("$", "dollar", "d[oó]lar"),
    "@": ("@", "at sign", "arroba"),
    "!": ("!", "exclamation", "signo de exclamaci[oó]n"),
    "~": ("~", "tilde"),
    "^": ("^", "caret", "circunflejo"),
}

#: Verbos/predicados de definición. ES/EN.
_DEFINITION_VERBS = (
    r"represents?|means?|stands?\s+for|denotes?|indicates?|matches?|"
    r"representa|significa|equivale\s+a|denota|indica|es|son|corresponde\s+a"
)

_MEANING_KINDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "alphanumeric_position",
        (
            "alphanumeric",
            "alfanum[eé]ric",
            "letter or digit",
            "letra o d[ií]gito",
        ),
    ),
    ("digit", ("digit", "d[ií]gito", "numeric", "num[eé]ric", "number")),
    ("letter", ("letter", "letra", "alphabetic", "alfab[eé]tic")),
    ("space", ("space", "espacio", "blank", "blanco", "empty")),
    (
        "any_char",
        (
            "any character",
            "cualquier car[aá]cter",
            "any position",
            "cualquier posici[oó]n",
            "wildcard",
            "comod[ií]n",
            "any alphanumeric",
        ),
    ),
    ("literal", ("literal", "fixed", "fijo", "exact character", "car[aá]cter exacto")),
)

_POSITIONAL_RE = re.compile(
    r"(?:position(?:al|s)?|posici[oó]n(?:es)?|left[\s-]*to[\s-]*right|"
    r"de\s+izquierda\s+a\s+derecha|en\s+orden|same\s+position|"
    r"misma\s+posici[oó]n|by\s+position|por\s+posici[oó]n)",
    re.IGNORECASE,
)
_LITERAL_RE = re.compile(
    r"(?:literal(?:ly)?|exact(?:ly)?|fixed\s+character|car[aá]cter\s+fijo|"
    r"must\s+match|debe\s+coincidir|coincidencia\s+exacta)",
    re.IGNORECASE,
)
_PREFIX_RE = re.compile(
    r"(?:prefix|prefijo|at\s+the\s+(?:start|beginning)|al\s+(?:inicio|principio)|"
    r"from\s+the\s+start|desde\s+el\s+(?:inicio|principio)|leftmost|m[aá]s\s+a\s+la\s+izquierda)",
    re.IGNORECASE,
)
_SUFFIX_RE = re.compile(
    r"(?:suffix|sufijo|at\s+the\s+end|al\s+final|from\s+the\s+end|"
    r"desde\s+el\s+final|rightmost|m[aá]s\s+a\s+la\s+derecha)",
    re.IGNORECASE,
)

#: Definición de un placeholder alfabético documentado («A represents one letter»).
_LETTER_DEF_RE = re.compile(
    r"\b(?P<symbol>[A-Z])\s*(?:=|:|,|—|-)?\s*"
    rf"(?:{_DEFINITION_VERBS})\s+"
    r"(?:(?:one|a|an|un|una)\s+)?(?P<meaning>[a-záéíóúñ][^.;\n]{2,60})"
)

_MAX_EVIDENCE_CHARS = 240_000


@dataclass(frozen=True, kw_only=True)
class SymbolDefinition:
    """Definición documentada de un símbolo de patrón."""

    symbol: str
    statement: str
    meaning: str
    evidence_ref: str = ""
    confidence: float = 0.8

    def accepts(self, char: str) -> bool | None:
        """¿El significado documentado acepta este carácter? None = no aplicable."""
        if self.meaning == "alphanumeric_position":
            return char.isalnum()
        if self.meaning == "digit":
            return char.isdigit()
        if self.meaning == "letter":
            return char.isalpha()
        if self.meaning == "space":
            return char == " "
        if self.meaning == "any_char":
            return True
        if self.meaning == "literal":
            return None
        return None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "meaning": self.meaning,
            "statement": self.statement[:200],
            "evidence_ref": self.evidence_ref,
        }


@dataclass(frozen=True, kw_only=True)
class PatternSemantics:
    """Gramática documentada extraída de la evidencia (sin LLM).

    ``length_policy`` reemplaza al booleano ``length_sensitive``. Mencionar
    "length" NO establece política: sin marcador la política es UNKNOWN y el
    motor devuelve UNDETERMINED. ``length_sensitive`` se conserva deprecado y
    solo es True con evidencia explícita de igualdad/fixed/exact length.
    """

    symbol_definitions: dict[str, SymbolDefinition] = field(default_factory=dict)
    positional: bool = False
    literal: bool = False
    length_policy: str = LengthPolicy.UNKNOWN.value
    length_value: int | None = None
    length_upper: int | None = None
    length_boundary: str = ""
    anchor_side: str = ""  # start | end | "" (no declarado)
    #: Política de longitud RELATIVA al patrón ("at least the number of
    #: characters referenced in the field"): el largo de referencia es la
    #: longitud del patrón runtime, no un número declarado.
    length_relative_to_pattern: bool = False
    statements: tuple[str, ...] = ()
    version: str = PATTERN_VERSION

    def definition_for(self, symbol: str) -> SymbolDefinition | None:
        return self.symbol_definitions.get(symbol)

    def matching_policy_known(self) -> bool:
        return bool(self.positional or self.literal)

    @property
    def length_sensitive(self) -> bool:
        """DEPRECADO. True solo con evidencia explícita de igualdad de largo."""
        return self.length_policy == LengthPolicy.EXACT.value

    @property
    def length_policy_known(self) -> bool:
        return self.length_policy not in ("", LengthPolicy.UNKNOWN.value)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "symbols": {
                symbol: definition.to_public_dict()
                for symbol, definition in self.symbol_definitions.items()
            },
            "positional": self.positional,
            "literal": self.literal,
            "length_policy": self.length_policy,
            "length_value": self.length_value,
            "length_upper": self.length_upper,
            "length_boundary": self.length_boundary,
            "length_sensitive": self.length_sensitive,
            "length_relative_to_pattern": self.length_relative_to_pattern,
            "anchor_side": self.anchor_side,
            "statements": list(self.statements[:6]),
        }


@dataclass(frozen=True, kw_only=True)
class PatternToken:
    index: int
    char: str
    kind: str  # literal | wildcard | unknown
    symbol: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        return {"index": self.index, "char": self.char, "kind": self.kind}


@dataclass(frozen=True, kw_only=True)
class PatternInstance:
    """Instancia concreta de un patrón aportada por el usuario/sistema."""

    raw_value: str
    tokens: tuple[PatternToken, ...]
    symbols: tuple[str, ...]
    literal_positions: tuple[tuple[int, str], ...]
    length: int
    user_supplied: bool = True
    requires_semantics: tuple[str, ...] = ()
    inferred_grammar: str = ""
    version: str = PATTERN_VERSION

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "raw_value": self.raw_value,
            "length": self.length,
            "symbols": list(self.symbols),
            "literal_positions": [
                {"position": position, "char": char}
                for position, char in self.literal_positions
            ],
            "tokens": [token.to_public_dict() for token in self.tokens[:32]],
            "user_supplied": self.user_supplied,
            "requires_semantics": list(self.requires_semantics),
            "inferred_grammar": self.inferred_grammar,
        }


class MatchStatus(StrEnum):
    MATCH = "MATCH"
    NO_MATCH = "NO_MATCH"
    UNDETERMINED = "UNDETERMINED"


@dataclass(frozen=True, kw_only=True)
class PositionalMatchResult:
    """Resultado determinista de aplicar una gramática a un valor."""

    status: str
    value: str
    pattern: str
    checked_positions: int = 0
    mismatches: tuple[dict[str, Any], ...] = ()
    missing_premises: tuple[str, ...] = ()
    premises_used: tuple[str, ...] = ()
    operation: str = "POSITIONAL_MATCH"
    reason: str = ""

    @property
    def derived(self) -> bool:
        return self.status in (MatchStatus.MATCH.value, MatchStatus.NO_MATCH.value)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "value": self.value[:120],
            "pattern": self.pattern[:120],
            "operation": self.operation,
            "checked_positions": self.checked_positions,
            "mismatches": [dict(item) for item in self.mismatches[:8]],
            "missing_premises": list(self.missing_premises[:8]),
            "premises_used": list(self.premises_used[:8]),
            "reason": self.reason,
        }


# -----------------------------------------------------------------------------
# Extracción de gramática desde evidencia
# -----------------------------------------------------------------------------


def _evidence_texts(items: Iterable[Any]) -> list[str]:
    texts: list[str] = []
    for item in items or ():
        content = getattr(item, "content", None)
        if content is None and isinstance(item, str):
            content = item
        text = str(content or "")
        if text.strip():
            texts.append(text)
    return texts


def _evidence_ref(item: Any, index: int) -> str:
    ref = str(getattr(item, "evidence_id", "") or "")
    return ref or f"E{index + 1}"


def _normalize_meaning(raw: str) -> str:
    text = (raw or "").lower()
    for kind, markers in _MEANING_KINDS:
        if any(re.search(marker, text) for marker in markers):
            return kind
    return "other"


def _symbol_pattern(symbol: str) -> str:
    aliases = _SYMBOL_ALIASES.get(symbol, (symbol,))
    return "|".join(re.escape(alias) for alias in aliases)


def _definition_regex(symbol: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?:[\"'«]?\s*(?:the\s+|el\s+|la\s+|símbolo\s+|symbol\s+|car[aá]cter\s+)?"
        rf"(?:{_symbol_pattern(symbol)})[\"'»]?\s*(?:=|:|,|—|-)?\s*"
        rf"(?:{_DEFINITION_VERBS})\s+)"
        rf"(?P<meaning>[^.;\n]{{3,120}})",
        re.IGNORECASE,
    )


def extract_pattern_semantics(
    items: Iterable[Any] | str,
    *,
    evidence_refs: Sequence[str] | None = None,
) -> PatternSemantics:
    """Extrae la gramática de patrón documentada en la evidencia.

    Acepta ítems con `.content` y `.evidence_id` o texto plano. Determinista:
    regex de definición por símbolo + política de matching/longitud/sufijo.
    """
    if isinstance(items, str):
        texts = [items] if items.strip() else []
        refs = list(evidence_refs or [])
    else:
        item_list = list(items or ())
        texts = _evidence_texts(item_list)
        refs = [
            str(ref) for ref in (evidence_refs or [_evidence_ref(item, i) for i, item in enumerate(item_list)])
        ]
    joined = "\n".join(texts)[:_MAX_EVIDENCE_CHARS]
    if not joined.strip():
        return PatternSemantics()

    definitions: dict[str, SymbolDefinition] = {}
    for symbol in WILDCARD_SYMBOLS:
        match = _definition_regex(symbol).search(joined)
        if not match:
            continue
        meaning = _normalize_meaning(match.group("meaning"))
        if meaning == "other":
            continue
        statement = match.group(0).strip()
        definitions[symbol] = SymbolDefinition(
            symbol=symbol,
            statement=statement,
            meaning=meaning,
            evidence_ref=refs[0] if refs else "",
        )
    # Placeholders alfabéticos documentados («A represents one letter»): permiten
    # patrones genéricos tipo AAA-### sin hardcodear el dominio.
    for match in _LETTER_DEF_RE.finditer(joined):
        symbol = match.group("symbol")
        if symbol in definitions:
            continue
        meaning = _normalize_meaning(match.group("meaning"))
        if meaning in ("other",):
            continue
        definitions[symbol] = SymbolDefinition(
            symbol=symbol,
            statement=match.group(0).strip(),
            meaning=meaning,
            evidence_ref=refs[0] if refs else "",
        )

    positional = bool(_POSITIONAL_RE.search(joined))
    literal = bool(_LITERAL_RE.search(joined))
    length_observation = classify_length_policy(joined)
    length_policy = length_observation.policy
    # Anclaje declarado (prefijo/sufijo): el operador de matching establece que
    # el valor puede extenderse más allá del patrón en el lado opuesto.
    if length_policy == LengthPolicy.UNKNOWN.value and (positional or literal):
        if _PREFIX_RE.search(joined) or _SUFFIX_RE.search(joined):
            length_policy = LengthPolicy.VALUE_MAY_BE_LONGER.value
    anchor_side = ""
    if _PREFIX_RE.search(joined):
        anchor_side = "start"
    if _SUFFIX_RE.search(joined):
        anchor_side = "end"
    statements: list[str] = []
    for pattern in (
        _POSITIONAL_RE,
        _LITERAL_RE,
        _PREFIX_RE,
        _SUFFIX_RE,
    ):
        for match in pattern.finditer(joined[:60_000]):
            snippet = joined[max(0, match.start() - 60) : match.end() + 60].strip()
            if snippet and snippet not in statements:
                statements.append(snippet)
            break
    if (
        length_observation.matched_text
        and length_observation.explicit
        and length_observation.matched_text not in statements
    ):
        statements.insert(0, length_observation.matched_text)
    return PatternSemantics(
        symbol_definitions=definitions,
        positional=positional,
        literal=literal,
        length_policy=length_policy,
        length_value=length_observation.value,
        length_upper=length_observation.upper,
        length_boundary=length_observation.boundary,
        length_relative_to_pattern=_is_pattern_relative_length(length_observation),
        anchor_side=anchor_side,
        statements=tuple(statements[:6]),
    )


def _is_pattern_relative_length(observation: Any) -> bool:
    """La observación declara que el largo de referencia es el del patrón."""
    if observation is None:
        return False
    if str(getattr(observation, "right_operand", "") or "").lower() == "pattern":
        return True
    note = str(getattr(observation, "note", "") or "").lower()
    return (
        "additional characters may follow" in note
        or "length referenced by the pattern" in note
    )


# -----------------------------------------------------------------------------
# Instancia de patrón
# -----------------------------------------------------------------------------


def analyze_pattern_instance(
    value: str,
    *,
    user_supplied: bool = True,
    symbols: Sequence[str] = WILDCARD_SYMBOLS,
) -> PatternInstance:
    """Parte un patrón concreto en tokens y deriva sus semánticas requeridas.

    `symbols` son los caracteres que actúan como comodín (los del alfabeto
    estándar o los que la gramática documentada defina, p. ej. «A»/«#»).
    """
    from src.intelligence.query_semantics import pattern_semantic_requirements

    raw = str(value or "").strip()
    symbol_set = {str(symbol) for symbol in symbols if symbol}
    tokens: list[PatternToken] = []
    found_symbols: list[str] = []
    literal_positions: list[tuple[int, str]] = []
    for index, char in enumerate(raw):
        if char in symbol_set:
            tokens.append(PatternToken(index=index, char=char, kind="wildcard", symbol=char))
            if char not in found_symbols:
                found_symbols.append(char)
        else:
            tokens.append(PatternToken(index=index, char=char, kind="literal"))
            if char.isalnum():
                literal_positions.append((index, char))
    grammar = ""
    if found_symbols:
        grammar = "wildcard positions: " + ", ".join(found_symbols)
    return PatternInstance(
        raw_value=raw,
        tokens=tuple(tokens),
        symbols=tuple(found_symbols),
        literal_positions=tuple(literal_positions),
        length=len(raw),
        user_supplied=bool(user_supplied),
        requires_semantics=pattern_semantic_requirements(raw),
        inferred_grammar=grammar,
    )


def _instance_for(pattern: str | PatternInstance, semantics: PatternSemantics) -> PatternInstance:
    if isinstance(pattern, PatternInstance):
        return pattern
    defined = tuple(semantics.symbol_definitions.keys())
    return analyze_pattern_instance(
        str(pattern), symbols=defined if defined else WILDCARD_SYMBOLS
    )


def missing_pattern_premises(
    pattern: str | PatternInstance,
    semantics: PatternSemantics,
    *,
    value_length: int | None = None,
) -> tuple[str, ...]:
    """Premisas del dominio que faltan para interpretar el patrón.

    El símbolo concreto no es una premisa; su SIGNIFICADO sí. La longitud es
    premisa SOLO cuando el valor y el patrón tienen largos distintos y la
    evidencia no establece política (ni anclaje). Una mención de "length" no
    alcanza: la política queda UNKNOWN y se declara la premisa faltante.
    """
    instance = _instance_for(pattern, semantics)
    missing: list[str] = []
    for symbol in instance.symbols:
        definition = semantics.definition_for(symbol)
        if definition is None:
            missing.append(f"definition:symbol:{symbol}")
        elif definition.meaning == "other":
            missing.append(f"semantics:symbol:{symbol}")
    if not semantics.matching_policy_known():
        missing.append("matching_policy")
    if value_length is not None and value_length != instance.length:
        if not semantics.length_policy_known and not semantics.anchor_side:
            missing.append("length_semantics")
        elif (
            numeric_length_policy(semantics.length_policy)
            and semantics.length_value is None
            and not semantics.length_relative_to_pattern
        ):
            missing.append("length_semantics")
    return tuple(dict.fromkeys(missing))


def _length_failure(
    value: str,
    instance: PatternInstance,
    semantics: PatternSemantics,
) -> PositionalMatchResult | None:
    """NO_MATCH por política numérica de longitud; None si el largo es válido."""
    policy = semantics.length_policy
    length = len(value)
    low = semantics.length_value
    high = semantics.length_upper
    if (
        low is None
        and semantics.length_relative_to_pattern
        and policy
        in (LengthPolicy.MIN_LENGTH.value, LengthPolicy.MAX_LENGTH.value)
    ):
        low = instance.length
    inclusive = semantics.length_boundary != BoundaryKind.EXCLUSIVE.value
    violation = ""
    if policy == LengthPolicy.MIN_LENGTH.value and low is not None:
        if length < low or (length == low and not inclusive):
            violation = f"{policy} {low}"
    elif policy == LengthPolicy.MAX_LENGTH.value and low is not None:
        if length > low or (length == low and not inclusive):
            violation = f"{policy} {low}"
    elif policy == LengthPolicy.RANGE.value and low is not None and high is not None:
        if length < low or length > high:
            violation = f"{policy} {low}..{high}"
    if not violation:
        return None
    return PositionalMatchResult(
        status=MatchStatus.NO_MATCH.value,
        value=value,
        pattern=instance.raw_value,
        mismatches=(
            {
                "position": 0,
                "expected": violation,
                "got": f"length {length}",
                "reason": "length_policy_violation",
            },
        ),
        premises_used=(f"documented length policy: {violation}",),
        reason="length_policy_violation",
    )


def positional_match(
    value: str,
    pattern: str | PatternInstance,
    semantics: PatternSemantics,
    *,
    case_sensitive: bool = False,
) -> PositionalMatchResult:
    """Aplica la gramática documentada al valor del escenario (determinista).

    Reglas de honestidad:
      - sin definición de un símbolo o sin política de matching → UNDETERMINED
        (jamás se inventa el significado del comodín);
      - largos distintos sin política documentada → UNDETERMINED;
      - política asimétrica: se respeta la dirección declarada (valor más
        largo vs patrón más largo), sin convertirla en igualdad;
      - límites numéricos (min/max/rango): se aplican tal como se declararon.
    """
    instance = _instance_for(pattern, semantics)
    text = str(value or "")
    missing = missing_pattern_premises(instance, semantics, value_length=len(text))
    premises_used: list[str] = []
    for symbol in instance.symbols:
        definition = semantics.definition_for(symbol)
        if definition is not None and definition.meaning != "other":
            premises_used.append(definition.statement)
    if semantics.positional:
        premises_used.append("matching is positional")
    if semantics.literal:
        premises_used.append("literal characters must match exactly")
    if semantics.length_policy_known:
        premises_used.append(f"documented length policy: {semantics.length_policy}")
    if semantics.anchor_side:
        premises_used.append(f"the pattern applies from the {semantics.anchor_side}")

    if missing:
        return PositionalMatchResult(
            status=MatchStatus.UNDETERMINED.value,
            value=text,
            pattern=instance.raw_value,
            missing_premises=missing,
            premises_used=tuple(premises_used),
            reason="missing_domain_premises",
        )

    mismatches: list[dict[str, Any]] = []
    checked = 0

    def _check_pair(index_in_value: int, token: PatternToken) -> None:
        nonlocal checked
        if index_in_value < 0 or index_in_value >= len(text):
            mismatches.append(
                {
                    "position": token.index + 1,
                    "expected": token.char,
                    "got": "",
                    "reason": "missing_position",
                }
            )
            return
        char = text[index_in_value]
        checked += 1
        if token.kind == "literal":
            left = char if case_sensitive else char.lower()
            right = token.char if case_sensitive else token.char.lower()
            if left != right:
                mismatches.append(
                    {
                        "position": token.index + 1,
                        "expected": token.char,
                        "got": char,
                        "reason": "literal_mismatch",
                    }
                )
        elif token.kind == "wildcard":
            definition = semantics.definition_for(token.symbol)
            accepts = definition.accepts(char) if definition is not None else None
            if accepts is not True:
                mismatches.append(
                    {
                        "position": token.index + 1,
                        "expected": f"{token.symbol} ({definition.meaning if definition else 'unknown'})",
                        "got": char,
                        "reason": "wildcard_reject",
                    }
                )
        else:
            mismatches.append(
                {
                    "position": token.index + 1,
                    "expected": token.char,
                    "got": char,
                    "reason": "unsupported_token",
                }
            )

    policy = semantics.length_policy
    if len(text) == instance.length:
        for token in instance.tokens:
            _check_pair(token.index, token)
    elif policy == LengthPolicy.EXACT.value:
        return PositionalMatchResult(
            status=MatchStatus.NO_MATCH.value,
            value=text,
            pattern=instance.raw_value,
            mismatches=(
                {
                    "position": 0,
                    "expected": f"length {instance.length}",
                    "got": f"length {len(text)}",
                    "reason": "length_mismatch",
                },
            ),
            premises_used=tuple(premises_used),
            reason="length_mismatch",
        )
    elif semantics.anchor_side == "end":
        # El patrón aplica desde el final: el valor puede tener sobrante al
        # inicio (sufijo). Posiciones fuera del valor no se exigen.
        offset = len(text) - instance.length
        for token in instance.tokens:
            if token.index + offset >= 0:
                _check_pair(token.index + offset, token)
    elif policy in (
        LengthPolicy.MIN_LENGTH.value,
        LengthPolicy.MAX_LENGTH.value,
        LengthPolicy.RANGE.value,
    ):
        failure = _length_failure(text, instance, semantics)
        if failure is not None:
            return failure
        for token in instance.tokens:
            if token.index < len(text):
                _check_pair(token.index, token)
    elif policy in (
        LengthPolicy.VALUE_MAY_BE_LONGER.value,
        LengthPolicy.PATTERN_MAY_BE_SHORTER.value,
        LengthPolicy.UNCONSTRAINED.value,
    ):
        # El valor puede ser más largo que el patrón: se compara desde el
        # inicio y el sobrante queda fuera del patrón (jamás se exige igualdad).
        for token in instance.tokens:
            _check_pair(token.index, token)
    elif policy in (
        LengthPolicy.VALUE_MAY_BE_SHORTER.value,
        LengthPolicy.PATTERN_MAY_BE_LONGER.value,
    ):
        # El valor puede ser más corto: solo se exigen las posiciones presentes.
        for token in instance.tokens:
            if token.index < len(text):
                _check_pair(token.index, token)
    else:
        # Política UNKNOWN con anclaje inicial declarado: comparación desde el
        # inicio, sobrante fuera del patrón.
        for token in instance.tokens:
            _check_pair(token.index, token)

    status = MatchStatus.MATCH.value if not mismatches else MatchStatus.NO_MATCH.value
    return PositionalMatchResult(
        status=status,
        value=text,
        pattern=instance.raw_value,
        checked_positions=checked,
        mismatches=tuple(mismatches),
        premises_used=tuple(premises_used),
        reason="derived_from_documented_grammar" if status == MatchStatus.MATCH.value else "position_mismatch",
    )


__all__ = [
    "MatchStatus",
    "PATTERN_VERSION",
    "PatternInstance",
    "PatternSemantics",
    "PatternToken",
    "PositionalMatchResult",
    "SymbolDefinition",
    "WILDCARD_SYMBOLS",
    "analyze_pattern_instance",
    "extract_pattern_semantics",
    "missing_pattern_premises",
    "positional_match",
]
