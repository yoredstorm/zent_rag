# =============================================================================
# Semantic Rule Compiler — candidatos y evidencia distribuida
# =============================================================================
# Una regla puede estar repartida entre páginas, secciones, tablas, notas y
# definiciones. Este módulo UNE esa evidencia:
#
#   units / windows / threads          (evidencia localizada)
#        + RuleCandidate (compilador)  (detección normativa existente)
#        -> CandidateRule con provenance[] de TODAS las piezas
#
# No convierte ejemplos en reglas. No inventa vínculos: un link se crea solo
# con coincidencia de términos/símbolos/secciones verificable.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from src.core.domain.rule_semantics import (
    MODALITY_STRENGTH,
    ClaimLayer,
    LogicOperator,
    ModalityKind,
    Polarity,
    RuleKind,
    VerificationState,
    analyze_language,
    is_example,
    is_normative,
)

from .language import StatementAnalysis, analyze_statement, classify_statement_kind
from .model import (
    CandidateRule,
    RuleArgument,
    RuleEvidence,
    RuleProperty,
    RuleScope,
    stable_id,
)

MAX_CANDIDATES = 400
_TOKEN_RE = re.compile(r"[a-z0-9áéíóúñ&*#%?]{3,}", re.IGNORECASE)
_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "that", "this", "from", "must", "shall",
        "may", "can", "los", "las", "del", "para", "con", "que", "una", "uno",
        "por", "como", "sus", "sea", "debe", "puede", "ser", "are",
    }
)


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN_RE.findall(str(text or ""))
        if token.lower() not in _STOPWORDS
    }


def _overlap(left: str, right: str) -> int:
    """Solapamiento por prefijo (tolera plural/género: reissue/reissued)."""
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    hits = 0
    for left_token in left_tokens:
        if any(left_token[:5] == right_token[:5] for right_token in right_tokens):
            hits += 1
    return hits


# -----------------------------------------------------------------------------
# Contexto de evidencia (unit/window/thread agnóstico)
# -----------------------------------------------------------------------------


@dataclass(kw_only=True)
class RuleContextItem:
    """Pieza de evidencia localizada, venga de donde venga."""

    item_id: str
    kind: str
    label: str
    text: str
    evidence_id: str = ""
    locator: dict = field(default_factory=dict)
    section_path: tuple[str, ...] = ()
    page: int | None = None
    block_id: str = ""
    source_key: str = ""
    attributes: dict = field(default_factory=dict)

    def to_evidence(self, *, role: str = "support", layer: str = ClaimLayer.OBSERVED.value) -> RuleEvidence:
        return RuleEvidence(
            evidence_id=self.evidence_id,
            locator=dict(self.locator),
            excerpt=self.text,
            unit_id=self.item_id,
            source_key=self.source_key,
            layer=layer,
            role=role,
            strength=0.85 if layer == ClaimLayer.OBSERVED.value else 0.6,
        )


def _locator_dict(evidence) -> dict:
    locator = getattr(evidence, "locator", None)
    if locator is None:
        return {}
    try:
        return locator.to_dict()
    except Exception:  # noqa: BLE001
        return dict(getattr(locator, "__dict__", {}) or {})


def context_items_from_units(
    units: Sequence[Any],
    *,
    document_id: str = "",
    source_key: str = "",
) -> list[RuleContextItem]:
    """SemanticUnit -> contexto localizado, con evidence_id determinista."""
    items: list[RuleContextItem] = []
    for unit in units or ():
        evidence = getattr(unit, "evidence", None)
        locator = _locator_dict(evidence)
        label = str(getattr(unit, "label", "") or "")
        kind = str(getattr(unit, "kind", "") or "")
        unit_id = str(getattr(unit, "key", "") or label or len(items))
        evidence_id = stable_id(
            "ev",
            document_id or locator.get("document_id"),
            locator.get("locator") or "source/unknown",
            kind,
            unit_id,
        )
        items.append(
            RuleContextItem(
                item_id=f"{kind}:{unit_id}"[:200],
                kind=kind,
                label=label[:200],
                text=str(getattr(unit, "text", "") or "")[:4000],
                evidence_id=evidence_id,
                locator=locator,
                section_path=tuple(locator.get("section_path") or ()),
                page=locator.get("page"),
                block_id=str(locator.get("block_id") or ""),
                source_key=source_key or str(locator.get("document_title") or ""),
                attributes=dict(getattr(unit, "attributes", {}) or {}),
            )
        )
    return items


