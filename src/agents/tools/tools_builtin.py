# =============================================================================
# Tools Builtin — search_knowledge, query_database, call_api
# =============================================================================
from __future__ import annotations

import ipaddress
import socket
import time
from typing import ClassVar
from urllib.parse import urlparse
from uuid import UUID

import httpx

from src.agents.tools.base import Tool, ToolContext, ToolError, ToolResult
from src.core.config import get_settings
from src.core.domain.entities import RetrievalContext
from src.core.ports.sql_expert import SqlExpert
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

# Presupuestos de salida de search_knowledge: los chunks tabulares (row-groups
# compactos) traen el match en cualquier parte del chunk; truncarlos a 1200
# chars dejaba solo el header. Los primeros N tabulares van completos.
_TEXT_CHARS = 1_200
_TABULAR_FULL_CHARS = 6_000
_TABULAR_TAIL_CHARS = 1_500
_TABULAR_FULL_CHUNKS = 2
_MAX_OUTPUT_CHARS = 14_000


def _format_tabular_result(result) -> str:
    """Bloque EXACT legible para el LLM (valor + procedencia + total)."""
    metadata = result.metadata or {}
    strategy = str(metadata.get("strategy") or "")
    label_first = "value+label" in strategy
    column = result.columns[-1] if result.columns else "value"
    value = result.rows[0][-1] if result.rows else ""
    if label_first and result.rows and result.columns:
        column = result.columns[0]
        value = result.rows[0][0]
    lines = ["[EXACT structured lookup]", f"{column}: {value}"]
    total = metadata.get("total")
    if total and int(total) > 1:
        lines.append(f"matching rows: {int(total)} (showing {len(result.rows)})")
    elif len(result.rows) > 1:
        lines.append(f"rows: {len(result.rows)}")
    for row in result.rows[1:6]:
        lines.append(" | ".join(str(cell) for cell in row))
    matches = metadata.get("row_matches")
    if matches and int(matches) > 1:
        lines.append(f"rows with this label: {int(matches)}")
    provenance = metadata.get("provenance") or []
    if provenance:
        first = provenance[0]
        lines.append(
            "source: {workbook} | sheet: {sheet} | table: {table} | "
            "row: {row} | cell: {cell}".format(
                workbook=first.get("workbook"),
                sheet=first.get("sheet"),
                table=first.get("table"),
                row=first.get("row"),
                cell=first.get("cell"),
            )
        )
    if strategy:
        lines.append(f"strategy: {strategy}")
    return "\n".join(lines)

# Dominios/redes que jamás puede tocar call_api (SSRF).
_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
]


