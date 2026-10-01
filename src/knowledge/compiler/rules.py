# =============================================================================
# Knowledge Compiler — RULE DISCOVERY
# =============================================================================
# Una regla se extrae de lenguaje normativo real, no de cualquier frase:
#   must / shall / required / is required to / has to
#   must not / shall not / forbidden / prohibited
#   debe / deberá / obligatorio / no debe / prohibido / no puede
#   máximo / mínimo / entre X e Y (restricciones numéricas)
#
# La regla conserva su enunciado original completo y la evidencia que la
# respalda. Sin marcador normativo no hay regla: es texto descriptivo.
# =============================================================================
from __future__ import annotations

import hashlib
import re

from src.core.domain.knowledge_v2 import StructuredDocument
from src.knowledge.compiler.model import (
    EvidenceRef,
    EvidenceType,
    RuleCandidate,
    TemporalScope,
    normalize_term,
)

_MAX_RULES = 2_000
_MIN_STATEMENT = 24

_MUST_NOT = re.compile(
    r"\b(must\s+not|shall\s+not|may\s+not|is\s+not\s+allowed|cannot|can't|"
    r"prohibited|forbidden|no\s+debe|no\s+podr[aá]|prohibido|qued[ao]\s+prohibido)\b",
    flags=re.IGNORECASE,
)
_MUST = re.compile(
    r"\b(must|shall|required\s+to|is\s+required|has\s+to|have\s+to|"
    r"debe|deber[aá]|obligatorio|requiere|requerido|es\s+necesario)\b",
    flags=re.IGNORECASE,
)
_SHOULD = re.compile(
    r"\b(should|recommended|it\s+is\s+advisable|se\s+recomienda|recomendable|conviene)\b",
    flags=re.IGNORECASE,
)
_CONSTRAINT = re.compile(
    r"\b(max(?:imum)?|min(?:imum)?|at\s+most|at\s+least|no\s+more\s+than|"
    r"between\s+\d|rango\s+de|m[aá]ximo|m[ií]nimo|no\s+m[aá]s\s+de|"
    r"no\s+menos\s+de|entre\s+\d)\b",
    flags=re.IGNORECASE,
)

_MODALITY_ORDER = ("must_not", "must", "constraint", "should")


def detect_modality(statement: str) -> str | None:
    """Modalidad normativa del enunciado. None = no es una regla."""
    text = statement or ""
    if _MUST_NOT.search(text):
        return "must_not"
    if _MUST.search(text):
        return "must"
    if _CONSTRAINT.search(text):
        return "constraint"
    if _SHOULD.search(text):
        return "should"
    return None


def rule_key(statement: str, subject: str) -> str:
    """Clave estable: el mismo enunciado produce la misma regla siempre."""
    digest = hashlib.sha256(
        f"{normalize_term(subject)}|{' '.join((statement or '').split()).lower()}".encode(
            "utf-8"
        )
    ).hexdigest()
    return digest[:24]


def _subject_for(statement: str, section_path: tuple[str, ...]) -> str:
    if section_path:
        return section_path[-1][:200]
    first = re.split(r"[:.。\n]", statement.strip(), maxsplit=1)[0]
    words = first.split()
    return " ".join(words[:8])[:200] if words else "documento"


def extract_rules(
    document: StructuredDocument, *, temporal: TemporalScope | None = None
) -> list[RuleCandidate]:
    """Reglas y restricciones declaradas explícitamente en el documento."""
    scope = temporal or TemporalScope()
    section_paths = {
        str(section.id): tuple(section.section_path) for section in document.sections
    }
    rules: list[RuleCandidate] = []
    seen: set[str] = set()

    for block in document.blocks:
        if block.metadata.get("chrome") or block.metadata.get("superseded"):
            continue
        text = " ".join((block.text or "").split())
        if len(text) < _MIN_STATEMENT:
            continue
        modality = detect_modality(text)
        if modality is None:
            continue
        section_path = section_paths.get(
            str(block.metadata.get("parent_section_id") or ""), ()
        )
        subject = _subject_for(text, section_path)
        key = rule_key(text, subject)
        if key in seen or len(rules) >= _MAX_RULES:
            continue
        seen.add(key)
        rule_type = "constraint" if modality == "constraint" else "business_rule"
        if any(
            marker in text.lower()
            for marker in ("procedimiento", "procedure", "paso ", "step ")
        ):
            rule_type = "process_step"
        rules.append(
            RuleCandidate(
                subject=subject,
                statement=text[:2000],
                rule_key=key,
                rule_type=rule_type,
                modality=modality,
                confidence=0.82 if modality in {"must", "must_not"} else 0.7,
                temporal=scope,
                evidence=[
                    EvidenceRef(
                        locator=_locator_for(document, block, section_path),
                        evidence_type=EvidenceType.DOCUMENT.value,
                        excerpt=text[:400],
                        method="deterministic",
                        confidence=0.82,
                    )
                ],
            )
        )

    return rules


def _locator_for(document: StructuredDocument, block, section_path):
    from src.knowledge.compiler.model import SourceLocator

    return SourceLocator(
        source_id=document.source_id,
        document_id=document.id,
        document_title=document.title,
        block_id=block.id,
        page=block.page,
        section_path=section_path,
        content_hash=block.content_hash or document.content_hash,
    )
