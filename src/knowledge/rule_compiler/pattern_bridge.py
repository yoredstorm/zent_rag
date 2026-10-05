# =============================================================================
# Semantic Rule Compiler — puente hacia la gramática de patrones
# =============================================================================
# Una CanonicalRule con propiedades de matching se traduce a PatternSemantics
# para que el motor determinista de patrones la ejecute SIN volver a
# interpretar el documento. La regla compilada es la premisa; la instancia del
# usuario sigue siendo dato de escenario.
# =============================================================================
from __future__ import annotations

import re
from typing import Any

from src.core.domain.rule_semantics import (
    LengthPolicy,
    MatchOperator,
)

from .model import CanonicalRule, RuleProperty

_ALPHABET_MEANING = {
    "alphanumeric": "alphanumeric_position",
    "digit": "digit",
    "letter": "letter",
    "space": "space",
    "any_char": "any_char",
}

_MEANING_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("alphanumeric_position", ("alphanumeric", "alfanum", "letter or digit", "letra o d")),
    ("digit", ("digit", "dígito", "digito", "numeric", "numér", "numer")),
    ("letter", ("letter", "letra", "alphabetic", "alfabét", "alfabet")),
    ("space", ("space", "espacio", "blank", "blanco")),
    ("any_char", ("any character", "cualquier caracter", "cualquier carácter", "wildcard", "comodín", "comodin")),
    ("literal", ("literal", "fixed", "fijo", "exact")),
)


def _meaning_from_property(prop: RuleProperty, *, symbol: str) -> str:
    note_match = re.search(r"alphabet=([a-z_]+)", str(prop.note or ""))
    if note_match is not None and note_match.group(1) in _ALPHABET_MEANING:
        return _ALPHABET_MEANING[note_match.group(1)]
    lowered = str(prop.value or "").lower()
    for meaning, markers in _MEANING_MARKERS:
        if any(marker in lowered for marker in markers):
            return meaning
    if symbol and len(symbol) == 1 and not symbol.isalnum():
        return "any_char"
    return "other"


def _symbol_meaning(
    rule: CanonicalRule, symbol: str, prop: RuleProperty
) -> str:
    alphabet_prop = rule.properties.get(f"matching.symbol.{symbol}.alphabet")
    if alphabet_prop is not None and alphabet_prop.known:
        mapped = _ALPHABET_MEANING.get(str(alphabet_prop.value))
        if mapped:
            return mapped
    return _meaning_from_property(prop, symbol=symbol)


def pattern_semantics_from_rule(rule: CanonicalRule) -> Any:
    """CanonicalRule -> PatternSemantics (lazy import, sin ciclos)."""
    from src.rag.longcontext.pattern import PatternSemantics, SymbolDefinition

    definitions: dict[str, SymbolDefinition] = {}
    statements: list[str] = []
    for name, prop in rule.properties.items():
        if not name.startswith("matching.symbol."):
            continue
        suffix = name[len("matching.symbol.") :]
        if suffix.endswith(".alphabet"):
            continue
        symbol = suffix
        if not symbol or not prop.known:
            continue
        meaning = _symbol_meaning(rule, symbol, prop)
        if meaning == "other":
            continue
        statement = str(prop.value or "")[:240]
        definitions[symbol] = SymbolDefinition(
            symbol=symbol,
            statement=statement,
            meaning=meaning,
            evidence_ref=(prop.evidence[0] if prop.evidence else ""),
        )
        if statement and statement not in statements:
            statements.append(statement)

    matching = rule.properties.get("matching.operator")
    operator = str(matching.value) if matching is not None and matching.known else ""
    positional = operator in (
        MatchOperator.POSITIONAL.value,
        MatchOperator.LITERAL.value,
        MatchOperator.FIXED_POSITION.value,
        MatchOperator.PREFIX.value,
        MatchOperator.SUFFIX.value,
    )
    literal_prop = rule.properties.get("matching.literal")
    literal = operator == MatchOperator.LITERAL.value or bool(
        literal_prop is not None and literal_prop.known and literal_prop.value
    )
    anchor_side = ""
    if operator == MatchOperator.PREFIX.value:
        anchor_side = "start"
    elif operator == MatchOperator.SUFFIX.value:
        anchor_side = "end"

    length_prop = rule.properties.get("length.policy")
    length_policy = (
        str(length_prop.value)
        if length_prop is not None and length_prop.known
        else LengthPolicy.UNKNOWN.value
    )
    length_value_prop = rule.properties.get("length.value")
    length_value = (
        length_value_prop.value
        if length_value_prop is not None and length_value_prop.known
        else None
    )
    boundary_prop = rule.properties.get("length.boundary")
    boundary = str(boundary_prop.value) if boundary_prop is not None and boundary_prop.known else ""

    return PatternSemantics(
        symbol_definitions=definitions,
        positional=positional,
        literal=literal,
        length_policy=length_policy,
        length_value=int(length_value) if isinstance(length_value, (int, float)) else None,
        length_boundary=boundary,
        anchor_side=anchor_side,
        statements=tuple(statements[:6]),
    )


__all__ = ["pattern_semantics_from_rule"]