def context_items_from_generic(
    entries: Sequence[Any],
    *,
    document_id: str = "",
    source_key: str = "",
) -> list[RuleContextItem]:
    """Items de ventana/thread (cualquier objeto con kind/label/text)."""
    items: list[RuleContextItem] = []
    for index, entry in enumerate(entries or ()):
        if isinstance(entry, dict):
            get = entry.get
        else:
            def get(name, default=None, _entry=entry):
                return getattr(_entry, name, default)

        kind = str(get("kind") or get("item_type") or "window_item")
        label = str(get("label") or get("name") or "")
        text = str(get("text") or get("statement") or get("value") or "")
        evidence_id = str(get("evidence_id") or "")
        locator = dict(get("locator") or {})
        if not evidence_id:
            evidence_id = stable_id(
                "ev", document_id, locator.get("locator") or f"item/{index}", kind, label
            )
        items.append(
            RuleContextItem(
                item_id=str(get("item_id") or get("unit_id") or f"{kind}:{index}")[:200],
                kind=kind,
                label=label[:200],
                text=text[:4000],
                evidence_id=evidence_id,
                locator=locator,
                section_path=tuple(get("section_path") or ()),
                page=get("page"),
                block_id=str(get("block_id") or ""),
                source_key=source_key,
                attributes=dict(get("attributes") or {}),
            )
        )
    return items


# -----------------------------------------------------------------------------
# Índices de enlaces
# -----------------------------------------------------------------------------


@dataclass
class _Indexes:
    definitions: dict[str, RuleContextItem] = field(default_factory=dict)
    symbols: dict[str, RuleContextItem] = field(default_factory=dict)
    sections: dict[str, RuleContextItem] = field(default_factory=dict)
    exceptions: list[RuleContextItem] = field(default_factory=list)
    examples: list[RuleContextItem] = field(default_factory=list)

    def to_public(self) -> dict:
        return {
            "definitions": len(self.definitions),
            "symbols": len(self.symbols),
            "sections": len(self.sections),
            "exceptions": len(self.exceptions),
            "examples": len(self.examples),
        }


def _is_symbol_label(label: str) -> bool:
    text = str(label or "").strip()
    return 0 < len(text) <= 3 and not text.isalnum()


def build_indexes(items: Sequence[RuleContextItem]) -> _Indexes:
    indexes = _Indexes()
    for item in items:
        normalized_label = " ".join(item.label.lower().split())
        if item.kind in ("definition", "term") and normalized_label:
            indexes.definitions.setdefault(normalized_label, item)
        if item.kind == "symbol" or (
            _is_symbol_label(item.label)
            and re.search(
                r"\b(represents?|means?|significa|representa|denotes?|indicates?|"
                r"can\s+be\s+used\s+to\s+(?:indicate|represent)|is\s+used\s+to|"
                r"can\s+match\s+to)\b",
                item.text,
                re.I,
            )
        ):
            symbol = item.label.strip()
            if symbol:
                indexes.symbols.setdefault(symbol, item)
                # Símbolos nombrados en el texto ("& representa...") también indexan.
        for symbol_match in re.finditer(
            r"[\"'«“(\[]?\s*(?P<sym>&|\*|\?|%|#|\$|@|!|~|\^)\s*[\"'»”) \]]?\s*"
            r"(?P<verb>"
            r"can\s+be\s+used\s+to\s+(?:indicate|represent|mean|match|specify)|"
            r"may\s+be\s+used\s+to\s+(?:indicate|represent|mean|match|specify)|"
            r"is\s+used\s+to\s+(?:indicate|represent|mean|match|specify)|"
            r"are\s+used\s+to\s+(?:indicate|represent|mean|match|specify)|"
            r"can\s+match\s+to|may\s+match\s+to|"
            r"represents?|means?|significa|representa|denotes?|indicates?|matches?|"
            r"stands?\s+for|es|son|is|are"
            r")\b",
            item.text,
            re.IGNORECASE,
        ):
            indexes.symbols.setdefault(symbol_match.group("sym"), item)
        if item.kind in ("section",) and normalized_label:
            indexes.sections.setdefault(normalized_label, item)
        logic = analyze_language(item.text).logic
        operators = {entry.operator for entry in logic}
        if LogicOperator.UNLESS.value in operators or LogicOperator.EXCEPTION.value in operators:
            indexes.exceptions.append(item)
        elif item.kind in ("warning", "note") and re.search(
            r"\b(except|unless|does\s+not\s+apply|no\s+aplica|salvo|excepto)\b",
            item.text,
            re.IGNORECASE,
        ):
            indexes.exceptions.append(item)
        if item.kind == "example" or is_example(item.text):
            indexes.examples.append(item)
    return indexes


