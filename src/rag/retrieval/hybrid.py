# =============================================================================
# HybridRetriever — pipeline completo: clasificar, fusionar, deduplicar,
# rerankear, filtrar por umbral y recortar al presupuesto de contexto.
# =============================================================================
from __future__ import annotations

import asyncio
import dataclasses
import time
from typing import Any

from src.core.domain.entities import RetrievalContext
from src.core.ports import HybridStore, LexicalStore, VectorStore
from src.infrastructure.observability.logging_config import get_logger
from src.rag.longcontext.exact_search import ExactRetriever
from src.rag.longcontext.must_keep import is_must_keep, merge_must_keep
from src.rag.reranking.base import Reranker
from src.rag.retrieval.base import Retriever
from src.rag.retrieval.builders import ContextBuilder
from src.rag.retrieval.classify import classify_query, normalize_query
from src.rag.retrieval.fusion import (
    apply_doc_type_priority,
    dedupe_chunks,
    filter_by_threshold,
    rrf_fusion,
    weighted_fusion,
)
from src.rag.retrieval.lexical_retriever import LexicalRetriever
from src.rag.retrieval.models import (
    FUSION_RRF,
    STRATEGY_HYBRID,
    STRATEGY_LEXICAL,
    STRATEGY_VECTOR,
    RetrievalQuery,
)
from src.rag.retrieval.vector_retriever import VectorRetriever

logger = get_logger(__name__)


