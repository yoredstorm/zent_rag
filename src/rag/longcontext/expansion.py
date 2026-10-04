# =============================================================================
# Expansión progresiva — cada etapa tiene una ESTRATEGIA, no sólo tamaño
# =============================================================================
# Orden default (configurable por el engine):
#   1. padre/sección, 2. vecindad de sección (siblings), 3. otros aciertos de
#   anchors exactos, 4. mismo documento, 5. tabla/nota referenciada,
#   6. cross-documento, 7. conceptos/entidades, 8. nivel documento.
# Best-effort y determinista: sin LLM; respeta tenant/ACL porque usa los
# métodos del store (los mismos filtros del retrieval normal).
# =============================================================================
from __future__ import annotations

import html
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from src.core.domain.entities import RetrievalChunk, RetrievalContext
from src.infrastructure.observability.logging_config import get_logger
from src.intelligence.response.anchors import Anchor
from src.rag.longcontext.must_keep import mark_must_keep
from src.rag.retrieval.models import RetrievalQuery

logger = get_logger(__name__)

RetrieveFn = Callable[[dict[str, Any]], Awaitable[RetrievalContext]]

_REFERENCE_RE = re.compile(
    r"\b(tabla|table|nota|note|ejemplo|example|figura|figure|record|registro|"
    r"f[oó]rmula|formula)\s*[#nº.\-]?\s*(\d{1,4}[a-z]?)\b",
    re.IGNORECASE,
)


@dataclass(kw_only=True)
class ExpansionCache:
    """Memo del run: análisis, needles ya barridos y fetches reutilizables.

    Sin esto, cada expansión repetía barridos literales y scrolls por sección
    que ya se habían hecho. La caché vive sólo lo que dura el run.
    """

    seen_document_ids: set[str] = field(default_factory=set)
    scanned_needles: set[str] = field(default_factory=set)
    store_results: dict[tuple, list[RetrievalChunk]] = field(default_factory=dict)
    retrieve_results: dict[tuple, RetrievalContext] = field(default_factory=dict)

    def get_chunks(self, key: tuple) -> list[RetrievalChunk] | None:
        cached = self.store_results.get(key)
        return list(cached) if cached is not None else None

    def put_chunks(self, key: tuple, chunks: list[RetrievalChunk]) -> None:
        self.store_results[key] = list(chunks)

    def get_context(self, key: tuple) -> RetrievalContext | None:
        return self.retrieve_results.get(key)

    def put_context(self, key: tuple, context: RetrievalContext) -> None:
        self.retrieve_results[key] = context


@dataclass(kw_only=True)
class ExpansionContext:
    """Todo lo que una estrategia puede mirar para decidir qué traer."""

    query: RetrievalQuery
    chunks: list[RetrievalChunk]
    anchors: list[Anchor] = field(default_factory=list)
    missing_needles: tuple[str, ...] = ()
    round_index: int = 0
    limit: int = 6
    max_points: int = 6000
    max_ms: float = 2000.0
    cache: ExpansionCache | None = None


@dataclass(kw_only=True)
class Expansion:
    name: str
    reason: str
    chunks: list[RetrievalChunk] = field(default_factory=list)
    strategy: str = ""
    queries: list[str] = field(default_factory=list)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.name,
            "reason": self.reason,
            "chunks": len(self.chunks),
            "queries": self.queries[:3],
        }


class ExpansionStrategy:
    """Contrato mínimo: nombre, motivo de negocio legible y expansión."""

    name = "expansion"
    reason = "ampliar contexto"

    async def expand(self, context: ExpansionContext) -> Expansion:
        raise NotImplementedError


def _domain_chunks(context: ExpansionContext, limit: int) -> list[RetrievalChunk]:
    return list(context.chunks[: max(1, limit)])


async def _retrieve_cached(
    cache: ExpansionCache | None,
    key: tuple,
    retrieve: RetrieveFn,
    spec: dict[str, Any],
) -> RetrievalContext:
    """Reutiliza el resultado de un retrieve idéntico dentro del mismo run."""
    if cache is not None:
        cached = cache.get_context(key)
        if cached is not None:
            return cached
    context = await retrieve(spec)
    if cache is not None:
        cache.put_context(key, context)
    return context