# -----------------------------------------------------------------------------
# Construcción de candidatos
# -----------------------------------------------------------------------------


def _modality_from_candidate(value: str) -> tuple[str, str]:
    mapping = {
        "must": (ModalityKind.MUST.value, Polarity.POSITIVE.value),
        "must_not": (ModalityKind.MUST_NOT.value, Polarity.NEGATIVE.value),
        "constraint": (ModalityKind.CONSTRAINT.value, Polarity.POSITIVE.value),
        "should": (ModalityKind.SHOULD.value, Polarity.POSITIVE.value),
        "may": (ModalityKind.MAY.value, Polarity.POSITIVE.value),
    }
    return mapping.get(str(value or "").lower(), (ModalityKind.NONE.value, Polarity.UNKNOWN.value))


def _ensure_modality(
    analysis: StatementAnalysis,
    evidence_id: str,
    fallback: tuple[str, str],
) -> None:
    prop = analysis.properties.get("modality")
    if prop is None or not prop.known:
        modality, polarity = fallback
        if modality == ModalityKind.NONE.value:
            return
        analysis.properties["modality"] = RuleProperty(
            name="modality",
            value=modality,
            evidence=[evidence_id],
            confidence=0.7,
            note="modalidad detectada por el pipeline normativo existente",
        )
        analysis.properties["polarity"] = RuleProperty(
            name="polarity",
            value=polarity,
            evidence=[evidence_id],
            confidence=0.7,
        )


def _attach_distributed_context(
    candidate: CandidateRule,
    analysis: StatementAnalysis,
    indexes: _Indexes,
) -> None:
    """Une definiciones, símbolos, excepciones, ejemplos y referencias."""
    relations: dict[str, list[str]] = {}
    text_tokens = _tokens(candidate.statement + " " + candidate.subject)

    # Definiciones usadas por la regla (pueden vivir en otra página/sección).
    for term, item in indexes.definitions.items():
        if len(term) >= 3 and term in candidate.statement.lower() and item.evidence_id not in candidate.evidence_ids:
            candidate.evidence.append(item.to_evidence(role="definition"))
            relations.setdefault("DEPENDS_ON", []).append(item.evidence_id)
            relations.setdefault("DEFINES", []).append(item.item_id)

    # Símbolos definidos antes / en otra sección.
    symbols_in_statement: set[str] = set()
    for symbol in indexes.symbols:
        if symbol and symbol in candidate.statement:
            symbols_in_statement.add(symbol)
    for symbol in sorted(symbols_in_statement):
        item = indexes.symbols[symbol]
        meaning = analyze_language(item.text)
        property_name = f"matching.symbol.{symbol}"
        definition_text = item.text or item.label
        if property_name not in analysis.properties:
            analysis.properties[property_name] = RuleProperty(
                name=property_name,
                value=definition_text[:200],
                layer=ClaimLayer.INFERRED.value,
                state=VerificationState.PROPOSED.value,
                evidence=[item.evidence_id],
                explicit=True,
                matched_text=item.label,
                note="definición de símbolo usada por la regla",
            )
        if item.evidence_id not in candidate.evidence_ids:
            candidate.evidence.append(item.to_evidence(role="symbol_definition"))
        relations.setdefault("USES_SYMBOL", []).append(item.evidence_id)
        if meaning.match.alphabet:
            analysis.properties.setdefault(
                f"matching.symbol.{symbol}.alphabet",
                RuleProperty(
                    name=f"matching.symbol.{symbol}.alphabet",
                    value=meaning.match.alphabet,
                    evidence=[item.evidence_id],
                    explicit=True,
                    matched_text=symbol,
                ),
            )

    # Excepciones alejadas (otra página/sección) por solapamiento de términos.
    source_item = getattr(candidate, "_source_item", None)
    source_evidence_id = str(source_item.evidence_id) if source_item is not None else ""
    for item in indexes.exceptions:
        if item.evidence_id in candidate.evidence_ids:
            continue
        if item.evidence_id == source_evidence_id:
            continue
        if _overlap(item.text, candidate.statement) >= 1 or (
            candidate.subject and _overlap(item.text, candidate.subject) >= 1
        ):
            exception_text = " ".join(item.text.split())[:400]
            if exception_text and exception_text not in candidate.exceptions:
                candidate.exceptions.append(exception_text)
                candidate.evidence.append(item.to_evidence(role="exception"))
                relations.setdefault("HAS_EXCEPTION", []).append(item.evidence_id)

    # Ejemplos: evidencia ilustrativa, NUNCA regla.
    for item in indexes.examples:
        if item.evidence_id in candidate.evidence_ids:
            continue
        if _overlap(item.text, candidate.statement) >= 2:
            candidate.corroborating.append(item.to_evidence(role="illustration"))
            relations.setdefault("HAS_EXAMPLE", []).append(item.evidence_id)

    if relations:
        candidate.relations.update(relations)


