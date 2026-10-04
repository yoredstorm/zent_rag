# =============================================================================
# Multi-Representation Embeddings — content / semantic / concept / question
# =============================================================================
# La representación densa por defecto sigue siendo `content` (comportamiento
# actual). `semantic` implementa contextual embedding real: el texto embebido
# incorpora contexto del Semantic Fabric (labels + definiciones) y de la
# sección, nunca evidencia inventada. `concept` y `question` quedan
# preparadas para benchmark (§34: no activar todo sin medir).
#
# La representación elegida entra al representation_fingerprint: cambiarla
# invalida SOLO el embedding (reindex), no la fuente.
# =============================================================================
from __future__ import annotations

from enum import StrEnum

from src.knowledge.representation.versions import EMBEDDING_REPRESENTATION_VERSION

REPRESENTATION_MODES: tuple[str, ...] = (
    "content",
    "semantic",
    "concept",
    "question",
)


class EmbeddingRepresentation(StrEnum):
    CONTENT = "content"
    SEMANTIC = "semantic"
    CONCEPT = "concept"
    QUESTION = "question"


def _setting(name: str, default):
    try:
        from src.core.config import get_settings

        return getattr(get_settings(), name, default)
    except Exception:  # noqa: BLE001
        return default


class EmbeddingTextPlanner:
    """Construye el texto que se embebe por retrieval unit (Fase 10)."""

    def __init__(
        self,
        *,
        representation: str | None = None,
        enrichment=None,
        fabric_context=None,
        max_labels: int = 12,
        max_definitions: int = 6,
        max_questions: int = 4,
    ) -> None:
        self._representation = (
            str(
                representation
                or _setting("RAG_EMBEDDING_DENSE_REPRESENTATION", "content")
                or "content"
            )
            .strip()
            .lower()
        )
        if self._representation not in REPRESENTATION_MODES:
            self._representation = "content"
        self._enrichment = enrichment
        self._fabric = fabric_context
        self._max_labels = max(0, int(max_labels))
        self._max_definitions = max(0, int(max_definitions))
        self._max_questions = max(0, int(max_questions))

    @property
    def representation(self) -> str:
        return self._representation

    @property
    def version(self) -> str:
        return f"{EMBEDDING_REPRESENTATION_VERSION}:{self._representation}"

    def plan(self, chunk, content_text: str) -> str:
        """Texto de embedding del chunk según la representación elegida."""
        mode = self._representation
        if mode == "content":
            return content_text
        block_ids = chunk.metadata.get("block_ids") or ()
        if mode == "semantic":
            context = self._semantic_context(block_ids)
            return f"{content_text}\n{context}".strip() if context else content_text
        if mode == "concept":
            labels = self._labels(block_ids)
            if not labels:
                return content_text
            return f"Concepts: {', '.join(labels)}\n{content_text}"
        if mode == "question":
            questions = self._questions(block_ids)
            if not questions:
                return content_text
            return f"{content_text}\nQuestions: {' | '.join(questions)}"
        return content_text

    # ------------------------------------------------------------------
    def _semantic_context(self, block_ids) -> str:
        parts: list[str] = []
        labels = self._labels(block_ids)
        if labels:
            parts.append(", ".join(labels))
        definitions = self._definitions(block_ids)
        if definitions:
            parts.append("; ".join(definitions))
        if not parts:
            return ""
        return "Semantic context: " + ". ".join(parts)

    def _nodes_for(self, block_ids) -> list[dict]:
        if self._fabric is None or not getattr(self._fabric, "enabled", False):
            return []
        found: dict[str, dict] = {}
        for raw in block_ids or ():
            for node in self._fabric.nodes_by_block.get(str(raw), ()):
                found.setdefault(str(node.get("id")), node)
        return list(found.values())

    def _labels(self, block_ids) -> list[str]:
        labels: list[str] = []
        for node in self._nodes_for(block_ids):
            if node.get("node_type") == "Evidence":
                continue
            label = str(node.get("label") or "").strip()
            if label and label not in labels:
                labels.append(label)
            if len(labels) >= self._max_labels:
                break
        return labels

    def _definitions(self, block_ids) -> list[str]:
        definitions: list[str] = []
        for node in self._nodes_for(block_ids):
            if node.get("node_type") != "Definition":
                continue
            text = str(node.get("text") or "").strip()
            if text and text not in definitions:
                definitions.append(text[:160])
            if len(definitions) >= self._max_definitions:
                break
        return definitions

    def _questions(self, block_ids) -> list[str]:
        if self._enrichment is None:
            return []
        block_set = {str(value) for value in block_ids or ()}
        questions: list[str] = []
        for question in self._enrichment.synthetic_questions:
            if not question.source_unit_ids:
                continue
            if block_set and not block_set.intersection(
                str(value) for value in question.source_unit_ids
            ):
                continue
            value = str(question.question or "").strip()
            if value and value not in questions:
                questions.append(value)
            if len(questions) >= self._max_questions:
                break
        return questions


__all__ = [
    "EMBEDDING_REPRESENTATION_VERSION",
    "REPRESENTATION_MODES",
    "EmbeddingRepresentation",
    "EmbeddingTextPlanner",
]
