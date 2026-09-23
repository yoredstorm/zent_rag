# =============================================================================
# RAG Query Route — Endpoint principal de consulta RAG
# =============================================================================
# POST /api/v1/rag/query
# Recibe una pregunta del usuario, ejecuta el flujo RAG completo y
# devuelve la respuesta generada por el LLM con fuentes y métricas.
# =============================================================================
from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from src.agents.runtime.orchestrator import RAGOrchestrator
from src.api.deps import get_rag_orchestrator
from src.api.schemas import RAGQueryRequest, RAGQueryResponse, sources_for_client
from src.api.security import (
    ORG_HEADER_DESCRIPTION,
    USER_HEADER_DESCRIPTION,
    decision_permissions,
)
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.observability.metrics import (
    rag_active_requests,
    rag_queries_total,
    rag_tokens_consumed,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["RAG"])


async def _resolve_organization_user(
    request: Request, x_organization_id: str, x_user_id: str
) -> tuple[UUID, UUID]:
    """Resuelve organization_id y user_id desde la identidad autenticada.

    El Bearer autenticado SIEMPRE gana: X-Organization-Id / X-User-Id que no
    coincidan con la sesión reciben 403 (anti cross-organization / impersonación).
    """
    from src.api.security import resolve_organization, resolve_user_id

    organization_id = resolve_organization(request, x_organization_id)
    user_id = await resolve_user_id(request, x_user_id)
    return organization_id, user_id


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _token_id(request: Request) -> UUID | None:
    """api_key_id del contexto autenticado (para atribución de uso)."""
    ctx = getattr(request.state, "tenant_context", None)
    return getattr(ctx, "token_id", None)


async def _resolve_workspace_filter(request: Request) -> UUID | None:
    """Workspace opcional para retrieval: solo filtra si X-Workspace-Id vino.

    Sin header se preserva el comportamiento org-wide legacy (los chunks V1
    pueden no llevar workspace_id en el payload)."""
    from src.platform.workspaces.context import (
        resolve_workspace,
        workspace_header_or_none,
    )

    if workspace_header_or_none(request) is None:
        return None
    workspace = await resolve_workspace(request)
    return workspace.id


def _record_metrics(result, organization_id: UUID) -> None:
    """Registra métricas Prometheus para una consulta finalizada."""
    rag_queries_total.labels(
        organization_id=str(organization_id),
        status=result.status.value,
        method=getattr(result, "method", "rag") or "rag",
    ).inc()

    if result.llm_response:
        rag_tokens_consumed.labels(
            organization_id=str(organization_id),
            model=result.llm_response.model,
            token_type="prompt",
        ).inc(result.llm_response.prompt_tokens)
        rag_tokens_consumed.labels(
            organization_id=str(organization_id),
            model=result.llm_response.model,
            token_type="completion",
        ).inc(result.llm_response.completion_tokens)
        rag_tokens_consumed.labels(
            organization_id=str(organization_id),
            model=result.llm_response.model,
            token_type="total",
        ).inc(result.llm_response.total_tokens)


def _has_dispatch_target(body: RAGQueryRequest) -> bool:
    """Explicit agent/workflow/tool target present in the request."""
    return bool(body.agent_id or body.workflow_id or body.tool)


async def _organization_config(organization_id: UUID) -> dict:
    try:
        from src.api.deps import get_organization_repo

        org = await get_organization_repo().get_by_id(organization_id)
        return dict(getattr(org, "config_json", None) or {})
    except Exception:  # noqa: BLE001
        return {}