def _resolve_references(
    candidate: CandidateRule,
    analysis: StatementAnalysis,
    indexes: _Indexes,
    items: Sequence[RuleContextItem],
) -> None:
    """Referencias cruzadas ('see section X'): resolved -> evidencia adjunta."""
    for name, prop in list(analysis.properties.items()):
        if not name.startswith("reference.target") or not prop.known:
            continue
        target = str(prop.value).lower()
        resolved_item = None
        for section_name, item in indexes.sections.items():
            if target and (target in section_name or section_name in target):
                resolved_item = item
                break
        if resolved_item is None:
            for item in items:
                if target and target in item.label.lower() and len(item.label) >= 3:
                    resolved_item = item
                    break
        if resolved_item is not None:
            prop.evidence.append(resolved_item.evidence_id)
            prop.missing_premises = [value for value in prop.missing_premises if not value.startswith("reference:")]
            candidate.relations.setdefault("REFERENCES", []).append(resolved_item.evidence_id)
            if resolved_item.evidence_id not in candidate.evidence_ids:
                candidate.evidence.append(resolved_item.to_evidence(role="reference"))
            candidate.missing_premises = [
                value for value in candidate.missing_premises if not value.startswith("reference:")
            ]
            analysis.missing_premises = [
                value for value in analysis.missing_premises if not value.startswith("reference:")
            ]
        else:
            candidate.relations.setdefault("UNRESOLVED_REFERENCE", []).append(str(prop.value))


def _merge_analysis_into_candidate(
    candidate: CandidateRule,
    analysis: StatementAnalysis,
) -> None:
    for name, prop in analysis.properties.items():
        candidate.properties.setdefault(name, prop)
    candidate.kind = analysis.kind
    candidate.formula = analysis.formula
    candidate.enumeration = analysis.enumeration
    candidate.temporal = analysis.temporal
    for exception in analysis.exceptions:
        if exception not in candidate.exceptions:
            candidate.exceptions.append(exception)
    for missing in analysis.missing_premises:
        if missing not in candidate.missing_premises:
            candidate.missing_premises.append(missing)
    for ambiguity in analysis.ambiguities:
        if ambiguity not in candidate.ambiguities:
            candidate.ambiguities.append(ambiguity)
    candidate.operator = analysis.operator


def _parse_scope_date(raw: str) -> str | None:
    """Fecha de vigencia de un enunciado -> ISO (o None)."""
    text = " ".join(str(raw or "").split())
    if not text:
        return None
    try:
        from src.knowledge.compiler.temporal import parse_date, parse_month

        parsed = parse_date(text) or parse_month(text)
        return parsed.isoformat() if parsed else None
    except Exception:  # noqa: BLE001 — fecha inválida no inventa vigencia
        return None


def _subject_from_section(    section_path: tuple[str, ...], statement: str, fallback: str
) -> str:
    for part in reversed(section_path):
        candidate = " ".join(str(part or "").split())
        if len(candidate) >= 3:
            return candidate[:200]
    first = re.split(r"[:.\n]", statement.strip(), maxsplit=1)[0]
    words = first.split()
    if words:
        return " ".join(words[:8])[:200]
    return fallback


