# =============================================================================
# Semantic Rule Compiler — lenguaje → propiedades semánticas
# =============================================================================
# Convierte señales lingüísticas deterministas (ES/EN) en RuleProperty con
# evidencia propia. Distingue SIEMPRE:
#
#   MENCION  ("length", "date", "match")        -> propiedad UNKNOWN
#   POLITICA ("may be longer than", "same as")  -> propiedad INFERRED
#
# Nunca eleva una señal lexical por encima de la evidencia:
#   - "may" != "must"
#   - "unless" conserva la excepción
#   - "not between" != "between"
#   - una condición no se vuelve bidireccional
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.core.domain.rule_semantics import (
    BoundaryKind,
    ClaimLayer,
    ComparisonOperator,
    ExtractionMethod,
    LanguageSignals,
    LengthPolicy,
    LogicOperator,
    MatchOperator,
    ModalityKind,
    Polarity,
    QuantifierKind,
    RuleKind,
    TemporalRelation,
    VerificationState,
    analyze_language,
    is_definition,
    is_example,
)

from .model import RuleEnumerationSpec, RuleFormulaSpec, RuleProperty, RuleTemporalSpec

#: Fórmulas: "total = price * (1 + tax_rate)".
_FORMULA_EQ_RE = re.compile(
    r"\b([a-z_áéíóúñ][a-z0-9_áéíóúñ ]{0,40}?)\s*=\s*([^=.\n;]+?[+\-*/][^=.\n;]+)",
    re.IGNORECASE,
)
_FORMULA_NATURAL_RE = re.compile(
    r"\b([a-z_áéíóúñ][a-z0-9_áéíóúñ ]{0,40}?)\s+(?:is|es)\s+"
    r"(?:calculated|calculad[ao])\s+(?:as|como)\s+([^.\n;]+)",
    re.IGNORECASE,
)
_FORMULA_UNIT_RE = re.compile(
    r"\b(?:in|en)\s+(?P<unit>days?|d[ií]as?|hours?|horas?|minutes?|minutos?|"
    r"percent|porcentaje|%|usd|eur|kg|km|m|cm|mm|l|ml)\b",
    re.IGNORECASE,
)

_ALLOWED_ENUM_RE = re.compile(
    r"\b(?:allowed\s+values?|permitted\s+values?|must\s+be\s+one\s+of|one\s+of\s+the\s+following|"
    r"valid\s+values?|only\s+the\s+following|valores\s+permitidos?|valores\s+v[aá]lidos?|"
    r"debe\s+ser\s+uno\s+de|solo\s+los\s+siguientes|"
    r"(?:allowed|permitted|supported|valid)\s+(?:\w+\s+){0,2}?"
    r"(?:are|is|include|son|es))\s*[:\-]?\s*"
    r"(?P<values>[^.;\n]{2,300})",
    re.IGNORECASE,
)
_PROHIBITED_ENUM_RE = re.compile(
    r"\b(?:prohibited\s+values?|forbidden\s+values?|must\s+not\s+be\s+any\s+of|"
    r"valores\s+prohibidos?|no\s+puede\s+ser\s+ninguno\s+de)\s*[:\-]?\s*(?P<values>[^.;\n]{2,300})",
    re.IGNORECASE,
)
_MAPPING_RE = re.compile(
    r"(?-i:(?P<code>[A-Z0-9][A-Z0-9_\-/&*#]{1,24}))\s*"
    r"(?:=|:|->|→|means|significa|stands\s+for|representa|corresponde\s+a)\s*"
    r"(?P<meaning>[^.;\n|]{3,120})",
    re.IGNORECASE,
)
_DEFINITION_RE = re.compile(
    r"^(?P<term>[^:.]{2,80}?)\s*(?::|=|means|significa|represents?|representa|"
    r"is\s+defined\s+as|se\s+define\s+como)\s*(?P<meaning>[^.;\n]{3,300})",
    re.IGNORECASE,
)

_REFERENCE_RE = re.compile(
    r"\b(?:see|refer\s+to|as\s+defined\s+in|per|according\s+to|ver|v[eé]ase|"
    r"consultar|seg[uú]n|de\s+acuerdo\s+con)\s+"
    r"(?P<target>[A-Z0-9][^.,;\n]{2,80}?)(?:[.,;]|$)",
)

_PROCEDURE_RE = re.compile(
    r"\b(?:procedure|procedimiento|paso\s+\d|step\s+\d|first|second|third|luego|"
    r"despu[eé]s|finalmente)\b",
    re.IGNORECASE,
)

_MAX_VALUES = 64


