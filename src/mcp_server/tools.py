# =============================================================================
# MCP Server — Tools (search_knowledge, query_database, get_document,
#                      execute_agent, get_usage)
# =============================================================================
# Cada tool pasa por el MISMO pipeline de seguridad que el resto de la
# plataforma: identidad del TenantContext (puesto por TenantMiddleware),
# política MCP (RBAC + config_json['mcp'] + rate limit por tool) y auditoría
# + usage engine al final. Nada de esto se puede saltar desde el protocolo.
# =============================================================================
from __future__ import annotations

import time
from uuid import UUID

from mcp.server.mcpserver.context import Context as McpSdkContext

from src.agents.runtime.agent_runtime import AgentRunRequest
from src.agents.runtime.trace_store import ensure_agent_runs_table, save_run
from src.infrastructure.observability.logging_config import get_logger
from src.mcp_server.audit import McpAudit
from src.mcp_server.backends import McpDeps
from src.mcp_server.context import (
    McpCallIdentity,
    client_identity_from_headers,
    new_call_id,
    resolve_effective_role,
    resolve_tenant_context,
)
from src.mcp_server.errors import McpAuthError, McpPolicyError, McpToolError
from src.mcp_server.policy import McpPolicy
from src.rag.retrieval.models import RetrievalQuery

logger = get_logger(__name__)

_MAX_CHUNK_CHARS = 2000
_MAX_ROWS = 100
_MAX_TOP_K = 50


async def _execute_tool(
    deps: McpDeps,
    policy: McpPolicy,
    audit: McpAudit,
    *,
    tool: str,
    sdk_ctx: McpSdkContext,
    client_role: str | None,
    run,
) -> dict:
    """Wrapper común: identidad -> policy -> ejecución -> auditoría/usage."""
    start = time.perf_counter()
    tenant = resolve_tenant_context()  # McpAuthError si no autenticado
    role = resolve_effective_role(tenant, client_role)
    identity = McpCallIdentity(
        tenant=tenant,
        tool=tool,
        role=role,
        call_id=new_call_id(),
        mcp_client=client_identity_from_headers(dict(sdk_ctx.headers) if sdk_ctx.headers else None),
    )

    try:
        org_config = await deps.organization_config(tenant.tenant_id)
        await policy.authorize(tenant, tool, role, org_config)
    except McpPolicyError as exc:
        await audit.record(
            identity,
            status="denied",
            latency_ms=(time.perf_counter() - start) * 1000,
            error_code=exc.error_code,
        )
        raise
    except McpAuthError:
        raise

    try:
        result = await run(tenant=tenant, role=role, org_config=org_config)
    except McpToolError as exc:
        await audit.record(
            identity,
            status="error",
            latency_ms=(time.perf_counter() - start) * 1000,
            error_code=exc.error_code,
        )
        raise
    except Exception as exc:
        logger.error("MCP tool failed", tool=tool, error=str(exc), exc_info=True)
        await audit.record(
            identity,
            status="error",
            latency_ms=(time.perf_counter() - start) * 1000,
            error_code="tool_error",
        )
        raise McpToolError(f"Tool '{tool}' failed: {exc}") from exc

    metrics = result.pop("_metrics", {})
    await audit.record(
        identity,
        status="ok",
        latency_ms=(time.perf_counter() - start) * 1000,
        cost=float(metrics.get("cost") or 0.0),
        tokens=int(metrics.get("tokens") or 0),
        retrieval_count=int(metrics.get("retrieval_count") or 0),
        model=metrics.get("model"),
    )
    return result


