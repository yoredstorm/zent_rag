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
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from src.api.deps import get_rag_orchestrator
from src.api.metrics import (
    rag_active_requests,
    rag_queries_total,
    rag_tokens_consumed,
)
from src.application.orchestrator import RAGOrchestrator
from src.domain.models import RAGQueryRequest, RAGQueryResponse, sources_for_client
from src.infrastructure.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["RAG"])


async def _resolve_tenant_user(
    request: Request, x_tenant_id: str, x_user_id: str
) -> tuple[UUID, UUID]:
    """Resuelve tenant_id y user_id desde Bearer token o headers."""
    tenant_id_str = x_tenant_id or getattr(request.state, "tenant_id", "")
    if not tenant_id_str:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Se requiere X-Tenant-Id header o Authorization: Bearer token",
        )

    try:
        tenant_id = UUID(tenant_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-Id debe ser un UUID valido",
        )

    # Resolver user_id: header o default del tenant
    user_id_str = x_user_id
    if not user_id_str:
        try:
            from src.infrastructure.relational_db import PostgresUserRepository
            user_repo = PostgresUserRepository()
            default_user = await user_repo.get_by_external_id(tenant_id, "default-admin")
            if default_user is None:
                default_user = await user_repo.get_any_user(tenant_id)
            if default_user is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No users found for this tenant. Create a user first.",
                )
            user_id_str = str(default_user.id)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error resolving user: {exc}",
            )
    try:
        user_id = UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-User-Id debe ser un UUID valido",
        )
    return tenant_id, user_id


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _record_metrics(result, tenant_id: UUID) -> None:
    """Registra métricas Prometheus para una consulta finalizada."""
    rag_queries_total.labels(
        tenant_id=str(tenant_id),
        status=result.status.value,
        method=getattr(result, "method", "rag") or "rag",
    ).inc()

    if result.llm_response:
        rag_tokens_consumed.labels(
            tenant_id=str(tenant_id),
            model=result.llm_response.model,
            token_type="prompt",
        ).inc(result.llm_response.prompt_tokens)
        rag_tokens_consumed.labels(
            tenant_id=str(tenant_id),
            model=result.llm_response.model,
            token_type="completion",
        ).inc(result.llm_response.completion_tokens)
        rag_tokens_consumed.labels(
            tenant_id=str(tenant_id),
            model=result.llm_response.model,
            token_type="total",
        ).inc(result.llm_response.total_tokens)


@router.post(
    "/rag/query",
    response_model=RAGQueryResponse,
    status_code=status.HTTP_200_OK,
    summary="Consulta RAG con contexto vectorial",
    description=(
        "Recibe una pregunta en lenguaje natural, recupera contexto relevante "
        "de la base de conocimiento vectorial del tenant y genera una respuesta "
        "fundamentada usando el LLM configurado."
    ),
    responses={
        200: {"description": "Respuesta generada exitosamente"},
        400: {"description": "Datos de entrada inválidos"},
        401: {"description": "API Key inválida o tenant no encontrado"},
        429: {"description": "Rate limit excedido para este tenant"},
        500: {"description": "Error interno del servidor"},
    },
)
async def rag_query(
    body: RAGQueryRequest,
    request: Request,
    x_tenant_id: str = Header(
        default="", alias="X-Tenant-Id", description="UUID del tenant (obligatorio si no usa Bearer token)"
    ),
    x_user_id: str = Header(
        default="", alias="X-User-Id", description="UUID del usuario (obligatorio si no usa Bearer token)"
    ),
    x_user_role: str = Header(
        default="admin",
        alias="X-User-Role",
        description="Rol del usuario: admin o customer",
    ),
    orchestrator: RAGOrchestrator = Depends(get_rag_orchestrator),
) -> RAGQueryResponse:
    # ---------------------------------------------------------------
    # Resolver tenant_id: Bearer token o header
    # ---------------------------------------------------------------
    tenant_id, user_id = await _resolve_tenant_user(request, x_tenant_id, x_user_id)

    # El body.role tiene prioridad sobre el header
    role = body.role if body.role else x_user_role
    if role not in ("admin", "customer"):
        role = "admin"

    # ---------------------------------------------------------------
    # Registro de advertencia de seguridad (prompt injection detection)
    # ---------------------------------------------------------------
    if body.has_injection_warning:
        logger.warning(
            "Potential prompt injection detected in query",
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            query_preview=body.query[:200],
        )

    # ---------------------------------------------------------------
    # Ejecución del flujo RAG
    # ---------------------------------------------------------------
    rag_active_requests.labels(tenant_id=str(tenant_id)).inc()

    try:
        result = await orchestrator.execute(
            tenant_id=tenant_id,
            user_id=user_id,
            query=body.query,
            model=body.model,
            max_tokens=body.max_tokens,
            temperature=body.temperature,
            top_k=body.top_k,
            conversation_id=body.conversation_id,
            role=role,
        )
    except Exception as exc:
        rag_active_requests.labels(tenant_id=str(tenant_id)).dec()
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
        rag_active_requests.labels(tenant_id=str(tenant_id)).dec()

    # ---------------------------------------------------------------
    # Respuesta de error controlado
    # ---------------------------------------------------------------
    if result.status == "failed":
        rag_queries_total.labels(
            tenant_id=str(tenant_id), status="failed", method=getattr(result, "method", "rag") or "rag"
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
        _record_metrics(result, tenant_id)
    else:
        _record_metrics(result, tenant_id)

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
    )


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
        401: {"description": "API Key inválida o tenant no encontrado"},
        429: {"description": "Rate limit excedido para este tenant"},
        500: {"description": "Error interno del servidor"},
    },
)
async def rag_query_stream(
    body: RAGQueryRequest,
    request: Request,
    x_tenant_id: str = Header(
        default="", alias="X-Tenant-Id", description="UUID del tenant (obligatorio si no usa Bearer token)"
    ),
    x_user_id: str = Header(
        default="", alias="X-User-Id", description="UUID del usuario (opcional)"
    ),
    x_user_role: str = Header(
        default="admin",
        alias="X-User-Role",
        description="Rol del usuario: admin o customer",
    ),
    orchestrator: RAGOrchestrator = Depends(get_rag_orchestrator),
) -> StreamingResponse:
    tenant_id, user_id = await _resolve_tenant_user(request, x_tenant_id, x_user_id)

    role = body.role if body.role else x_user_role
    if role not in ("admin", "customer"):
        role = "admin"

    queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
    await queue.put(("status", {"phase": "searching"}))

    streamed_parts: list[str] = []

    async def on_delta(text: str) -> None:
        streamed_parts.append(text)
        await queue.put(("delta", text))

    async def run_pipeline() -> None:
        """Ejecuta el flujo RAG completo y encola eventos finales."""
        rag_active_requests.labels(tenant_id=str(tenant_id)).inc()
        try:
            result = await orchestrator.execute(
                tenant_id=tenant_id,
                user_id=user_id,
                query=body.query,
                model=body.model,
                max_tokens=body.max_tokens,
                temperature=body.temperature,
                top_k=body.top_k,
                conversation_id=body.conversation_id,
                role=role,
                on_delta=on_delta,
            )
            _record_metrics(result, tenant_id)

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
                    },
                )
            )
        except Exception as exc:
            logger.error(
                "Unhandled exception in RAG stream query",
                error=str(exc),
                exc_info=True,
            )
            await queue.put(("error", {"message": str(exc)}))
        finally:
            rag_active_requests.labels(tenant_id=str(tenant_id)).dec()
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