class SearchKnowledgeTool(Tool):
    """Busca en la base de conocimiento vectorial del tenant."""

    name: ClassVar[str] = "search_knowledge"
    description: ClassVar[str] = (
        "Busca documentos/chunks en la knowledge base del tenant. "
        "Input: query (pregunta), top_k (opcional, default 5)."
    )
    input_schema: ClassVar[dict] = {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string", "minLength": 1},
            "top_k": {"type": "integer", "minimum": 0, "maximum": 50},
        },
    }

    def __init__(self, retriever, embedder=None, tabular_query=None) -> None:
        self._retriever = retriever
        self._embedder = embedder
        self._tabular_query = tabular_query
        # Timeout configurable (antes heredaba 10s del contrato base). Se
        # instrumenta la latencia por etapa para calibrarlo con datos reales.
        try:
            self.timeout_seconds = float(
                get_settings().RAG_SEARCH_KNOWLEDGE_TIMEOUT_SECONDS
            )
        except Exception:  # pragma: no cover - settings siempre disponible
            self.timeout_seconds = 20.0

    async def _try_tabular_exact(
        self, ctx: ToolContext, query_text: str, source_ids, kb_ids
    ):
        """SQL-first determinista: valor exacto + provenance sobre Excel/CSV.

        Se intenta ANTES del retrieval vectorial. Si no hay señal o falla, se
        continúa con el flujo normal (nunca rompe la tool).
        """
        if not source_ids and not kb_ids:
            return None
        try:
            service = self._tabular_query
            if service is None:
                from src.api.deps import get_tabular_query_service

                service = get_tabular_query_service()
            return await service.try_answer(
                ctx.tenant_id,
                query_text,
                source_ids=list(source_ids) or None,
                knowledge_base_id=kb_ids[0] if kb_ids else None,
                role=ctx.role,
                user_id=ctx.user_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "search_knowledge tabular exact failed", error=str(exc)[:200]
            )
            return None

    @staticmethod
    def _format_tabular_result(result) -> str:
        """Bloque EXACT legible para el LLM (valor + procedencia)."""
        return _format_tabular_result(result)

    @staticmethod
    def _observe_stages(organization_id: UUID, stage_ms: dict[str, float]) -> None:
        try:
            from src.infrastructure.observability.metrics import (
                rag_retrieval_stage_latency,
            )

            for stage, elapsed_ms in stage_ms.items():
                rag_retrieval_stage_latency.labels(
                    organization_id=str(organization_id),
                    stage=stage.removesuffix("_ms"),
                ).observe(max(0.0, elapsed_ms) / 1000.0)
        except Exception:  # pragma: no cover - métricas nunca rompen la tool
            pass

    @staticmethod
    def _retrieval_overrides(ctx: ToolContext) -> dict:
        """Overrides de retrieval del agente (tab Retrieval del builder).

        `agents.config_json.retrieval` → {strategy, top_k, score_threshold,
        reranker}. Solo se aplican los valores definidos; el resto conserva
        el comportamiento por defecto de la tool.
        """
        raw = (ctx.agent_config or {}).get("retrieval")
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    async def _priority_sources(
        ctx: ToolContext, query_text: str, source_ids: list[UUID]
    ) -> list[UUID]:
        """Fuentes cuyo NOMBRE coincide con lo que la pregunta nombra, en orden.

        «categoría 31 byte 105» → `Cat31_dapp_C.pdf` primero: la sección que
        explica el campo vive ahí, aunque la búsqueda densa haya traído otro
        documento. Determinista y barato (una consulta por búsqueda).
        """
        try:
            from src.intelligence.response.entities import asked_entities

            entidades = asked_entities(query_text)
            if not entidades or not source_ids:
                return []
            agujas: list[str] = []
            for entidad in entidades:
                valor = entidad.value.strip().lower()
                if not valor:
                    continue
                agujas.append(valor)
                if entidad.kind == "categoría":
                    agujas.extend([f"cat{valor}", f"cat {valor}", f"cat_{valor}"])
            if not agujas:
                return []

            from sqlalchemy import bindparam
            from sqlalchemy import text as sql_text

            from src.infrastructure.postgres.session import get_async_session

            session = await get_async_session()
            try:
                stmt = sql_text(
                    "SELECT id::text, name FROM kb_sources "
                    "WHERE organization_id = :oid AND id::text IN :ids"
                ).bindparams(bindparam("ids", expanding=True))
                filas = (
                    await session.execute(
                        stmt,
                        {
                            "oid": str(ctx.tenant_id),
                            "ids": [str(sid) for sid in source_ids],
                        },
                    )
                ).fetchall()
            finally:
                await session.close()

            prioridad: list[UUID] = []
            for fila in filas:
                nombre = str(fila[1] or "").lower().replace("-", " ")
                if any(aguja in nombre for aguja in agujas):
                    try:
                        prioridad.append(UUID(str(fila[0])))
                    except ValueError:
                        continue
            return prioridad
        except Exception as exc:  # noqa: BLE001 — la prioridad es opcional
            logger.warning("Priority sources lookup failed", error=str(exc)[:150])
            return []

    @staticmethod
    def _default_strategy() -> str:
        """Cascada real: lo que diga el motor (RAG_RETRIEVAL_STRATEGY) y si no, vector.

        Antes la tool fijaba "vector" y el default del sistema quedaba ignorado:
        el agente nunca podía usar la pata léxica que sí existe en el motor.
        """
        try:
            from src.core.config import get_settings
            from src.rag.retrieval.models import RETRIEVAL_STRATEGIES, STRATEGY_VECTOR

            strategy = str(getattr(get_settings(), "RAG_RETRIEVAL_STRATEGY", "") or "")
            return strategy if strategy in RETRIEVAL_STRATEGIES else STRATEGY_VECTOR
        except Exception:  # noqa: BLE001 — nunca romper la tool por un flag
            return "vector"

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        start = time.perf_counter()
        stage_ms: dict[str, float] = {}
        try:
            from src.rag.retrieval.models import RetrievalQuery

            overrides = self._retrieval_overrides(ctx)
            try:
                top_k = int(arguments.get("top_k") or 5)
            except (TypeError, ValueError):
                top_k = 5
            # El modelo puede mandar 0 o negativos (el schema no lo garantiza):
            # `chunks[:top_k]` con negativo devuelve todo menos los últimos.
            top_k = max(1, min(top_k, 50))
            agent_top_k = overrides.get("top_k")
            if agent_top_k is not None:
                top_k = min(top_k, int(agent_top_k))
            strategy = str(overrides.get("strategy") or self._default_strategy())
            score_threshold = float(overrides.get("score_threshold") or 0.0)
            source_ids = self._uuids(ctx, "source_ids")
            kb_ids = self._uuids(ctx, "knowledge_base_ids")
            query_text = str(arguments["query"])
            exact_start = time.perf_counter()
            exact_result = await self._try_tabular_exact(
                ctx, query_text, source_ids, kb_ids
            )
            stage_ms["tabular_exact_ms"] = (
                time.perf_counter() - exact_start
            ) * 1000
            exact_block = (
                self._format_tabular_result(exact_result)
                if exact_result is not None
                else ""
            )
            embedding_start = time.perf_counter()
            query_embedding = (
                await self._embed_query(query_text, strategy)
                if source_ids or kb_ids
                else None
            )
            stage_ms["query_embedding_ms"] = (
                time.perf_counter() - embedding_start
            ) * 1000
            retrieval_start = time.perf_counter()
            chunks = []
            prioridad = await self._priority_sources(ctx, query_text, source_ids)
            if source_ids:
                rquery = RetrievalQuery(
                    query=query_text,
                    organization_id=ctx.tenant_id,
                    role=ctx.role,
                    source_ids=source_ids,
                    source_priority=prioridad,
                    top_k=top_k,
                    effective_top_k=top_k,
                    score_threshold=score_threshold,
                    strategy=strategy,
                    query_embedding=query_embedding,
                )
                part: RetrievalContext = await self._retriever.retrieve(rquery)
                chunks = list(part.chunks)
            elif kb_ids:
                for kb_id in kb_ids:
                    rquery = RetrievalQuery(
                        query=query_text,
                        organization_id=ctx.tenant_id,
                        role=ctx.role,
                        knowledge_base_id=kb_id,
                        top_k=top_k,
                        effective_top_k=top_k,
                        score_threshold=score_threshold,
                        strategy=strategy,
                        query_embedding=query_embedding,
                    )
                    part: RetrievalContext = await self._retriever.retrieve(rquery)
                    chunks.extend(part.chunks)
            stage_ms["retrieve_ms"] = (time.perf_counter() - retrieval_start) * 1000
            chunks = chunks[:top_k]
            stage_ms["total_ms"] = (time.perf_counter() - start) * 1000
            self._observe_stages(ctx.tenant_id, stage_ms)
            logger.info(
                "search_knowledge completed",
                organization_id=str(ctx.tenant_id),
                chunks=len(chunks),
                **{key: round(value, 2) for key, value in stage_ms.items()},
            )
            if not chunks:
                if exact_block:
                    return ToolResult(
                        output=exact_block,
                        latency_ms=(time.perf_counter() - start) * 1000,
                        meta={
                            "stage_ms": stage_ms,
                            "exact": True,
                            "strategy": (exact_result.metadata or {}).get("strategy"),
                        },
                    )
                return ToolResult(
                    output="(no results)",
                    latency_ms=(time.perf_counter() - start) * 1000,
                    meta={"stage_ms": stage_ms},
                )
            used: list[str] = []
            lines: list[str] = []
            evidence: list[dict] = []
            seen_refs: set[str] = set()
            pinned = sum(
                1
                for chunk in chunks
                if str((chunk.metadata or {}).get("retrieval") or "").startswith("entity")
            )
            if exact_block:
                lines.append(exact_block)
            full_tabular_left = _TABULAR_FULL_CHUNKS
            for i, chunk in enumerate(chunks):
                metadata = chunk.metadata or {}
                source_id = str(metadata.get("source_id") or "")
                if source_id and source_id not in used:
                    used.append(source_id)
                knowledge_type = str(metadata.get("knowledge_type") or "")
                is_tabular = knowledge_type.startswith("table_")
                # Evidencia estructurada para "Ver flujo": la UI no debe
                # reconstruir fuentes a partir del texto del output.
                document_id = str(getattr(chunk, "document_id", "") or "")
                ref = document_id or source_id or f"chunk-{i}"
                if ref not in seen_refs:
                    seen_refs.add(ref)
                    item: dict = {
                        "ref": ref,
                        "document_id": document_id or None,
                        "source_id": source_id or None,
                        "chunk_id": str(metadata.get("chunk_id") or document_id or "") or None,
                        "title": str(
                            metadata.get("filename")
                            or metadata.get("title")
                            or metadata.get("source")
                            or ""
                        )[:160]
                        or None,
                        "score": round(float(getattr(chunk, "score", 0.0) or 0.0), 4),
                        "status": "USED",
                        "knowledge_type": knowledge_type or None,
                    }
                    authority = str(metadata.get("authority") or "")
                    if authority:
                        item["authority"] = authority[:32]
                    if is_tabular and metadata.get("table_name"):
                        item["table"] = str(metadata["table_name"])[:120]
                    evidence.append(item)
                if is_tabular:
                    budget = (
                        _TABULAR_FULL_CHARS
                        if full_tabular_left > 0
                        else _TABULAR_TAIL_CHARS
                    )
                    full_tabular_left -= 1
                else:
                    budget = _TEXT_CHARS
                tag = f"[Doc {i + 1}"
                if source_id:
                    tag += f" | source:{source_id}"
                if is_tabular:
                    table_name = metadata.get("table_name")
                    row_start = metadata.get("row_start")
                    row_end = metadata.get("row_end")
                    if table_name:
                        tag += f" | table:{table_name}"
                    if row_start is not None:
                        tag += (
                            f" | rows:{row_start}-{row_end}"
                            if row_end is not None
                            else f" | row:{row_start}"
                        )
                tag += "]"
                lines.append(f"{tag} {chunk.content[:budget]}")
            snippet = "\n\n".join(lines)
            top_score = max(
                (float(getattr(chunk, "score", 0.0) or 0.0) for chunk in chunks),
                default=0.0,
            )
            return ToolResult(
                output=snippet[:_MAX_OUTPUT_CHARS],
                truncated=len(snippet) > _MAX_OUTPUT_CHARS,
                latency_ms=(time.perf_counter() - start) * 1000,
                meta={
                    "source_ids": used,
                    "evidence": evidence[:24],
                    "retrieval": {
                        "chunks": len(chunks),
                        "strategy": strategy,
                        "exact": bool(exact_block),
                        "top_score": round(top_score, 4),
                        "entity_pin": pinned,
                    },
                    "stage_ms": stage_ms,
                    "exact": bool(exact_block),
                    "strategy": (exact_result.metadata or {}).get("strategy")
                    if exact_result is not None
                    else None,
                },
            )
        except Exception as exc:
            stage_ms["total_ms"] = (time.perf_counter() - start) * 1000
            self._observe_stages(ctx.tenant_id, stage_ms)
            logger.warning("search_knowledge failed", error=str(exc)[:200])
            return ToolResult(
                error=str(exc),
                latency_ms=(time.perf_counter() - start) * 1000,
                meta={"stage_ms": stage_ms},
            )

    async def _embed_query(self, text: str, strategy: str) -> list[float] | None:
        if strategy == "lexical":
            return None
        embedder = self._embedder
        if embedder is None:
            from src.api.deps import get_embedding_provider

            embedder = get_embedding_provider()
        vector = await embedder.embed(text)
        if not vector:
            return None
        if isinstance(vector[0], list):
            vector = vector[0]
        return list(vector)

    @staticmethod
    def _uuids(ctx: ToolContext, key: str) -> list[UUID]:
        raw = (ctx.org_config or {}).get(key) or []
        ids: list[UUID] = []
        for item in raw:
            try:
                ids.append(UUID(str(item)))
            except ValueError:
                continue
        return ids


