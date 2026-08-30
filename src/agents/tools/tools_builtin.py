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
            "top_k": {"type": "integer", "minimum": 1, "maximum": 50},
        },
    }

    def __init__(self, retriever) -> None:
        self._retriever = retriever

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        start = time.perf_counter()
        try:
            from src.rag.retrieval.models import RetrievalQuery

            top_k = int(arguments.get("top_k") or 5)
            kb_ids = self._knowledge_base_ids(ctx)
            chunks = []
            if kb_ids:
                for kb_id in kb_ids:
                    rquery = RetrievalQuery(
                        query=str(arguments["query"]),
                        organization_id=ctx.tenant_id,
                        role=ctx.role,
                        knowledge_base_id=kb_id,
                        top_k=top_k,
                        effective_top_k=top_k,
                        score_threshold=0.0,
                        strategy="vector",
                    )
                    part: RetrievalContext = await self._retriever.retrieve(rquery)
                    chunks.extend(part.chunks)
            else:
                rquery = RetrievalQuery(
                    query=str(arguments["query"]),
                    organization_id=ctx.tenant_id,
                    role=ctx.role,
                    top_k=top_k,
                    effective_top_k=top_k,
                    score_threshold=0.0,
                    strategy="vector",
                )
                context: RetrievalContext = await self._retriever.retrieve(rquery)
                chunks = list(context.chunks)
            chunks = chunks[:top_k]
            if not chunks:
                return ToolResult(
                    output="(no results)",
                    latency_ms=(time.perf_counter() - start) * 1000,
                )
            snippet = "\n\n".join(
                f"[Doc {i + 1}] {c.content[:1200]}"
                for i, c in enumerate(chunks)
            )
            return ToolResult(
                output=snippet[:6000],
                truncated=len(snippet) > 6000,
                latency_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return ToolResult(
                error=str(exc), latency_ms=(time.perf_counter() - start) * 1000
            )

    @staticmethod
    def _knowledge_base_ids(ctx: ToolContext) -> list[UUID]:
        raw = (ctx.org_config or {}).get("knowledge_base_ids") or []
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
        "(ventas, clientes, stock, etc). Devuelve filas de la BD. "
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

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        start = time.perf_counter()
        try:
            result = await self._sql_expert.execute(
                organization_id=ctx.tenant_id,
                question=str(arguments["question"]),
                role=ctx.role,
                permissions=(ctx.org_config or {}).get("sql"),
                user_id=ctx.user_id,
            )
            if result.error:
                return ToolResult(
                    error=result.error,
                    latency_ms=(time.perf_counter() - start) * 1000,
                )
            if result.row_count == 0:
                return ToolResult(
                    output="(no rows)",
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


def register_builtin_tools(retriever, sql_expert) -> None:
    """Registra las tools genéricas del core."""
    from src.agents.tools.registry import register_tool

    register_tool(SearchKnowledgeTool(retriever))
    register_tool(QueryDatabaseTool(sql_expert))
    register_tool(CallApiTool())
    logger.info("Builtin agent tools registered", count=3)
