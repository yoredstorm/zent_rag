# =============================================================================
# Public Query API — consumo desde ERP/CRM/WMS via deployment slug
# =============================================================================
# POST /api/v1/deployments/{slug}/query
#   Body:  {"input": "...", "user": {"id": "external"}, "context": {}}
#   Resp:  {"request_id", "answer", "data", "sources", "confidence", "latency_ms"}
# El deployment resuelve la version del agente (snapshot inmutable) y la
# respuesta se valida contra el output_schema configurado, si existe.
# =============================================================================
from __future__ import annotations

import time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from src.api.deps import (
    get_agent_repo,
    get_agent_runtime,
    get_agent_version_repo,
    get_deployment_repo,
)
from src.core.ports import (
    AgentRepository,
    AgentVersionRepository,
    DeploymentRepository,
)
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["Public API"])


class PublicQueryUser(BaseModel):
    id: str | None = Field(default=None, max_length=200)


class PublicQueryRequest(BaseModel):
    input: str = Field(..., min_length=1, max_length=32000)
    user: PublicQueryUser | None = None
    context: dict = Field(default_factory=dict)


class PublicQueryResponse(BaseModel):
    request_id: str
    answer: str
    data: dict | list | None = None
    sources: list = Field(default_factory=list)
    confidence: float | None = None
    latency_ms: float | None = None
    guardrails: dict | None = None