class QueryTabularDataTool(Tool):
    """Responde preguntas exactas sobre Excel/CSV vía la representación estructurada.

    Es el camino SQL-first para agentes: lookup de valor exacto (posición,
    longitud, código, fecha), agregaciones simples y filtros de rango con
    provenance a workbook/hoja/tabla/fila/celda. Si no hay coincidencia exacta,
    el agente debe usar `search_knowledge` para evidencia semántica.
    """

    name: ClassVar[str] = "query_tabular_data"
    description: ClassVar[str] = (
        "Consulta EXACTA sobre archivos Excel/CSV ingestados: devuelve el valor "
        "de una fila/columna (p. ej. 'posición de Carrier Code'), conteos con "
        "filtro o filas en un rango numérico, con cita a la fuente. Úsala antes "
        "de buscar por similitud cuando la pregunta pida un dato puntual."
    )
    input_schema: ClassVar[dict] = {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string", "minLength": 1},
        },
    }
    # Sin permiso RBAC: read-only sobre la representación estructurada del
    # propio tenant; el gate de agregaciones se aplica por rol en el servicio.
    timeout_seconds: ClassVar[float] = 15.0

    def __init__(self, service) -> None:
        self._service = service

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        start = time.perf_counter()
        query = str(arguments.get("query") or "").strip()
        if not query:
            return ToolResult(error="query is required", latency_ms=0.0)
        source_ids = self._uuids(ctx, "source_ids")
        kb_ids = self._uuids(ctx, "knowledge_base_ids")
        try:
            result = await self._service.try_answer(
                ctx.tenant_id,
                query,
                source_ids=source_ids or None,
                knowledge_base_id=kb_ids[0] if kb_ids else None,
                role=ctx.role,
                user_id=ctx.user_id,
            )
        except Exception as exc:  # noqa: BLE001 - nunca romper al agente
            logger.warning("query_tabular_data failed", error=str(exc)[:200])
            return ToolResult(
                error=str(exc), latency_ms=(time.perf_counter() - start) * 1000
            )
        latency_ms = (time.perf_counter() - start) * 1000
        if result is None:
            return ToolResult(
                output="(sin coincidencia exacta; usa search_knowledge)",
                latency_ms=latency_ms,
                meta={"matched": False},
            )
        metadata = result.metadata or {}
        return ToolResult(
            output=_format_tabular_result(result),
            latency_ms=latency_ms,
            meta={
                "matched": True,
                "strategy": metadata.get("strategy"),
                "confidence": metadata.get("confidence"),
                "total": metadata.get("total"),
                "columns": list(result.columns),
                "rows": [list(row) for row in result.rows[:5]],
                "tables": metadata.get("tables"),
            },
        )

    @staticmethod
    def _uuids(ctx: ToolContext, key: str) -> list[UUID]:
        raw = (ctx.org_config or {}).get(key) or []
        ids: list[UUID] = []
        for item in raw:
            try:
                ids.append(UUID(str(item)))
            except ValueError:
                continue
        return ids


