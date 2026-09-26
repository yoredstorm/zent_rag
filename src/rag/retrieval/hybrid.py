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

    async def retrieve(self, query: RetrievalQuery) -> RetrievalContext:
        start = time.perf_counter()
        classification = classify_query(query.query)
        normalized = normalize_query(query.query)

        context: RetrievalContext
        server_fused = False
        if query.strategy == STRATEGY_HYBRID:
            context, server_fused = await self._retrieve_hybrid(query, normalized)
        elif query.strategy == STRATEGY_LEXICAL:
            context = await self._retrieve_lexical(query, normalized)
        elif query.strategy == STRATEGY_VECTOR:
            context = await self._vector.retrieve(query)
        else:
            raise ValueError(f"Unknown retrieval strategy: {query.strategy}")

        chunks = dedupe_chunks(context.chunks)
        chunks = apply_doc_type_priority(chunks, query.doc_type_priority)
        if not server_fused:
            # La fusión client-side conserva los scores por pata (coseno /
            # dot-product), comparables con el umbral anti-alucinación. La
            # fusión server-side devuelve scores RRF (~1/(k+rank)); aplicarles
            # el umbral coseno descartaría hits válidos, así que se omiten
            # (las patas ya fueron filtradas por el store).
            chunks = filter_by_threshold(chunks, query.score_threshold)

        # Pin por entidad: lo que la pregunta nombra (byte 105, categoría 31,
        # record 4, tabla 961) tiene que estar. Va después del umbral para que
        # el umbral no lo descarte y antes del rerank para que el reranker lo vea.
        chunks = await self._pin_asked_entities(query, chunks)
        chunks = await self._expand_pinned_parents(query, chunks)

        if self._reranker is not None and chunks:
            try:
                chunks = await self._reranker.rerank(
                    query=query.query,
                    chunks=chunks,
                    top_n=query.rerank_top_k,
                    organization_id=str(query.organization_id),
                )
            except Exception as exc:
                logger.warning(
                    "Rerank failed, using retrieval order",
                    error=str(exc),
                    organization_id=str(query.organization_id),
                )

        chunks = self._builder.fit_budget(chunks)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "Hybrid retrieval completed",
            strategy=query.strategy,
            classification=classification.kind,
            results_count=len(chunks),
            retrieval_latency_ms=round(elapsed_ms, 2),
            organization_id=str(query.organization_id),
        )
        return RetrievalContext(
            chunks=chunks,
            query_embedding=query.query_embedding,
            retrieval_latency_ms=context.retrieval_latency_ms,
        )

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

        from src.intelligence.response.entities import (
            AskedEntity,
            asked_entities,
            normalize,
        )

        entidades = asked_entities(query.query)
        if not entidades:
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
                needles_titulo = [entidad.label]
                normalizado = normalize(entidad.label)
                if normalizado and normalizado != entidad.label:
                    needles_titulo.append(normalizado)
                etapas["heading"] += await _barrer(needles_titulo, heading_only=True)
                # Sólo se corta cuando TODAS las entidades nombradas aparecieron:
                # cortar con la primera dejaba sin buscar la segunda («categoría
                # 31» encontrada, «byte 105» nunca buscado).
                if all(_presente(e, _texto(pinned)) for e in entidades):
                    break

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
            etapas["lexical"] = len(pinned)

        # Etapa 2: barrido por frase cuando la entidad no aparece ni siquiera
        # mencionada (el título ya se intentó arriba).
        faltantes = [
            entidad
            for entidad in entidades
            if not _presente(entidad, _texto(chunks + pinned))
        ]
        escaneados = 0
        if faltantes and max_points > 0:
            needle_variants: list[str] = []
            for entidad in faltantes:
                needle_variants.append(entidad.label)
                normalizado = normalize(entidad.label)
                if normalizado and normalizado not in needle_variants:
                    needle_variants.append(normalizado)
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
    ) -> tuple[RetrievalContext, bool]:
        """Retorna (contexto, fusion_server_side).

        La fusión client-side tiene prioridad cuando hay LexicalStore: conserva
        los scores por pata para el umbral anti-alucinación. La fusión
        server-side (un solo round-trip) queda como fallback cuando no hay
        pata lexical local; sus scores son RRF y el umbral coseno se omite.
        """
        if self._lexical is not None:
            vector_task = asyncio.ensure_future(self._vector.retrieve(query))
            lexical_task = asyncio.ensure_future(self._lexical.retrieve(query))
            vector_ctx, lexical_ctx = await asyncio.gather(vector_task, lexical_task)

            if query.fusion == FUSION_RRF:
                fused = rrf_fusion([vector_ctx.chunks, lexical_ctx.chunks], k=query.rrf_k)
            else:
                fused = weighted_fusion(
                    [vector_ctx.chunks, lexical_ctx.chunks],
                    weights=[1.0 - query.lexical_weight, query.lexical_weight],
                )
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
            return ctx, True

        return await self._vector.retrieve(query), False
