# =============================================================================
# Evidence Requirements — qué necesita la respuesta para estar completa
# =============================================================================
# Antes del retrieval la pregunta se descompone en requerimientos genéricos:
# anchors exactos, entidades nombradas, cláusulas de la pregunta y estructura
# pedida (tabla/nota/fórmula). Encontrar «&&&F» no vuelve la evidencia
# suficiente: cada requirement se evalúa FOUND / PARTIAL / MISSING /
# CONFLICTING. Sin dominio: todo por forma y heurística de idioma.
# =============================================================================
from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from src.intelligence.response.anchors import Anchor

_STOPWORDS = frozenset(
    {
        "de", "la", "el", "los", "las", "un", "una", "unos", "unas", "y", "o",
        "que", "en", "a", "con", "para", "por", "es", "son", "del", "al", "se",
        "no", "si", "como", "su", "sus", "lo", "le", "cual", "cuales",
        "cuando", "donde", "quien", "the", "of", "and", "or", "to",
        "in", "on", "for", "with", "is", "are", "was", "were", "be", "does",
        "do", "did", "how", "what", "which", "when", "where", "who",
    }
)
_CLAUSE_SPLIT_RE = re.compile(r"(?:\?|¿|¡|!|;|:|\by\b|\band\b|\bo\b|\bor\b)")
_TOKEN_RE = re.compile(r"[a-z0-9&*%#._-]{2,}")
_TABLE_HINT_RE = re.compile(
    r"\b(tabla|table|record|registro|byte|campo|field|columna|column|fila|row)\b",
    re.IGNORECASE,
)
_NOTE_HINT_RE = re.compile(
    r"\b(nota|note|footnote|pie de p[aá]gina|ejemplo|example|caption)\b",
    re.IGNORECASE,
)
_FORMULA_HINT_RE = re.compile(r"\b(f[oó]rmula|formula|ecuaci[oó]n|equation)\b", re.IGNORECASE)

#: Cláusulas que son el PEDIDO de la pregunta, no una premisa documental.
_ASK_TOKENS: frozenset[str] = frozenset(
    {
        "cumple", "cumplir", "cumpliria", "cumpliría", "aplica", "aplicar",
        "funciona", "funcionaria", "funcionaría", "sirve", "valida", "validar",
        "corresponde", "pasa", "ocurre", "match", "matches", "applies", "apply",
        "works", "eligible", "valido", "válido", "califica",
    }
)

#: Palabras de ENCUADRE de la pregunta («cuéntame sobre…», «dime acerca de…»):
#: piden la explicación, no son premisas documentales. Genérico, sin dominio.
_FRAMING_TOKENS: frozenset[str] = frozenset(
    {
        "cuentame", "cuentanos", "contame", "dime", "diganos", "decime",
        "explicame", "explicanos", "explica", "explicar", "hablame", "hablar",
        "muestrame", "mostrar", "describe", "describir", "detalla", "detallar",
        "resumeme", "resume", "resumen", "sobre", "acerca", "respecto",
        "tell", "about", "explain", "show", "summary", "summarize",
        "information", "informacion", "info", "mas",
    }
)


class RequirementState(StrEnum):
    FOUND = "found"
    PARTIAL = "partial"
    MISSING = "missing"
    CONFLICTING = "conflicting"


@dataclass(kw_only=True)
class EvidenceRequirement:
    id: str
    kind: str
    description: str
    needles: tuple[str, ...] = ()
    weight: float = 1.0
    hint: str = ""
    role: str = ""
    #: Suave = no bloquea la suficiencia (prosa larga o cláusula que contiene un
    #: valor de ejemplo del usuario). Igual pondera para la cobertura.
    soft: bool = False
    state: str = RequirementState.MISSING.value
    evidence_ids: tuple[str, ...] = ()
    #: Instancia de patrón (kind="pattern_semantics") y valor de runtime a evaluar.
    pattern: str = ""
    value: str = ""
    symbols: tuple[str, ...] = ()
    #: Aliases del vocabulario cargado (packs de dominio) que materializan el
    #: requirement con otro nombre/idioma («cambio de fechas» → Effective Date).
    aliases: tuple[str, ...] = ()

    @property
    def documentable(self) -> bool:
        """¿Exige aparecer en la documentación? EXAMPLE_VALUE no."""
        if self.kind == "example":
            return False
        if self.role in ("example_value", "example"):
            return False
        return self.weight > 0.0

    @property
    def runtime_data(self) -> bool:
        """Dato del escenario: nunca cuenta como faltante documental."""
        return self.kind in ("example", "runtime_value") or self.role in (
            "example_value",
            "example",
            "runtime_value",
            "runtime_parameter",
        )

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "description": self.description,
            "needles": list(self.needles[:6]),
            "state": self.state,
            "weight": round(self.weight, 3),
        }
        if self.role:
            payload["role"] = self.role
        if self.soft:
            payload["soft"] = True
        if not self.documentable:
            payload["requires_source_match"] = False
        if self.pattern:
            payload["pattern"] = self.pattern
        if self.symbols:
            payload["symbols"] = list(self.symbols)
        return payload


