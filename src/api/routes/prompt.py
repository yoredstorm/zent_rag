# =============================================================================
# Prompt Management — GET/PUT/DELETE/test del system prompt por tenant y rol
# =============================================================================
# Permite iterar el system prompt sin redeploy. Cada tenant puede tener
# prompts diferentes por rol (admin vs customer). El test hace dry-run
# conectado al pipeline RAG real (vectores + SQL expert).
# Variables disponibles: {role}, {tenant_name}, {date}, {top_k}
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Header, Query, Request, status
from pydantic import BaseModel, Field

from src.api.deps import (
    get_embedding_provider,
    get_llm_provider,
    get_rag_orchestrator,
    get_tenant_repo,
)
from src.application.orchestrator import RAG_SYSTEM_PROMPT, RAGOrchestrator
from src.domain.ports import EmbeddingProvider, TenantRepository
from src.infrastructure.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/admin", tags=["Prompt Management"])


def _resolve_tenant_id(request: Request, x_tenant_id: str) -> UUID:
    tid = x_tenant_id or getattr(request.state, "tenant_id", "")
    if not tid:
        raise HTTPException(400, "X-Tenant-Id header required")
    try:
        return UUID(tid)
    except ValueError:
        raise HTTPException(400, "X-Tenant-Id must be a valid UUID")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ROLE_KEYS = ["admin", "customer"]


def _extract_role_prompt(cfg: dict, role: str) -> dict:
    return {
        "system_prompt": cfg.get(f"system_prompt_{role}") or cfg.get("system_prompt", RAG_SYSTEM_PROMPT),
        "custom_instructions": cfg.get(f"custom_instructions_{role}") or cfg.get("custom_instructions", ""),
        "is_customized": f"system_prompt_{role}" in cfg or bool(cfg.get("system_prompt")),
    }


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class RolePromptInfo(BaseModel):
    system_prompt: str
    custom_instructions: str
    is_customized: bool


class PromptStatus(BaseModel):
    tenant_id: str
    roles: dict[str, RolePromptInfo]
    default_system_prompt: str
    available_variables: list[str] = Field(
        default_factory=lambda: ["{role}", "{tenant_name}", "{date}", "{top_k}"]
    )


class PromptConfig(BaseModel):
    system_prompt: str = Field(..., description="System prompt para el asistente RAG")
    custom_instructions: str = Field(
        default="",
        description="Instrucciones adicionales que se concatenan al system_prompt",
    )
    role: str | None = Field(
        default=None,
        pattern=r"^(admin|customer)$",
        description="Rol al que aplica: admin, customer, o null para genérico",
    )


class PromptTestRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000, description="Query de prueba")
    system_prompt: str = Field(..., description="Prompt a testear (no se guarda)")
    custom_instructions: str = Field(default="", description="Instrucciones adicionales")
    role: str = Field(default="admin", pattern=r"^(admin|customer)$", description="Rol para la prueba")
    top_k: int = Field(default=200, ge=1, le=500)
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    model: str | None = Field(default=None, max_length=100)


class TestChunk(BaseModel):
    document_id: str
    content: str
    score: float


class PromptTestResponse(BaseModel):
    answer: str
    sources: list[TestChunk] = Field(default_factory=list)
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float


# ---------------------------------------------------------------------------
# GET /api/v1/admin/prompt
# ---------------------------------------------------------------------------


@router.get(
    "/prompt",
    response_model=PromptStatus,
    summary="Ver system prompt del tenant por rol",
    description="Devuelve los prompts configurados para admin y customer, más el default.",
)
async def get_prompt(
    request: Request,
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
    repo: TenantRepository = Depends(get_tenant_repo),
) -> PromptStatus:
    tenant_id = _resolve_tenant_id(request, x_tenant_id)
    tenant = await repo.get_by_id(tenant_id)
    if tenant is None:
        raise HTTPException(404, "Tenant not found")

    cfg = tenant.config_json or {}

    return PromptStatus(
        tenant_id=str(tenant_id),
        roles={
            role: RolePromptInfo(**_extract_role_prompt(cfg, role))
            for role in _ROLE_KEYS
        },
        default_system_prompt=RAG_SYSTEM_PROMPT,
    )


# ---------------------------------------------------------------------------
# PUT /api/v1/admin/prompt
# ---------------------------------------------------------------------------


