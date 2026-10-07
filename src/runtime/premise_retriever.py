# =============================================================================
# Premise Evidence Retriever — adapter canónico de evidence search
# =============================================================================
# Único adapter reusable para Premise Closure. Usa el retriever CANÓNICO de
# Knowledge OS (get_knowledge_retriever / StructuredRetriever) y la pata
# exacta del MISMO QdrantVectorStore (scan_text_literal). No crea un segundo
# índice, no llama endpoints HTTP, no amplía scope.
#
# Lanes (§6):
#   1. exact literal (símbolos y frases entrecomilladas) — primero para
#      símbolos de un carácter, que el tokenizador BM25 destruye.
#   2. retrieval canónico (lexical/dense) con el texto de la premisa.
# Cada hit registra su lane en EvidenceHit.lane.
# =============================================================================
from __future__ import annotations

import hashlib
import html
import re
from typing import Any, Sequence
from uuid import UUID

from src.runtime.premise_closure import EvidenceHit, SourceScope

_SYMBOLS = "&*?%#$@!~^|"
_SYMBOL_TOKEN = re.compile(rf"[^\s]*[{re.escape(_SYMBOLS)}][^\s]*")
_QUOTED = re.compile(r"[\"“”'‘’]([^\"“”'‘’]{2,80})[\"“”'‘’]")
_MIN_EXACT_NEEDLE = 2


def _uuid(value: Any) -> UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _identity(content: str, evidence_id: str) -> str:
    if evidence_id:
        return evidence_id
    return hashlib.sha256(str(content or "")[:400].encode("utf-8")).hexdigest()[:32]


def _section_path(metadata: dict[str, Any]) -> tuple[str, ...]:
    raw = metadata.get("section_path") or metadata.get("heading_path") or ()
    if isinstance(raw, str):
        try:
            import json

            parsed = json.loads(raw)
            raw = parsed if isinstance(parsed, list) else [raw]
        except (TypeError, ValueError):
            raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(str(part) for part in raw if str(part or "").strip())


def _page(metadata: dict[str, Any]) -> int | None:
    for key in ("page", "page_start", "page_number"):
        value = metadata.get(key)
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _chunk_to_hit(chunk: Any, *, lane: str, matched: tuple[str, ...] = ()) -> EvidenceHit | None:
    content = str(getattr(chunk, "content", "") or getattr(chunk, "text", "") or "")
    if not content.strip():
        return None
    metadata = getattr(chunk, "metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    evidence_id = str(
        metadata.get("chunk_id")
        or metadata.get("evidence_id")
        or getattr(chunk, "evidence_id", "")
        or ""
    )
    document_id = str(metadata.get("document_id") or getattr(chunk, "document_id", "") or "")
    source_id = str(metadata.get("source_id") or getattr(chunk, "source_id", "") or "")
    return EvidenceHit(
        evidence_id=evidence_id,
        content=content[:4000],
        document_id=document_id,
        source_id=source_id,
        page=_page(metadata),
        section_path=_section_path(metadata),
        score=float(getattr(chunk, "score", 0.0) or 0.0),
        matched_premises=matched,
        lane=lane,
    )


def exact_needles(query: str) -> list[str]:
    """Needles literales de una premisa: símbolos y frases entrecomilladas."""
    text = html.unescape(str(query or ""))
    needles: list[str] = []
    for match in _SYMBOL_TOKEN.finditer(text):
        token = match.group(0).strip(".,;:()[]")
        if len(token) >= _MIN_EXACT_NEEDLE and token not in needles:
            needles.append(token)
    for quoted in _QUOTED.findall(text):
        value = quoted.strip()
        if len(value) >= _MIN_EXACT_NEEDLE and value not in needles:
            needles.append(value)
    return needles[:6]