def register_tools(server, deps: McpDeps | None = None) -> None:
    """Registra las tools MCP en el server (FastMCP/MCPServer v2)."""
    from src.mcp_server.policy import McpPolicy, McpRateLimiter

    deps = deps or McpDeps()
    policy = McpPolicy(McpRateLimiter(deps.cache()))
    audit = McpAudit()

    # ---------------------------------------------------------------------
    # search_knowledge
    # ---------------------------------------------------------------------
    @server.tool(
        description=(
            "Semantic search over the organization's knowledge base. "
            "Returns relevant document chunks with scores and metadata. "
            "Use to find facts, policies or content stored in Zent."
        ),
    )
    async def search_knowledge(
        query: str,
        top_k: int = 5,
        role: str | None = None,
        filters: dict[str, str] | None = None,
        knowledge_base_id: str | None = None,
        ctx: McpSdkContext = None,  # type: ignore[assignment]
    ) -> dict:
        async def _run(*, tenant, role, org_config):
            top_k_eff = max(1, min(int(top_k or 5), _MAX_TOP_K))
            embedding = await deps.embedding().embed(query)
            kb_id = None
            if knowledge_base_id:
                kb_id = UUID(knowledge_base_id)
            rquery = RetrievalQuery(
                query=query,
                organization_id=tenant.tenant_id,
                role=role,
                knowledge_base_id=kb_id,
                top_k=top_k_eff,
                effective_top_k=top_k_eff,
                score_threshold=0.0,
                strategy="vector",
                filters=filters or {},
                query_embedding=embedding if isinstance(embedding, list) else None,
            )
            result = await deps.retriever().retrieve(rquery)
            chunks = [
                {
                    "document_id": str(c.document_id),
                    "content": c.content[:_MAX_CHUNK_CHARS],
                    "score": round(c.score, 4),
                    "metadata": c.metadata,
                }
                for c in result.chunks
            ]
            return {
                "query": query,
                "count": len(chunks),
                "chunks": chunks,
                "retrieval_latency_ms": round(result.retrieval_latency_ms, 2),
                "_metrics": {"retrieval_count": len(chunks)},
            }

        return await _execute_tool(
            deps, policy, audit, tool="search_knowledge", sdk_ctx=ctx,
            client_role=role, run=_run,
        )

    # ---------------------------------------------------------------------
    # query_database
    # ---------------------------------------------------------------------
    @server.tool(
        description=(
            "Ask a natural-language question over the organization's business "
            "data (sales, customers, stock...). Zent translates it to safe, "
            "read-only SQL (SELECT) and returns rows. Admin role only for "
            "aggregations."
        ),
    )
    async def query_database(
        question: str,
        role: str | None = None,
        ctx: McpSdkContext = None,  # type: ignore[assignment]
    ) -> dict:
        async def _run(*, tenant, role, org_config):
            result = await deps.sql_expert().execute(
                organization_id=tenant.tenant_id,
                question=question,
                role=role,
                permissions=(org_config or {}).get("sql"),
                user_id=tenant.user_id,
            )
            if result.error:
                raise McpToolError(result.error, "sql_error")
            payload: dict = {
                "columns": list(result.columns),
                "rows": [list(row) for row in result.rows[:_MAX_ROWS]],
                "row_count": int(result.row_count),
                "truncated": bool(result.truncated) or result.row_count > _MAX_ROWS,
                "cost": round(float(result.cost or 0.0), 8),
                "_metrics": {
                    "cost": float(result.cost or 0.0),
                },
            }
            # El SQL solo se expone a admin (mismo criterio que REST).
            if role == "admin":
                payload["sql"] = result.sql
            return payload

        return await _execute_tool(
            deps, policy, audit, tool="query_database", sdk_ctx=ctx,
            client_role=role, run=_run,
        )

    # ---------------------------------------------------------------------
    # get_document
    # ---------------------------------------------------------------------
    @server.tool(
        description=(
            "Fetch stored document chunks by their document_id (Qdrant point "
            "IDs). Always scoped to the authenticated organization; IDs from "
            "other tenants are never returned."
        ),
    )
    async def get_document(
        document_ids: list[str],
        role: str | None = None,
        ctx: McpSdkContext = None,  # type: ignore[assignment]
    ) -> dict:
        async def _run(*, tenant, role, org_config):
            parsed: list[UUID] = []
            for raw in document_ids:
                try:
                    parsed.append(UUID(raw))
                except ValueError as exc:
                    raise McpToolError(
                        f"Invalid document_id: {raw}", "invalid_document_id"
                    ) from exc
            result = await deps.vector_store().get_documents(
                tenant.tenant_id, parsed, role=role
            )
            documents = [
                {
                    "document_id": str(c.document_id),
                    "content": c.content,
                    "metadata": c.metadata,
                }
                for c in result.chunks
            ]
            return {
                "count": len(documents),
                "documents": documents,
                "latency_ms": round(result.retrieval_latency_ms, 2),
                "_metrics": {"retrieval_count": len(documents)},
            }

        return await _execute_tool(
            deps, policy, audit, tool="get_document", sdk_ctx=ctx,
            client_role=role, run=_run,
        )

    # ---------------------------------------------------------------------
    # execute_agent
    # ---------------------------------------------------------------------
    @server.tool(
        description=(
            "Run a configured Zent agent (ReAct loop with tool access). The "
            "agent's tool allowlist, guardrails, quotas and cost limits are "
            "enforced exactly as in the REST API."
        ),
    )
    async def execute_agent(
        agent_id: str,
        message: str,
        role: str | None = None,
        conversation_id: str | None = None,
        ctx: McpSdkContext = None,  # type: ignore[assignment]
    ) -> dict:
        async def _run(*, tenant, role, org_config):
            try:
                agent_uuid = UUID(agent_id)
            except ValueError as exc:
                raise McpToolError(f"Invalid agent_id: {agent_id}", "invalid_agent_id") from exc
            agent = await deps.agent_repo().get_agent(tenant.tenant_id, agent_uuid)
            if agent is None:
                raise McpToolError("Agent not found", "agent_not_found")
            if not agent.is_active:
                raise McpToolError("Agent is not active", "agent_inactive")

            conv_id = None
            if conversation_id:
                try:
                    conv_id = UUID(conversation_id)
                except ValueError:
                    conv_id = None

            result = await deps.agent_runtime().run(
                AgentRunRequest(
                    agent=agent,
                    message=message,
                    user_id=tenant.user_id,
                    role=role,
                    conversation_id=conv_id,
                    permissions=tenant.permissions,
                    org_config=org_config or {},
                )
            )
            # Persistencia durable del run (misma tabla que REST).
            await ensure_agent_runs_table()
            await save_run(result)

            quota_hit = any(
                s.get("type") == "guardrail" and "quota_exceeded" in str(s.get("detail", ""))
                for s in result.steps
            )
            return {
                "run_id": str(result.run_id),
                "agent_id": str(result.agent_id),
                "status": "quota" if quota_hit else result.status,
                "answer": result.answer,
                "steps": result.steps,
                "total_latency_ms": round(result.total_latency_ms, 2),
                "total_tokens": result.total_tokens,
                "cost": round(result.cost, 8),
                "injection_detected": result.injection_detected,
                "_metrics": {
                    # El AgentRuntime ya registra su propio usage event
                    # (idempotente por run_id): aquí solo auditoría.
                },
            }

        return await _execute_tool(
            deps, policy, audit, tool="execute_agent", sdk_ctx=ctx,
            client_role=role, run=_run,
        )

    # ---------------------------------------------------------------------
    # get_usage
    # ---------------------------------------------------------------------
    @server.tool(
        description=(
            "Organization usage summary: requests, tokens, latency and "
            "estimated cost for the last N days (usage:read permission)."
        ),
    )
    async def get_usage(
        days: int = 30,
        limit: int = 50,
        ctx: McpSdkContext = None,  # type: ignore[assignment]
    ) -> dict:
        async def _run(*, tenant, role, org_config):
            from src.platform.usage.aggregation import get_organization_usage

            return await get_organization_usage(
                tenant.tenant_id, days=days, limit=limit
            )

        return await _execute_tool(
            deps, policy, audit, tool="get_usage", sdk_ctx=ctx,
            client_role=None, run=_run,
        )
