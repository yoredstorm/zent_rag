# =============================================================================
# Parent Semantic Representation — el padre no se trunca, se COMPONE
# =============================================================================
# Un parent chunk es la evidencia recuperable de una sección completa. Embeber
# `parent_text[:N]` representa mal el padre (y castiga al retrieval). Acá el
# texto de embedding se construye con señal semántica:
#
#   título del documento + sección + conceptos + aliases + identificadores +
#   hechos/reglas compiladas + scope temporal + resumen de hijos + términos
#
# El contenido original del parent NUNCA se modifica ni se descarta: queda
# entero en el payload del punto (`content`) y los children siguen siendo la
# evidencia citable. Esta representación es `derived=true, canonical=false`.
# =============================================================================
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from src.core.domain.knowledge_v2 import DocumentChunk, StructuredDocument

from .versions import PARENT_REPRESENTATION_VERSION

_WORD = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-z0-9_\-]{2,}")
_STOPWORDS = frozenset(
    {
        "para", "como", "este", "esta", "esto", "estos", "estas", "cada", "donde",
        "desde", "hasta", "entre", "sobre", "tiene", "debe", "puede", "será",
        "the", "and", "for", "with", "that", "this", "from", "are", "was",
        "were", "will", "shall", "must", "not", "any", "all", "其", "por",
        "según", "cuando", "todo", "toda", "más", "menos", "otro", "otra",
    }
)


@dataclass(frozen=True, kw_only=True)
class ParentSemanticRepresentation:
    """Representación compacta y trazable de un parent chunk."""

    text: str
    version: str = PARENT_REPRESENTATION_VERSION
    section_title: str = ""
    section_path: tuple[str, ...] = ()
    source_unit_ids: tuple[str, ...] = ()
    concepts: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    identifiers: tuple[str, ...] = ()
    entity_names: tuple[str, ...] = ()
    fact_hints: tuple[str, ...] = ()
    rule_hints: tuple[str, ...] = ()
    temporal_scope: tuple[str, ...] = ()
    retrieval_questions: tuple[str, ...] = ()
    child_summaries: tuple[str, ...] = ()
    child_ids: tuple[str, ...] = ()
    child_count: int = 0
    token_count: int = 0
    max_chars: int = 0
    truncated: bool = False
    fallback: bool = False
    preliminary: bool = False
    metadata: dict = field(default_factory=dict)

    def to_payload(self) -> dict:
        """Payload acotado para el índice (sin texto crudo duplicado)."""
        return {
            "parent_representation_version": self.version,
            "parent_representation_chars": len(self.text),
            "parent_representation_truncated": bool(self.truncated),
            "parent_representation_fallback": bool(self.fallback),
            "parent_representation_preliminary": bool(self.preliminary),
            "parent_child_count": int(self.child_count),
            "parent_question_count": len(self.retrieval_questions),
            "parent_representation_source_units": list(self.source_unit_ids[:64]),
        }


def _keywords(text: str, limit: int = 12) -> list[str]:
    tokens = [
        token.lower()
        for token in _WORD.findall(text or "")
        if token.lower() not in _STOPWORDS and len(token) >= 4
    ]
    return [token for token, _count in Counter(tokens).most_common(limit)]


def _first_sentence(text: str, limit: int = 240) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ""
    match = re.search(r"[.!?]\s", cleaned)
    sentence = cleaned[: match.start()] if match else cleaned
    return sentence[:limit].strip()