@dataclass(kw_only=True)
class RequirementCoverage:
    requirements: list[EvidenceRequirement] = field(default_factory=list)
    coverage: float = 0.0
    found: int = 0
    partial: int = 0
    missing: int = 0
    conflicting: int = 0
    #: Valores de ejemplo del usuario: se aplican con la regla, no se buscan.
    examples: tuple[str, ...] = ()
    examples_found: tuple[str, ...] = ()
    #: Todas las partes duras (anchor/entidad/cláusula corta) FOUND.
    all_hard_found: bool = False

    @property
    def requested(self) -> int:
        return len(self.requirements)

    @property
    def documentable_requested(self) -> int:
        return sum(1 for requirement in self.requirements if requirement.documentable)

    @property
    def domain_requirements(self) -> tuple[EvidenceRequirement, ...]:
        """Requisitos del DOMINIO (premisas): los únicos que pueden faltar."""
        return tuple(
            requirement
            for requirement in self.requirements
            if requirement.documentable
        )

    @property
    def runtime_requirements(self) -> tuple[EvidenceRequirement, ...]:
        """Datos del escenario: aceptados por definición, nunca 'faltantes'."""
        return tuple(
            requirement
            for requirement in self.requirements
            if requirement.runtime_data
        )

    @property
    def domain_requirement_coverage(self) -> float:
        """Cobertura de premisas del dominio (sin datos de runtime)."""
        domain = self.domain_requirements
        if not domain:
            return 0.0
        total = sum(max(0.0, requirement.weight) for requirement in domain)
        earned = 0.0
        for requirement in domain:
            if requirement.state == RequirementState.FOUND.value:
                earned += max(0.0, requirement.weight)
            elif requirement.state == RequirementState.PARTIAL.value:
                earned += max(0.0, requirement.weight) * 0.5
        return earned / total if total else 0.0

    @property
    def runtime_input_coverage(self) -> float:
        """El dato del usuario se acepta: 1.0 con o sin match en fuentes."""
        return 1.0 if self.runtime_requirements else 0.0

    @property
    def unanswered(self) -> tuple[EvidenceRequirement, ...]:
        """Requirements duros sin cubrir (soft y estructurales no dirigen)."""
        return tuple(
            requirement
            for requirement in self.requirements
            if requirement.documentable
            and not requirement.soft
            and requirement.kind not in ("structural", "example")
            and requirement.state
            in (RequirementState.MISSING.value, RequirementState.CONFLICTING.value)
        )

    @property
    def missing_needles(self) -> tuple[str, ...]:
        needles: list[str] = []
        for requirement in self.unanswered:
            for needle in requirement.needles:
                value = str(needle or "").strip()
                if value and value not in needles:
                    needles.append(value)
        return tuple(needles[:12])

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "requested": self.requested,
            "documentable_requested": self.documentable_requested,
            "coverage": round(self.coverage, 4),
            "found": self.found,
            "partial": self.partial,
            "missing": self.missing,
            "conflicting": self.conflicting,
            "all_hard_found": self.all_hard_found,
            "pending": [
                requirement.description for requirement in self.unanswered[:8]
            ],
            "requirements": [
                requirement.to_public_dict() for requirement in self.requirements[:12]
            ],
        }
        if self.examples:
            payload["examples"] = list(self.examples)
            payload["examples_requires_source_match"] = False
            payload["examples_found_in_evidence"] = list(self.examples_found)
        payload["domain_requirement_coverage"] = round(
            self.domain_requirement_coverage, 4
        )
        payload["runtime_input_coverage"] = round(self.runtime_input_coverage, 4)
        runtime = self.runtime_requirements
        if runtime:
            payload["runtime_data"] = [
                requirement.to_public_dict() for requirement in runtime[:8]
            ]
        return payload