async def _write_api_log(
    organization_id,
    *,
    deployment_id,
    agent_id,
    request_id,
    endpoint,
    method,
    status,
    latency_ms,
    tokens=0,
    cost=None,
    api_key_id=None,
    error=None,
) -> None:
    """Registra la llamada pública (fail-silent) + evento en tiempo real."""
    from src.platform.realtime.stream import publish_api_query

    try:
        await publish_api_query(
            organization_id,
            deployment_id=deployment_id,
            status=status,
            latency_ms=latency_ms,
            tokens=tokens,
            cost=cost or 0.0,
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        from sqlalchemy import text

        from src.infrastructure.postgres.session import get_async_session

        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO api_logs (id, organization_id, deployment_id, agent_id, "
                    "request_id, endpoint, method, status, latency_ms, tokens, cost, "
                    "api_key_id, error) "
                    "VALUES (gen_random_uuid(), :oid, :did, :aid, :rid, :ep, :m, :st, "
                    ":lat, :tok, :cost, :kid, :err)"
                ),
                {
                    "oid": organization_id,
                    "did": deployment_id,
                    "aid": agent_id,
                    "rid": request_id,
                    "ep": endpoint,
                    "m": method,
                    "st": status,
                    "lat": latency_ms,
                    "tok": tokens,
                    "cost": cost,
                    "kid": api_key_id,
                    "err": (error or None)[:500] if error else None,
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
    except Exception as exc:
        logger.warning("Failed to write api log", error=str(exc))


@router.post(
    "/deployments/{deployment_slug}/query",
    response_model=PublicQueryResponse,
    summary="Query pública de un deployment (ERP/CRM)",
)
async def deployment_query(
    deployment_slug: str,
    body: PublicQueryRequest,
    request: Request,
    response: Response,
    deployment_repo: DeploymentRepository = Depends(get_deployment_repo),
    agent_repo: AgentRepository = Depends(get_agent_repo),
    version_repo: AgentVersionRepository = Depends(get_agent_version_repo),
    runtime: object = Depends(get_agent_runtime),
):
    from src.platform.deployments.versions import resolve_agent
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:execute")
    organization_id = ctx.organization_id
    start = time.perf_counter()
    request_id = uuid4()

    async def _respond(status: int, *, answer: str = "", data=None, sources=None,
                 confidence=None, error=None, tokens=0, cost=None,
                 deployment_id=None, agent_id=None) -> PublicQueryResponse:
        await _write_api_log(
            organization_id,
            deployment_id=deployment_id,
            agent_id=agent_id,
            request_id=request_id,
            endpoint=f"/api/v1/deployments/{deployment_slug}/query",
            method="POST",
            status=status,
            latency_ms=(time.perf_counter() - start) * 1000,
            tokens=tokens,
            cost=cost,
            api_key_id=ctx.token_id,
            error=error,
        )
        if status >= 400:
            raise HTTPException(status_code=status, detail=error or "Query failed")
        return PublicQueryResponse(
            request_id=str(request_id),
            answer=answer,
            data=data,
            sources=sources or [],
            confidence=confidence,
            latency_ms=(time.perf_counter() - start) * 1000,
        )

    deployment = await deployment_repo.get_deployment_by_slug(
        organization_id, deployment_slug
    )
    if deployment is None:
        return await _respond(404, error="Deployment not found")
    if deployment.status.value != "healthy":
        return await _respond(
            409,
            error=f"Deployment no está healthy (estado: {deployment.status.value})",
            deployment_id=deployment.id,
        )

    agent = await agent_repo.get_agent(organization_id, deployment.agent_id)
    version = await version_repo.get_version(
        organization_id, deployment.agent_id, deployment.agent_version_id
    )
    if agent is None or version is None:
        return await _respond(404, error="Agent/version not found", deployment_id=deployment.id)

    resolved = resolve_agent(agent, version.config_snapshot)

    # Trust & Safety: moderación del INPUT (block → 422).
    mod = None
    try:
        from src.platform.trustsafety.trust_safety import moderate_text

        mod = await moderate_text(organization_id, body.input, direction="input")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Input moderation failed", error=str(exc)[:150])
    if mod is not None and mod["blocked"]:
        return await _respond(
            422,
            answer="",
            error="Entrada bloqueada por la política de contenido",
            deployment_id=deployment.id,
        )

    # Edge Cache: lookup antes de ejecutar (bypass con ?cache=false o no-cache).
    from src.platform.edge.multiregion import (
        bump_stats,
        bypass_requested,
        cache_key,
        get_cached,
        org_cache_generation,
        set_cached,
        ttl_for_org,
    )

    edge_key: str | None = None
    if not bypass_requested(request):
        generation = await org_cache_generation(organization_id)
        edge_key = cache_key(
            organization_id,
            deployment.id,
            deployment.agent_version_id,
            body.input,
            generation=generation,
        )
        cached = await get_cached(edge_key)
        if cached is not None:
            await bump_stats(True)
            response.headers["X-Zent-Cache"] = "HIT"
            response.headers["Age"] = str(int(cached.get("ttl", 0)))
            response.headers["Cache-Control"] = "public, max-age=0"
            return PublicQueryResponse(
                request_id=str(request_id),
                answer=cached["answer"],
                data=cached.get("data"),
                sources=cached.get("sources", []),
                confidence=cached.get("confidence"),
                latency_ms=(time.perf_counter() - start) * 1000,
                guardrails=cached.get("guardrails"),
            )
        await bump_stats(False)
    else:
        response.headers["X-Zent-Cache"] = "BYPASS"

    from src.agents.runtime.agent_runtime import AgentRunRequest

    run_request = AgentRunRequest(
        agent=resolved,
        message=body.input,
        user_id=ctx.user_id,
        deployment_id=deployment.id,
        role="admin",
        conversation_id=uuid4(),
        permissions=ctx.permissions,
        org_config={},
        trace_id=request.headers.get("X-Trace-Id") or str(request_id),
    )
    try:
        result = await runtime.run(run_request)
    except Exception as exc:
        logger.error("Public query agent run failed", error=str(exc), exc_info=True)
        return await _respond(
            500, error=f"Agent run failed: {exc}", deployment_id=deployment.id
        )

    latency_ms = (time.perf_counter() - start) * 1000
    tokens = getattr(result, "total_tokens", 0) or 0
    cost = getattr(result, "cost", None)

    output_schema = (resolved.config_json or {}).get("output_schema")
    data: dict | list | None = None
    confidence: float | None = None
    if isinstance(output_schema, dict) and output_schema:
        from src.platform.deployments.output_schema import validate_json_answer

        parsed, errors = validate_json_answer(result.answer, output_schema)
        if errors:
            return await _respond(
                422,
                answer=result.answer,
                error="Respuesta no cumple el output_schema: " + "; ".join(errors[:5]),
                tokens=tokens,
                cost=cost,
                deployment_id=deployment.id,
                agent_id=agent.id,
            )
        data = parsed
        confidence = 1.0

    await _write_api_log(
        organization_id,
        deployment_id=deployment.id,
        agent_id=agent.id,
        request_id=request_id,
        endpoint=f"/api/v1/deployments/{deployment_slug}/query",
        method="POST",
        status=200,
        latency_ms=latency_ms,
        tokens=tokens,
        cost=cost,
        api_key_id=ctx.token_id,
    )
    # Guardrails AI: PII masking según política de la org.
    from src.platform.ai_governance.ai_governance import apply_guardrails

    final_answer, masked = await apply_guardrails(organization_id, result.answer)
    # Guardrails de salida (Model Health v2): toxicity/pii/temas/regex.
    try:
        from src.platform.modelhealth.guardrails import protect_answer

        final_answer, violations, blocked = await protect_answer(
            organization_id, final_answer
        )
        if blocked:
            return await _respond(
                422,
                answer="",
                error="Respuesta bloqueada por guardrail de salida",
                tokens=tokens,
                cost=cost,
                deployment_id=deployment.id,
                agent_id=agent.id,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Output guardrails failed", error=str(exc)[:150])
    # Trust & Safety: moderación del OUTPUT (block → 422).
    mod_out = None
    try:
        from src.platform.trustsafety.trust_safety import moderate_text

        mod_out = await moderate_text(organization_id, final_answer, direction="output")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Output moderation failed", error=str(exc)[:150])
    if mod_out is not None and mod_out["blocked"]:
        return await _respond(
            422,
            answer="",
            error="Respuesta bloqueada por la política de contenido",
            tokens=tokens,
            cost=cost,
            deployment_id=deployment.id,
            agent_id=agent.id,
        )
    # Partner ecosystem: metering por consumo si la key es de un partner.
    if getattr(ctx, "partner_id", None):
        from src.platform.partners.partners import record_partner_usage

        await record_partner_usage(
            ctx.partner_id, organization_id, tokens=tokens, cost=cost or 0.0
        )
    payload = PublicQueryResponse(
        request_id=str(request_id),
        answer=final_answer,
        data=data,
        sources=[],
        confidence=confidence,
        latency_ms=latency_ms,
        guardrails={"pii_masked": masked} if masked else None,
    )
    if edge_key is not None:
        ttl = await ttl_for_org(organization_id)
        await set_cached(
            edge_key,
            {
                "answer": final_answer,
                "data": data,
                "sources": [],
                "confidence": confidence,
                "guardrails": {"pii_masked": masked} if masked else None,
                "ttl": ttl,
            },
            ttl,
        )
        response.headers["X-Zent-Cache"] = "MISS"
        response.headers["Cache-Control"] = f"public, max-age={ttl}"
    return payload


@router.get("/deployments/logs", summary="Logs de la API pública (org)")
async def list_public_logs(
    request: Request,
    limit: int = 100,
    deployment_id: str | None = None,
):
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "deployments:read")
    session = await get_async_session()
    try:
        query = (
            "SELECT id, deployment_id, agent_id, request_id, endpoint, method, "
            "status, latency_ms, tokens, cost, api_key_id, error, created_at "
            "FROM api_logs WHERE organization_id = :oid"
        )
        params: dict = {"oid": ctx.organization_id, "limit": min(limit, 500)}
        if deployment_id:
            query += " AND deployment_id = CAST(:did AS uuid)"
            params["did"] = deployment_id
        query += " ORDER BY created_at DESC LIMIT :limit"
        rows = (await session.execute(text(query), params)).fetchall()
    finally:
        await session.close()
    return {
        "logs": [
            {
                "id": str(r.id),
                "deployment_id": str(r.deployment_id) if r.deployment_id else None,
                "agent_id": str(r.agent_id) if r.agent_id else None,
                "request_id": str(r.request_id),
                "endpoint": r.endpoint,
                "method": r.method,
                "status": r.status,
                "latency_ms": r.latency_ms,
                "tokens": int(r.tokens or 0),
                "cost": r.cost,
                "api_key_id": str(r.api_key_id) if r.api_key_id else None,
                "error": r.error,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "count": len(rows),
    }
