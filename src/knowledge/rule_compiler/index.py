# =============================================================================
# Canonical Rule Index — representación recuperable de una CanonicalRule
# =============================================================================
# Las CanonicalRules son conocimiento de primera clase: su descubrimiento no
# puede depender de que un raw chunk recuperado casualmente traiga
# `canonical_rule_ids`. Este módulo construye una representación determinista
# e independiente de dominio para recuperarlas por SÍ MISMAS (statement,
# operador, propiedades semánticas, símbolos, alcance, alias, entidades).
#
# La AUTORIDAD sigue siendo la CanonicalRule persistida en
# knowledge_canonical_objects; este índice es solo discovery. El documento de
# índice se persiste como `metadata.retrieval_index` junto a la regla (sin
# migración) y también se puede construir desde la regla en memoria.
#
# Determinismo:
#   - mismos campos => mismo `fingerprint` (sha256 de contenido normalizado);
#   - mismo request => mismo orden de candidatos (score, rule_id);
#   - sin listados dependientes del orden de dict: todo se ordena.
# =============================================================================
from __future__ import annotations

import re
from hashlib import sha256
from typing import Any, Iterable, Mapping, Sequence

RULE_INDEX_VERSION = "canonical-rule-index-1"

#: Mismo alfabeto de comodines que la gramática de patrones (pattern.py).
_SYMBOL_CHARS = "&*?%#$@!~^"
_SYMBOL_RE = re.compile(rf"[{re.escape(_SYMBOL_CHARS)}]")

_WORD_RE = re.compile(r"[a-z0-9_áéíóúñü]{2,}", re.IGNORECASE)

#: Stopwords ES/EN irrelevantes para el discovery (lista corta y explícita).
_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "that", "this", "from", "are", "was",
        "you", "your", "our", "what", "when", "where", "which", "who",
        "how", "does", "did", "can", "could", "should", "would", "about",
        "into", "than", "then", "they", "there", "their", "have", "has",
        "los", "las", "del", "una", "uno", "unos", "unas", "por", "para",
        "con", "sin", "que", "como", "cuando", "donde", "cual", "cuales",
        "este", "esta", "estos", "estas", "ese", "esa", "esos", "esas",
        "puede", "pueden", "debe", "deben", "ser", "está", "son",
        "es", "el", "la", "en", "de", "y", "o", "a", "al",
    }
)

#: Nombres de propiedades que declaran alias/conceptos de la regla.
_ALIAS_PROPERTIES = (
    "alias",
    "aliases",
    "concept",
    "concepts",
    "entity",
    "entities",
    "field",
    "fields",
    "term",
    "terms",
    "synonym",
    "synonyms",
)


def normalize_text(value: Any) -> str:
    """Normalización estable (whitespace + minúsculas), nunca semántica."""
    return " ".join(str(value or "").lower().split())


def rule_tokens(text: Any) -> tuple[str, ...]:
    """Tokens deterministas: ordenados, sin stopwords, sin duplicados."""
    found: set[str] = set()
    for match in _WORD_RE.finditer(normalize_text(text)):
        token = match.group(0)
        if token in _STOPWORDS or len(token) < 3:
            continue
        found.add(token)
    return tuple(sorted(found))


def rule_symbols(rule: Any) -> tuple[str, ...]:
    """Símbolos de patrón que la regla declara o menciona (ordenados)."""
    symbols: set[str] = set()
    for name in getattr(rule, "properties", {}) or {}:
        if name.startswith("matching.symbol."):
            suffix = name[len("matching.symbol.") :]
            if suffix.endswith(".alphabet"):
                continue
            if suffix:
                symbols.add(suffix)
    texts: list[str] = [
        str(getattr(rule, "statement", "") or ""),
        str(getattr(rule, "subject", "") or ""),
    ]
    for argument in getattr(rule, "arguments", ()) or ():
        texts.append(str(getattr(argument, "value", "") or ""))
    for prop in (getattr(rule, "properties", {}) or {}).values():
        value = getattr(prop, "value", None)
        if isinstance(value, (str, int, float)):
            texts.append(str(value))
    for text in texts:
        for symbol in _SYMBOL_RE.findall(text):
            symbols.add(symbol)
    return tuple(sorted(symbols))