def build_candidates(
    *,
    document_id: str = "",
    document_title: str = "",
    units: Sequence[Any] = (),
    rule_candidates: Sequence[Any] = (),
    extra_items: Sequence[Any] = (),
    max_candidates: int = MAX_CANDIDATES,
) -> tuple[list[CandidateRule], _Indexes]:
    """Unidades + candidatos normativos -> CandidateRule con provenance unida."""
    items = context_items_from_units(units, document_id=document_id, source_key=document_title)
    items.extend(
        context_items_from_generic(extra_items, document_id=document_id, source_key=document_title)
    )
    indexes = build_indexes(items)

    # Indice por locator/block para encontrar la pieza fuente de un RuleCandidate.
    by_block: dict[str, RuleContextItem] = {}
    by_excerpt: dict[str, RuleContextItem] = {}
    for item in items:
        if item.block_id:
            by_block.setdefault(item.block_id, item)
        normalized = " ".join(item.text.lower().split())[:160]
        if normalized:
            by_excerpt.setdefault(normalized, item)

    candidates: list[CandidateRule] = []
    seen: set[str] = set()

    def add_candidate(
        *,
        statement: str,
        subject: str,
        source_item: RuleContextItem,
        extra_evidence: Iterable[RuleEvidence] = (),
        modality_fallback: tuple[str, str] = (ModalityKind.NONE.value, Polarity.UNKNOWN.value),
        confidence: float = 0.75,
    ) -> CandidateRule | None:
        text = " ".join(str(statement or "").split())
        if len(text) < 12 or len(candidates) >= max_candidates:
            return None
        candidate_id = stable_id("cand", document_id, subject.lower(), text.lower()[:400])
        if candidate_id in seen:
            return None
        seen.add(candidate_id)
        analysis = analyze_statement(text, evidence_id=source_item.evidence_id)
        _ensure_modality(analysis, source_item.evidence_id, modality_fallback)
        modality_prop = analysis.properties.get("modality")
        modality = (
            str(modality_prop.value)
            if modality_prop is not None and modality_prop.known
            else ModalityKind.NONE.value
        )
        polarity_prop = analysis.properties.get("polarity")
        polarity = (
            str(polarity_prop.value)
            if polarity_prop is not None and polarity_prop.known
            else Polarity.UNKNOWN.value
        )
        effective_from = None
        if str(analysis.temporal.relation) == "EFFECTIVE_FROM" and analysis.temporal.value:
            effective_from = _parse_scope_date(analysis.temporal.value)
        scope = RuleScope(
            section_path=source_item.section_path,
            document_id=document_id,
            document_title=document_title,
            page_start=source_item.page,
            page_end=source_item.page,
            effective_from=effective_from,
            priority=1 if analysis.scope_priority else None,
            evidence=[source_item.evidence_id],
        )
        candidate = CandidateRule(
            candidate_id=candidate_id,
            statement=text[:2000],
            subject=subject[:200],
            kind=analysis.kind,
            modality=modality,
            polarity=polarity,
            operator=analysis.operator,
            scope=scope,
            arguments=[
                RuleArgument(
                    name="subject",
                    value=subject[:200],
                    role="subject",
                    evidence=[source_item.evidence_id],
                )
            ],
            confidence=max(0.05, min(1.0, confidence * max(0.4, MODALITY_STRENGTH.get(modality, 0.4)))),
        )
        candidate.evidence.append(source_item.to_evidence())
        for entry in extra_evidence:
            if entry.evidence_id and entry.evidence_id not in candidate.evidence_ids:
                candidate.evidence.append(entry)
        candidate._source_item = source_item  # type: ignore[attr-defined]
        _merge_analysis_into_candidate(candidate, analysis)
        _attach_distributed_context(candidate, analysis, indexes)
        _resolve_references(candidate, analysis, indexes, items)
        # Reunir missing de properties.
        for prop in candidate.properties.values():
            for missing in prop.missing_premises:
                if missing not in candidate.missing_premises:
                    candidate.missing_premises.append(missing)
        candidate.missing_premises = list(dict.fromkeys(candidate.missing_premises))[:24]
        candidates.append(candidate)
        return candidate

    # 1. Candidatos normativos ya detectados por el Knowledge Compiler.
    for rule in rule_candidates or ():
        statement = str(getattr(rule, "statement", "") or "")
        subject = str(getattr(rule, "subject", "") or "")
        locator = _locator_dict((getattr(rule, "evidence", None) or [None])[0])
        block_id = str(locator.get("block_id") or "")
        source_item = by_block.get(block_id) if block_id else None
        if source_item is None:
            normalized = " ".join(statement.lower().split())[:160]
            source_item = by_excerpt.get(normalized)
        if source_item is None:
            evidence_id = stable_id(
                "ev", document_id, locator.get("locator") or "candidate", "rule", subject
            )
            source_item = RuleContextItem(
                item_id=f"rule:{subject}"[:200],
                kind="rule",
                label=subject,
                text=statement,
                evidence_id=evidence_id,
                locator=locator,
                section_path=tuple(locator.get("section_path") or ()),
                page=locator.get("page"),
                block_id=block_id,
                source_key=str(locator.get("document_title") or document_title),
            )
        extra: list[RuleEvidence] = []
        for evidence in getattr(rule, "evidence", ()) or ():
            ref_locator = _locator_dict(evidence)
            ref_id = stable_id(
                "ev",
                document_id,
                ref_locator.get("locator") or "source/unknown",
                "rule",
                str(getattr(rule, "rule_key", "") or subject),
            )
            if ref_id != source_item.evidence_id:
                extra.append(
                    RuleEvidence(
                        evidence_id=ref_id,
                        locator=ref_locator,
                        excerpt=str(getattr(evidence, "excerpt", "") or statement),
                        unit_id=f"rule:{subject}",
                        source_key=document_title,
                        role="secondary",
                        strength=0.7,
                    )
                )
        fallback = _modality_from_candidate(str(getattr(rule, "modality", "") or ""))
        resolved_subject = subject or _subject_from_section(
            source_item.section_path, statement, document_title or "documento"
        )
        add_candidate(
            statement=statement,
            subject=resolved_subject,
            source_item=source_item,
            extra_evidence=extra,
            modality_fallback=fallback,
            confidence=float(getattr(rule, "confidence", 0.75) or 0.75),
        )

    # 2. Unidades normativas que el detector no capturó (p.ej. "only if") y
    #    unidades de definición/mapping/constraint/fórmula/excepción: son
    #    conocimiento canónico; los EJEMPLOS nunca son regla.
    for item in items:
        text = item.text
        if not text or item.kind in ("example",):
            continue
        kind = classify_statement_kind(text)
        normative = is_normative(text, min_length=24)
        if kind == RuleKind.EXAMPLE.value:
            continue
        if not normative and kind not in (
            RuleKind.DEFINITION.value,
            RuleKind.MAPPING.value,
            RuleKind.CONSTRAINT.value,
            RuleKind.FORMULA.value,
            RuleKind.EXCEPTION.value,
        ):
            continue
        if item.kind in ("warning", "note") and not normative:
            continue
        subject = _subject_from_section(item.section_path, text, item.label or document_title)
        add_candidate(
            statement=text,
            subject=subject,
            source_item=item,
            confidence=0.7 if normative else 0.6,
        )

    # Excepción sin solape léxico con ninguna regla: si hay UNA sola regla
    # normativa, se adjunta (evidencia distribuida). Con varias reglas no se
    # crea un vínculo arbitrario: la cobertura queda incompleta y visible.
    unreferenced = [
        item
        for item in indexes.exceptions
        if item.evidence_id
        not in {
            evidence_id
            for candidate in candidates
            for evidence_id in candidate.evidence_ids
        }
    ]
    normative = [
        candidate
        for candidate in candidates
        if candidate.kind
        in (
            RuleKind.NORMATIVE_RULE.value,
            RuleKind.CONSTRAINT.value,
            RuleKind.FORMULA.value,
        )
        and not candidate.exceptions
    ]
    if len(normative) == 1:
        target = normative[0]
        for item in unreferenced:
            text = " ".join(item.text.split())[:400]
            if not text or text in target.exceptions:
                continue
            target.exceptions.append(text)
            target.evidence.append(item.to_evidence(role="exception"))
            target.relations.setdefault("HAS_EXCEPTION", []).append(item.evidence_id)
            if "exception_condition" not in target.missing_premises:
                target.missing_premises.append("exception_condition")

    return candidates, indexes


def candidate_public_stats(candidates: Sequence[CandidateRule]) -> dict:
    by_kind: dict[str, int] = {}
    for candidate in candidates:
        by_kind[candidate.kind] = by_kind.get(candidate.kind, 0) + 1
    return {
        "total": len(candidates),
        "by_kind": by_kind,
        "with_exceptions": sum(1 for candidate in candidates if candidate.exceptions),
        "with_missing_premises": sum(1 for candidate in candidates if candidate.missing_premises),
    }


__all__ = [
    "MAX_CANDIDATES",
    "RuleContextItem",
    "build_candidates",
    "build_indexes",
    "candidate_public_stats",
    "context_items_from_generic",
    "context_items_from_units",
]
