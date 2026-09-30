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

    @property
    def documentable(self) -> bool:
        """¿Exige aparecer en la documentación? EXAMPLE_VALUE no."""
        if self.kind == "example":
            return False
        if self.role in ("example_value", "example"):
            return False
        return self.weight > 0.0

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
    def unanswered(self) -> tuple[EvidenceRequirement, ...]:
        return tuple(
            requirement
            for requirement in self.requirements
            if requirement.documentable
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
        return payload


def build_requirements(
    query: str,
    anchors: list[Anchor] | tuple[Anchor, ...] = (),
    entities: list[Any] | tuple[Any, ...] = (),
    *,
    examples: list[str] | tuple[str, ...] = (),
    max_clauses: int = 6,
) -> list[EvidenceRequirement]:
    """Descompone la pregunta en requerimientos evaluables, sin dominio.

    Los tokens que son VALOR DEL USUARIO (rol example_value) se registran como
    `example`: viajan a la búsqueda, pero no exigen aparecer en las fuentes.
    La documentación debe probar la regla y el campo, no el ejemplo concreto.
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

    for anchor in assign_roles(text, list(anchors or ())):
        value = str(getattr(anchor, "value", "") or "").strip()
        if not value:
            continue
        role = str(getattr(anchor, "role", "") or "")
        kind = str(getattr(anchor, "kind", ""))
        if role == AnchorRole.EXAMPLE_VALUE.value:
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
        clause_lower = clause.lower()
        contains_example = any(
            str(example or "").strip().lower()
            and str(example).strip().lower() in clause_lower
            for example in (examples or ())
        )
        # Prosa larga o cláusula con el valor del usuario: informa la cobertura
        # pero no bloquea. Cláusula corta y técnica: dura.
        soft = contains_example or len(tokens) > 5
        _add(
            EvidenceRequirement(
                id=f"clause:{index}:{' '.join(tokens[:3]).lower()}",
                kind="clause",
                description=f"respuesta a: {' '.join(clause.split())[:80]}",
                needles=tuple(tokens[:8]),
                weight=0.3 if soft else 0.6,
                soft=soft,
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

    found = partial = missing = conflicts = 0
    weighted_total = 0.0
    weighted_found = 0.0
    hard_seen = False
    hard_all_found = True
    examples: list[str] = []
    examples_found: list[str] = []
    for requirement in requirements or ():
        state = _state_for(requirement, joined, items, conflicting)
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
) -> str:
    needles = [str(needle).strip().lower() for needle in requirement.needles if needle]
    if needles and any(needle in conflicting for needle in needles):
        return RequirementState.CONFLICTING.value
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
        return (
            RequirementState.FOUND.value
            if any(needle in joined for needle in needles)
            else RequirementState.MISSING.value
        )
    present = sum(1 for needle in needles if needle and needle in joined)
    ratio = present / len(needles)
    if requirement.kind == "clause":
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
    for token in _TOKEN_RE.findall(clause.lower()):
        if token in _STOPWORDS or len(token) < 3:
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens


__all__ = [
    "EvidenceRequirement",
    "RequirementCoverage",
    "RequirementState",
    "build_requirements",
    "evaluate_requirements",
]