async def _maybe_dispatch(
    request: Request,
    body: RAGQueryRequest,
    *,
    organization_id: UUID,
    user_id: UUID,
    role: str,
    workspace_id: UUID | None,
):
    """Run an explicit capability target through the Decision Engine dispatcher.

    Returns a RAGQueryResult when the target was executed, or None to fall
    back to the RAG flow. Raises HTTPException for denied/needs-target.

    Judgment Fabric: sin target explícito, si `RAG_DECISION_TARGET_SELECTION`
    está en shadow/on, se resuelve el CandidateSet autorizado y JEV elige; la
    política re-autoriza. En shadow se observa y se sigue con RAG.
    """
    explicit = _has_dispatch_target(body)
    from src.api.deps import get_capability_dispatcher, get_decision_hook
    from src.core.domain.entities import LLMResponse, QueryStatus, RAGQueryResult
    from src.runtime.dispatcher import DispatchRequest, with_target

    dispatcher = get_capability_dispatcher()
    if not explicit and not dispatcher.selection_enabled():
        return None

    permissions = decision_permissions(request)
    decision_request_id = uuid4()
    org_config = await _organization_config(organization_id)
    hook = get_decision_hook()
    decision = await hook.evaluate(
        organization_id=organization_id,
        request_id=decision_request_id,
        user_id=user_id,
        query=body.query,
        role=role,
        sql_enabled=True,
        permissions=permissions,
        include_advisory=True,
        conversation_state={"turn_count": 0, "is_followup": False},
        tenant_policy=dict(org_config.get("decision") or {}),
        explicit_agent_id=str(body.agent_id) if body.agent_id else None,
        explicit_workflow_id=str(body.workflow_id) if body.workflow_id else None,
        explicit_tool=body.tool,
    )
    if explicit and decision.metadata.get("authorization_denied"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Capability not permitted: {decision.metadata.get('denied_capability')}",
        )
    if not decision.resolved or not dispatcher.can_dispatch(decision.capability):
        return None
    dispatch_request = DispatchRequest(
        organization_id=organization_id,
        user_id=user_id,
        role=role,
        permissions=permissions,
        query=body.query,
        conversation_id=body.conversation_id,
        workspace_id=workspace_id,
        agent_id=body.agent_id,
        workflow_id=body.workflow_id,
        run_id=body.run_id,
        tool=body.tool,
        tool_arguments=dict(body.tool_arguments or {}),
        org_config=org_config,
        api_key_id=_token_id(request),
        trace_id=request.headers.get("X-Trace-Id"),
        request_id=decision_request_id,
        tenant_policy=dict(org_config.get("decision") or {}),
    )
    authorized = None
    if not explicit:
        resolution = await dispatcher.resolve_target(decision, dispatch_request)
        if resolution is None or not resolution.executable:
            # La selección nunca ejecuta por sí sola: se sigue con RAG.
            return None
        dispatch_request = with_target(
            dispatch_request, resolution.selection.kind, str(resolution.selection.target_id)
        )
        authorized = resolution.policy
    dispatched = await dispatcher.dispatch(decision, dispatch_request, authorized=authorized)
    if dispatched.status == "needs_target":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=dispatched.error or "missing target",
        )
    if dispatched.status == "denied":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=dispatched.error or "permission denied",
        )
    if dispatched.status == "unavailable":
        return None

    method = str(dispatched.data.get("method") or dispatched.handler or "runtime")
    try:
        await hook.after_actual(
            organization_id=organization_id,
            request_id=decision_request_id,
            user_id=user_id,
            query=body.query,
            actual_method=method,
            actual_capability=dispatched.capability,
            engine_decision=decision,
            sql_enabled=True,
            role=role,
        )
    except Exception:  # noqa: BLE001 — trace ground truth is best-effort
        pass
    result = RAGQueryResult(
        query_id=uuid4(),
        organization_id=organization_id,
        user_id=user_id,
        query=body.query,
        conversation_id=body.conversation_id or uuid4(),
        role=role,
        status=QueryStatus.COMPLETED if dispatched.completed else QueryStatus.FAILED,
        llm_response=LLMResponse(
            content=dispatched.answer or "",
            model=str(dispatched.data.get("model") or dispatched.handler or method),
            prompt_tokens=int(dispatched.prompt_tokens or 0),
            completion_tokens=int(dispatched.completion_tokens or 0),
            total_tokens=int(dispatched.tokens or 0),
            latency_ms=dispatched.latency_ms,
        ),
        total_latency_ms=dispatched.latency_ms,
        method=method,
        error_message=dispatched.error,
        trace_id=request.headers.get("X-Trace-Id"),
        rag_trace={
            "dispatch": {
                "capability": dispatched.capability,
                "handler": dispatched.handler,
                "status": dispatched.status,
                "run_id": dispatched.run_id,
            }
        },
    )
    # "Ver flujo" también para runs despachados (agente/workflow/tool).
    try:
        decider = "Agente" if method == "agent" else "Workflow" if method == "workflow" else "Runtime"
        route = "Herramientas" if method == "agent" else "Nodos" if method == "workflow" else method
        from src.runtime.agent_flow import steps_to_flow

        mapped = steps_to_flow(dispatched.data.get("steps"))
        result.flow = {
            "query_id": str(result.query_id),
            "organization_id": str(organization_id),
            "conversation_id": str(result.conversation_id) if result.conversation_id else None,
            "method": method,
            "status": str(result.status),
            "verdict": {"decider": decider, "route": route},
            "decision": {
                "evaluated": True,
                "provider": method,
                "capability": dispatched.capability,
                "confidence": 0,
                "fallback_used": False,
                "acting": True,
                "mode": "ReAct + JEV" if mapped["jev"]["used"] else "ReAct",
            },
            "jev": mapped["jev"],
            "generation": {
                "model": dispatched.data.get("model"),
                "total_tokens": int(dispatched.tokens or 0),
                "cost": float(dispatched.cost or 0.0),
                "ms": round(float(dispatched.latency_ms or 0.0), 1),
            },
            "steps": mapped["steps"],
            "timings": {"total_ms": round(float(dispatched.latency_ms or 0.0), 1)},
            "sources": [],
            "fallbacks": [],
        }
        from src.rag.flow_store import record_flow
        from src.rag.flow_story import with_story

        result.flow = with_story(result.flow)

        await record_flow(
            query_id=result.query_id,
            organization_id=organization_id,
            flow=result.flow,
            conversation_id=result.conversation_id,
            request_id=decision_request_id,
            user_id=user_id,
            method=method,
            status=str(result.status),
        )
    except Exception:  # noqa: BLE001 — el flujo nunca rompe la respuesta
        pass
    return result


