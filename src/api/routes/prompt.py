# =============================================================================
# Prompt Management — GET/PUT/DELETE/test del system prompt por tenant
# =============================================================================
# Permite iterar el system prompt sin redeploy. Cada tenant puede tener
# su propio prompt + custom_instructions. El test hace dry-run sin guardar.
# Variables disponibles: {role}, {tenant_name}, {date}, {top_k}
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from pydantic import BaseModel, Field

from src.api.deps import get_llm_provider, get_tenant_repo
from src.application.orchestrator import RAG_SYSTEM_PROMPT
from src.domain.ports import LLMProvider, TenantRepository
from src.infrastructure.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/admin", tags=["Prompt Management"])

DEFAULT_CONFIG: dict[str, str] = {
    "system_prompt": RAG_SYSTEM_PROMPT,
    "custom_instructions": "",
}


def _resolve_tenant_id(request: Request, x_tenant_id: str) -> UUID:
    tid = x_tenant_id or getattr(request.state, "tenant_id", "")
    if not tid:
        raise HTTPException(400, "X-Tenant-Id header required")
    try:
        return UUID(tid)
    except ValueError:
        raise HTTPException(400, "X-Tenant-Id must be a valid UUID")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class PromptConfig(BaseModel):
    system_prompt: str = Field(..., description="System prompt completo para el asistente RAG")
    custom_instructions: str = Field(
        default="",
        description="Instrucciones adicionales que se concatenan al system_prompt",
    )


class PromptStatus(BaseModel):
    tenant_id: str
    system_prompt: str
    custom_instructions: str
    default_system_prompt: str
    is_customized: bool
    available_variables: list[str] = Field(
        default_factory=lambda: ["{role}", "{tenant_name}", "{date}", "{top_k}"]
    )


class PromptTestRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000, description="Query de prueba")
    system_prompt: str = Field(..., description="Prompt a testear (no se guarda)")
    custom_instructions: str = Field(default="", description="Instrucciones adicionales")


class PromptTestResponse(BaseModel):
    answer: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


# ---------------------------------------------------------------------------
# GET /api/v1/admin/prompt — Ver prompt actual
# ---------------------------------------------------------------------------


@router.get(
    "/prompt",
    response_model=PromptStatus,
    summary="Ver system prompt del tenant",
    description="Devuelve el system_prompt y custom_instructions actuales del tenant, junto con el default.",
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
    current_prompt = cfg.get("system_prompt", RAG_SYSTEM_PROMPT)
    current_instructions = cfg.get("custom_instructions", "")

    return PromptStatus(
        tenant_id=str(tenant_id),
        system_prompt=current_prompt,
        custom_instructions=current_instructions,
        default_system_prompt=RAG_SYSTEM_PROMPT,
        is_customized="system_prompt" in cfg,
    )


# ---------------------------------------------------------------------------
# PUT /api/v1/admin/prompt — Actualizar prompt
# ---------------------------------------------------------------------------


@router.put(
    "/prompt",
    response_model=PromptStatus,
    summary="Actualizar system prompt del tenant",
    description="Guarda un nuevo system_prompt y/o custom_instructions para el tenant.",
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
    new_config["system_prompt"] = body.system_prompt
    if body.custom_instructions:
        new_config["custom_instructions"] = body.custom_instructions
    elif "" == body.custom_instructions:
        new_config.pop("custom_instructions", None)

    updated = await repo.update_config(tenant_id, new_config)
    cfg = updated.config_json or {}

    logger.info(
        "System prompt updated for tenant",
        tenant_id=str(tenant_id),
        prompt_length=len(body.system_prompt),
    )

    return PromptStatus(
        tenant_id=str(tenant_id),
        system_prompt=cfg.get("system_prompt", RAG_SYSTEM_PROMPT),
        custom_instructions=cfg.get("custom_instructions", ""),
        default_system_prompt=RAG_SYSTEM_PROMPT,
        is_customized=True,
    )


# ---------------------------------------------------------------------------
# DELETE /api/v1/admin/prompt — Resetear a default
# ---------------------------------------------------------------------------


@router.delete(
    "/prompt",
    response_model=PromptStatus,
    summary="Resetear system prompt al default",
    description="Elimina la personalización del tenant y vuelve al prompt por defecto.",
)
async def reset_prompt(
    request: Request,
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
    repo: TenantRepository = Depends(get_tenant_repo),
) -> PromptStatus:
    tenant_id = _resolve_tenant_id(request, x_tenant_id)
    tenant = await repo.get_by_id(tenant_id)
    if tenant is None:
        raise HTTPException(404, "Tenant not found")

    new_config = dict(tenant.config_json or {})
    new_config.pop("system_prompt", None)
    new_config.pop("custom_instructions", None)

    await repo.update_config(tenant_id, new_config)

    logger.info(
        "System prompt reset to default for tenant",
        tenant_id=str(tenant_id),
    )

    return PromptStatus(
        tenant_id=str(tenant_id),
        system_prompt=RAG_SYSTEM_PROMPT,
        custom_instructions="",
        default_system_prompt=RAG_SYSTEM_PROMPT,
        is_customized=False,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/admin/prompt/test — Probar prompt sin guardar
# ---------------------------------------------------------------------------


@router.post(
    "/prompt/test",
    response_model=PromptTestResponse,
    summary="Testear system prompt sin guardar",
    description="Ejecuta una query de prueba con el prompt dado (dry-run). No modifica la configuración.",
)
async def test_prompt(
    body: PromptTestRequest,
    llm: LLMProvider = Depends(get_llm_provider),
) -> PromptTestResponse:
    system_prompt = body.system_prompt
    if body.custom_instructions:
        system_prompt += "\n\n" + body.custom_instructions

    response = await llm.generate(
        prompt=body.query,
        system_prompt=system_prompt,
        max_tokens=1024,
        temperature=0.3,
    )

    logger.info(
        "Prompt test executed",
        prompt_length=len(body.system_prompt),
        query_preview=body.query[:100],
        model=response.model,
    )

    return PromptTestResponse(
        answer=response.content,
        model=response.model,
        prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
        total_tokens=response.total_tokens,
    )