@dataclass(kw_only=True)
class StatementAnalysis:
    """Propiedades semánticas de un enunciado, todas con evidencia."""

    statement: str = ""
    kind: str = RuleKind.NORMATIVE_RULE.value
    properties: dict[str, RuleProperty] = field(default_factory=dict)
    formula: RuleFormulaSpec = field(default_factory=RuleFormulaSpec)
    enumeration: RuleEnumerationSpec = field(default_factory=RuleEnumerationSpec)
    temporal: RuleTemporalSpec = field(default_factory=RuleTemporalSpec)
    exceptions: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    consequences: list[str] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)
    missing_premises: list[str] = field(default_factory=list)
    signals: LanguageSignals = field(default_factory=LanguageSignals)
    #: Alcance específico declarado ("For products marked FINAL"): la regla
    #: específica pesa más que la general cuando su condición se cumple.
    scope_priority: int = 0

    @property
    def operator(self) -> str:
        """Operador primario, prioridad explícita y auditable."""
        for name in (
            "matching.operator",
            "comparison.operator",
            "length.policy",
            "temporal.relation",
            "formula.expression",
        ):
            prop = self.properties.get(name)
            if prop is not None and prop.known:
                return str(prop.value)
        return ""


def _inferred(
    name: str,
    value,
    evidence_id: str,
    *,
    matched_text: str = "",
    explicit: bool = True,
    missing: tuple[str, ...] = (),
    note: str = "",
    confidence: float = 0.75,
    value_kind: str = "scalar",
) -> RuleProperty:
    return RuleProperty(
        name=name,
        value=value,
        value_kind=value_kind,
        layer=ClaimLayer.INFERRED.value,
        state=VerificationState.PROPOSED.value,
        evidence=[evidence_id],
        method=ExtractionMethod.DETERMINISTIC.value,
        confidence=confidence,
        explicit=explicit,
        matched_text=matched_text,
        missing_premises=list(missing),
        note=note,
    )


def _observed(evidence_id: str, statement: str, *, role: str = "observed") -> RuleProperty:
    return RuleProperty(
        name="observed.statement",
        value=statement[:1000],
        layer=ClaimLayer.OBSERVED.value,
        state=VerificationState.PROPOSED.value,
        evidence=[evidence_id],
        confidence=0.9,
        explicit=True,
        note=role,
    )


def _split_values(raw: str) -> list[str]:
    cleaned = re.split(r"[,;|]|\s+or\s+|\s+o\s+|\s+and\s+|\s+y\s+", raw or "")
    values: list[str] = []
    for value in cleaned:
        text = " ".join(value.strip(" .:;\"'()[]").split())
        if 1 <= len(text) <= 60 and text.lower() not in {"etc", "other", "otros", "otras"}:
            if text not in values:
                values.append(text)
    return values[:_MAX_VALUES]