class QueryDatabaseTool(Tool):
    """Consulta analítica SQL segura (SELECT-only) sobre las tablas del tenant."""

    name: ClassVar[str] = "query_database"
    description: ClassVar[str] = (
        "Haz preguntas analíticas sobre los datos de negocio del tenant "
        "(ventas, clientes, stock, etc) y sobre los Excel/CSV ingestados: "
        "las tablas materializadas viven con prefijo `zent_` "
        "(p. ej. zent_atpco_attributes). Devuelve filas de la BD. "
        "Input: question (pregunta en lenguaje natural)."
    )
    input_schema: ClassVar[dict] = {
        "type": "object",
        "required": ["question"],
        "properties": {
            "question": {"type": "string", "minLength": 1},
        },
    }
    permission: ClassVar[str] = "tool:query_database"
    timeout_seconds: ClassVar[float] = 30.0

    def __init__(self, sql_expert: SqlExpert) -> None:
        self._sql_expert = sql_expert

    async def _materialized_schema_hint(self, ctx: ToolContext) -> str:
        """Esquema compacto de las tablas materializadas (`zent_*`) de la org.

        Se agrega cuando la consulta falla o no devuelve filas: le da al LLM
        las tablas y columnas reales para auto-corregir el SQL.
        """
        try:
            from sqlalchemy import text as _text

            from src.platform.managed_db.service import open_managed_query_session

            session = await open_managed_query_session(
                ctx.tenant_id, (ctx.org_config or {}).get("workspace_id")
            )
            if session is None:
                return ""
            try:
                rows = (
                    await session.execute(
                        _text(
                            "SELECT table_name, "
                            "string_agg(column_name, ', ' ORDER BY ordinal_position) "
                            "FROM information_schema.columns "
                            "WHERE table_schema = 'public' AND table_name LIKE 'zent\\_%' "
                            "GROUP BY table_name ORDER BY table_name LIMIT 10"
                        )
                    )
                ).fetchall()
            finally:
                await session.close()
            if not rows:
                return ""
            lines = ["[materialized tables]"]
            lines.extend(f"{name}({columns})" for name, columns in rows)
            return "\n".join(lines)
        except Exception:  # noqa: BLE001 - el hint nunca rompe la tool
            return ""

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        start = time.perf_counter()
        question = str(arguments.get("question") or "")

        # Rechazo rápido (sin LLM): si la pregunta es de definición/identidad
        # ("quién es X") y no tiene ninguna señal analítica, el SQL Expert
        # solo puede fallar caro. Se guía al LLM a la vía documental.
        from src.agents.tools.sql_router import SqlIntentRouter

        profile = SqlIntentRouter.signal_profile(question)
        analytical = (
            profile["aggregation"]
            + profile["ranking"]
            + profile["date"]
            + profile["catalog"]
        )
        if analytical == 0 and (
            profile["entity"] == 0
            or profile["definitional"] > 0
            or profile["rag"] > 0
        ):
            return ToolResult(
                error=(
                    "Esta pregunta no parece ser sobre datos/tablas (SQL no "
                    "aplica). Usá search_knowledge para documentos o formulá "
                    "una pregunta de datos con tablas, columnas o métricas."
                ),
                latency_ms=(time.perf_counter() - start) * 1000,
            )

        try:
            result = await self._sql_expert.execute(
                organization_id=ctx.tenant_id,
                question=question,
                role=ctx.role,
                permissions=(ctx.org_config or {}).get("sql"),
                user_id=ctx.user_id,
                extra_schema=await self._materialized_schema_hint(ctx) or None,
            )
            if result.error:
                hint = await self._materialized_schema_hint(ctx)
                error = result.error if not hint else f"{result.error}\n{hint}"
                return ToolResult(
                    error=error,
                    latency_ms=(time.perf_counter() - start) * 1000,
                )
            if result.row_count == 0:
                hint = await self._materialized_schema_hint(ctx)
                output = "(no rows)" if not hint else f"(no rows)\n{hint}"
                return ToolResult(
                    output=output,
                    latency_ms=(time.perf_counter() - start) * 1000,
                )
            header = " | ".join(result.columns)
            rows = "\n".join(
                " | ".join(row) for row in result.rows[:25]
            )
            output = (
                f"Columns: {header}\n"
                f"Rows ({result.row_count} total"
                f"{'+, truncated' if result.truncated else ''}):\n{rows}"
            )
            return ToolResult(
                output=output[:6000],
                truncated=len(output) > 6000,
                latency_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return ToolResult(
                error=str(exc), latency_ms=(time.perf_counter() - start) * 1000
            )


class CallApiTool(Tool):
    """Llama APIs HTTP externas permitidas por el tenant (allowlist estricta).

    Por defecto TODO está bloqueado: el tenant debe listar dominios en
    config_json: {"agent": {"api_allowlist": ["api.example.com"]}}.
    """

    name: ClassVar[str] = "call_api"
    description: ClassVar[str] = (
        "Llama una API HTTP externa (GET/POST). Solo dominios en la "
        "allowlist del tenant. Input: url, method (opcional), "
        "json_body (opcional)."
    )
    input_schema: ClassVar[dict] = {
        "type": "object",
        "required": ["url"],
        "properties": {
            "url": {"type": "string", "minLength": 1},
            "method": {"type": "string", "enum": ["GET", "POST"]},
            "json_body": {"type": "object"},
        },
    }
    permission: ClassVar[str] = "tool:call_api"
    timeout_seconds: ClassVar[float] = 10.0

    @staticmethod
    def _host_allowed(host: str, allowlist: list[str]) -> bool:
        host_l = host.lower()
        for allowed in allowlist:
            allowed_l = allowed.lower().strip()
            if not allowed_l:
                continue
            if host_l == allowed_l or host_l.endswith(f".{allowed_l}"):
                return True
        return False

    @staticmethod
    def _resolve_ip(host: str) -> str | None:
        try:
            infos = socket.getaddrinfo(host, None)
            if not infos:
                return None
            return str(infos[0][4][0])
        except OSError:
            return None

    @classmethod
    def _ssrf_check(cls, host: str) -> None:
        if host.lower() in _BLOCKED_HOSTS:
            raise ToolError(f"Blocked host: {host}")
        ip = cls._resolve_ip(host)
        if ip is None:
            raise ToolError(f"Cannot resolve host: {host}")
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            raise ToolError(f"Invalid IP: {ip}") from None
        for network in _BLOCKED_NETWORKS:
            if addr in network:
                raise ToolError(f"Blocked private network IP: {ip}")

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        start = time.perf_counter()
        allowlist = ((ctx.org_config or {}).get("agent") or {}).get(
            "api_allowlist", []
        )
        if not allowlist:
            return ToolResult(error="call_api blocked: no api_allowlist configured for tenant")

        url = str(arguments["url"])
        try:
            parsed = urlparse(url)
        except ValueError as exc:
            return ToolResult(error=f"Invalid URL: {exc}")
        if parsed.scheme not in ("https", "http"):
            return ToolResult(error=f"Blocked URL scheme: {parsed.scheme}")
        if not parsed.hostname:
            return ToolResult(error="URL without host")
        if not self._host_allowed(parsed.hostname, allowlist):
            return ToolResult(
                error=f"Host '{parsed.hostname}' not in tenant api_allowlist"
            )
        try:
            self._ssrf_check(parsed.hostname)
        except ToolError as exc:
            return ToolResult(error=str(exc))

        method = (arguments.get("method") or "GET").upper()
        settings = get_settings()
        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=min(self.timeout_seconds, float(settings.RAG_AGENT_TOOL_TIMEOUT_SECONDS)),
            ) as client:
                if method == "POST":
                    resp = await client.post(url, json=arguments.get("json_body") or {})
                else:
                    resp = await client.get(url)
            body = resp.text[:4000]
            return ToolResult(
                output=f"HTTP {resp.status_code}\n{body}",
                truncated=len(resp.text) > 4000,
                latency_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return ToolResult(
                error=str(exc), latency_ms=(time.perf_counter() - start) * 1000
            )


def register_builtin_tools(
    retriever,
    sql_expert,
    embedder=None,
    tabular_query=None,
) -> None:
    """Registra las tools genéricas del core."""
    from src.agents.tools.registry import register_tool

    register_tool(SearchKnowledgeTool(retriever, embedder=embedder, tabular_query=tabular_query))
    register_tool(QueryDatabaseTool(sql_expert))
    register_tool(CallApiTool())
    if tabular_query is not None:
        register_tool(QueryTabularDataTool(tabular_query))
    try:
        from src.agents.tools.marketplace_tool import MarketplaceActionTool

        register_tool(MarketplaceActionTool())
        logger.info("Marketplace agent tool registered", count=4)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Marketplace tool registration failed", error=str(exc)[:150])
    logger.info("Builtin agent tools registered", count=4)