def build_requirements(
    query: str,
    anchors: list[Anchor] | tuple[Anchor, ...] = (),
    entities: list[Any] | tuple[Any, ...] = (),
    *,
    examples: list[str] | tuple[str, ...] = (),
    runtime_value: str = "",
    max_clauses: int = 6,
) -> list[EvidenceRequirement]:
    """Descompone la pregunta en requerimientos evaluables, sin dominio.

    Los tokens que son VALOR DEL USUARIO (rol example_value) se registran como
    `example`: viajan a la búsqueda, pero no exigen aparecer en las fuentes.
    La documentación debe probar la regla y el campo, no el ejemplo concreto.

    Una INSTANCIA DE PATRÓN (rol runtime_pattern) exige la SEMÁNTICA documentada
    de sus símbolos (kind="pattern_semantics"), no su presencia literal.
    """
    from src.rag.longcontext.roles import AnchorRole, assign_roles

    text = html.unescape(query or "")
    requirements: list[EvidenceRequirement] = []
    seen: set[str] = set()

    def _add(requirement: EvidenceRequirement) -> None:
        key = requirement.id.lower()
        if key in seen:
            return
        seen.add(key)
        requirements.append(requirement)

    runtime_needles: list[str] = []
    for anchor in assign_roles(text, list(anchors or ())):
        value = str(getattr(anchor, "value", "") or "").strip()
        if not value:
            continue
        role = str(getattr(anchor, "role", "") or "")
        kind = str(getattr(anchor, "kind", ""))
        if role in (
            AnchorRole.EXAMPLE_VALUE.value,
            AnchorRole.RUNTIME_VALUE.value,
        ):
            _add(
                EvidenceRequirement(
                    id=f"example:{value.lower()}",
                    kind="example",
                    description=f"aplicar la regla documentada al valor {value}",
                    needles=(value,) + tuple(
                        str(needle)
                        for needle in getattr(anchor, "needles", ())
                        if needle and str(needle) != value
                    )[:1],
                    weight=0.0,
                    role=role,
                )
            )
            continue
        if role == AnchorRole.RUNTIME_PATTERN.value:
            from src.intelligence.query_semantics import pattern_semantic_requirements

            runtime_needles.append(value.lower())
            symbols = tuple(
                dict.fromkeys(
                    char
                    for char in value
                    if char in "&*?%#$@!~^"
                )
            )
            _add(
                EvidenceRequirement(
                    id=f"pattern:{value.lower()}",
                    kind="pattern_semantics",
                    description=(
                        f"semántica documentada del patrón {value}"
                        + (
                            f" (símbolos: {' '.join(symbols)})"
                            if symbols
                            else ""
                        )
                    ),
                    needles=(value,),
                    weight=1.0,
                    role=role,
                    pattern=value,
                    value=runtime_value,
                    symbols=symbols,
                    hint="pattern",
                )
            )
            # La semántica derivada completa (matching, longitud, literales)
            # viaja como requisitos suaves: informan la cobertura, no duplican.
            for semantic in pattern_semantic_requirements(value):
                if semantic.startswith("symbol:") or semantic.startswith("definition:"):
                    continue
                _add(
                    EvidenceRequirement(
                        id=f"pattern-sem:{value.lower()}:{semantic}",
                        kind="pattern_policy",
                        description=f"política documentada: {semantic}",
                        weight=0.4,
                        role=role,
                        pattern=value,
                        value=runtime_value,
                        symbols=symbols,
                        hint="pattern",
                        soft=True,
                    )
                )
            continue
        weight = 1.2 if kind in ("mascara", "rango") else (1.0 if kind == "sigla" else 1.0)
        _add(
            EvidenceRequirement(
                id=f"anchor:{value.lower()}",
                kind="anchor",
                description=f"evidencia literal de {value}",
                needles=tuple(
                    str(needle) for needle in getattr(anchor, "needles", ()) if needle
                )
                or (value,),
                weight=weight,
                role=role,
                # Una máscara puede acreditarse por su gramática documentada
                # aunque la instancia concreta no aparezca: la semántica alcanza.
                hint="pattern" if kind == "mascara" else "",
                pattern=value if kind == "mascara" else "",
                value=runtime_value if kind == "mascara" else "",
                symbols=(
                    tuple(dict.fromkeys(char for char in value if char in "&*?%#$@!~^"))
                    if kind == "mascara"
                    else ()
                ),
            )
        )

    for example in examples or ():
        value = str(example or "").strip()
        if not value:
            continue
        _add(
            EvidenceRequirement(
                id=f"example:{value.lower()}",
                kind="example",
                description=f"aplicar la regla documentada al valor {value}",
                needles=(value,),
                weight=0.0,
                role=AnchorRole.EXAMPLE_VALUE.value,
            )
        )

    for entity in entities or ():
        label = str(getattr(entity, "label", "") or "").strip()
        if not label:
            continue
        variants = tuple(
            str(variant) for variant in getattr(entity, "variants", ()) if variant
        ) or (label,)
        _add(
            EvidenceRequirement(
                id=f"entity:{label.lower()}",
                kind="entity",
                description=f"definición o explicación de {label}",
                needles=variants,
                weight=1.0,
                role=AnchorRole.ENTITY.value,
            )
        )

    for index, clause in enumerate(_clauses(text)[:max_clauses]):
        tokens = _clause_tokens(clause)
        if not tokens:
            continue
        # «¿cumple?» es el PEDIDO de la pregunta, no una premisa documental.
        if all(token in _ASK_TOKENS for token in tokens):
            continue
        clause_lower = clause.lower()
        contains_example = any(
            str(example or "").strip().lower()
            and str(example).strip().lower() in clause_lower
            for example in (examples or ())
        )
        contains_runtime = any(
            needle and needle in clause_lower for needle in runtime_needles
        )
        # Prosa larga, valor del usuario o instancia de patrón: informa la
        # cobertura pero no bloquea. Cláusula corta y técnica: dura.
        soft = contains_example or contains_runtime or len(tokens) > 5
        _add(
            EvidenceRequirement(
                id=f"clause:{index}:{' '.join(tokens[:3]).lower()}",
                kind="clause",
                description=f"respuesta a: {' '.join(clause.split())[:80]}",
                needles=tuple(tokens[:8]),
                weight=0.3 if soft else 0.6,
                soft=soft,
                aliases=_clause_alias_terms(clause),
            )
        )

    hints: list[tuple[str, str, float]] = []
    if _TABLE_HINT_RE.search(text):
        hints.append(("table", "tabla o estructura de campos aplicable", 0.8))
    if _NOTE_HINT_RE.search(text):
        hints.append(("note", "nota, ejemplo o pie que complementa la regla", 0.7))
    if _FORMULA_HINT_RE.search(text):
        hints.append(("formula", "fórmula o expresión exacta aplicable", 0.9))
    for hint, description, weight in hints:
        _add(
            EvidenceRequirement(
                id=f"structural:{hint}",
                kind="structural",
                description=description,
                weight=weight,
                hint=hint,
            )
        )
    return requirements