def detect_formula(text: str) -> tuple[str, str]:
    """(target, expression) documentados, si existen."""
    match = _FORMULA_EQ_RE.search(text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    match = _FORMULA_NATURAL_RE.search(text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return "", ""


_FLAG_EQUALS_RE = re.compile(
    r"(?:(?P<operand>[a-záéíóúñ][\w\s]{0,30}?)\s+)?"
    r"(?:is|are|est[aá]|est[aá]n)\s+"
    r"(?:classified\s+as|marked(?:\s+as)?|flagged\s+as|set\s+to|equal\s+to|"
    r"denominad[oa]s?\s+como)\s+"
    r"(?P<value>[A-Za-z][A-Za-z0-9_\-]{1,30})",
    re.IGNORECASE,
)
_FLAG_ACTIVE_RE = re.compile(
    r"both\s+(?P<a>[A-Za-z0-9_]{1,16})\s+and\s+(?P<b>[A-Za-z0-9_]{1,16})\s+"
    r"are\s+(?P<state>active|enabled|on|true|activos?|habilitad[oa]s?)",
    re.IGNORECASE,
)


def _condition_equals_properties(    clause: str,
    prefix: str,
    evidence_id: str,
    properties: dict,
) -> bool:
    """Condición de bandera: 'customer is classified as VIP' -> equals."""
    match = _FLAG_EQUALS_RE.search(clause)
    if not match:
        return False
    value = " ".join(str(match.group("value") or "").split())
    operand_raw = " ".join(str(match.group("operand") or "").split())
    operand = operand_raw.split()[-1].lower() if operand_raw else ""
    properties[f"{prefix}.equals"] = _inferred(
        f"{prefix}.equals",
        value,
        evidence_id,
        matched_text=match.group(0),
        confidence=0.7,
    )
    if operand:
        properties[f"{prefix}.operand"] = _inferred(
            f"{prefix}.operand", operand, evidence_id, matched_text=match.group(0)
        )
    properties[f"{prefix}.alternative_operand"] = _inferred(
        f"{prefix}.alternative_operand",
        value.lower(),
        evidence_id,
        matched_text=match.group(0),
        confidence=0.6,
    )
    return True


def _condition_flags_properties(
    clause: str,
    prefix: str,
    evidence_id: str,
    properties: dict,
) -> bool:
    """Condición booleana: 'both A and B are active' -> flags [a, b]."""
    match = _FLAG_ACTIVE_RE.search(clause)
    if not match:
        return False
    flags = [match.group("a").lower(), match.group("b").lower()]
    properties[f"{prefix}.flags"] = _inferred(
        f"{prefix}.flags",
        flags,
        evidence_id,
        value_kind="list",
        matched_text=match.group(0),
        confidence=0.7,
    )
    properties[f"{prefix}.expect"] = _inferred(
        f"{prefix}.expect", True, evidence_id, matched_text=match.group(0)
    )
    return True


def _apply_condition_extras(
    clause: str,
    prefix: str,
    evidence_id: str,
    properties: dict,
) -> bool:
    """Intenta bandera booleana o igualdad; False si no hay estructura."""
    if _condition_flags_properties(clause, prefix, evidence_id, properties):
        return True
    return _condition_equals_properties(clause, prefix, evidence_id, properties)


def analyze_statement(statement: str, *, evidence_id: str) -> StatementAnalysis:
    """Convierte un enunciado en propiedades semánticas con evidencia."""
    text = " ".join(str(statement or "").split())
    analysis = StatementAnalysis(statement=text)
    if not text:
        analysis.ambiguities.append("empty_statement")
        return analysis
    signals = analyze_language(text)
    analysis.signals = signals
    analysis.properties["observed.statement"] = _observed(evidence_id, text)

    # --- modalidad y polaridad ------------------------------------------------
    modality = signals.modality
    if modality.matched_text:
        analysis.properties["modality"] = _inferred(
            "modality",
            modality.modality,
            evidence_id,
            matched_text=modality.matched_text,
            confidence=0.85,
        )
        analysis.properties["polarity"] = _inferred(
            "polarity",
            modality.polarity,
            evidence_id,
            matched_text=modality.matched_text,
            confidence=0.85,
        )
    elif signals.negation.negated:
        analysis.properties["polarity"] = _inferred(
            "polarity",
            Polarity.NEGATIVE.value,
            evidence_id,
            matched_text=signals.negation.matched_text,
            confidence=0.6,
            note="negación léxica sin modalidad explícita",
        )
    if modality.modality == ModalityKind.MAY.value and signals.negation.negated:
        # "may" con negación NO se convierte en "must": se mantiene la duda.
        analysis.ambiguities.append("may_with_negation")

    # --- lógica ---------------------------------------------------------------
    logic_operators = [item.operator for item in signals.logic]
    condition_comparison_keys: set[tuple[str, str]] = set()
    if logic_operators:
        analysis.properties["logic.operators"] = _inferred(
            "logic.operators",
            logic_operators,
            evidence_id,
            value_kind="list",
            matched_text=signals.logic[0].matched_text,
            confidence=0.7,
        )
    if LogicOperator.UNLESS.value in logic_operators or LogicOperator.EXCEPTION.value in logic_operators:
        analysis.properties["exception.present"] = _inferred(
            "exception.present",
            True,
            evidence_id,
            matched_text=next(
                item.matched_text
                for item in signals.logic
                if item.operator in (LogicOperator.UNLESS.value, LogicOperator.EXCEPTION.value)
            ),
            confidence=0.8,
        )
        # La excepción se conserva textualmente y, cuando su cláusula tiene una
        # condición estructurada (comparación/rango), se compila para poder
        # evaluarla en runtime. Sin condición evaluable -> UNDETERMINED.
        for marker in re.finditer(
            r"\b(unless|except\s+(?:when|if|where|for)|salvo\s+que|excepto\s+(?:cuando|si|para)|"
            r"a\s+menos\s+que|no\s+aplica\s+(?:cuando|si|para))\b",
            text,
            re.IGNORECASE,
        ):
            clause = text[marker.start() : marker.end() + 220].strip(" ,.;")
            if len(clause) < 10 or clause in analysis.exceptions:
                continue
            analysis.exceptions.append(clause[:400])
            clause_signals = analyze_language(clause)
            condition_prefix = f"exception.condition.{len(analysis.exceptions) - 1}"
            if clause_signals.comparisons:
                comparison = clause_signals.comparisons[0]
                condition_comparison_keys.add(
                    (
                        comparison.operator,
                        " ".join(str(comparison.right_operand or "").split()),
                    )
                )
                analysis.properties[f"{condition_prefix}.operator"] = _inferred(
                    f"{condition_prefix}.operator",
                    comparison.operator,
                    evidence_id,
                    matched_text=comparison.matched_text,
                    confidence=0.7,
                )
                if comparison.right_operand:
                    analysis.properties[f"{condition_prefix}.right"] = _inferred(
                        f"{condition_prefix}.right",
                        comparison.right_operand,
                        evidence_id,
                        matched_text=comparison.matched_text,
                    )
                if comparison.boundary != BoundaryKind.UNKNOWN.value:
                    analysis.properties[f"{condition_prefix}.boundary"] = _inferred(
                        f"{condition_prefix}.boundary",
                        comparison.boundary,
                        evidence_id,
                        matched_text=comparison.matched_text,
                    )
            elif clause_signals.quantities:
                quantity = clause_signals.quantities[0]
                if quantity.value is not None or quantity.upper is not None:
                    analysis.properties[f"{condition_prefix}.operator"] = _inferred(
                        f"{condition_prefix}.operator",
                        "GTE" if quantity.value is not None else "LTE",
                        evidence_id,
                        matched_text=quantity.matched_text,
                        confidence=0.6,
                    )
                    analysis.properties[f"{condition_prefix}.right"] = _inferred(
                        f"{condition_prefix}.right",
                        quantity.value if quantity.value is not None else quantity.upper,
                        evidence_id,
                        matched_text=quantity.matched_text,
                    )
            elif _apply_condition_extras(
                clause, condition_prefix, evidence_id, analysis.properties
            ):
                pass
            else:
                analysis.properties[f"{condition_prefix}.text"] = _inferred(
                    f"{condition_prefix}.text",
                    clause,
                    evidence_id,
                    explicit=False,
                    missing=("exception_condition",),
                    note="excepción sin condición estructurada evaluable",
                    confidence=0.5,
                )
                analysis.missing_premises.append("exception_condition")

    # "only if": condición de aplicabilidad. Sin estructura evaluable ->
    # UNDETERMINED (no se asume que la condición se cumple).
    only_if_match = re.search(
        r"\b(only\s+if|only\s+when|solo\s+si|solamente\s+si|s[oó]lo\s+cuando|"
        r"únicamente\s+si|si\s+y\s+solo\s+si|if\s+and\s+only\s+if)\b",
        text,
        re.IGNORECASE,
    )
    if only_if_match:
        clause = text[only_if_match.end() : only_if_match.end() + 220].strip(" ,.;")
        analysis.conditions.append(clause[:400])
        clause_signals = analyze_language(clause)
        prefix = "condition.only_if"
        if clause_signals.comparisons:
            comparison = clause_signals.comparisons[0]
            condition_comparison_keys.add(
                (
                    comparison.operator,
                    " ".join(str(comparison.right_operand or "").split()),
                )
            )
            analysis.properties[f"{prefix}.operator"] = _inferred(
                f"{prefix}.operator", comparison.operator, evidence_id,
                matched_text=comparison.matched_text, confidence=0.7,
            )
            if comparison.right_operand:
                analysis.properties[f"{prefix}.right"] = _inferred(
                    f"{prefix}.right", comparison.right_operand, evidence_id,
                    matched_text=comparison.matched_text,
                )
            if comparison.boundary != BoundaryKind.UNKNOWN.value:
                analysis.properties[f"{prefix}.boundary"] = _inferred(
                    f"{prefix}.boundary", comparison.boundary, evidence_id,
                    matched_text=comparison.matched_text,
                )
        elif clause_signals.quantities:
            quantity = clause_signals.quantities[0]
            if quantity.value is not None or quantity.upper is not None:
                analysis.properties[f"{prefix}.operator"] = _inferred(
                    f"{prefix}.operator",
                    "GTE" if quantity.value is not None else "LTE",
                    evidence_id,
                    matched_text=quantity.matched_text,
                    confidence=0.6,
                )
                analysis.properties[f"{prefix}.right"] = _inferred(
                    f"{prefix}.right",
                    quantity.value if quantity.value is not None else quantity.upper,
                    evidence_id,
                    matched_text=quantity.matched_text,
                )
        elif _apply_condition_extras(clause, prefix, evidence_id, analysis.properties):
            pass
        else:
            analysis.properties[f"{prefix}.text"] = _inferred(
                f"{prefix}.text",
                clause,
                evidence_id,
                explicit=False,
                missing=("condition_only_if",),
                note="condición only_if sin estructura evaluable",
                confidence=0.5,
            )
            analysis.missing_premises.append("condition_only_if")

    # Alcance específico declarado: "For products marked FINAL" -> la regla
    # aplica con prioridad cuando el objeto runtime coincide.
    for index, scope_match in enumerate(
        re.finditer(
            r"\bfor\s+(?P<subject>[a-záéíóúñ][\w\s]{0,40}?)\s+"
            r"(?:marked|classified|flagged|labelled|labeled|denominad[oa]s?)\s+"
            r"(?:as\s+)?(?P<value>[A-Za-z][A-Za-z0-9_\-]{1,30})",
            text,
            re.IGNORECASE,
        )
    ):
        prefix = f"scope.condition.{index}"
        value = " ".join(str(scope_match.group("value") or "").split())
        subject_raw = " ".join(str(scope_match.group("subject") or "").split())
        operand = subject_raw.split()[-1].lower() if subject_raw else ""
        analysis.properties[f"{prefix}.equals"] = _inferred(
            f"{prefix}.equals",
            value,
            evidence_id,
            matched_text=scope_match.group(0),
            confidence=0.7,
        )
        if operand:
            analysis.properties[f"{prefix}.operand"] = _inferred(
                f"{prefix}.operand",
                operand.rstrip("s"),
                evidence_id,
                matched_text=scope_match.group(0),
            )
        analysis.properties[f"{prefix}.alternative_operand"] = _inferred(
            f"{prefix}.alternative_operand",
            value.lower(),
            evidence_id,
            matched_text=scope_match.group(0),
            confidence=0.6,
        )
        analysis.scope_priority = max(analysis.scope_priority, 1)

    # Símbolo definido por el propio enunciado ("& represents ...").
    symbol_definitions = list(
        re.finditer(
            r"[\"'«]?\s*(?P<symbol>[^\w\s]|[A-Z])\s*"
            r"(?P<verb>represents?|means?|stands?\s+for|denotes?|significa|representa|"
            r"is|are|es|son)\s+"
            r"(?P<meaning>[^.;\n]{3,120})",
            text,
        )
    )
    for symbol_match in symbol_definitions:
        symbol = symbol_match.group("symbol")
        prop_name = f"matching.symbol.{symbol}"
        if prop_name in analysis.properties:
            continue
        meaning = " ".join(symbol_match.group("meaning").split())
        if symbol.isalpha() and not re.match(
            r"(?:(?:a|an|one|un|una)\s+)?"
            r"(?:letter|digit|character|alphanumeric|position|symbol|"
            r"letra|d[ií]gito|car[aá]cter|posici[oó]n|s[ií]mbolo)\b",
            meaning,
            re.IGNORECASE,
        ):
            # "Rule A is processed" no es una definición de símbolo: solo se
            # acepta un significado declarativo (letra/dígito/posición/...).
            continue
        alphabet_match = analyze_language(meaning)
        analysis.properties[prop_name] = _inferred(
            prop_name,
            meaning,
            evidence_id,
            matched_text=symbol_match.group(0),
            confidence=0.85,
        )
        if alphabet_match.match.alphabet:
            analysis.properties[f"{prop_name}.alphabet"] = _inferred(
                f"{prop_name}.alphabet",
                alphabet_match.match.alphabet,
                evidence_id,
                matched_text=symbol_match.group(0),
            )

    # --- comparaciones (asimetría preservada) --------------------------------
    for index, comparison in enumerate(signals.comparisons):
        if (
            comparison.operator,
            " ".join(str(comparison.right_operand or "").split()),
        ) in condition_comparison_keys:
            # La comparación es la condición de una excepción/only_if: se evalúa
            # como condición, no como cuerpo principal de la regla.
            continue
        suffix = "" if index == 0 else f".{index}"
        analysis.properties[f"comparison.operator{suffix}"] = _inferred(
            f"comparison.operator{suffix}",
            comparison.operator,
            evidence_id,
            matched_text=comparison.matched_text,
            confidence=0.8,
        )
        if comparison.left_operand:
            analysis.properties[f"comparison.left{suffix}"] = _inferred(
                f"comparison.left{suffix}",
                comparison.left_operand,
                evidence_id,
                matched_text=comparison.matched_text,
            )
        if comparison.right_operand:
            analysis.properties[f"comparison.right{suffix}"] = _inferred(
                f"comparison.right{suffix}",
                comparison.right_operand,
                evidence_id,
                matched_text=comparison.matched_text,
            )
        if comparison.operator in (
            ComparisonOperator.BETWEEN.value,
            ComparisonOperator.OUTSIDE_RANGE.value,
        ) and comparison.boundary == BoundaryKind.UNKNOWN.value:
            analysis.properties[f"comparison.boundary{suffix}"] = _inferred(
                f"comparison.boundary{suffix}",
                BoundaryKind.UNKNOWN.value,
                evidence_id,
                matched_text=comparison.matched_text,
                explicit=False,
                missing=("boundary",),
                note="rango sin inclusividad declarada",
            )
            analysis.missing_premises.append("boundary")
        elif comparison.boundary != BoundaryKind.UNKNOWN.value:
            analysis.properties[f"comparison.boundary{suffix}"] = _inferred(
                f"comparison.boundary{suffix}",
                comparison.boundary,
                evidence_id,
                matched_text=comparison.matched_text,
            )

    # --- longitud -------------------------------------------------------------
    length = signals.length
    if length.policy != LengthPolicy.UNKNOWN.value or length.mention_only:
        analysis.properties["length.policy"] = _inferred(
            "length.policy",
            length.policy,
            evidence_id,
            matched_text=length.matched_text,
            explicit=length.explicit,
            missing=length.missing_premises,
            note=length.note,
            confidence=0.85 if length.explicit else 0.4,
        )
        if length.value is not None:
            analysis.properties["length.value"] = _inferred(
                "length.value", length.value, evidence_id, matched_text=length.matched_text
            )
        if length.upper is not None:
            analysis.properties["length.upper"] = _inferred(
                "length.upper", length.upper, evidence_id, matched_text=length.matched_text
            )
        if length.boundary != BoundaryKind.UNKNOWN.value:
            analysis.properties["length.boundary"] = _inferred(
                "length.boundary", length.boundary, evidence_id, matched_text=length.matched_text
            )
        if length.directional:
            analysis.properties["length.left_operand"] = _inferred(
                "length.left_operand", length.left_operand, evidence_id, matched_text=length.matched_text
            )
            analysis.properties["length.right_operand"] = _inferred(
                "length.right_operand", length.right_operand, evidence_id, matched_text=length.matched_text
            )
        analysis.missing_premises.extend(length.missing_premises)
        if length.mention_only:
            analysis.ambiguities.append("length_mentioned_without_policy")

    # --- matching -------------------------------------------------------------
    match = signals.match
    is_symbol_statement = bool(symbol_definitions)
    # "exactly N characters" es longitud, no política de matching literal.
    length_handles_literal = bool(
        signals.length.is_policy
        and match.operator == MatchOperator.LITERAL
        and "match" not in (match.matched_text or "").lower()
    )
    has_match_detail = bool(
        match.case_sensitive is not None
        or match.alphabet
        or match.prohibited_alphabet
        or match.fixed_position is not None
        or match.optional_positions
        or match.repeated_positions
        or match.separator
        or match.normalization
        or match.literal
    )
    if match.operator != MatchOperator.UNKNOWN.value and not length_handles_literal:
        analysis.properties["matching.operator"] = _inferred(
            "matching.operator",
            match.operator,
            evidence_id,
            matched_text=match.matched_text,
            confidence=0.8,
        )
    if match.explicit or has_match_detail:
        if match.literal and not length_handles_literal:
            analysis.properties["matching.literal"] = _inferred(
                "matching.literal",
                True,
                evidence_id,
                matched_text=match.matched_text,
                confidence=0.75,
            )
        if match.case_sensitive is not None:
            analysis.properties["matching.case_sensitive"] = _inferred(
                "matching.case_sensitive",
                match.case_sensitive,
                evidence_id,
                matched_text=match.matched_text,
            )
        if match.alphabet and not is_symbol_statement:
            analysis.properties["matching.alphabet"] = _inferred(
                "matching.alphabet", match.alphabet, evidence_id, matched_text=match.matched_text
            )
        if match.prohibited_alphabet:
            analysis.properties["matching.prohibited_alphabet"] = _inferred(
                "matching.prohibited_alphabet",
                match.prohibited_alphabet,
                evidence_id,
                matched_text=match.matched_text,
            )
        if match.fixed_position is not None:
            analysis.properties["matching.fixed_position"] = _inferred(
                "matching.fixed_position", match.fixed_position, evidence_id, matched_text=match.matched_text
            )
        for name, value in (
            ("matching.optional_positions", match.optional_positions),
            ("matching.repeated_positions", match.repeated_positions),
        ):
            if value:
                analysis.properties[name] = _inferred(name, value, evidence_id, matched_text=match.matched_text)
        if match.separator:
            analysis.properties["matching.separator"] = _inferred(
                "matching.separator", match.separator, evidence_id, matched_text=match.matched_text
            )
        if match.normalization:
            analysis.properties["matching.normalization"] = _inferred(
                "matching.normalization", match.normalization, evidence_id, matched_text=match.matched_text
            )
    elif re.search(r"\bmatch(?:ing|es)?\b|\bcoincid\w+\b", text, re.IGNORECASE):
        # Mención de matching sin política: UNKNOWN explícito.
        analysis.properties["matching.operator"] = _inferred(
            "matching.operator",
            MatchOperator.UNKNOWN.value,
            evidence_id,
            matched_text="match",
            explicit=False,
            missing=("matching_policy",),
            note="se menciona matching sin establecer política",
            confidence=0.4,
        )
        analysis.missing_premises.append("matching_policy")
        analysis.ambiguities.append("matching_mentioned_without_policy")

    # --- cuantificador --------------------------------------------------------
    if signals.quantifier != QuantifierKind.UNKNOWN.value:
        analysis.properties["quantifier"] = _inferred(
            "quantifier", signals.quantifier, evidence_id, confidence=0.7
        )

    # --- cantidades/rangos ----------------------------------------------------
    for index, quantity in enumerate(signals.quantities):
        suffix = "" if index == 0 else f".{index}"
        prefix = f"quantity{suffix}"
        if quantity.value is not None:
            analysis.properties[f"{prefix}.minimum"] = _inferred(
                f"{prefix}.minimum", quantity.value, evidence_id, matched_text=quantity.matched_text
            )
        if quantity.upper is not None:
            analysis.properties[f"{prefix}.maximum"] = _inferred(
                f"{prefix}.maximum", quantity.upper, evidence_id, matched_text=quantity.matched_text
            )
        if quantity.unit:
            unit_key = f"{prefix}.unit"
            if quantity.unit in {"days", "day", "dias", "días", "día", "dia", "hours", "hour",
                                 "horas", "hora", "weeks", "week", "semanas", "meses", "months"}:
                analysis.ambiguities.append(f"temporal_unit:{quantity.unit}")
            analysis.properties[unit_key] = _inferred(
                unit_key, quantity.unit, evidence_id, matched_text=quantity.matched_text
            )
        elif quantity.value is not None or quantity.upper is not None:
            number = quantity.value if quantity.value is not None else quantity.upper
            covered_by_comparison = False
            for comp_name, comp_prop in analysis.properties.items():
                if not comp_name.startswith("comparison.") or not comp_prop.known:
                    continue
                if "left" in comp_name or "right" in comp_name:
                    if re.search(
                        rf"(?<!\d){re.escape(str(number).rstrip('0').rstrip('.'))}(?!\d)",
                        str(comp_prop.value),
                    ):
                        covered_by_comparison = True
                        break
            if covered_by_comparison:
                continue
            missing_unit = f"{prefix}.unit"
            analysis.properties[missing_unit] = _inferred(
                missing_unit,
                "",
                evidence_id,
                matched_text=quantity.matched_text,
                explicit=False,
                note="unidad no declarada; se compara en la escala del dato",
                confidence=0.4,
            )
        if quantity.boundary != BoundaryKind.UNKNOWN.value:
            analysis.properties[f"{prefix}.boundary"] = _inferred(
                f"{prefix}.boundary", quantity.boundary, evidence_id, matched_text=quantity.matched_text
            )
        else:
            analysis.properties[f"{prefix}.boundary"] = _inferred(
                f"{prefix}.boundary",
                BoundaryKind.UNKNOWN.value,
                evidence_id,
                matched_text=quantity.matched_text,
                explicit=False,
                missing=("boundary",),
                note="límite sin inclusividad declarada",
                confidence=0.4,
            )
            if f"boundary:{prefix}" not in analysis.missing_premises:
                analysis.missing_premises.append(f"boundary:{prefix}")

    # --- tiempo ---------------------------------------------------------------
    temporal = signals.temporal
    if temporal.relation != TemporalRelation.UNKNOWN.value:
        analysis.temporal = RuleTemporalSpec(
            relation=temporal.relation,
            value=temporal.value,
            evidence=[evidence_id],
        )
        analysis.properties["temporal.relation"] = _inferred(
            "temporal.relation", temporal.relation, evidence_id, matched_text=temporal.matched_text
        )
        if temporal.value:
            analysis.properties["temporal.value"] = _inferred(
                "temporal.value", temporal.value, evidence_id, matched_text=temporal.matched_text
            )
        analysis.temporal.value = temporal.value
        analysis.temporal.evidence = [evidence_id]

    # --- fórmula --------------------------------------------------------------
    target, expression = detect_formula(text)
    if expression:
        unit_match = _FORMULA_UNIT_RE.search(text)
        unit = unit_match.group("unit") if unit_match else ""
        if unit:
            # "price * quantity in USD": la unidad no es parte de la expresión.
            cleaned = re.sub(
                rf"\s*\b(?:in|en)\s+{re.escape(unit)}\b\.?\s*$",
                "",
                expression,
                flags=re.IGNORECASE,
            ).strip()
            expression = cleaned or expression
        analysis.formula = RuleFormulaSpec(
            target=target,
            expression=expression,
            unit=unit,
            evidence=[evidence_id],
        )
        analysis.properties["formula.expression"] = _inferred(
            "formula.expression", expression, evidence_id, confidence=0.85
        )
        analysis.properties["formula.target"] = _inferred("formula.target", target, evidence_id)
        if unit:
            analysis.properties["formula.unit"] = _inferred("formula.unit", unit, evidence_id)
        else:
            analysis.ambiguities.append("formula_unit_unspecified")

    # --- enumeraciones --------------------------------------------------------
    allowed_match = _ALLOWED_ENUM_RE.search(text)
    if allowed_match:
        values = _split_values(allowed_match.group("values"))
        if values:
            analysis.enumeration.allowed = values
            analysis.enumeration.evidence = [evidence_id]
            analysis.properties["enumeration.allowed"] = _inferred(
                "enumeration.allowed", values, evidence_id, value_kind="list",
                matched_text=allowed_match.group(0),
            )
    prohibited_match = _PROHIBITED_ENUM_RE.search(text)
    if prohibited_match:
        values = _split_values(prohibited_match.group("values"))
        if values:
            analysis.enumeration.prohibited = values
            analysis.enumeration.evidence = [evidence_id]
            analysis.properties["enumeration.prohibited"] = _inferred(
                "enumeration.prohibited", values, evidence_id, value_kind="list",
                matched_text=prohibited_match.group(0),
            )

    # --- definiciones / mappings ---------------------------------------------
    mapping_match = _MAPPING_RE.search(text)
    if mapping_match and not expression:
        code = mapping_match.group("code").strip()
        meaning = " ".join(mapping_match.group("meaning").split())
        if code and meaning:
            analysis.enumeration.mapping = {code: meaning}
            analysis.enumeration.evidence = [evidence_id]
            analysis.properties["mapping.code"] = _inferred(
                "mapping.code", code, evidence_id, matched_text=mapping_match.group(0)
            )
            analysis.properties["mapping.meaning"] = _inferred(
                "mapping.meaning", meaning, evidence_id, matched_text=mapping_match.group(0)
            )

    # --- referencias cruzadas -------------------------------------------------
    for index, reference in enumerate(_REFERENCE_RE.finditer(text)):
        target_ref = " ".join(reference.group("target").split())
        key = "reference.target" if index == 0 else f"reference.target.{index}"
        analysis.properties[key] = _inferred(
            key,
            target_ref,
            evidence_id,
            matched_text=reference.group(0),
            explicit=True,
            missing=(f"reference:{target_ref}",),
            note="referencia cruzada por resolver",
            confidence=0.6,
        )
        analysis.missing_premises.append(f"reference:{target_ref}")

    # --- clasificación documental --------------------------------------------
    analysis.kind = classify_statement_kind(text, signals=signals)
    return analysis


def classify_statement_kind(text: str, *, signals: LanguageSignals | None = None) -> str:
    """NORMATIVA vs DEFINICIÓN vs EJEMPLO vs NOTA/PROCEDIMIENTO/REFERENCIA/FÓRMULA."""
    signals = signals or analyze_language(text)
    if is_example(text):
        return RuleKind.EXAMPLE.value
    if signals.modality.normative:
        if LogicOperator.UNLESS.value in {item.operator for item in signals.logic}:
            return RuleKind.NORMATIVE_RULE.value
        if detect_formula(text)[1]:
            return RuleKind.FORMULA.value
        if _PROCEDURE_RE.search(text):
            return RuleKind.PROCEDURE.value
        return RuleKind.NORMATIVE_RULE.value
    if is_definition(text):
        return RuleKind.DEFINITION.value
    if LogicOperator.UNLESS.value in {item.operator for item in signals.logic}:
        return RuleKind.EXCEPTION.value
    if {
        item.operator for item in signals.logic
    } & {
        LogicOperator.ONLY_IF.value,
        LogicOperator.IF_AND_ONLY_IF.value,
        LogicOperator.UNLESS.value,
    }:
        # Una regla condicional sigue siendo normativa aunque no use "must".
        return RuleKind.NORMATIVE_RULE.value
    if detect_formula(text)[1]:
        return RuleKind.FORMULA.value
    if _REFERENCE_RE.search(text):
        return RuleKind.REFERENCE.value
    if _PROCEDURE_RE.search(text):
        return RuleKind.PROCEDURE.value
    if _ALLOWED_ENUM_RE.search(text) or _PROHIBITED_ENUM_RE.search(text):
        return RuleKind.CONSTRAINT.value
    if signals.temporal.relation != TemporalRelation.UNKNOWN.value:
        return RuleKind.CONSTRAINT.value
    if signals.comparisons or signals.quantities:
        return RuleKind.CONSTRAINT.value
    if signals.length.is_policy or signals.match.explicit:
        return RuleKind.CONSTRAINT.value
    return RuleKind.NOTE.value


__all__ = [
    "StatementAnalysis",
    "analyze_statement",
    "classify_statement_kind",
    "detect_formula",
]