def build_parent_representation(
    document: StructuredDocument,
    chunk: DocumentChunk,
    *,
    enrichment=None,
    compiled=None,
    children: list[DocumentChunk] | None = None,
    max_chars: int = 1800,
    max_concepts: int = 12,
    max_identifiers: int = 16,
    max_questions: int = 3,
    max_child_summaries: int = 8,
) -> ParentSemanticRepresentation:
    """Compone la representación del padre. Determinista, sin inventar datos.

    `enrichment`/`compiled` son opcionales: sin ellos cae al fallback
    determinista (título + sección + términos + primera oración de cada hijo).
    El contenido del parent jamás se corta: si sobra presupuesto, se descartan
    componentes opcionales y se marca `truncated=True` (truncar la
    representación, no la evidencia).
    """
    title = (document.title or "").strip()
    heading = str(
        chunk.metadata.get("heading")
        or chunk.metadata.get("section_title")
        or ""
    ).strip()
    section_path = tuple(
        str(part).strip()
        for part in (chunk.metadata.get("section_path") or ())
        if str(part).strip()
    )
    block_ids = {str(value) for value in (chunk.metadata.get("block_ids") or ())}
    unit_key = str(chunk.metadata.get("unit_id") or "")
    child_list = list(children or [])

    concepts: list[str] = []
    aliases: list[str] = []
    identifiers: list[str] = []
    questions: list[str] = []
    temporal: list[str] = []
    fact_hints: list[str] = []
    rule_hints: list[str] = []
    entity_names: list[str] = []

    if enrichment is not None:
        for concept in enrichment.concepts:
            if not _touches(concept.source_unit_ids, block_ids, unit_key):
                continue
            concepts.append(concept.canonical_name)
            aliases.extend(concept.aliases)
            identifiers.extend(concept.identifiers)
        for identifier in enrichment.identifiers:
            if _touches(identifier.source_unit_ids, block_ids, unit_key):
                identifiers.append(identifier.value)
        for qualifier in enrichment.temporal_qualifiers:
            if _touches(qualifier.source_unit_ids, block_ids, unit_key):
                temporal.append(qualifier.normalized_value or qualifier.value)
        for question in enrichment.synthetic_questions:
            if _touches((question.source_unit_id,), block_ids, unit_key):
                questions.append(question.question)

    if compiled is not None:
        for entity in getattr(compiled, "entities", ())[:24]:
            evidence = getattr(entity, "evidence", ()) or ()
            if any(
                _touches((str(getattr(item, "unit_id", "") or ""),), block_ids, unit_key)
                for item in evidence
            ):
                entity_names.append(str(entity.name))
        for fact in getattr(compiled, "facts", ())[:64]:
            evidence = getattr(fact, "evidence", ()) or ()
            if any(
                _touches((str(getattr(item, "unit_id", "") or ""),), block_ids, unit_key)
                for item in evidence
            ):
                statement = str(getattr(fact, "statement", "") or "")[:160]
                if statement:
                    fact_hints.append(statement)
        for rule in getattr(compiled, "rules", ())[:32]:
            evidence = getattr(rule, "evidence", ()) or ()
            if any(
                _touches((str(getattr(item, "unit_id", "") or ""),), block_ids, unit_key)
                for item in evidence
            ):
                hint = str(
                    getattr(rule, "statement", None)
                    or getattr(rule, "description", None)
                    or getattr(rule, "rule_key", "")
                    or ""
                )[:160]
                if hint:
                    rule_hints.append(hint)

    child_summaries = [
        summary
        for child in child_list[:max_child_summaries]
        if (summary := _first_sentence(child.content))
    ]
    keywords = _keywords(chunk.content, limit=12)

    # Dedupe preservando orden y acotando.
    concepts = _dedupe(concepts)[:max_concepts]
    aliases = _dedupe(aliases)[:max_concepts * 2]
    identifiers = _dedupe(identifiers)[:max_identifiers]
    temporal = _dedupe(temporal)[:8]
    entity_names = _dedupe(entity_names)[:8]
    fact_hints = _dedupe(fact_hints)[:6]
    rule_hints = _dedupe(rule_hints)[:4]
    questions = _dedupe(questions)[:max_questions]
    child_summaries = _dedupe(child_summaries)[:max_child_summaries]

    # Identificadores exactos detectados por understanding (siempre presentes).
    for literal in chunk.metadata.get("exact_literals") or ():
        value = str(literal or "").strip()
        if value and value not in identifiers:
            identifiers.append(value)
    identifiers = identifiers[:max_identifiers]

    fallback = enrichment is None and compiled is None
    preliminary = compiled is None

    # Composición etiquetada; las secciones vacías NO se incluyen.
    optional_blocks: list[tuple[str, str]] = []
    summary = _first_sentence(chunk.content, limit=240) if fallback else ""
    if summary:
        optional_blocks.append(("summary", f"Summary: {summary}"))
    if concepts:
        line = "Concepts: " + ", ".join(concepts)
        if aliases:
            line += " | Aliases: " + ", ".join(aliases)
        optional_blocks.append(("concepts", line))
    if identifiers:
        optional_blocks.append(("identifiers", "Identifiers: " + ", ".join(identifiers)))
    if entity_names:
        optional_blocks.append(("entities", "Entities: " + ", ".join(entity_names)))
    if rule_hints:
        optional_blocks.append(("rules", "Rules: " + " | ".join(rule_hints)))
    if fact_hints:
        optional_blocks.append(("facts", "Key facts: " + " | ".join(fact_hints)))
    if temporal:
        optional_blocks.append(("temporal", "Temporal scope: " + ", ".join(temporal)))
    if questions:
        optional_blocks.append(
            ("questions", "Questions: " + " | ".join(questions))
        )
    if child_summaries:
        optional_blocks.append(
            ("children", "Children: " + " | ".join(child_summaries))
        )
    if keywords and not fallback:
        optional_blocks.append(("terms", "Terms: " + ", ".join(keywords)))

    header_parts: list[str] = []
    if title:
        header_parts.append(f"Title: {title}")
    section_line = " > ".join(part for part in (section_path or (heading,)) if part)
    if section_line:
        header_parts.append(f"Section: {section_line}")
    text = ". ".join(header_parts)

    # Presupuesto: se descartan bloques opcionales ENTEROS (nunca el texto padre).
    truncated = False
    for _name, block in optional_blocks:
        candidate = f"{text}. {block}" if text else block
        if max_chars and len(candidate) > max_chars:
            truncated = True
            continue
        text = candidate

    # Fallback puro: sin enrichment ni compiler, al menos la señal estructural.
    if not text:
        text = section_line or title or "section"
        truncated = False

    if max_chars and len(text) > max_chars:
        # Último recurso: recortar SOLO la representación (nunca el parent real).
        text = text[:max_chars].rstrip()
        truncated = True

    token_count = max(1, len(text) // 4)
    source_unit_ids = _dedupe(
        [str(value) for value in (chunk.metadata.get("block_ids") or ())]
        + ([str(chunk.metadata.get("unit_id"))] if chunk.metadata.get("unit_id") else [])
    )
    return ParentSemanticRepresentation(
        text=text,
        section_title=heading,
        section_path=section_path,
        source_unit_ids=tuple(source_unit_ids),
        concepts=tuple(concepts),
        aliases=tuple(aliases),
        identifiers=tuple(identifiers),
        entity_names=tuple(entity_names),
        fact_hints=tuple(fact_hints),
        rule_hints=tuple(rule_hints),
        temporal_scope=tuple(temporal),
        retrieval_questions=tuple(questions),
        child_summaries=tuple(child_summaries),
        child_ids=tuple(str(child.id) for child in child_list[:max_child_summaries]),
        child_count=len(child_list),
        token_count=token_count,
        max_chars=max(0, int(max_chars)),
        truncated=truncated,
        fallback=fallback,
        preliminary=preliminary,
        metadata={
            "derived": True,
            "canonical": False,
            "derivation_method": "deterministic_compose",
            "representation_version": PARENT_REPRESENTATION_VERSION,
            "preliminary": preliminary,
        },
    )


def _touches(source_unit_ids, block_ids: set[str], unit_key: str) -> bool:
    if not source_unit_ids:
        return False
    if not block_ids and not unit_key:
        return True
    for value in source_unit_ids:
        text = str(value or "")
        if not text:
            continue
        if text in block_ids or (unit_key and text == unit_key):
            return True
    return False


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = " ".join(str(value or "").split())
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result