#: Niveles de uso de símbolo (mencionar != definir != ejecutar).
SYMBOL_MENTIONED = "mentioned"
SYMBOL_DEFINED = "defined"
SYMBOL_EXECUTABLE = "executable"

_SYMBOL_LEVEL_ORDER: dict[str, int] = {
    SYMBOL_MENTIONED: 0,
    SYMBOL_DEFINED: 1,
    SYMBOL_EXECUTABLE: 2,
}

#: Sufijos de propiedad que NO son la definición canónica del símbolo.
_NON_DEFINITION_SUFFIXES = (".alphabet", ".unmerged", ".superseded")


def _max_symbol_level(current: str | None, candidate: str) -> str:
    if current is None:
        return candidate
    if _SYMBOL_LEVEL_ORDER[candidate] > _SYMBOL_LEVEL_ORDER[current]:
        return candidate
    return current


def rule_symbol_usage(rule: Any) -> dict[str, str]:
    """Símbolo -> nivel de uso semántico por parte de la regla.

    - executable: `matching.symbol.X` definido Y con `matching.operator`/mode
      (la regla puede EJECUTAR el símbolo, no solo nombrarlo);
    - defined: `matching.symbol.X` definido sin operador de matching;
    - mentioned: el símbolo solo aparece en statement/subject/props/conditions.

    El ranking NUNCA debe tratar `mentioned` como `executable`.
    """
    properties = getattr(rule, "properties", {}) or {}
    has_matching_operator = False
    has_matching_mode = False
    for name, prop in properties.items():
        if not getattr(prop, "known", False):
            continue
        text_name = str(name)
        if text_name == "matching.operator":
            has_matching_operator = True
        elif text_name.startswith("matching.mode"):
            has_matching_mode = True
    executable_level = has_matching_operator or has_matching_mode

    usage: dict[str, str] = {}
    for name, prop in properties.items():
        text_name = str(name)
        if not text_name.startswith("matching.symbol."):
            continue
        if not getattr(prop, "known", False):
            continue
        suffix = text_name[len("matching.symbol.") :]
        if not suffix or suffix.endswith(_NON_DEFINITION_SUFFIXES):
            continue
        level = SYMBOL_EXECUTABLE if executable_level else SYMBOL_DEFINED
        usage[suffix] = _max_symbol_level(usage.get(suffix), level)

    texts: list[str] = [
        str(getattr(rule, "statement", "") or ""),
        str(getattr(rule, "subject", "") or ""),
    ]
    for argument in getattr(rule, "arguments", ()) or ():
        texts.append(str(getattr(argument, "value", "") or ""))
    for item in getattr(rule, "conditions", ()) or ():
        texts.append(str(item))
    for prop in properties.values():
        value = getattr(prop, "value", None)
        if isinstance(value, (str, int, float)):
            texts.append(str(value))
    for text in texts:
        for symbol in _SYMBOL_RE.findall(text):
            if symbol not in usage:
                usage[symbol] = SYMBOL_MENTIONED
    return {name: usage[name] for name in sorted(usage)}


def _known_properties(rule: Any) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for name in sorted((getattr(rule, "properties", {}) or {}).keys()):
        prop = rule.properties[name]
        if not getattr(prop, "known", False):
            continue
        properties[str(name)] = getattr(prop, "value", None)
    return properties


def _alias_terms(rule: Any) -> tuple[str, ...]:
    terms: set[str] = set()
    for name, value in _known_properties(rule).items():
        base = name.split(".")[0]
        if base in _ALIAS_PROPERTIES:
            values = value if isinstance(value, (list, tuple, set)) else [value]
            for item in values:
                text = normalize_text(item)
                if text:
                    terms.add(text[:120])
    for argument in getattr(rule, "arguments", ()) or ():
        text = normalize_text(getattr(argument, "value", ""))
        if text and len(text) >= 3:
            terms.add(text[:120])
    return tuple(sorted(terms))


