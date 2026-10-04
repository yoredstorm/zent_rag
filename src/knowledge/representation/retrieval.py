# =============================================================================
# Knowledge OS — Retrieval Representation Builder
# =============================================================================
# Cada chunk tiene DOS representaciones, nunca una sola:
#
#   CONTENT REPRESENTATION   = sección + texto real (lo que el usuario cita)
#   RETRIEVAL REPRESENTATION = título + conceptos + aliases + identificadores +
#                              descripción corta + preguntas (lo que se busca)
#
# El contenido de evidencia NUNCA se contamina: la representación de retrieval
# es derivada, versionada y trazable a las unidades fuente. Se usa para la pata
# lexical (sparse) y como metadata acotada del punto; el dense de children usa
# la representación de contenido.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field

from src.core.domain.knowledge_v2 import DocumentChunk, StructuredDocument

from .versions import (
    CONTENT_REPRESENTATION_VERSION,
    RETRIEVAL_REPRESENTATION_VERSION,
)

_SENTENCE_END = (". ", "! ", "? ", ".\n")


@dataclass(frozen=True, kw_only=True)
class ContentRepresentation:
    """Título/sección + texto real. Es lo que se embebe para el child."""

    text: str
    version: str = CONTENT_REPRESENTATION_VERSION
    section_title: str = ""
    section_path: tuple[str, ...] = ()
    token_count: int = 0
    prefixed: bool = False

    def to_payload(self) -> dict:
        return {
            "content_representation_version": self.version,
            "content_representation_prefixed": bool(self.prefixed),
        }


@dataclass(frozen=True, kw_only=True)
class RetrievalRepresentation:
    """Señal de búsqueda (derivada). No es evidencia."""

    text: str
    version: str = RETRIEVAL_REPRESENTATION_VERSION
    section_path: tuple[str, ...] = ()
    concepts: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    identifiers: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()
    entity_names: tuple[str, ...] = ()
    source_unit_ids: tuple[str, ...] = ()
    max_chars: int = 0
    truncated: bool = False
    preliminary: bool = False
    token_count: int = 0
    metadata: dict = field(default_factory=dict)

    def to_payload(self) -> dict:
        return {
            "retrieval_representation_version": self.version,
            "retrieval_representation_chars": len(self.text),
            "retrieval_representation_truncated": bool(self.truncated),
            "retrieval_representation_preliminary": bool(self.preliminary),
            "retrieval_representation_concepts": list(self.concepts[:8]),
            "retrieval_representation_questions": list(self.questions[:6]),
        }