def evaluate_requirements(
    requirements: list[EvidenceRequirement] | tuple[EvidenceRequirement, ...],
    items: list[Any] | tuple[Any, ...],
    *,
    conflicting_needles: set[str] | None = None,
) -> RequirementCoverage:
    """Estado por requirement contra la evidencia actual (texto + estructura)."""
    texts = [
        html.unescape(str(getattr(item, "content", "") or "")).lower()
        for item in items
    ]
    joined = "\n".join(texts)
    conflicting = {needle.lower() for needle in (conflicting_needles or set())}
    pattern_semantics = None
    requirement_list = list(requirements or ())
    if any(
        requirement.kind in ("pattern_semantics", "pattern_policy")
        or requirement.hint == "pattern"
        for requirement in requirement_list
    ):
        from src.rag.longcontext.pattern import extract_pattern_semantics

        pattern_semantics = extract_pattern_semantics(list(items or ()))

    found = partial = missing = conflicts = 0
    weighted_total = 0.0
    weighted_found = 0.0
    hard_seen = False
    hard_all_found = True
    examples: list[str] = []
    examples_found: list[str] = []
    for requirement in requirement_list:
        state = _state_for(
            requirement, joined, items, conflicting, pattern_semantics
        )
        requirement.state = state
        if not requirement.documentable:
            # Ejemplo del usuario: se reporta si apareció, pero no exige match
            # ni entra en la cobertura ponderada.
            if requirement.kind == "example":
                value = requirement.needles[0] if requirement.needles else requirement.description
                examples.append(value)
                if state == RequirementState.FOUND.value:
                    examples_found.append(value)
            continue
        weighted_total += requirement.weight
        if state == RequirementState.FOUND.value:
            found += 1
            weighted_found += requirement.weight
        elif state == RequirementState.PARTIAL.value:
            partial += 1
            weighted_found += requirement.weight * 0.5
        elif state == RequirementState.CONFLICTING.value:
            conflicts += 1
        else:
            missing += 1
        if not requirement.soft and requirement.kind != "structural":
            hard_seen = True
            if state != RequirementState.FOUND.value:
                hard_all_found = False
    coverage = weighted_found / weighted_total if weighted_total else 0.0
    return RequirementCoverage(
        requirements=list(requirements or ()),
        coverage=coverage,
        found=found,
        partial=partial,
        missing=missing,
        conflicting=conflicts,
        examples=tuple(examples),
        examples_found=tuple(examples_found),
        all_hard_found=hard_seen and hard_all_found,
    )