def rule_index_document(rule: Any) -> dict:
    """Representación recuperable y serializable de una CanonicalRule."""
    scope = getattr(rule, "scope", None)
    temporal = getattr(rule, "temporal", None)
    provenance = list(getattr(rule, "provenance", ()) or ())
    document: dict[str, Any] = {
        "rule_index_version": RULE_INDEX_VERSION,
        "rule_id": str(getattr(rule, "rule_id", "") or ""),
        "subject": normalize_text(getattr(rule, "subject", ""))[:300],
        "statement_normalized": normalize_text(getattr(rule, "statement", ""))[:1200],
        "rule_kind": str(getattr(rule, "kind", "") or ""),
        "operator": str(getattr(rule, "operator", "") or ""),
        "modality": str(getattr(rule, "modality", "") or ""),
        "conditions": [
            normalize_text(item)[:240] for item in (getattr(rule, "conditions", ()) or ())
        ][:12],
        "exceptions": [
            normalize_text(item)[:240] for item in (getattr(rule, "exceptions", ()) or ())
        ][:12],
        "scope": {
            "section_path": [str(item) for item in (getattr(scope, "section_path", ()) or ())][:8],
            "document_id": str(getattr(scope, "document_id", "") or ""),
            "document_title": str(getattr(scope, "document_title", "") or "")[:200],
            "version_label": str(getattr(scope, "version_label", "") or ""),
            "effective_from": getattr(scope, "effective_from", None),
            "effective_to": getattr(scope, "effective_to", None),
            "applies_to": [str(item) for item in (getattr(scope, "applies_to", ()) or ())][:8],
        },
        "semantic_properties": _known_properties(rule),
        "symbols": list(rule_symbols(rule)),
        "temporal": {
            "relation": str(getattr(temporal, "relation", "") or ""),
            "value": str(getattr(temporal, "value", "") or ""),
            "upper": str(getattr(temporal, "upper", "") or ""),
        },
        "aliases": list(_alias_terms(rule)),
        "provenance_refs": [
            {
                "evidence_id": str(getattr(item, "evidence_id", "") or ""),
                "unit_id": str(getattr(item, "unit_id", "") or ""),
                "document_id": str((getattr(item, "locator", {}) or {}).get("document_id") or ""),
                "page": (getattr(item, "locator", {}) or {}).get("page"),
                "section_path": [
                    str(part)
                    for part in ((getattr(item, "locator", {}) or {}).get("section_path") or ())
                ][:8],
            }
            for item in provenance[:16]
        ],
        "verification_state": str(getattr(rule, "verification_state", "") or ""),
        "executable": bool(getattr(rule, "executable", False)),
        "confidence": round(float(getattr(rule, "confidence", 0.0) or 0.0), 4),
        "rule_version": str(getattr(rule, "version", "") or ""),
    }
    document["fingerprint"] = _fingerprint_of(document)
    return document


def _fingerprint_of(document: Mapping[str, Any]) -> str:
    material = "|".join(
        f"{key}={_stable_value(document.get(key))}"
        for key in sorted(document)
        if key != "fingerprint"
    )
    return sha256(material.encode("utf-8")).hexdigest()[:32]


def _stable_value(value: Any) -> str:
    if isinstance(value, Mapping):
        return "{" + ",".join(
            f"{key}:{_stable_value(value[key])}" for key in sorted(value)
        ) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_stable_value(item) for item in value) + "]"
    return normalize_text(value)


def rule_fingerprint(rule: Any) -> str:
    """Huella determinista del contenido semántico de la regla."""
    return str(rule_index_document(rule)["fingerprint"])