class RetrievalRepresentationBuilder:
    """Builder determinista de las dos representaciones de un chunk."""

    def __init__(
        self,
        *,
        max_retrieval_chars: int = 800,
        max_concepts: int = 8,
        max_aliases: int = 10,
        max_identifiers: int = 8,
        max_questions: int = 6,
        max_entities: int = 8,
    ) -> None:
        self._max_chars = max(120, int(max_retrieval_chars))
        self._max_concepts = max(0, int(max_concepts))
        self._max_aliases = max(0, int(max_aliases))
        self._max_identifiers = max(0, int(max_identifiers))
        self._max_questions = max(0, int(max_questions))
        self._max_entities = max(0, int(max_entities))

    def build(
        self,
        document: StructuredDocument,
        chunk: DocumentChunk,
        *,
        enrichment=None,
        compiled=None,
    ) -> tuple[ContentRepresentation, RetrievalRepresentation]:
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
        if not section_path and heading:
            section_path = (heading,)

        content = self._content_representation(document, chunk, section_path)
        retrieval = self._retrieval_representation(
            document,
            chunk,
            enrichment=enrichment,
            compiled=compiled,
            section_path=section_path,
        )
        return content, retrieval

    # ------------------------------------------------------------------
    def _content_representation(
        self,
        document: StructuredDocument,
        chunk: DocumentChunk,
        section_path: tuple[str, ...],
    ) -> ContentRepresentation:
        body = chunk.content or ""
        header = " > ".join(section_path)
        if header and header.casefold() not in body[: len(header) + 40].casefold():
            text = f"{header}\n\n{body}"
            prefixed = True
        else:
            text = body
            prefixed = False
        return ContentRepresentation(
            text=text,
            section_title=section_path[-1] if section_path else "",
            section_path=section_path,
            token_count=max(1, len(text) // 4),
            prefixed=prefixed,
        )

    def _retrieval_representation(
        self,
        document: StructuredDocument,
        chunk: DocumentChunk,
        *,
        enrichment,
        compiled,
        section_path: tuple[str, ...],
    ) -> RetrievalRepresentation:
        block_ids = {str(value) for value in (chunk.metadata.get("block_ids") or ())}
        unit_key = str(chunk.metadata.get("unit_id") or "")

        def touches(units) -> bool:
            if not units:
                return False
            if not block_ids and not unit_key:
                return True
            for value in units:
                text = str(value or "")
                if text and (text in block_ids or (unit_key and text == unit_key)):
                    return True
            return False

        concepts: list[str] = []
        aliases: list[str] = []
        identifiers: list[str] = []
        questions: list[str] = []
        entity_names: list[str] = []
        if enrichment is not None:
            for concept in enrichment.concepts:
                if touches(concept.source_unit_ids):
                    concepts.append(concept.canonical_name)
                    aliases.extend(concept.aliases)
                    identifiers.extend(concept.identifiers)
            for alias in enrichment.retrieval_aliases:
                if touches(alias.source_unit_ids):
                    aliases.append(alias.value)
            for identifier in enrichment.identifiers:
                if touches(identifier.source_unit_ids):
                    identifiers.append(identifier.value)
            for question in enrichment.synthetic_questions:
                if touches(question.source_unit_ids):
                    questions.append(question.question)
        if compiled is not None:
            for entity in getattr(compiled, "entities", ())[:32]:
                evidence = getattr(entity, "evidence", ()) or ()
                if any(
                    touches((str(getattr(item, "unit_id", "") or ""),))
                    for item in evidence
                ):
                    entity_names.append(str(entity.name))

        concepts = _dedupe(concepts)[: self._max_concepts]
        aliases = _dedupe(aliases)[: self._max_aliases]
        identifiers = _dedupe(identifiers)[: self._max_identifiers]
        questions = _dedupe(questions)[: self._max_questions]
        entity_names = _dedupe(entity_names)[: self._max_entities]

        # Identificadores exactos que viven en el chunk (siempre verbatim).
        for literal in chunk.metadata.get("exact_literals") or ():
            value = str(literal or "").strip()
            if value and value not in identifiers:
                identifiers.append(value)
        identifiers = identifiers[: self._max_identifiers]

        blocks: list[str] = []
        if section_path:
            blocks.append("Section: " + " > ".join(section_path))
        description = _first_sentence(chunk.content or "")
        if description:
            blocks.append("About: " + description)
        if concepts:
            blocks.append("Concepts: " + ", ".join(concepts))
        if aliases:
            blocks.append("Aliases: " + ", ".join(aliases))
        if identifiers:
            blocks.append("Identifiers: " + ", ".join(identifiers))
        if entity_names:
            blocks.append("Entities: " + ", ".join(entity_names))
        if questions:
            blocks.append("Questions: " + " | ".join(questions))

        text = ". ".join(blocks)
        truncated = False
        if len(text) > self._max_chars:
            # Se descartan bloques opcionales enteros (nunca se corta la evidencia).
            kept: list[str] = []
            for block in blocks:
                candidate = ". ".join([*kept, block])
                if len(candidate) > self._max_chars:
                    truncated = True
                    continue
                kept.append(block)
            text = ". ".join(kept)

        source_unit_ids = _dedupe(
            [str(value) for value in (chunk.metadata.get("block_ids") or ())]
            + ([unit_key] if unit_key else [])
        )
        return RetrievalRepresentation(
            text=text,
            section_path=section_path,
            concepts=tuple(concepts),
            aliases=tuple(aliases),
            identifiers=tuple(identifiers),
            questions=tuple(questions),
            entity_names=tuple(entity_names),
            source_unit_ids=tuple(source_unit_ids),
            max_chars=self._max_chars,
            truncated=truncated,
            preliminary=compiled is None,
            token_count=max(1, len(text) // 4),
            metadata={
                "derived": True,
                "canonical": False,
                "derivation_method": "deterministic_compose",
            },
        )


def _first_sentence(text: str, limit: int = 200) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ""
    cut = len(cleaned)
    for marker in _SENTENCE_END:
        position = cleaned.find(marker)
        if position != -1:
            cut = min(cut, position + 1)
    return cleaned[:cut][:limit].strip()


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