class ParentSectionExpansion(ExpansionStrategy):
    name = "parent_sections"
    reason = "el fragmento no explica solo: falta su sección padre"

    def __init__(self, store: object) -> None:
        self._store = store

    async def expand(self, context: ExpansionContext) -> Expansion:
        fetch = getattr(self._store, "get_documents_by_chunk_ids", None)
        if not callable(fetch):
            return Expansion(name=self.name, reason=self.reason)
        parent_ids: list[str] = []
        for chunk in _domain_chunks(context, context.limit):
            parent_id = str((chunk.metadata or {}).get("parent_id") or "").strip()
            if parent_id and parent_id not in parent_ids:
                parent_ids.append(parent_id)
        if not parent_ids:
            return Expansion(name=self.name, reason=self.reason)
        key = ("parents", tuple(parent_ids))
        if context.cache is not None:
            cached = context.cache.get_chunks(key)
            if cached is not None:
                chunks = [_mark(chunk, "expansion_parent") for chunk in cached]
                return Expansion(
                    name=self.name, reason=self.reason, chunks=chunks, strategy="parent"
                )
        try:
            ctx = await fetch(
                context.query.organization_id,
                parent_ids,
                role=context.query.role,
                user_id=context.query.user_id,
                groups=context.query.groups,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Parent expansion failed", error=str(exc)[:150])
            return Expansion(name=self.name, reason=self.reason)
        raw = [
            chunk
            for chunk in ctx.chunks
            if str((chunk.metadata or {}).get("chunk_id") or "")
            in set(parent_ids)
        ]
        if context.cache is not None:
            context.cache.put_chunks(key, raw)
        chunks = [_mark(chunk, "expansion_parent") for chunk in raw]
        return Expansion(name=self.name, reason=self.reason, chunks=chunks, strategy="parent")


class SectionNeighborhoodExpansion(ExpansionStrategy):
    name = "section_neighborhood"
    reason = "la explicación vive en secciones vecinas de la misma rama"

    def __init__(self, store: object) -> None:
        self._store = store

    async def expand(self, context: ExpansionContext) -> Expansion:
        fetch = getattr(self._store, "get_neighborhood", None)
        if not callable(fetch):
            return Expansion(name=self.name, reason=self.reason)
        parent_ids: list[str] = []
        section_ids: list[str] = []
        neighbor_ids: list[str] = []
        for chunk in _domain_chunks(context, context.limit):
            metadata = chunk.metadata or {}
            parent = str(metadata.get("parent_id") or "").strip()
            section = str(metadata.get("section_id") or "").strip()
            if parent and parent not in parent_ids:
                parent_ids.append(parent)
            if section and section not in section_ids:
                section_ids.append(section)
            # Vecindad exacta de lectura (ingesta nueva): hermano anterior/siguiente.
            for key in ("prev_chunk_id", "next_chunk_id"):
                value = str(metadata.get(key) or "").strip()
                if value and value not in neighbor_ids:
                    neighbor_ids.append(value)
        if not parent_ids and not section_ids and not neighbor_ids:
            return Expansion(name=self.name, reason=self.reason)
        key = ("neighborhood", tuple(parent_ids + neighbor_ids), tuple(parent_ids), tuple(section_ids))
        if context.cache is not None:
            cached = context.cache.get_chunks(key)
            if cached is not None:
                chunks = [_mark(chunk, "expansion_section") for chunk in cached]
                return Expansion(
                    name=self.name, reason=self.reason, chunks=chunks, strategy="neighborhood"
                )
        try:
            ctx = await fetch(
                context.query.organization_id,
                chunk_ids=parent_ids + neighbor_ids,
                parent_ids=parent_ids,
                section_ids=section_ids,
                role=context.query.role,
                user_id=context.query.user_id,
                groups=context.query.groups,
                limit=max(context.limit * 3, 12),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Neighborhood expansion failed", error=str(exc)[:150])
            return Expansion(name=self.name, reason=self.reason)
        if context.cache is not None:
            context.cache.put_chunks(key, list(ctx.chunks))
        chunks = [_mark(chunk, "expansion_section") for chunk in ctx.chunks]
        return Expansion(
            name=self.name, reason=self.reason, chunks=chunks, strategy="neighborhood"
        )


class ExactAnchorExpansion(ExpansionStrategy):
    name = "exact_anchors"
    reason = "hay anchors exactos todavía sin cubrir"

    def __init__(self, store: object) -> None:
        self._store = store

    async def expand(self, context: ExpansionContext) -> Expansion:
        scan = getattr(self._store, "scan_text_literal", None)
        if not callable(scan):
            return Expansion(name=self.name, reason=self.reason)
        needles: list[str] = []
        for needle in context.missing_needles:
            value = str(needle or "").strip()
            if value and value not in needles:
                needles.append(value)
        for anchor in context.anchors:
            for needle in getattr(anchor, "needles", ()) or ():
                value = str(needle or "").strip()
                if value and value not in needles:
                    needles.append(value)
        if not needles:
            return Expansion(name=self.name, reason=self.reason)
        if context.cache is not None:
            pending = [
                needle
                for needle in needles
                if needle.lower() not in context.cache.scanned_needles
            ]
            if not pending:
                return Expansion(name=self.name, reason=self.reason)
            needles = pending
        try:
            ctx = await scan(
                organization_id=context.query.organization_id,
                needles=needles[:12],
                source_ids=context.query.source_ids or None,
                knowledge_base_id=context.query.knowledge_base_id,
                workspace_id=context.query.workspace_id,
                role=context.query.role,
                user_id=context.query.user_id,
                groups=context.query.groups,
                limit=max(context.limit, 4),
                max_points=context.max_points,
                max_ms=context.max_ms,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Exact anchor expansion failed", error=str(exc)[:150])
            return Expansion(name=self.name, reason=self.reason)
        if context.cache is not None:
            for needle in needles:
                context.cache.scanned_needles.add(needle.lower())
        chunks = []
        for chunk in ctx.chunks:
            content = (chunk.content or "").lower()
            matched = next((needle for needle in needles if needle.lower() in content), "")
            chunks.append(
                mark_must_keep(
                    chunk,
                    needle=matched,
                    kind="literal",
                    retrieval="expansion_exact",
                )
            )
        return Expansion(name=self.name, reason=self.reason, chunks=chunks, strategy="exact")


class SameDocumentExpansion(ExpansionStrategy):
    name = "same_document"
    reason = "el documento que ya acierta tiene más contexto aplicable"

    def __init__(self, retrieve: RetrieveFn) -> None:
        self._retrieve = retrieve

    async def expand(self, context: ExpansionContext) -> Expansion:
        source_ids: list[str] = []
        for chunk in _domain_chunks(context, context.limit):
            source_id = str((chunk.metadata or {}).get("source_id") or "").strip()
            if source_id and source_id not in source_ids:
                source_ids.append(source_id)
        if not source_ids:
            return Expansion(name=self.name, reason=self.reason)
        spec = {
            "text": context.query.query,
            "strategy": "hybrid",
            "top_k": max(context.limit * 4, 16),
            "source_ids": source_ids[:3],
        }
        try:
            ctx = await _retrieve_cached(
                context.cache,
                ("retrieve", "hybrid", spec["text"], tuple(spec["source_ids"])),
                self._retrieve,
                spec,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Same-document expansion failed", error=str(exc)[:150])
            return Expansion(name=self.name, reason=self.reason)
        chunks = [_mark(chunk, "expansion_document") for chunk in ctx.chunks]
        return Expansion(name=self.name, reason=self.reason, chunks=chunks, strategy="same_document")


class TableNoteExpansion(ExpansionStrategy):
    name = "table_notes"
    reason = "el fragmento referencia una tabla o nota que hay que traer"

    def __init__(self, store: object) -> None:
        self._store = store

    async def expand(self, context: ExpansionContext) -> Expansion:
        scan = getattr(self._store, "scan_text_literal", None)
        if not callable(scan):
            return Expansion(name=self.name, reason=self.reason)
        needles: list[str] = []
        for chunk in context.chunks:
            content = html.unescape(chunk.content or "")
            for match in _REFERENCE_RE.finditer(content):
                needle = f"{match.group(1)} {match.group(2)}"
                if needle.lower() not in [value.lower() for value in needles]:
                    needles.append(needle)
        if not needles:
            return Expansion(name=self.name, reason=self.reason)
        if context.cache is not None:
            needles = [
                needle
                for needle in needles
                if needle.lower() not in context.cache.scanned_needles
            ]
            if not needles:
                return Expansion(name=self.name, reason=self.reason)
        try:
            ctx = await scan(
                organization_id=context.query.organization_id,
                needles=needles[:8],
                source_ids=context.query.source_ids or None,
                knowledge_base_id=context.query.knowledge_base_id,
                workspace_id=context.query.workspace_id,
                role=context.query.role,
                user_id=context.query.user_id,
                groups=context.query.groups,
                limit=max(context.limit, 4),
                max_points=context.max_points,
                max_ms=context.max_ms,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Table/note expansion failed", error=str(exc)[:150])
            return Expansion(name=self.name, reason=self.reason)
        if context.cache is not None:
            for needle in needles:
                context.cache.scanned_needles.add(needle.lower())
        chunks = [_mark(chunk, "expansion_table_note") for chunk in ctx.chunks]
        return Expansion(
            name=self.name,
            reason=self.reason,
            chunks=chunks,
            strategy="table_notes",
            queries=needles[:3],
        )


class CrossDocumentExpansion(ExpansionStrategy):
    name = "cross_document"
    reason = "la respuesta puede cruzar reglas de otro documento"

    def __init__(self, retrieve: RetrieveFn) -> None:
        self._retrieve = retrieve

    async def expand(self, context: ExpansionContext) -> Expansion:
        terms: list[str] = []
        for needle in context.missing_needles:
            value = str(needle or "").strip()
            if value and value not in terms:
                terms.append(value)
        for anchor in context.anchors:
            expansion_terms = getattr(anchor, "expansion_terms", ()) or ()
            for term in expansion_terms:
                value = str(term or "").strip()
                if value and value not in terms:
                    terms.append(value)
        if not terms:
            return Expansion(name=self.name, reason=self.reason)
        text = " ".join([context.query.query, *terms[:8]])
        try:
            ctx = await _retrieve_cached(
                context.cache,
                ("retrieve", "hybrid", text),
                self._retrieve,
                {
                    "text": text,
                    "strategy": "hybrid",
                    "top_k": max(context.limit * 4, 16),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cross-document expansion failed", error=str(exc)[:150])
            return Expansion(name=self.name, reason=self.reason)
        chunks = [_mark(chunk, "expansion_cross_document") for chunk in ctx.chunks]
        return Expansion(
            name=self.name, reason=self.reason, chunks=chunks, strategy="cross_document"
        )


class ConceptExpansion(ExpansionStrategy):
    name = "concepts"
    reason = "faltan conceptos o entidades relacionados que la pregunta nombra"

    def __init__(self, retrieve: RetrieveFn) -> None:
        self._retrieve = retrieve

    async def expand(self, context: ExpansionContext) -> Expansion:
        terms: list[str] = []
        for anchor in context.anchors:
            hint = str(getattr(anchor, "semantic_hint", "") or "").strip()
            if hint and hint not in terms:
                terms.append(hint)
            for term in getattr(anchor, "expansion_terms", ()) or ():
                value = str(term or "").strip()
                if value and value not in terms:
                    terms.append(value)
        if not terms:
            return Expansion(name=self.name, reason=self.reason)
        text = " ".join(terms[:6])
        try:
            ctx = await _retrieve_cached(
                context.cache,
                ("retrieve", "lexical", text),
                self._retrieve,
                {
                    "text": text,
                    "strategy": "lexical",
                    "top_k": max(context.limit, 6),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Concept expansion failed", error=str(exc)[:150])
            return Expansion(name=self.name, reason=self.reason)
        chunks = [_mark(chunk, "expansion_concept") for chunk in ctx.chunks]
        return Expansion(name=self.name, reason=self.reason, chunks=chunks, strategy="concepts")


class DocumentLevelExpansion(ExpansionStrategy):
    name = "document_level"
    reason = "la consulta pide contexto amplio del documento completo"

    def __init__(self, retrieve: RetrieveFn) -> None:
        self._retrieve = retrieve

    async def expand(self, context: ExpansionContext) -> Expansion:
        source_ids: list[str] = []
        for chunk in _domain_chunks(context, context.limit):
            source_id = str((chunk.metadata or {}).get("source_id") or "").strip()
            if source_id and source_id not in source_ids:
                source_ids.append(source_id)
        if not source_ids:
            return Expansion(name=self.name, reason=self.reason)
        spec = {
            "text": context.query.query,
            "strategy": "vector",
            "top_k": max(context.limit * 2, 8),
            "source_ids": source_ids[:2],
            "filters": {"metadata.v2_doc": "true"},
        }
        try:
            ctx = await _retrieve_cached(
                context.cache,
                ("retrieve", "vector", spec["text"], tuple(spec["source_ids"]), "v2_doc"),
                self._retrieve,
                spec,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Document-level expansion failed", error=str(exc)[:150])
            return Expansion(name=self.name, reason=self.reason)
        chunks = [_mark(chunk, "expansion_doc_level") for chunk in ctx.chunks]
        return Expansion(
            name=self.name, reason=self.reason, chunks=chunks, strategy="document_level"
        )


class GlobalSourceFallbackExpansion(ExpansionStrategy):
    name = "global_sources"
    reason = "la regla/campo no apareció en las fuentes preferidas: barrido global"

    def __init__(self, retrieve: RetrieveFn) -> None:
        self._retrieve = retrieve

    async def expand(self, context: ExpansionContext) -> Expansion:
        text = context.query.query
        spec = {
            "text": text,
            "strategy": "hybrid",
            "top_k": max(context.limit * 4, 20),
            "global_fallback": True,
        }
        try:
            ctx = await _retrieve_cached(
                context.cache,
                ("retrieve", "global", text),
                self._retrieve,
                spec,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Global source fallback failed", error=str(exc)[:150])
            return Expansion(name=self.name, reason=self.reason)
        chunks = [_mark(chunk, "expansion_global") for chunk in ctx.chunks]
        return Expansion(
            name=self.name, reason=self.reason, chunks=chunks, strategy="global"
        )


def _mark(chunk: RetrievalChunk, retrieval: str) -> RetrievalChunk:
    import dataclasses

    metadata = {**(chunk.metadata or {}), "retrieval": retrieval}
    return dataclasses.replace(chunk, metadata=metadata)


def default_strategies(store: object, retrieve: RetrieveFn) -> list[ExpansionStrategy]:
    """Etapas en el orden recomendado: de lo más preciso a lo más amplio."""
    # Import diferido: graph_activation depende de este módulo (evita ciclo).
    from .graph_activation import FabricActivationExpansion

    return [
        ParentSectionExpansion(store),
        SectionNeighborhoodExpansion(store),
        ExactAnchorExpansion(store),
        TableNoteExpansion(store),
        FabricActivationExpansion(store),
        SameDocumentExpansion(retrieve),
        CrossDocumentExpansion(retrieve),
        ConceptExpansion(retrieve),
        DocumentLevelExpansion(retrieve),
        GlobalSourceFallbackExpansion(retrieve),
    ]


__all__ = [
    "ConceptExpansion",
    "CrossDocumentExpansion",
    "DocumentLevelExpansion",
    "ExactAnchorExpansion",
    "Expansion",
    "ExpansionCache",
    "ExpansionContext",
    "ExpansionStrategy",
    "GlobalSourceFallbackExpansion",
    "ParentSectionExpansion",
    "RetrieveFn",
    "SameDocumentExpansion",
    "SectionNeighborhoodExpansion",
    "TableNoteExpansion",
    "default_strategies",
]