def rule_search_text(rule: Any) -> str:
    """Texto normalizado para ranking léxico (determinista)."""
    parts: list[str] = [
        str(getattr(rule, "rule_id", "") or ""),
        str(getattr(rule, "subject", "") or ""),
        str(getattr(rule, "statement", "") or ""),
        str(getattr(rule, "kind", "") or ""),
        str(getattr(rule, "operator", "") or ""),
        str(getattr(rule, "modality", "") or ""),
    ]
    for name in sorted((getattr(rule, "properties", {}) or {}).keys()):
        prop = rule.properties[name]
        if not getattr(prop, "known", False):
            continue
        parts.append(name)
        value = getattr(prop, "value", None)
        if isinstance(value, (list, tuple, set)):
            parts.extend(str(item) for item in sorted(str(v) for v in value))
        elif isinstance(value, dict):
            parts.extend(f"{k}={value[k]}" for k in sorted(value))
        else:
            parts.append(str(value))
    for argument in getattr(rule, "arguments", ()) or ():
        parts.append(str(getattr(argument, "value", "") or ""))
    for item in (getattr(rule, "conditions", ()) or ()):
        parts.append(str(item))
    for item in (getattr(rule, "exceptions", ()) or ()):
        parts.append(str(item))
    scope = getattr(rule, "scope", None)
    if scope is not None:
        parts.append(str(getattr(scope, "document_title", "") or ""))
        parts.extend(str(part) for part in (getattr(scope, "section_path", ()) or ()))
        parts.extend(str(part) for part in (getattr(scope, "applies_to", ()) or ()))
    return normalize_text(" ".join(parts))


#: Intención de operación -> operadores compatibles (genérico, sin dominio).
_OPERATORS_BY_INTENT: dict[str, tuple[str, ...]] = {
    "APPLY_RULE": ("POSITIONAL_MATCH", "MATCH", "LITERAL", "PREFIX", "SUFFIX", "ENUM", "RANGE"),
    "VALIDATE": ("POSITIONAL_MATCH", "MATCH", "LITERAL", "PREFIX", "SUFFIX", "ENUM", "RANGE"),
    "COMPARE": ("COMPARISON", "RANGE", "ORDERING"),
    "CALCULATE": ("FORMULA", "ARITHMETIC", "UNIT_CONVERSION"),
    "ELIGIBILITY": ("BOOLEAN", "CONDITION", "ENUM"),
    "MATCH": ("POSITIONAL_MATCH", "MATCH"),
    "RANGE_CHECK": ("RANGE", "COMPARISON"),
    "DATE_RULE": ("TEMPORAL", "DATE"),
    "ENUM_CHECK": ("ENUM", "SET"),
}