class HybridRetriever(Retriever):
    """Motor de retrieval por tenant. Sin acoplamiento a negocio vertical.

    Rutas:
      - vector:  VectorRetriever (comportamiento histórico, aggregated first).
      - lexical: LexicalRetriever (BM25).
      - hybrid:  fusión server-side (HybridStore) o client-side (dos patas
                 en paralelo + RRF/weighted), luego rerank + threshold +
                 budget de contexto.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        lexical_store: LexicalStore | None = None,
        hybrid_store: HybridStore | None = None,
        reranker: Reranker | None = None,
        context_builder: ContextBuilder | None = None,
    ) -> None:
        self._vector = VectorRetriever(vector_store)
        self._lexical = (
            LexicalRetriever(lexical_store) if lexical_store is not None else None
        )
        self._hybrid_store = hybrid_store
        self._store = vector_store
        self._reranker = reranker
        self._builder = context_builder or ContextBuilder(max_context_tokens=32000)
        # Tercera pata: candidatos literales (máscaras, símbolos, códigos) que
        # la densa y la léxica no ven. Aditiva y best-effort.
        self._exact = ExactRetriever(vector_store)

    async def retrieve(self, query: RetrievalQuery) -> RetrievalContext:
        start = time.perf_counter()
        stage_ms: dict[str, float] = {}
        classification = classify_query(query.query)
        normalized = normalize_query(query.query)

        # La pata exacta corre en paralelo: no penaliza latencia del resto.
        async def _timed_exact() -> list[Any]:
            exact_start = time.perf_counter()
            try:
                return await self._retrieve_exact_leg(query)
            finally:
                stage_ms["exact_ms"] = (time.perf_counter() - exact_start) * 1000

        exact_task = asyncio.ensure_future(_timed_exact())

        # SOURCE ROUTING: PASS A limitado a las fuentes preferidas. El fallback
        # global ocurre sólo si PASS A no trajo nada (o lo decide el engine
        # cuando la evidencia sigue incompleta).
        preferred = [
            source_id
            for source_id in (getattr(query, "preferred_source_ids", None) or [])
            if source_id
        ]
        pass_query = (
            dataclasses.replace(query, source_ids=preferred) if preferred else query
        )
        context: RetrievalContext
        server_fused = False
        route_fallback = False
        dispatch_start = time.perf_counter()
        try:
            context, server_fused = await self._dispatch(pass_query, normalized, timing=stage_ms)
            if preferred and not context.chunks:
                context, server_fused = await self._dispatch(query, normalized, timing=stage_ms)
                route_fallback = True
        except Exception:
            exact_task.cancel()
            raise
        stage_ms["dispatch_ms"] = (time.perf_counter() - dispatch_start) * 1000

        chunks = dedupe_chunks(context.chunks)
        chunks = apply_doc_type_priority(chunks, query.doc_type_priority)
        if not server_fused:
            # La fusión client-side conserva los scores por pata (coseno /
            # dot-product), comparables con el umbral anti-alucinación. La
            # fusión server-side devuelve scores RRF (~1/(k+rank)); aplicarles
            # el umbral coseno descartaría hits válidos, así que se omiten
            # (las patas ya fueron filtradas por el store).
            chunks = filter_by_threshold(chunks, query.score_threshold)

        # MUST_KEEP: la evidencia exacta entra después del umbral (no la
        # descarta un cosine bajo) y antes del pin, del rerank y del builder.
        exact_chunks = await exact_task
        if exact_chunks:
            chunks = merge_must_keep(exact_chunks, chunks)

        # Pin por entidad: lo que la pregunta nombra (byte 105, categoría 31,
        # record 4, tabla 961) tiene que estar. Va después del umbral para que
        # el umbral no lo descarte y antes del rerank para que el reranker lo vea.
        pin_start = time.perf_counter()
        chunks = await self._pin_asked_entities(query, chunks)
        stage_ms["entity_pin_ms"] = (time.perf_counter() - pin_start) * 1000
        parent_start = time.perf_counter()
        chunks = await self._expand_pinned_parents(query, chunks)
        stage_ms["parent_expansion_ms"] = (time.perf_counter() - parent_start) * 1000

        if self._reranker is not None and chunks:
            rerank_start = time.perf_counter()
            try:
                reranked = await self._reranker.rerank(
                    query=query.query,
                    chunks=chunks,
                    top_n=query.rerank_top_k,
                    organization_id=str(query.organization_id),
                )
                chunks = self._protect_must_keep(chunks, reranked)
            except Exception as exc:
                logger.warning(
                    "Rerank failed, using retrieval order",
                    error=str(exc),
                    organization_id=str(query.organization_id),
                )
            finally:
                stage_ms["rerank_ms"] = (time.perf_counter() - rerank_start) * 1000

        context_start = time.perf_counter()
        chunks = self._builder.fit_budget(
            chunks, max_context_tokens=query.context_token_budget
        )
        stage_ms["context_build_ms"] = (time.perf_counter() - context_start) * 1000
        stage_ms["retrieval_total_ms"] = (time.perf_counter() - start) * 1000
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "Hybrid retrieval completed",
            strategy=query.strategy,
            classification=classification.kind,
            results_count=len(chunks),
            preferred_sources=len(preferred),
            global_fallback=route_fallback,
            retrieval_latency_ms=round(elapsed_ms, 2),
            organization_id=str(query.organization_id),
        )
        return RetrievalContext(
            chunks=chunks,
            query_embedding=query.query_embedding,
            retrieval_latency_ms=context.retrieval_latency_ms,
            stage_ms=dict(stage_ms),
        )

    async def _dispatch(
        self,
        query: RetrievalQuery,
        normalized: str,
        *,
        timing: dict[str, float] | None = None,
    ) -> tuple[RetrievalContext, bool]:
        if query.strategy == STRATEGY_HYBRID:
            return await self._retrieve_hybrid(query, normalized, timing=timing)
        if query.strategy == STRATEGY_LEXICAL:
            started = time.perf_counter()
            context = await self._retrieve_lexical(query, normalized)
            if timing is not None:
                timing["lexical_ms"] = (time.perf_counter() - started) * 1000
            return context, False
        if query.strategy == STRATEGY_VECTOR:
            started = time.perf_counter()
            context = await self._vector.retrieve(query)
            if timing is not None:
                timing["vector_ms"] = (time.perf_counter() - started) * 1000
            return context, False
        raise ValueError(f"Unknown retrieval strategy: {query.strategy}")

    async def _retrieve_exact_leg(self, query: RetrievalQuery) -> list[Any]:
        """Candidatos literales POR ANCHOR de la consulta cruda (best-effort)."""
        try:
            from src.rag.longcontext.exact_search import spec_from_needle

            items: list[Any] = list(getattr(query, "exact_anchors", None) or [])
            if not items:
                needles = [
                    str(needle).strip()
                    for needle in (query.exact_needles or [])
                    if str(needle or "").strip()
                ]
                if needles:
                    items = [spec_from_needle(needle) for needle in needles]
                else:
                    from src.rag.longcontext.views import build_query_views

                    views = build_query_views(query.query)
                    items = list(views.anchors) if views.exact_terms else []
            if not items:
                return []
            context = await self._exact.retrieve(query, items)
            return list(context.chunks)
        except Exception as exc:  # noqa: BLE001 — la pata exacta jamás tumba el retrieval
            logger.warning("Exact leg failed", error=str(exc)[:200])
            return []

    @staticmethod
    def _protect_must_keep(
        chunks: list[Any],
        reranked: list[Any],
    ) -> list[Any]:
        """El reranker ordena, no expulsa: MUST_KEEP vuelve al frente."""
        keep_ids = {chunk.document_id for chunk in reranked}
        protected = [
            chunk
            for chunk in chunks
            if is_must_keep(chunk) and chunk.document_id not in keep_ids
        ]
        if not protected:
            return list(reranked)
        return protected + list(reranked)

    async def _retrieve_lexical(
        self, query: RetrievalQuery, normalized: str
    ) -> RetrievalContext:
        if self._lexical is None:
            raise ValueError("Lexical strategy requires a LexicalStore")
        return await self._lexical.retrieve(query)

    # ------------------------------------------------------------------
    # Pin por entidad nombrada en la pregunta
    # ------------------------------------------------------------------
    def _entity_pin_settings(self) -> tuple[bool, int, int, float]:
        """(activo, límite de chunks, puntos, ms) del pin. Tolerante a settings."""
        try:
            from src.core.config import get_settings

            settings = get_settings()

            def _leer(nombre: str, default):
                return getattr(settings, nombre, default)

            activo = str(_leer("RAG_RETRIEVAL_ENTITY_PIN", "on")).lower() not in (
                "off",
                "0",
                "false",
            )
            return (
                activo,
                max(int(_leer("RAG_RETRIEVAL_ENTITY_PIN_CHUNKS", 3) or 3), 1),
                max(int(_leer("RAG_RETRIEVAL_ENTITY_SCAN_MAX_POINTS", 3000) or 0), 0),
                max(float(_leer("RAG_RETRIEVAL_ENTITY_SCAN_MAX_MS", 1500) or 0), 0.0),
            )
        except Exception:  # noqa: BLE001 — el pin nunca rompe el retrieval
            return True, 3, 3000, 1500.0

    async def _pin_asked_entities(
        self,
        query: RetrievalQuery,
        chunks: list[Any],
    ) -> list[Any]:
        """Garantiza que lo que la pregunta nombra esté en la evidencia.

        Dos etapas, ambas deterministas y sin LLM:
        1. pata léxica con **sólo** el label de la entidad («byte 105»): la
           pregunta completa diluye el token exacto, el label no;
        2. si la entidad sigue sin aparecer, barrido por frase acotado
           (puntos + tiempo) sobre las fuentes de la consulta.
        Los aciertos se ordenan al frente con el score del mejor hit primario
        para que el recorte por presupuesto no los descarte.
        """
        activo, pin_chunks, max_points, max_ms = self._entity_pin_settings()
        if not activo:
            return chunks

        from src.intelligence.response.anchors import (
            Anchor,
            anchor_covered,
            extract_anchors,
        )
        from src.intelligence.response.entities import (
            AskedEntity,
            asked_entities,
            normalize,
        )

        entidades = asked_entities(query.query)
        anchors = extract_anchors(query.query)
        if not entidades and not anchors:
            return chunks

        def _texto(items: list[Any]) -> str:
            return "\n".join(getattr(item, "content", "") or "" for item in items)

        def _presente(entidad: AskedEntity, texto: str) -> bool:
            """Frase exacta del label («byte 105»), no el número suelto.

            `entity_covered` es deliberadamente laxo para la nota de cobertura
            (cualquier «105» cuenta); para el pin hace falta precisión: si no
            aparece la frase, hay que ir a buscarla.
            """
            haystack = normalize(texto)
            if not haystack:
                return False
            return any(variante and variante in haystack for variante in entidad.variants)

        def _presente_en_titulo(entidad: AskedEntity, items: list[Any]) -> bool:
            """¿La entidad aparece en el TÍTULO de algún chunk ya recuperado?

            Sólo cuenta la primera línea y sólo si es una línea de título: una
            fila de tabla («Byte 105 | Fee application | …») menciona el campo en
            su arranque pero NO lo explica, y daba la entidad por cubierta.
            """
            for item in items:
                contenido = str(getattr(item, "content", "") or "")
                primera = contenido.splitlines()[0] if contenido.strip() else ""
                if not primera or "|" in primera:
                    continue
                linea = normalize(primera)
                if any(variante and variante in linea for variante in entidad.variants):
                    return True
            return False

        etapas: dict[str, int] = {}
        pinned: list[Any] = []

        def _needles_de_entidad(entidad: AskedEntity) -> list[str]:
            """Label, normalizado y variantes: la forma EN cubre docs en inglés."""
            needles = [entidad.label]
            normalizado = normalize(entidad.label)
            if normalizado and normalizado != entidad.label:
                needles.append(normalizado)
            for variant in entidad.variants:
                if variant and variant not in needles:
                    needles.append(variant)
            return needles

        def _anchor_presente(anchor: Anchor, texto: str) -> bool:
            return anchor_covered(anchor, texto)

        def _anchor_presente_en_titulo(anchor: Anchor, items: list[Any]) -> bool:
            for item in items:
                contenido = str(getattr(item, "content", "") or "")
                primera = contenido.splitlines()[0] if contenido.strip() else ""
                if not primera or "|" in primera:
                    continue
                linea = normalize(primera)
                if any(variante and variante in linea for variante in anchor.variants):
                    return True
            return False

        def _todo_presente(items: list[Any]) -> bool:
            texto = _texto(items)
            return all(_presente(e, texto) for e in entidades) and all(
                _anchor_presente(a, texto) for a in anchors
            )

        def _fuentes_relevantes() -> list[Any]:
            """Fuentes que ya aparecieron en la búsqueda: las del tema."""
            vistas: list[Any] = []
            for chunk in chunks + pinned:
                metadata = getattr(chunk, "metadata", None) or {}
                source_id = metadata.get("source_id")
                if source_id and source_id not in vistas:
                    vistas.append(source_id)
            return vistas

        def _objetivos() -> list[list[Any] | None]:
            relevantes = _fuentes_relevantes()
            grupos: list[list[Any] | None] = []
            # 1) Las fuentes cuyo NOMBRE coincide con lo que la pregunta nombra
            #    («Cat31_dapp_C.pdf» para «categoría 31»): ahí está la sección.
            if query.source_priority:
                grupos.append(list(query.source_priority))
            # 2) Las que ya aparecieron en la búsqueda (del tema).
            if relevantes:
                grupos.append(relevantes)
            # 3) El resto de las fuentes de la consulta.
            ya_vistas = {
                str(item)
                for grupo in grupos
                for item in (grupo or [])
            }
            resto = [
                sid for sid in (query.source_ids or []) if str(sid) not in ya_vistas
            ]
            if resto:
                grupos.append(resto)
            if not grupos:
                # Sin fuentes declaradas (p. ej. chat por colección): barrido de
                # organización, acotado por puntos y tiempo.
                grupos.append(None)
            return grupos

        async def _barrer(
            needles: list[str], *, heading_only: bool, solo_relevantes: bool = False
        ) -> int:
            scan = getattr(self._store, "scan_text", None)
            if not callable(scan) or not needles:
                return 0
            encontrados_total = 0
            for indice, objetivo in enumerate(_objetivos()):
                if solo_relevantes and objetivo is None:
                    break
                # El primer grupo (fuentes prioritarias/relevantes) se lleva el
                # presupuesto completo; los siguientes, la mitad: ahí el barrido
                # es una red de seguridad, no la vía principal.
                factor = 1.0 if indice == 0 else 0.5
                try:
                    encontrados = await scan(
                        organization_id=query.organization_id,
                        needles=needles,
                        source_ids=objetivo,
                        knowledge_base_id=query.knowledge_base_id,
                        workspace_id=query.workspace_id,
                        role=query.role,
                        user_id=query.user_id,
                        groups=query.groups,
                        limit=pin_chunks,
                        max_points=max(200, int(max_points * factor)),
                        max_ms=max(200.0, max_ms * factor),
                        heading_only=heading_only,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Entity phrase scan failed", error=str(exc)[:150])
                    continue
                encontrados_total += len(encontrados.chunks)
                pinned.extend(encontrados.chunks)
                if encontrados.chunks:
                    break
            return encontrados_total

        # Etapa 0: la sección cuyo TÍTULO es lo que se pregunta («4.6.2 Fee
        # Application (byte 105)»). Una mención al pasar en una tabla de campos
        # no explica nada: el título sí. Se busca por entidad y con el label
        # exacto: las variantes sueltas («cat 31») matchean títulos de documento
        # y desplazan a la sección que importa.
        etapas["heading"] = 0
        if max_points > 0:
            for entidad in entidades:
                # Sin atajos: la sección cuyo título ES el campo pedido es la que
                # lo explica, y cuesta milisegundos traerla. Los atajos por
                # «mención presente» dejaban afuera justamente esa sección.
                # Las needles incluyen las variantes («category 5»): la pregunta
                # puede venir en español y el documento estar en inglés.
                etapas["heading"] += await _barrer(
                    _needles_de_entidad(entidad), heading_only=True
                )
                # Sólo se corta cuando TODAS las entidades nombradas aparecieron:
                # cortar con la primera dejaba sin buscar la segunda («categoría
                # 31» encontrada, «byte 105» nunca buscado).
                if _todo_presente(pinned):
                    break
            for anchor in anchors:
                if _todo_presente(pinned):
                    break
                etapas["heading"] += await _barrer(
                    list(anchor.needles), heading_only=True
                )

        # Etapa 1: léxico por entidad (una consulta por entidad, sin el resto).
        if self._lexical is not None:
            for entidad in entidades[:2]:
                if _presente_en_titulo(entidad, chunks + pinned):
                    continue
                try:
                    parte = await self._lexical.retrieve(
                        dataclasses.replace(
                            query,
                            query=entidad.label,
                            top_k=pin_chunks,
                            effective_top_k=pin_chunks,
                            score_threshold=0.0,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Entity lexical pin failed", error=str(exc)[:150])
                    continue
                pinned.extend(
                    dataclasses.replace(chunk, metadata={**chunk.metadata, "retrieval": "entity_lexical"})
                    for chunk in parte.chunks[:pin_chunks]
                )
            for anchor in anchors[:2]:
                if not anchor.needles:
                    continue
                if _anchor_presente_en_titulo(anchor, chunks + pinned):
                    continue
                try:
                    parte = await self._lexical.retrieve(
                        dataclasses.replace(
                            query,
                            query=anchor.needles[0],
                            top_k=pin_chunks,
                            effective_top_k=pin_chunks,
                            score_threshold=0.0,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Anchor lexical pin failed", error=str(exc)[:150])
                    continue
                pinned.extend(
                    dataclasses.replace(chunk, metadata={**chunk.metadata, "retrieval": "entity_lexical"})
                    for chunk in parte.chunks[:pin_chunks]
                )
            etapas["lexical"] = len(pinned)

        # Etapa 2: barrido por frase cuando la entidad no aparece ni siquiera
        # mencionada (el título ya se intentó arriba).
        faltantes = [
            entidad
            for entidad in entidades
            if not _presente(entidad, _texto(chunks + pinned))
        ]
        faltantes_anchors = [
            anchor
            for anchor in anchors
            if not _anchor_presente(anchor, _texto(chunks + pinned))
        ]
        escaneados = 0
        if (faltantes or faltantes_anchors) and max_points > 0:
            needle_variants: list[str] = []
            for entidad in faltantes:
                for needle in _needles_de_entidad(entidad):
                    if needle not in needle_variants:
                        needle_variants.append(needle)
            for anchor in faltantes_anchors:
                for needle in anchor.needles:
                    if needle and needle not in needle_variants:
                        needle_variants.append(needle)
            # Primero las fuentes que ya aparecieron en la búsqueda (son las
            # relevantes al tema); si no alcanza, el resto. Sin este orden, con
            # 60+ fuentes el barrido puede no llegar nunca a la que tiene el dato.
            escaneados = await _barrer(needle_variants, heading_only=False)
        etapas["scan"] = escaneados

        if not pinned:
            self._observe_entity_pin(query, etapas, cubiertas=True)
            return chunks

        conocido = {getattr(chunk, "document_id", None) for chunk in chunks}
        nuevos = [c for c in pinned if getattr(c, "document_id", None) not in conocido]
        top_score = max((float(getattr(c, "score", 0.0) or 0.0) for c in chunks), default=0.0)
        destacados = [
            dataclasses.replace(chunk, score=max(float(chunk.score or 0.0), top_score))
            for chunk in nuevos
        ]
        self._observe_entity_pin(query, etapas, cubiertas=bool(destacados))
        return destacados + chunks

    async def _expand_pinned_parents(
        self,
        query: RetrievalQuery,
        chunks: list[Any],
    ) -> list[Any]:
        """Cambia un fragmento pineado por la sección completa que lo contiene.

        Los hijos del chunker son piezas de ~600 chars que repiten el título; el
        texto que explica el campo vive en el padre de sección. Sin este paso la
        entidad queda «cubierta» por una tabla partida y el generador rellena de
        memoria. Best-effort: si el store no sabe buscar por `metadata.chunk_id`
        o la fuente no tiene padre indexado, se conservan los hijos.
        """
        if not chunks:
            return chunks
        fetch = getattr(self._store, "get_documents_by_chunk_ids", None)
        if not callable(fetch):
            return chunks
        objetivos: dict[str, list[Any]] = {}
        for chunk in chunks:
            metadata = getattr(chunk, "metadata", None) or {}
            parent_id = str(metadata.get("parent_id") or "")
            retrieval = str(metadata.get("retrieval") or "")
            if parent_id and retrieval.startswith("entity"):
                objetivos.setdefault(parent_id, []).append(chunk)
        if not objetivos:
            return chunks
        try:
            contexto = await fetch(
                query.organization_id,
                list(objetivos)[:8],
                role=query.role,
                user_id=query.user_id,
                groups=query.groups,
            )
        except Exception as exc:  # noqa: BLE001 — la expansión nunca rompe el retrieval
            logger.warning("Pinned parent expansion failed", error=str(exc)[:150])
            return chunks

        padres: dict[str, Any] = {}
        for parent in contexto.chunks:
            metadata = getattr(parent, "metadata", None) or {}
            chunk_id = str(metadata.get("chunk_id") or "")
            if chunk_id not in objetivos:
                continue
            score = max(
                [float(getattr(hijo, "score", 0.0) or 0.0) for hijo in objetivos[chunk_id]]
                + [float(getattr(parent, "score", 0.0) or 0.0)]
            )
            padres[chunk_id] = dataclasses.replace(
                parent,
                score=score,
                metadata={
                    **metadata,
                    "retrieval": "entity_section",
                    "v2_parent": "true",
                },
            )
        if not padres:
            return chunks

        expansion = [padres[chunk_id] for chunk_id in objetivos if chunk_id in padres]
        expansion_ids = {padre.document_id for padre in expansion}
        restantes = [
            chunk
            for chunk in chunks
            if str((getattr(chunk, "metadata", None) or {}).get("parent_id") or "")
            not in padres
            and getattr(chunk, "document_id", None) not in expansion_ids
        ]
        logger.info(
            "Pinned fragments expanded to their section",
            fragments=sum(len(hijos) for hijos in objetivos.values()),
            sections=len(expansion),
            organization_id=str(query.organization_id),
        )
        return expansion + restantes

    @staticmethod
    def _observe_entity_pin(query: RetrievalQuery, etapas: dict[str, int], *, cubiertas: bool) -> None:
        try:
            from src.infrastructure.observability.metrics import (
                zent_retrieval_entity_pin_total,
            )

            zent_retrieval_entity_pin_total.labels(
                outcome="hit" if cubiertas else "miss",
                stage="lexical" if etapas.get("lexical") else "scan",
            ).inc()
        except Exception:  # noqa: BLE001 — métrica nunca rompe el retrieval
            return
        logger.info(
            "Entity pin applied",
            entity_lexical=etapas.get("lexical", 0),
            entity_scan=etapas.get("scan", 0),
            organization_id=str(query.organization_id),
        )

    async def _retrieve_hybrid(
        self,
        query: RetrievalQuery,
        normalized: str,
        *,
        timing: dict[str, float] | None = None,
    ) -> tuple[RetrievalContext, bool]:
        """Retorna (contexto, fusion_server_side).

        La fusión client-side tiene prioridad cuando hay LexicalStore: conserva
        los scores por pata para el umbral anti-alucinación. La fusión
        server-side (un solo round-trip) queda como fallback cuando no hay
        pata lexical local; sus scores son RRF y el umbral coseno se omite.
        """

        async def _timed(coro, key: str):
            started = time.perf_counter()
            try:
                return await coro
            finally:
                if timing is not None:
                    timing[key] = (time.perf_counter() - started) * 1000

        if self._lexical is not None:
            vector_task = asyncio.ensure_future(
                _timed(self._vector.retrieve(query), "vector_ms")
            )
            lexical_task = asyncio.ensure_future(
                _timed(self._lexical.retrieve(query), "lexical_ms")
            )
            vector_ctx, lexical_ctx = await asyncio.gather(vector_task, lexical_task)

            fusion_started = time.perf_counter()
            if query.fusion == FUSION_RRF:
                fused = rrf_fusion([vector_ctx.chunks, lexical_ctx.chunks], k=query.rrf_k)
            else:
                fused = weighted_fusion(
                    [vector_ctx.chunks, lexical_ctx.chunks],
                    weights=[1.0 - query.lexical_weight, query.lexical_weight],
                )
            if timing is not None:
                timing["hybrid_fusion_ms"] = (
                    time.perf_counter() - fusion_started
                ) * 1000
            return (
                RetrievalContext(
                    chunks=fused,
                    query_embedding=query.query_embedding,
                    retrieval_latency_ms=vector_ctx.retrieval_latency_ms
                    + lexical_ctx.retrieval_latency_ms,
                ),
                False,
            )

        # Sin pata lexical local: fusión server-side si el adaptador la soporta.
        if self._hybrid_store is not None and query.query_embedding is not None:
            started = time.perf_counter()
            ctx = await self._hybrid_store.search_hybrid(
                organization_id=query.organization_id,
                query_text=normalized,
                query_embedding=query.query_embedding,
                top_k=query.top_k,
                filters=query.filters or None,
                exclude_filters=query.exclude_filters or None,
                score_threshold=query.score_threshold,
                role=query.role,
                user_id=query.user_id,
                groups=query.groups,
                knowledge_base_id=query.knowledge_base_id,
                workspace_id=query.workspace_id,
                source_ids=query.source_ids or None,
            )
            if timing is not None:
                timing["hybrid_fusion_ms"] = (time.perf_counter() - started) * 1000
            return ctx, True

        started = time.perf_counter()
        ctx = await self._vector.retrieve(query)
        if timing is not None:
            timing["vector_ms"] = (time.perf_counter() - started) * 1000
        return ctx, False