@router.post(
    "/rag/query",
    response_model=RAGQueryResponse,
    status_code=status.HTTP_200_OK,
    summary="Consulta RAG con contexto vectorial",
    description=(
        "Recibe una pregunta en lenguaje natural, recupera contexto relevante "
        "de la base de conocimiento vectorial del organization y genera una respuesta "
        "fundamentada usando el LLM configurado."
    ),
    responses={
        200: {"description": "Respuesta generada exitosamente"},
        400: {"description": "Datos de entrada inválidos"},
        401: {"description": "API Key inválida o organization no encontrado"},
        429: {"description": "Rate limit excedido para este organization"},
        500: {"description": "Error interno del servidor"},
    },
)
async def rag_query(
    body: RAGQueryRequest,
    request: Request,
    x_organization_id: str = Header(
        default="", alias="X-Organization-Id", description=ORG_HEADER_DESCRIPTION
    ),
    x_user_id: str = Header(
        default="", alias="X-User-Id", description=USER_HEADER_DESCRIPTION
    ),
    x_user_role: str = Header(
        default="",
        alias="X-User-Role",
        deprecated=True,
        description=(
          "DEPRECATED. Nunca es autoridad: solo puede degradar el rol RAG "
          "(admin→customer). La autorización se deriva del Bearer."
        ),
    ),
    orchestrator: RAGOrchestrator = Depends(get_rag_orchestrator),
) -> RAGQueryResponse:
    # ---------------------------------------------------------------
    # Resolver organization_id: Bearer token o header
    # ---------------------------------------------------------------
    organization_id, user_id = await _resolve_organization_user(request, x_organization_id, x_user_id)

    from src.platform.rbac.policy import require_permission

    require_permission(request, "rag:read")

    # Rol server-side: el cliente solo puede degradar (admin -> customer),
    # nunca elevar (customer -> admin).
    from src.api.security import resolve_effective_role

    requested_role = body.role if body.role else x_user_role
    role = await resolve_effective_role(request, requested_role)
    workspace_id = await _resolve_workspace_filter(request)

    # ---------------------------------------------------------------
    # Registro de advertencia de seguridad (prompt injection detection)
    # ---------------------------------------------------------------
    if body.has_injection_warning:
        logger.warning(
            "Potential prompt injection detected in query",
            organization_id=str(organization_id),
            user_id=str(user_id),
            query_preview=body.query[:200],
        )

    # ---------------------------------------------------------------
    # Ejecución del flujo RAG
    # ---------------------------------------------------------------
    rag_active_requests.labels(organization_id=str(organization_id)).inc()

    try:
        result = await _maybe_dispatch(
            request,
            body,
            organization_id=organization_id,
            user_id=user_id,
            role=role,
            workspace_id=workspace_id,
        )
        if result is None:
            result = await orchestrator.execute(
                organization_id=organization_id,
                user_id=user_id,
                query=body.query,
                model=body.model,
                max_tokens=body.max_tokens,
                temperature=body.temperature,
                top_k=body.top_k,
                conversation_id=body.conversation_id,
                role=role,
                metadata_filters=body.metadata_filters,
                rerank_top_k=body.rerank_top_k,
                score_threshold_override=body.score_threshold,
                retrieval_strategy=body.retrieval_strategy,
                language=body.language,
                api_key_id=_token_id(request),
                workspace_id=workspace_id,
                permissions=decision_permissions(request),
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Unhandled exception in RAG query",
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error processing RAG query",
        )
    finally:
        rag_active_requests.labels(organization_id=str(organization_id)).dec()

    # ---------------------------------------------------------------
    # Respuesta de error controlado
    # ---------------------------------------------------------------
    if result.status == "failed":
        rag_queries_total.labels(
            organization_id=str(organization_id), status="failed", method=getattr(result, "method", "rag") or "rag"
        ).inc()

        if "rate limit" in (result.error_message or "").lower():
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=result.error_message,
            )
        if "not found" in (result.error_message or "").lower():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=result.error_message,
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.error_message or "Unknown error",
        )

    # ---------------------------------------------------------------
    # Métricas de negocio
    # ---------------------------------------------------------------
    if result.status == "failed":
        _record_metrics(result, organization_id)
    else:
        _record_metrics(result, organization_id)

    # ---------------------------------------------------------------
    # Construcción de la respuesta
    # ---------------------------------------------------------------
    sources = sources_for_client(result)

    # SQL reveals internal schema — expose only to admin role
    sql_for_client = None
    if (
        result.method == "sql"
        and result.role == "admin"
        and result.sql_query
    ):
        sql_for_client = result.sql_query

    return RAGQueryResponse(
        query_id=result.query_id,
        conversation_id=result.conversation_id,
        role=result.role,
        status=result.status,
        answer=result.llm_response.content if result.llm_response else "",
        sources=sources,
        model=result.llm_response.model if result.llm_response else "unknown",
        usage={
            "prompt_tokens": result.llm_response.prompt_tokens if result.llm_response else 0,
            "completion_tokens": result.llm_response.completion_tokens if result.llm_response else 0,
            "total_tokens": result.llm_response.total_tokens if result.llm_response else 0,
        },
        latency_ms=result.total_latency_ms,
        method=result.method,
        sql_query=sql_for_client,
        lazy_ingested=bool(getattr(result, "lazy_ingested", False)),
        answerability=_answerability_for_client(result),
        trace_id=getattr(result, "trace_id", None),
        rag_trace=getattr(result, "rag_trace", None),
        flow=getattr(result, "flow", None),
    )