@router.put(
    "/prompt",
    response_model=PromptStatus,
    summary="Actualizar system prompt del tenant",
    description="Guarda un nuevo system_prompt para un rol específico (o genérico).",
)
async def update_prompt(
    body: PromptConfig,
    request: Request,
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
    repo: TenantRepository = Depends(get_tenant_repo),
) -> PromptStatus:
    tenant_id = _resolve_tenant_id(request, x_tenant_id)
    tenant = await repo.get_by_id(tenant_id)
    if tenant is None:
        raise HTTPException(404, "Tenant not found")

    new_config = dict(tenant.config_json or {})

    if body.role:
        prompt_key = f"system_prompt_{body.role}"
        instr_key = f"custom_instructions_{body.role}"
    else:
        prompt_key = "system_prompt"
        instr_key = "custom_instructions"

    new_config[prompt_key] = body.system_prompt
    if body.custom_instructions:
        new_config[instr_key] = body.custom_instructions
    elif instr_key in new_config:
        del new_config[instr_key]

    updated = await repo.update_config(tenant_id, new_config)
    cfg = updated.config_json or {}

    logger.info(
        "System prompt updated for tenant",
        tenant_id=str(tenant_id),
        role=body.role or "generic",
        prompt_length=len(body.system_prompt),
    )

    return PromptStatus(
        tenant_id=str(tenant_id),
        roles={
            role: RolePromptInfo(**_extract_role_prompt(cfg, role))
            for role in _ROLE_KEYS
        },
        default_system_prompt=RAG_SYSTEM_PROMPT,
    )


# ---------------------------------------------------------------------------
# DELETE /api/v1/admin/prompt
# ---------------------------------------------------------------------------


@router.delete(
    "/prompt",
    response_model=PromptStatus,
    summary="Resetear system prompt al default",
    description="Elimina personalización. Usa ?role=admin para resetear solo un rol.",
)
async def reset_prompt(
    request: Request,
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
    role: str | None = Query(default=None, pattern=r"^(admin|customer)$"),
    repo: TenantRepository = Depends(get_tenant_repo),
) -> PromptStatus:
    tenant_id = _resolve_tenant_id(request, x_tenant_id)
    tenant = await repo.get_by_id(tenant_id)
    if tenant is None:
        raise HTTPException(404, "Tenant not found")

    new_config = dict(tenant.config_json or {})

    if role:
        new_config.pop(f"system_prompt_{role}", None)
        new_config.pop(f"custom_instructions_{role}", None)
        log_msg = f"System prompt reset for role '{role}'"
    else:
        for k in list(new_config.keys()):
            if k.startswith("system_prompt") or k.startswith("custom_instructions"):
                del new_config[k]
        log_msg = "All system prompts reset to default"

    await repo.update_config(tenant_id, new_config)

    logger.info(log_msg, tenant_id=str(tenant_id))

    cfg = await repo.get_by_id(tenant_id)
    cfg = (cfg and cfg.config_json) or {}

    return PromptStatus(
        tenant_id=str(tenant_id),
        roles={
            r: RolePromptInfo(**_extract_role_prompt(cfg, r))
            for r in _ROLE_KEYS
        },
        default_system_prompt=RAG_SYSTEM_PROMPT,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/admin/prompt/test — Probar prompt con RAG real
# ---------------------------------------------------------------------------


@router.post(
    "/prompt/test",
    response_model=PromptTestResponse,
    summary="Testear system prompt con pipeline RAG real",
    description="Ejecuta el flujo RAG completo (embedding + vector search + SQL) con el prompt dado. Dry-run: no guarda ni afecta caché de conversación.",
)
async def test_prompt(
    body: PromptTestRequest,
    request: Request,
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
    x_user_id: str = Header(default="00000000-0000-0000-0000-000000000002", alias="X-User-Id"),
    orchestrator: RAGOrchestrator = Depends(get_rag_orchestrator),
    repo: TenantRepository = Depends(get_tenant_repo),
) -> PromptTestResponse:
    tenant_id = _resolve_tenant_id(request, x_tenant_id)
    tenant = await repo.get_by_id(tenant_id)
    if tenant is None:
        raise HTTPException(404, "Tenant not found")

    try:
        user_id = UUID(x_user_id)
    except ValueError:
        raise HTTPException(400, "X-User-Id must be a valid UUID")

    full_prompt = body.system_prompt
    if body.custom_instructions:
        full_prompt += "\n\n" + body.custom_instructions

    result = await orchestrator.execute(
        tenant_id=tenant_id,
        user_id=user_id,
        query=body.query,
        model=body.model,
        max_tokens=2048,
        temperature=body.temperature,
        top_k=body.top_k,
        conversation_id=None,
        role=body.role,
        system_prompt_override=full_prompt,
    )

    sources: list[TestChunk] = []
    if result.retrieval_context:
        sources = [
            TestChunk(
                document_id=str(chunk.document_id),
                content=chunk.content[:500],
                score=chunk.score,
            )
            for chunk in result.retrieval_context.chunks[:5]
        ]

    llm_resp = result.llm_response

    logger.info(
        "Prompt test executed (RAG pipeline)",
        prompt_length=len(body.system_prompt),
        role=body.role,
        query_preview=body.query[:100],
        sources_count=len(sources),
        model=llm_resp.model if llm_resp else "unknown",
    )

    return PromptTestResponse(
        answer=llm_resp.content if llm_resp else "No response generated",
        sources=sources,
        model=llm_resp.model if llm_resp else "unknown",
        prompt_tokens=llm_resp.prompt_tokens if llm_resp else 0,
        completion_tokens=llm_resp.completion_tokens if llm_resp else 0,
        total_tokens=llm_resp.total_tokens if llm_resp else 0,
        latency_ms=result.total_latency_ms,
    )