class PremiseEvidenceRetriever:
    """EvidenceSearchFn sobre el retrieval canónico + pata exacta del store."""

    def __init__(
        self,
        *,
        organization_id: Any,
        workspace_id: Any = None,
        role: str = "admin",
        user_id: Any = None,
        groups: Sequence[str] = (),
        retriever: Any = None,
        vector_store: Any = None,
        embedding_provider: Any = None,
        exact_limit: int = 4,
    ) -> None:
        self._organization_id = _uuid(organization_id)
        self._workspace_id = _uuid(workspace_id)
        self._role = str(role or "admin")
        self._user_id = _uuid(user_id)
        self._groups = [str(group) for group in groups or ()]
        self._retriever = retriever
        self._vector_store = vector_store
        self._embedder = embedding_provider
        self._exact_limit = max(1, int(exact_limit))
        self.last_lanes: dict[str, int] = {}

    # -- lanes --------------------------------------------------------------

    async def _exact_lane(self, query: str, scope: SourceScope, limit: int) -> list[EvidenceHit]:
        if self._vector_store is None or self._organization_id is None:
            return []
        needles = exact_needles(query)
        if not needles:
            return []
        context = await self._vector_store.scan_text_literal(
            self._organization_id,
            needles,
            source_ids=[u for u in (_uuid(s) for s in scope.source_ids) if u],
            workspace_id=self._workspace_id,
            role=self._role,
            user_id=self._user_id,
            groups=self._groups,
            limit=min(limit, self._exact_limit),
        )
        hits = [
            hit
            for chunk in (getattr(context, "chunks", None) or [])
            if (hit := _chunk_to_hit(chunk, lane="exact", matched=tuple(needles)))
        ]
        return hits

    async def _canonical_lane(self, query: str, scope: SourceScope, limit: int) -> list[EvidenceHit]:
        if self._retriever is None or self._organization_id is None or not query.strip():
            return []
        from src.rag.retrieval.models import RetrievalQuery
        from src.rag.retrieval.structured import V2RetrievalOptions

        embedding: list[float] | None = None
        if self._embedder is not None:
            embedded = await self._embedder.embed(query)
            if embedded and isinstance(embedded[0], list):
                embedded = embedded[0]
            if embedded and isinstance(embedded[0], (int, float)):
                embedding = [float(value) for value in embedded]
        filters: dict[str, str] = {}
        document_id = str(scope.document_id or "")
        if document_id:
            filters["metadata.document_id"] = document_id
        request = RetrievalQuery(
            query=query,
            organization_id=self._organization_id,
            role=self._role,
            user_id=self._user_id,
            groups=self._groups,
            workspace_id=self._workspace_id,
            source_ids=[u for u in (_uuid(s) for s in scope.source_ids) if u],
            top_k=max(limit * 3, limit),
            effective_top_k=max(limit * 3, limit),
            rerank_top_k=max(limit, 8),
            score_threshold=0.0,
            filters=filters,
            query_embedding=embedding,
        )
        assembled = await self._retriever.retrieve(
            request,
            V2RetrievalOptions(
                candidate_k=max(40, limit * 4),
                rerank_k=max(limit, 8),
                final_context_k=limit,
                parent_expansion=False,
                source_diversity=False,
            ),
        )
        chunks = list(getattr(assembled, "context", None) or [])
        if not chunks:
            chunks = list(getattr(assembled, "children", None) or [])
        wanted_documents = {str(item) for item in scope.document_ids if item}
        hits: list[EvidenceHit] = []
        for chunk in chunks:
            hit = _chunk_to_hit(chunk, lane="canonical")
            if hit is None:
                continue
            if wanted_documents and hit.document_id not in wanted_documents:
                continue
            if scope.section_path and hit.section_path[: len(scope.section_path)] != tuple(scope.section_path):
                continue
            hits.append(hit)
            if len(hits) >= limit:
                break
        return hits

    # -- contract -----------------------------------------------------------

    async def search(self, query: str, scope: SourceScope, limit: int) -> list[EvidenceHit]:
        """EvidenceSearchFn: mismo contrato que Premise Closure espera."""
        limit = max(1, int(limit or 1))
        hits: list[EvidenceHit] = []
        seen: set[str] = set()
        for lane_name, lane in (
            ("exact", self._exact_lane),
            ("canonical", self._canonical_lane),
        ):
            try:
                lane_hits = await lane(str(query or ""), scope, limit)
            except Exception:  # noqa: BLE001 — lane fail-soft, la closure sigue
                self.last_lanes[f"{lane_name}_errors"] = (
                    self.last_lanes.get(f"{lane_name}_errors", 0) + 1
                )
                continue
            self.last_lanes[lane_name] = self.last_lanes.get(lane_name, 0) + len(lane_hits)
            for hit in lane_hits:
                identity = _identity(hit.content, hit.evidence_id)
                if identity in seen:
                    continue
                seen.add(identity)
                hits.append(hit)
            if len(hits) >= limit:
                break
        return hits[:limit]


def build_premise_evidence_search(
    organization_id: Any,
    *,
    workspace_id: Any = None,
    role: str = "admin",
    user_id: Any = None,
    groups: Sequence[str] = (),
    retriever: Any = None,
    vector_store: Any = None,
    embedding_provider: Any = None,
) -> Any | None:
    """Factory central: un solo adapter para orchestrator y agent_runtime.

    Fail-soft: si el retriever canónico no está disponible (tests/CLI),
    devuelve None y Premise Closure mantiene su comportamiento previo.
    """
    try:
        if retriever is None or vector_store is None or embedding_provider is None:
            from src.api.deps import (
                get_embedding_provider,
                get_knowledge_retriever,
                get_vector_store,
            )

            retriever = retriever or get_knowledge_retriever()
            vector_store = vector_store or get_vector_store()
            embedding_provider = embedding_provider or get_embedding_provider()
    except Exception:  # noqa: BLE001 — sin deps no hay adapter, no hay crash
        return None
    adapter = PremiseEvidenceRetriever(
        organization_id=organization_id,
        workspace_id=workspace_id,
        role=role,
        user_id=user_id,
        groups=groups,
        retriever=retriever,
        vector_store=vector_store,
        embedding_provider=embedding_provider,
    )
    return adapter.search


__all__ = [
    "PremiseEvidenceRetriever",
    "build_premise_evidence_search",
    "exact_needles",
]
