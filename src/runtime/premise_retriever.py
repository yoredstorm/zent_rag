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
_INFORMATIVE = re.compile(r"[A-Za-zÁÉÍÓÚÑÜáéíóúñü]{5,}")
_MIN_EXACT_NEEDLE = 2
_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "before",
        "being",
        "between",
        "could",
        "other",
        "should",
        "their",
        "there",
        "these",
        "those",
        "through",
        "under",
        "using",
        "where",
        "which",
        "while",
        "would",
    }
)


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


def exact_needles(query: str, *, max_needles: int = 8) -> list[str]:
    """Needles literales de una premisa.

    Incluye símbolos, frases entrecomilladas y términos informativos (>=5
    letras, sin stopwords) para que la pata exacta encuentre la definición
    aunque el símbolo solo (1 char) no sea escaneable.
    """
    text = html.unescape(str(query or ""))
    needles: list[str] = []

    def add(value: str) -> None:
        value = value.strip()
        if value and value not in needles:
            needles.append(value)

    for match in _SYMBOL_TOKEN.finditer(text):
        token = match.group(0).strip(".,;:()[]")
        if len(token) >= _MIN_EXACT_NEEDLE:
            add(token)
    for quoted in _QUOTED.findall(text):
        add(quoted)
    for token in _INFORMATIVE.findall(text):
        lowered = token.lower()
        if lowered in _STOPWORDS:
            continue
        add(lowered)
        if lowered.endswith("s") and len(lowered) - 1 >= 5:
            add(lowered[:-1])
    return needles[:max_needles]


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
        exact_limit: int = 8,
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
        source_ids = [u for u in (_uuid(s) for s in scope.source_ids) if u]
        # Escalado §4: doc/source primero; tenant/workspace autorizado después.
        tiers: list[dict[str, Any]] = [{"source_ids": source_ids}] if source_ids else []
        tiers.append({})
        scanners = [self._vector_store.scan_text_literal]
        tokenized = getattr(self._vector_store, "scan_text", None)
        if tokenized is not None:
            scanners.append(tokenized)
        for tier in tiers:
            for scanner in scanners:
                try:
                    context = await scanner(
                        self._organization_id,
                        needles,
                        source_ids=tier.get("source_ids"),
                        workspace_id=self._workspace_id,
                        role=self._role,
                        user_id=self._user_id,
                        groups=self._groups,
                        limit=min(limit, self._exact_limit),
                    )
                except Exception:  # noqa: BLE001, S112 — lane fail-soft
                    continue
                hits = [
                    hit
                    for chunk in (getattr(context, "chunks", None) or [])
                    if (
                        hit := _chunk_to_hit(
                            chunk, lane="exact", matched=tuple(needles)
                        )
                    )
                ]
                if hits:
                    # Ranking por cobertura de needles: el chunk que explica el
                    # símbolo (alias + posición + alfanumérico) gana sobre el
                    # que solo lo menciona al pasar.
                    lowered = [needle.lower() for needle in needles]

                    def _coverage(hit: EvidenceHit, needles_lower: list[str] = lowered) -> int:
                        text = hit.content.lower()
                        return sum(1 for needle in needles_lower if needle in text)

                    hits.sort(key=_coverage, reverse=True)
                    return hits
        return []

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
        source_ids = [u for u in (_uuid(s) for s in scope.source_ids) if u]
        document_id = str(scope.document_id or "")
        # Escalado §4: documento -> source -> tenant/workspace autorizado.
        tiers: list[dict[str, Any]] = []
        if document_id:
            tiers.append({"document_id": document_id, "source_ids": source_ids})
        if source_ids:
            tiers.append({"source_ids": source_ids})
        tiers.append({})
        for tier in tiers:
            filters: dict[str, str] = {}
            if tier.get("document_id"):
                filters["metadata.document_id"] = tier["document_id"]
            request = RetrievalQuery(
                query=query,
                organization_id=self._organization_id,
                role=self._role,
                user_id=self._user_id,
                groups=self._groups,
                workspace_id=self._workspace_id,
                source_ids=tier.get("source_ids") or [],
                top_k=max(limit * 3, limit),
                effective_top_k=max(limit * 3, limit),
                rerank_top_k=max(limit, 8),
                score_threshold=0.0,
                filters=filters,
                query_embedding=embedding,
            )
            try:
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
            except Exception:  # noqa: BLE001, S112 — tier fail-soft
                continue
            chunks = list(getattr(assembled, "context", None) or [])
            if not chunks:
                chunks = list(getattr(assembled, "children", None) or [])
            strict = bool(tier.get("document_id") or tier.get("source_ids"))
            hits: list[EvidenceHit] = []
            for chunk in chunks:
                hit = _chunk_to_hit(chunk, lane="canonical")
                if hit is None:
                    continue
                if tier.get("document_id") and hit.document_id != tier["document_id"]:
                    continue
                if (
                    strict
                    and scope.section_path
                    and hit.section_path[: len(scope.section_path)]
                    != tuple(scope.section_path)
                ):
                    continue
                hits.append(hit)
                if len(hits) >= limit:
                    break
            if hits:
                return hits
        return []

    # -- contract -----------------------------------------------------------

    async def search(self, query: str, scope: SourceScope, limit: int) -> list[EvidenceHit]:
        """EvidenceSearchFn: mismo contrato que Premise Closure espera.

        Corre AMBOS lanes (exact + canónico) y rankea por cobertura de needles:
        el lane exacto no debe tapar un chunk que el canónico sí encontró.
        """
        limit = max(1, int(limit or 1))
        needles = [needle.lower() for needle in exact_needles(query)]
        collected: list[EvidenceHit] = []
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
            collected.extend(lane_hits)

        def _rank(hit: EvidenceHit) -> float:
            text = hit.content.lower()
            coverage = sum(1 for needle in needles if needle in text)
            lane_bonus = 0.5 if hit.lane == "exact" else 0.0
            return coverage + lane_bonus + min(float(hit.score or 0.0), 1.0) * 0.1

        hits: list[EvidenceHit] = []
        seen: set[str] = set()
        for hit in sorted(collected, key=_rank, reverse=True):
            identity = _identity(hit.content, hit.evidence_id)
            if identity in seen:
                continue
            seen.add(identity)
            hits.append(hit)
            if len(hits) >= limit:
                break
        # Preferencia de scope (§4): si hay hits del documento/fuente pedidos,
        # se usan esos; solo si no hay ninguno se conserva la búsqueda ampliada.
        wanted = {str(item) for item in scope.document_ids if item}
        if wanted:
            scoped = [hit for hit in hits if hit.document_id in wanted]
            if scoped:
                return scoped[:limit]
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