def _answerability_for_client(result) -> dict | None:
    """Convierte la decisión del gate en el bloque answerability de la API."""
    decision = getattr(result, "answerability", None)
    if decision is None:
        return None
    return {
        "status": decision.status.value,
        "answerable": decision.answerable,
        "confidence": decision.confidence_level.value,
        "reason_codes": list(decision.reason_codes),
        "missing_context": list(decision.missing_context),
        "missing_data": list(decision.missing_data),
        "conflicting_sources": list(decision.conflicting_sources),
        "clarifying_question": decision.clarifying_question,
        "recommended_actions": list(decision.recommended_actions),
        "evidence": list(decision.evidence_summaries or []),
    }


@router.post(
    "/rag/query/stream",
    status_code=status.HTTP_200_OK,
    summary="Consulta RAG con respuesta en streaming (SSE)",
    description=(
        "Igual que POST /rag/query pero devuelve la respuesta token a token "
        "mediante Server-Sent Events. Eventos: status, sources, delta, done, error."
    ),
    responses={
        200: {"description": "Streaming de eventos SSE"},
        400: {"description": "Datos de entrada inválidos"},
        401: {"description": "API Key inválida o organization no encontrado"},
        429: {"description": "Rate limit excedido para este organization"},
        500: {"description": "Error interno del servidor"},
    },
)
async def rag_query_stream(
    body: RAGQueryRequest,
    request: Request,
    x_organization_id: str = Header(
        default="", alias="X-Organization-Id", description=ORG_HEADER_DESCRIPTION
    ),
    x_user_id: str = Header(
        default="", alias="X-User-Id", description=USER_HEADER_DESCRIPTION
    ),
    x_user_role: str = Header(
        default="",
        alias="X-User-Role",
        deprecated=True,
        description=(
          "DEPRECATED. Nunca es autoridad: solo puede degradar el rol RAG "
          "(admin→customer). La autorización se deriva del Bearer."
        ),
    ),
    orchestrator: RAGOrchestrator = Depends(get_rag_orchestrator),
) -> StreamingResponse:
    organization_id, user_id = await _resolve_organization_user(request, x_organization_id, x_user_id)

    from src.platform.rbac.policy import require_permission

    require_permission(request, "rag:read")

    from src.api.security import resolve_effective_role

    requested_role = body.role if body.role else x_user_role
    role = await resolve_effective_role(request, requested_role)
    workspace_id = await _resolve_workspace_filter(request)

    queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
    await queue.put(("status", {"phase": "searching"}))

    streamed_parts: list[str] = []

    async def on_delta(text: str) -> None:
        streamed_parts.append(text)
        await queue.put(("delta", text))

    async def run_pipeline() -> None:
        """Ejecuta el flujo RAG completo y encola eventos finales."""
        rag_active_requests.labels(organization_id=str(organization_id)).inc()
        try:
            result = await _maybe_dispatch(
                request,
                body,
                organization_id=organization_id,
                user_id=user_id,
                role=role,
                workspace_id=workspace_id,
            )
            if result is None:
                result = await orchestrator.execute(
                    organization_id=organization_id,
                    user_id=user_id,
                    query=body.query,
                    model=body.model,
                    max_tokens=body.max_tokens,
                    temperature=body.temperature,
                    top_k=body.top_k,
                    conversation_id=body.conversation_id,
                    role=role,
                    on_delta=on_delta,
                    metadata_filters=body.metadata_filters,
                    rerank_top_k=body.rerank_top_k,
                    score_threshold_override=body.score_threshold,
                    retrieval_strategy=body.retrieval_strategy,
                    language=body.language,
                    api_key_id=_token_id(request),
                    workspace_id=workspace_id,
                    permissions=decision_permissions(request),
                )
            _record_metrics(result, organization_id)

            if result.status == "failed":
                await queue.put(
                    (
                        "error",
                        {
                            "message": result.error_message
                            or "Error procesando la consulta",
                            "status": result.status.value,
                        },
                    )
                )
                return

            # Respuestas sin streaming real (cache hit, "no hay información",
            # etc.) devuelven contenido sin pasar por on_delta: emitirlo
            # completo para que el cliente lo muestre.
            if not streamed_parts and result.llm_response and result.llm_response.content:
                await queue.put(("delta", result.llm_response.content))

            sources = [
                s.model_dump(mode="json") for s in sources_for_client(result)[:6]
            ]
            sql_for_client = None
            if result.method == "sql" and result.role == "admin" and result.sql_query:
                sql_for_client = result.sql_query

            await queue.put(
                (
                    "sources",
                    {
                        "sources": sources,
                        "method": result.method,
                        "sql_query": sql_for_client,
                        "lazy_ingested": bool(getattr(result, "lazy_ingested", False)),
                    },
                )
            )
            await queue.put(
                (
                    "done",
                    {
                        "conversation_id": str(result.conversation_id),
                        "query_id": str(result.query_id),
                        "model": result.llm_response.model if result.llm_response else "unknown",
                        "usage": {
                            "prompt_tokens": result.llm_response.prompt_tokens if result.llm_response else 0,
                            "completion_tokens": result.llm_response.completion_tokens if result.llm_response else 0,
                            "total_tokens": result.llm_response.total_tokens if result.llm_response else 0,
                        },
                        "latency_ms": result.total_latency_ms,
                        "answerability": _answerability_for_client(result),
                        "trace_id": getattr(result, "trace_id", None),
                        "rag_trace": getattr(result, "rag_trace", None),
                        "flow": getattr(result, "flow", None),
                    },
                )
            )
        except HTTPException as exc:
            await queue.put(
                ("error", {"message": exc.detail, "status": exc.status_code})
            )
        except Exception as exc:
            logger.error(
                "Unhandled exception in RAG stream query",
                error=str(exc),
                exc_info=True,
            )
            await queue.put(("error", {"message": str(exc)}))
        finally:
            rag_active_requests.labels(organization_id=str(organization_id)).dec()
            await queue.put(("__end__", {}))

    task = asyncio.create_task(run_pipeline())

    async def event_stream():
        try:
            while True:
                event, payload = await queue.get()
                if event == "__end__":
                    return
                if event == "delta":
                    yield _sse("delta", {"text": payload})
                elif event == "status":
                    yield _sse("status", payload)
                elif event == "sources":
                    yield _sse("sources", payload)
                elif event == "done":
                    yield _sse("done", payload)
                elif event == "error":
                    yield _sse("error", payload)
                    return
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/rag/queries/{query_id}/flow",
    summary="Flujo completo de una respuesta (Ver flujo)",
    description=(
        "Traza de una respuesta previa: decisión (JEV/reglas/LLM/legacy), "
        "ruta, SQL, retrieval, generación y ms por etapa. Scoped por organización."
    ),
)
async def rag_query_flow(query_id: str, request: Request) -> dict:
    from src.api.security import resolve_organization
    from src.platform.rbac.policy import require_permission

    require_permission(request, "rag:read")
    organization_id = resolve_organization(request)
    try:
        qid = UUID(query_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="query_id must be a valid UUID",
        ) from exc
    from src.rag.flow_store import get_flow

    flow = await get_flow(organization_id, qid)
    if flow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Flow not found"
        )
    return {"flow": flow}