def _state_for(
    requirement: EvidenceRequirement,
    joined: str,
    items: list[Any] | tuple[Any, ...],
    conflicting: set[str],
    pattern_semantics: Any | None = None,
) -> str:
    needles = [str(needle).strip().lower() for needle in requirement.needles if needle]
    if needles and any(needle in conflicting for needle in needles):
        return RequirementState.CONFLICTING.value
    if requirement.kind in ("pattern_semantics", "pattern_policy"):
        return _pattern_state(requirement, items, pattern_semantics)
    if requirement.kind == "structural":
        return (
            RequirementState.FOUND.value
            if _structural_present(requirement.hint, joined, items)
            else RequirementState.MISSING.value
        )
    if not needles:
        return RequirementState.MISSING.value
    if requirement.kind == "entity":
        # Las variantes de una entidad son ALTERNATIVAS («record 2» o «registro
        # 2»): encontrar cualquiera la cubre. No son conjunciones.
        return (
            RequirementState.FOUND.value
            if any(needle in joined for needle in needles)
            else RequirementState.MISSING.value
        )
    if requirement.kind == "anchor":
        # Los needles de un anchor son formas del MISMO token (valor original,
        # minúscula, rango con barra): encontrar cualquiera lo cubre.
        if any(needle in joined for needle in needles):
            return RequirementState.FOUND.value
        # Una máscara puede acreditarse por su GRAMÁTICA documentada aunque la
        # instancia concreta no exista en las fuentes (GROUNDING != COPY).
        if requirement.hint == "pattern" and requirement.pattern:
            return _pattern_state(requirement, items, pattern_semantics)
        return RequirementState.MISSING.value
    present = sum(1 for needle in needles if needle and needle in joined)
    if requirement.kind == "clause":
        # Matching de cláusula tolerante: acentos, plural/singular simple y
        # aliases del vocabulario cargado («cambio de fechas» vs «fecha»,
        # «Effective Date») no bloquean.
        folded = _fold(joined)
        present = sum(
            1 for needle in needles if needle and _needle_present(needle, folded)
        )
        ratio = present / len(needles)
        if ratio < 0.8 and requirement.aliases and any(
            alias and alias in folded for alias in requirement.aliases
        ):
            # El vocabulario del pack nombra el aspecto con otro término:
            # materialmente está documentado.
            ratio = 1.0
        if ratio >= 0.8:
            return RequirementState.FOUND.value
        if ratio >= 0.4:
            return RequirementState.PARTIAL.value
        return RequirementState.MISSING.value
    if present == len(needles):
        return RequirementState.FOUND.value
    if present > 0:
        return RequirementState.PARTIAL.value
    return RequirementState.MISSING.value


def _pattern_state(
    requirement: EvidenceRequirement,
    items: list[Any] | tuple[Any, ...],
    pattern_semantics: Any | None,
) -> str:
    """Evalúa un requisito de patrón: la instancia no exige match; su gramática sí."""
    from src.rag.longcontext.pattern import (
        analyze_pattern_instance,
        extract_pattern_semantics,
        missing_pattern_premises,
    )

    semantics = pattern_semantics
    if semantics is None:
        semantics = extract_pattern_semantics(list(items or ()))
    joined = "\n".join(
        str(getattr(item, "content", "") or "").lower() for item in (items or ())
    )
    if requirement.kind == "pattern_policy":
        key = requirement.description.rsplit(": ", 1)[-1]
        if key == "matching_policy":
            found = semantics.matching_policy_known()
        elif key == "positional_semantics":
            found = bool(semantics.positional)
        elif key == "literal_semantics":
            found = bool(semantics.literal)
        elif key == "length_semantics":
            found = bool(semantics.length_policy_known or semantics.anchor_side)
        else:
            found = False
        return RequirementState.FOUND.value if found else RequirementState.MISSING.value

    pattern = requirement.pattern or (requirement.needles[0] if requirement.needles else "")
    if not pattern:
        return RequirementState.MISSING.value
    instance = analyze_pattern_instance(str(pattern))
    missing = missing_pattern_premises(
        instance,
        semantics,
        value_length=len(requirement.value) if requirement.value else None,
    )
    if not missing:
        return RequirementState.FOUND.value
    # La instancia documentada literalmente («La máscara &&&F exige…») acredita
    # la premisa del patrón aunque no exista una definición genérica del
    # símbolo: la evidencia explica ESA máscara. La derivación de un valor
    # concreto seguirá exigiendo la gramática (el motor grounded la evalúa).
    needles = [str(needle).strip().lower() for needle in requirement.needles if needle]
    if needles and any(needle in joined for needle in needles):
        return RequirementState.FOUND.value
    defined = sum(
        1 for symbol in instance.symbols if semantics.definition_for(symbol) is not None
    )
    if defined and defined < len(instance.symbols):
        return RequirementState.PARTIAL.value
    return RequirementState.MISSING.value