def rank_rule(
    rule: Any,
    *,
    tokens: Sequence[str] = (),
    anchors: Sequence[str] = (),
    entities: Sequence[str] = (),
    concepts: Sequence[str] = (),
    symbols: Sequence[str] = (),
    intent: str = "",
) -> tuple[float, tuple[str, ...]]:
    """Score determinista + motivos legibles (ordenados)."""
    subject = normalize_text(getattr(rule, "subject", ""))
    statement = normalize_text(getattr(rule, "statement", ""))
    search_text = rule_search_text(rule)
    properties = _known_properties(rule)
    symbol_usage = rule_symbol_usage(rule)
    score = 0.0
    reasons: list[str] = []

    if tokens:
        hit_tokens: list[str] = []
        for token in tokens:
            if not token:
                continue
            weight = 0.0
            if token in subject:
                weight = 4.0
            elif token in statement:
                weight = 2.5
            elif token in search_text:
                weight = 1.0
            if weight:
                score += weight
                hit_tokens.append(token)
        if hit_tokens:
            reasons.append("lexical:" + ",".join(sorted(hit_tokens)[:6]))

    for anchor in anchors:
        text = normalize_text(anchor)
        if not text or len(text) < 2:
            continue
        if text in statement or text in subject or text in search_text:
            score += 5.0
            reasons.append(f"anchor:{text[:40]}")

    # Símbolo: MENCIONARLO no vale lo mismo que DEFINIRLO ni que EJECUTARLO.
    # Un statement que nombra `&` no puede competir con la gramática que lo
    # ejecuta (`matching.symbol.&` + `matching.operator`).
    for symbol in symbols:
        if not symbol:
            continue
        level = symbol_usage.get(symbol)
        if level == SYMBOL_EXECUTABLE:
            score += 10.0
            reasons.append(f"symbol:{symbol}:executable")
        elif level == SYMBOL_DEFINED:
            score += 4.0
            reasons.append(f"symbol:{symbol}:defined")
        elif level == SYMBOL_MENTIONED:
            score += 1.5
            reasons.append(f"symbol:{symbol}:mentioned")

    for entity in entities:
        text = normalize_text(entity)
        if text and text in search_text:
            score += 3.0
            reasons.append(f"entity:{text[:40]}")

    for concept in concepts:
        text = normalize_text(concept)
        if text and text in search_text:
            score += 2.0
            reasons.append(f"concept:{text[:40]}")

    compatible = _OPERATORS_BY_INTENT.get(intent.upper(), ())
    operator = str(getattr(rule, "operator", "") or "")
    if compatible and operator:
        if any(item.lower() in operator.lower() for item in compatible):
            score += 2.0
            reasons.append(f"operator:{operator}")

    state = str(getattr(rule, "verification_state", "") or "")
    if state == "SUPPORTED":
        score += 8.0
        reasons.append("verification:SUPPORTED")
    elif state == "CONFLICTING":
        score -= 12.0
        reasons.append("verification:CONFLICTING")
    if getattr(rule, "executable", False):
        score += 4.0
        reasons.append("executable")

    return round(score, 4), tuple(sorted(reasons))


def merge_rule_candidates(
    hits: Iterable[tuple[Any, float, str]],
    *,
    max_rules: int = 24,
) -> list[Any]:
    """Fusiona candidatos de ambos carriles con orden determinista.

    `hits` es (rule, score, source). El mismo `rule_id` conserva la mejor
    fuente/score; el orden final nunca depende del orden de llegada.
    """
    best: dict[str, tuple[Any, float, str]] = {}
    for rule, score, source in hits:
        rule_id = str(getattr(rule, "rule_id", "") or "")
        if not rule_id:
            continue
        current = best.get(rule_id)
        if current is None or score > current[1] or (
            score == current[1] and source < current[2]
        ):
            best[rule_id] = (rule, float(score), source)
    ordered = sorted(best.values(), key=lambda item: (-item[1], str(item[0].rule_id)))
    return [item[0] for item in ordered[:max_rules]]


def query_tokens(question: Any, extra: Iterable[Any] = ()) -> tuple[str, ...]:
    """Tokens de la pregunta (ordenados) + términos explícitos del caller."""
    tokens = set(rule_tokens(question))
    for value in extra:
        tokens.update(rule_tokens(value))
    return tuple(sorted(tokens))


def query_symbols(question: Any, patterns: Iterable[Any] = ()) -> tuple[str, ...]:
    """Símbolos de patrón presentes en la pregunta o en sus patrones runtime."""
    symbols: set[str] = set()
    for text in [question, *patterns]:
        for symbol in _SYMBOL_RE.findall(str(text or "")):
            symbols.add(symbol)
    return tuple(sorted(symbols))


__all__ = [
    "RULE_INDEX_VERSION",
    "SYMBOL_DEFINED",
    "SYMBOL_EXECUTABLE",
    "SYMBOL_MENTIONED",
    "merge_rule_candidates",
    "normalize_text",
    "query_symbols",
    "query_tokens",
    "rank_rule",
    "rule_fingerprint",
    "rule_index_document",
    "rule_search_text",
    "rule_symbol_usage",
    "rule_symbols",
    "rule_tokens",
]