def _structural_present(
    hint: str,
    joined: str,
    items: list[Any] | tuple[Any, ...],
) -> bool:
    if hint == "table":
        if " | " in joined or "\t" in joined:
            return True
        return bool(
            re.search(r"^\s*(tabla|table)\b", joined, re.IGNORECASE | re.MULTILINE)
        )
    if hint == "note":
        if re.search(r"^\s*(nota|note|footnote)\b", joined, re.IGNORECASE | re.MULTILINE):
            return True
        for item in items:
            metadata = getattr(item, "metadata", None) or {}
            chunk_type = str(metadata.get("chunk_type") or "").lower()
            if "note" in chunk_type:
                return True
        return False
    if hint == "formula":
        return "=" in joined
    return True


def _clauses(text: str) -> list[str]:
    clauses = [part.strip(" ,.") for part in _CLAUSE_SPLIT_RE.split(text)]
    return [clause for clause in clauses if len(clause) >= 3]


def _clause_tokens(clause: str) -> list[str]:
    tokens: list[str] = []
    for token in _TOKEN_RE.findall(_fold(clause)):
        if token in _STOPWORDS or token in _FRAMING_TOKENS or len(token) < 3:
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens


def _fold(text: str) -> str:
    """Minúsculas sin diacríticos (matching léxico tolerante, no stemmer)."""
    return (
        unicodedata.normalize("NFKD", str(text or ""))
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )


def _needle_variants(needle: str) -> tuple[str, ...]:
    """Variantes morfológicas simples ES/EN (plural -> singular)."""
    value = str(needle or "").strip().lower()
    if not value:
        return ()
    variants = [value]
    if len(value) > 4:
        if value.endswith("es") and len(value) > 5:
            variants.append(value[:-2])
        if value.endswith("s"):
            variants.append(value[:-1])
    return tuple(dict.fromkeys(variants))


def _needle_present(needle: str, folded_text: str) -> bool:
    return any(variant in folded_text for variant in _needle_variants(needle))


def _clause_alias_terms(clause: str) -> tuple[str, ...]:
    """Aliases del vocabulario cargado (packs) para la cláusula.

    Prueba la cláusula sin encuadre/artículos iniciales y sus prefijos
    («cuéntame el cambio de fechas del Record 2» → «cambio de fechas»).
    Genérico: sólo consulta el vocabulario registrado; no conoce dominios.
    """
    try:
        from src.knowledge.enrichment.profiling import expand_aliases
    except Exception:  # noqa: BLE001 — sin enrichment no hay puente
        return ()
    words = [word for word in re.split(r"\s+", _fold(clause)) if word]
    candidates: list[str] = []
    while words and words[0] in (_STOPWORDS | _FRAMING_TOKENS) and len(words) > 1:
        words = words[1:]
        candidates.append(" ".join(words))
    if not candidates and words:
        candidates.append(" ".join(words))
    found: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        parts = candidate.split()
        for end in range(len(parts), 1, -1):
            probe = " ".join(parts[:end])
            try:
                aliases = expand_aliases(probe)
            except Exception:  # noqa: BLE001
                aliases = ()
            for alias in aliases:
                folded = _fold(alias)
                if folded and folded not in seen:
                    seen.add(folded)
                    found.append(folded)
    return tuple(found)


__all__ = [
    "EvidenceRequirement",
    "RequirementCoverage",
    "RequirementState",
    "build_requirements",
    "evaluate_requirements",
]
