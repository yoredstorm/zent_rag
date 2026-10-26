# =============================================================================
# Agents Routes — CRUD de agentes (organization-scoped, project opcional)
# =============================================================================
from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError, field_validator
from pydantic_core import PydanticCustomError
from sqlalchemy.exc import IntegrityError

from src.api.deps import get_agent_repo
from src.core.ports import AgentRepository
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.relational_db import PostgresAuditLogRepository
from src.platform.audit.service import AuditLogService

router = APIRouter(prefix="/api/v1/agents", tags=["Agents"])

logger = get_logger(__name__)

MAX_AGENT_SOURCE_IDS = 500
AGENT_SOURCE_CAP_MSG = "Un agente admite como máximo 500 fuentes."


def _audit() -> AuditLogService:
    return AuditLogService(PostgresAuditLogRepository())


class AgentLimits(BaseModel):
    max_steps: int | None = Field(default=None, ge=1, le=100)
    max_tokens: int | None = Field(default=None, ge=1, le=2_000_000)
    max_cost_usd: float | None = Field(default=None, ge=0, le=1000)


class AgentSecurity(BaseModel):
    sql_enabled: bool = False
    api_calls_enabled: bool = False


class AgentRuntimeConfig(BaseModel):
    """Overrides de JEV por agente (None = hereda el flag del sistema)."""

    tool_routing: bool | None = None
    termination_gate: bool | None = None
    answer_gate: bool | None = None


class ResponseProfileConfig(BaseModel):
    """Cómo debe explicar el agente (§28). Estructura, no un prompt gigante."""

    preset: str | None = Field(default=None, max_length=40)
    language: str | None = Field(default=None, max_length=16)
    tone: str | None = Field(default=None, max_length=20)
    technical_level: str | None = Field(default=None, max_length=20)
    default_detail: str | None = Field(default=None, max_length=20)
    audience: str | None = Field(default=None, max_length=20)
    conclusion_first: bool | None = None
    use_headings: bool | None = None
    use_bold: bool | None = None
    use_tables: bool | None = None
    use_examples: bool | None = None
    cite_sources: bool | None = None
    show_uncertainty: bool | None = None
    show_practical_implications: bool | None = None
    preserve_domain_terms: bool | None = None
    preferred_blueprints: list[str] | None = Field(default=None, max_length=6)
    custom_instructions: str | None = Field(default=None, max_length=800)
    profile_id: str | None = Field(default=None, max_length=40)
    communication_strategy: str | None = Field(default=None, max_length=40)
    detail_budget: str | None = Field(default=None, max_length=20)
    structure_policy: str | None = Field(default=None, max_length=60)
    example_policy: str | None = Field(default=None, max_length=30)
    analysis_depth: str | None = Field(default=None, max_length=40)
    terminology_policy: str | None = Field(default=None, max_length=40)
    source_presentation_policy: str | None = Field(default=None, max_length=30)
    audience_assumptions: str | None = Field(default=None, max_length=240)


class AgentConfig(BaseModel):
    purpose: str | None = Field(default=None, max_length=2000)
    temperature: float = Field(default=0.2, ge=0, le=1)
    tone: str = Field(default="professional", pattern="^(professional|friendly|concise)$")
    knowledge_base_ids: list[UUID] = Field(default_factory=list, max_length=50)
    source_ids: list[UUID] = Field(default_factory=list)
    knowledge_scope: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Alcance de conocimiento declarativo (C7): fuentes, bases, workspaces, "
            "kinds, dominios y tags. Estrecha el scope legacy; nunca lo amplía."
        ),
    )
    limits: AgentLimits | None = None
    security: AgentSecurity | None = None
    retrieval: dict | None = Field(
        default=None,
        description="Overrides de retrieval (strategy, top_k, score_threshold).",
    )
    output_schema: dict | None = Field(
        default=None,
        description="JSON Schema para respuestas estructuradas (ERP/CRM).",
    )
    runtime: AgentRuntimeConfig | None = Field(
        default=None,
        description="JEV por agente: tool_routing, termination_gate, answer_gate.",
    )
    response_profile: ResponseProfileConfig | None = Field(
        default=None,
        description="Cómo debe responder: tono, nivel, detalle, formato, citas (§28).",
    )

    @field_validator("source_ids")
    @classmethod
    def cap_source_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(value) > MAX_AGENT_SOURCE_IDS:
            raise PydanticCustomError("too_long", AGENT_SOURCE_CAP_MSG)
        return value


class CreateAgentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    project_id: UUID | None = None
    workspace_id: UUID | None = None
    system_prompt: str | None = Field(default=None, max_length=16000)
    tools: list[str] = Field(default_factory=list, max_length=20)
    model: str | None = Field(default=None, max_length=100)
    config: AgentConfig | None = None


class UpdateAgentRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    project_id: UUID | None = None
    workspace_id: UUID | None = None
    system_prompt: str | None = Field(default=None, max_length=16000)
    tools: list[str] | None = Field(default=None, max_length=20)
    model: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None
    config: AgentConfig | None = None


def parse_agent_config(raw: dict | None) -> dict:
    try:
        return AgentConfig.model_validate(raw or {}).model_dump(mode="json")
    except ValidationError:
        return AgentConfig().model_dump(mode="json")


def _agent_response(agent, *, warnings: list[str] | None = None) -> dict:
    config = parse_agent_config(agent.config_json)
    # El perfil se devuelve ya resuelto (preset + estrategia + defaults), no
    # como el delta crudo que mandó el cliente: la UI y el runtime ven lo mismo.
    if config.get("response_profile"):
        from src.intelligence.response.profile import profile_from_config

        config["response_profile"] = profile_from_config(config).to_public_dict()
    payload = {
        "id": str(agent.id),
        "name": agent.name,
        "description": agent.description,
        "project_id": str(agent.project_id) if agent.project_id else None,
        "workspace_id": str(agent.workspace_id) if agent.workspace_id else None,
        "status": agent.status.value if hasattr(agent.status, "value") else str(agent.status),
        "system_prompt": agent.system_prompt,
        "tools": agent.tools,
        "model": agent.model,
        "is_active": agent.is_active,
        # FASE 03 (S17): identidad de agente diferenciada del usuario humano.
        "identity": f"agent://{agent.organization_id}/{agent.id}",
        "created_by": str(agent.created_by) if agent.created_by else None,
        "created_at": agent.created_at.isoformat(),
        "config": config,
    }
    if warnings:
        payload["warnings"] = list(warnings)
    return payload


@router.get("", summary="Listar agentes")
async def list_agents(
    request: Request,
    workspace_id: str | None = None,
    status: str | None = None,
    repo: AgentRepository = Depends(get_agent_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:read")
    agents = await repo.list_agents(ctx.organization_id)
    if workspace_id is not None:
        try:
            wid = UUID(workspace_id)
        except ValueError:
            raise HTTPException(400, "workspace_id must be a valid UUID")
        agents = [a for a in agents if a.workspace_id == wid]
    if status is not None:
        agents = [a for a in agents if a.status.value == status]
    return {"agents": [_agent_response(a) for a in agents], "count": len(agents)}


@router.post("", status_code=201, summary="Crear agente")
async def create_agent(
    body: CreateAgentRequest,
    request: Request,
    repo: AgentRepository = Depends(get_agent_repo),
):
    from src.platform.billing.plan_limits import (
        PlanLimitError,
        check_resource_limit,
        plan_limit_detail,
    )
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:write")
    try:
        await check_resource_limit(ctx.organization_id, "agents")
    except PlanLimitError as exc:
        raise HTTPException(status_code=409, detail=plan_limit_detail(exc)) from None
    if body.project_id is not None:
        await _require_own_project(ctx, body.project_id)
    if body.workspace_id is not None:
        await _require_own_workspace(ctx, body.workspace_id)
    config_payload = None
    warnings: list[str] = []
    if body.config is not None:
        config, warnings = await _apply_source_config(ctx, body.config)
        config_payload = config.model_dump(mode="json")
    try:
        agent = await repo.create_agent(
            ctx.organization_id,
            body.name,
            description=body.description,
            project_id=body.project_id,
            workspace_id=body.workspace_id,
            system_prompt=body.system_prompt,
            tools=body.tools,
            model=body.model,
            config_json=config_payload,
            created_by=ctx.user_id,
        )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "duplicate_agent_name",
                "message": (
                    f"Ya existe un agente llamado «{body.name}» en esta organización. "
                    "Ábrelo para editarlo o elige otro nombre."
                ),
            },
        ) from exc
    await _audit().write(ctx, "agent.created", "agent", agent.id, metadata={"name": agent.name})
    try:
        from src.platform.onboardingv2.onboarding import sync_progress

        await sync_progress(ctx.organization_id)
    except Exception:  # noqa: BLE001
        pass
    return _agent_response(agent, warnings=warnings)


@router.get("/assistants", summary="Living assistants: agentes y sus automatizaciones")
async def list_assistants(request: Request, repo: AgentRepository = Depends(get_agent_repo)):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.assistants import agent_automations

    ctx = require_permission(request, "agents:read")
    agents = await repo.list_agents(ctx.organization_id)
    out: list[dict] = []
    for agent in agents[:40]:
        data = await agent_automations(ctx.organization_id, agent.id)
        summary = (data or {}).get("summary") or {}
        automations = (data or {}).get("automations") or []
        status = agent.status.value if hasattr(agent.status, "value") else str(agent.status)
        out.append(
            {
                "id": str(agent.id),
                "name": agent.name,
                "description": agent.description,
                "status": status,
                "is_active": bool(agent.is_active),
                "owner_id": str(agent.created_by) if agent.created_by else None,
                "automations": summary.get("automations", 0),
                "active": summary.get("active", 0),
                "actions_today": summary.get("actions_today", 0),
                "last_activity": summary.get("last_activity"),
                "health": summary.get("health", "idle"),
                "watches": [str(a.get("when")) for a in automations][:4],
                "automation_names": [str(a.get("name")) for a in automations][:4],
            }
        )
    out.sort(key=lambda item: int(item.get("automations") or 0), reverse=True)
    return {"assistants": out, "count": len(out)}


@router.get("/{agent_id}/activity", summary="Living assistant: feed de actividad legible")
async def agent_activity_endpoint(agent_id: str, request: Request, limit: int = 40):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.assistant_activity import agent_activity

    ctx = require_permission(request, "agents:read")
    try:
        aid = UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "agent_id must be a valid UUID")
    result = await agent_activity(ctx.organization_id, aid, limit=limit)
    if result is None:
        raise HTTPException(404, "Agent not found")
    return result


async def _require_own_agent(request, organization_id, agent_id) -> None:
    from src.api.deps import get_agent_repo

    agent = await get_agent_repo().get_agent(organization_id, agent_id)
    if agent is None:
        raise HTTPException(404, "Agent not found")


@router.get("/{agent_id}/permissions", summary="Permisos delegados del agente (FASE 03)")
async def get_agent_permissions(agent_id: str, request: Request):
    from src.platform.agents.permissions import get_agent_permissions as _load
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:read")
    try:
        aid = UUID(agent_id)
    except ValueError as exc:
        raise HTTPException(400, "agent_id must be a valid UUID") from exc
    await _require_own_agent(request, ctx.organization_id, aid)
    perms = await _load(aid)
    return {
        "agent_id": agent_id,
        "permissions": sorted(p for p in (perms or []) if p != "__zent_deny_all__"),
        "explicit": perms is not None,
    }


@router.put("/{agent_id}/permissions", summary="Asignar permisos delegados del agente (FASE 03)")
async def set_agent_permissions(body: dict, agent_id: str, request: Request):
    from src.platform.agents.permissions import set_agent_permissions as _save
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:write")
    try:
        aid = UUID(agent_id)
    except ValueError as exc:
        raise HTTPException(400, "agent_id must be a valid UUID") from exc
    await _require_own_agent(request, ctx.organization_id, aid)
    permissions = [str(p) for p in (body.get("permissions") or []) if isinstance(p, str)]
    await _save(ctx.organization_id, aid, permissions)
    return {"agent_id": agent_id, "permissions": sorted(set(permissions))}


@router.get("/{agent_id}", summary="Obtener agente")
async def get_agent(
    agent_id: str,
    request: Request,
    repo: AgentRepository = Depends(get_agent_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:read")
    try:
        aid = UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "agent_id must be a valid UUID")
    agent = await repo.get_agent(ctx.organization_id, aid)
    if agent is None:
        raise HTTPException(404, "Agent not found")
    return _agent_response(agent)


@router.get("/{agent_id}/automations", summary="Living assistant: automatizaciones del agente")
async def agent_automations_endpoint(agent_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.assistants import agent_automations

    ctx = require_permission(request, "agents:read")
    try:
        aid = UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "agent_id must be a valid UUID")
    result = await agent_automations(ctx.organization_id, aid)
    if result is None:
        raise HTTPException(404, "Agent not found")
    return result


@router.put("/{agent_id}", summary="Actualizar agente")
async def update_agent(
    agent_id: str,
    body: UpdateAgentRequest,
    request: Request,
    repo: AgentRepository = Depends(get_agent_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:write")
    try:
        aid = UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "agent_id must be a valid UUID")
    if body.project_id is not None:
        await _require_own_project(ctx, body.project_id)
    if body.workspace_id is not None:
        await _require_own_workspace(ctx, body.workspace_id)
    fields = body.model_dump(exclude_none=True)
    warnings: list[str] = []
    if "config" in fields:
        if body.config is not None:
            applied, warnings = await _apply_source_config(ctx, body.config)
            fields["config_json"] = applied.model_dump(mode="json")
        else:
            fields["config_json"] = {}
        del fields["config"]
    try:
        agent = await repo.update_agent(ctx.organization_id, aid, **fields)
    except ValueError:
        raise HTTPException(404, "Agent not found")
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "duplicate_agent_name",
                "message": (
                    f"Ya existe otro agente llamado «{fields.get('name') or agent_id}» "
                    "en esta organización."
                ),
            },
        ) from exc
    await _audit().write(ctx, "agent.updated", "agent", aid, metadata={"name": agent.name})
    return _agent_response(agent, warnings=warnings)


@router.delete("/{agent_id}", summary="Eliminar agente")
async def delete_agent(
    agent_id: str,
    request: Request,
    repo: AgentRepository = Depends(get_agent_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:write")
    try:
        aid = UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "agent_id must be a valid UUID")
    if await repo.get_agent(ctx.organization_id, aid) is None:
        raise HTTPException(404, "Agent not found")
    await repo.delete_agent(ctx.organization_id, aid)
    await _audit().write(ctx, "agent.deleted", "agent", aid)
    return {"status": "deleted", "agent_id": str(aid)}


@router.get("/response-profile/catalog", summary="Presets de respuesta y formas de explicación")
async def response_profile_catalog(request: Request):
    """Catálogo para Agent Studio: presets + blueprints (§29, §51)."""
    from src.core.domain.response import ResponseProfile
    from src.intelligence.response.blueprints import public_blueprints
    from src.intelligence.response.profile import public_presets

    return {
        "schema": "zent.response_profile_catalog/v2",
        "presets": public_presets(),
        "blueprints": public_blueprints(),
        "defaults": ResponseProfile().to_public_dict(),
    }


class GeneratePurposeRequest(BaseModel):
    #: P16: borrador actual del formulario, aunque no esté guardado.
    purpose: str | None = Field(default=None, max_length=2000)
    instructions: str | None = Field(default=None, max_length=16000)
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    profile: ResponseProfileConfig | None = None
    mode: str | None = Field(default=None, max_length=20)
    source_ids: list[UUID] | None = Field(default=None, max_length=50)
    tools: list[str] | None = Field(default=None, max_length=20)


class GenerateProfileRequest(BaseModel):
    preset: str | None = Field(default=None, max_length=40)
    instructions: str | None = Field(default=None, max_length=1000)


class PreviewRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    mock_evidence: str | None = Field(default=None, max_length=4000)
    #: Perfil temporal del preview. Si falta, se usa el guardado del agente.
    profile: ResponseProfileConfig | None = None


class CompareRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    profile_ids: list[str] = Field(min_length=2, max_length=4)
    mock_evidence: str | None = Field(default=None, max_length=4000)


async def _agent_config_context(
    request: Request,
    ctx,
    agent,
    *,
    source_ids_override: list[UUID] | None = None,
) -> object:
    """Contexto del configurador: sólo datos reales del agente (§31, §33)."""
    from src.intelligence.response.generator import context_from_agent

    source_kinds: list[str] = []
    source_titles: list[str] = []
    try:
        from src.api.deps import get_source_repo

        config = agent.config_json or {}
        source_ids = (
            list(source_ids_override)
            if source_ids_override is not None
            else list(config.get("source_ids") or [])
        )[:20]
        if source_ids:
            repo = get_source_repo()
            for raw_id in source_ids:
                try:
                    source = await repo.get_source(ctx.organization_id, UUID(str(raw_id)))
                except Exception as exc:  # noqa: BLE001 — una fuente ilegible no rompe el draft
                    logger.warning("source lookup failed for config draft", error=str(exc)[:150])
                    continue
                if source is None:
                    continue
                source_kinds.append(str(getattr(source, "source_type", "") or ""))
                source_titles.append(
                    str(getattr(source, "title", "") or getattr(source, "name", "") or "")[:80]
                )
    except Exception:  # noqa: BLE001
        source_kinds = []
        source_titles = []
    return context_from_agent(
        agent=agent,
        source_kinds=[item for item in source_kinds if item],
        source_titles=[item for item in source_titles if item],
    )


async def _generate_text(
    prompt: str, *, max_tokens: int = 400, temperature: float = 0.2
) -> str:
    """Generación corta para el configurador. Fail-soft: sin LLM, sin draft."""
    from src.api.deps import get_llm_provider
    from src.core.config import get_settings

    settings = get_settings()
    provider = get_llm_provider()
    model = getattr(settings, "LITELLM_DEFAULT_MODEL", None)
    response = await provider.generate(
        prompt=prompt,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return str(getattr(response, "content", "") or "")


@router.post("/{agent_id}/config/purpose", summary="Construir propósito con IA (P16)")
async def generate_agent_purpose(agent_id: str, body: GeneratePurposeRequest, request: Request):
    from src.intelligence.response.generator import (
        PURPOSE_MODE_AUTO,
        PURPOSE_MODES,
        build_purpose_prompt,
        build_purpose_repair_prompt,
        effective_purpose_mode,
        evaluate_purpose_intent,
        parse_purpose_response,
        suggest_purpose_intent,
    )
    from src.intelligence.response.profile import profile_from_config
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:write")
    agent = await _get_owned_agent(ctx, agent_id)
    context = await _agent_config_context(
        request,
        ctx,
        agent,
        source_ids_override=body.source_ids,
    )
    profile = (
        profile_from_config(
            {"response_profile": body.profile.model_dump(exclude_none=True)}
        )
        if body.profile is not None
        else context.profile
    )
    requested_mode = str(body.mode or PURPOSE_MODE_AUTO).strip().lower()
    mode = requested_mode if requested_mode in PURPOSE_MODES else PURPOSE_MODE_AUTO
    # Compatibilidad legacy: antes `instructions` transportaba el propósito.
    legacy_purpose = body.purpose is None and body.instructions is not None
    context = replace(
        context,
        name=body.name if body.name is not None else context.name,
        description=body.description if body.description is not None else context.description,
        purpose=(
            body.purpose
            if body.purpose is not None
            else (body.instructions if legacy_purpose else context.purpose)
        ),
        instructions="" if legacy_purpose else (
            body.instructions if body.instructions is not None else context.instructions
        ),
        profile=profile,
        profile_audience=profile.audience if profile is not None else context.profile_audience,
        tools=tuple(body.tools) if body.tools is not None else context.tools,
        mode=mode,
    )
    mode = effective_purpose_mode(context)
    warnings: list[str] = []
    raw = ""
    try:
        raw = await _generate_text(
            build_purpose_prompt(context, mode=mode),
            max_tokens=3000,
            temperature=0.0,
        )
    except Exception as exc:  # noqa: BLE001 — nunca sustituir la intención por 503
        warnings.append(f"generation_unavailable:{type(exc).__name__}")
        logger.warning(
            "agent purpose generation unavailable; preserving input",
            agent_id=agent_id,
            organization_id=str(ctx.organization_id),
            error=str(exc)[:200],
        )

    if raw.strip():
        draft = parse_purpose_response(raw, context)
    else:
        warnings.append("empty_model_output")
        draft = suggest_purpose_intent(context, mode=mode)
    quality = evaluate_purpose_intent(draft, context)
    source = draft.generation_source

    # Reparación acotada: una sola pasada si el incumplimiento es material.
    if not quality.passed and raw.strip() and draft.purpose:
        try:
            repaired_raw = await _generate_text(
                build_purpose_repair_prompt(context, draft, quality.issues),
                max_tokens=3000,
                temperature=0.1,
            )
            repaired = parse_purpose_response(repaired_raw, context)
            repaired_quality = evaluate_purpose_intent(repaired, context)
            if repaired_quality.score >= quality.score and repaired.purpose:
                repaired_quality.repaired = True
                draft, quality, source = repaired, repaired_quality, "model_repaired"
        except Exception as exc:  # noqa: BLE001 — la reparación no rompe el borrador
            warnings.append(f"repair_unavailable:{type(exc).__name__}")

    # Fallo definitivo: conservar la entrada original, no inventar un propósito.
    if not quality.passed and any(
        str(value or "").strip()
        for value in (context.purpose, context.description, context.name)
    ):
        original = suggest_purpose_intent(context, mode=mode)
        compatibility_warnings: list[str] = []
        if quality.unnecessary_tools or "capability_grounding" in quality.issues:
            compatibility_warnings.append("mentions_unconfigured_capability")
        original.warnings = list(dict.fromkeys([
            "quality_failed_preserved_original",
            *quality.issues[:8],
            *compatibility_warnings,
            *warnings,
        ]))
        draft = original
        quality = evaluate_purpose_intent(draft, context)
        source = "rules"

    warnings = list(dict.fromkeys([
        *draft.warnings,
        *quality.issues,
        *warnings,
    ]))[:12]
    if source == "rules":
        logger.warning(
            "agent purpose preserved input after generation/quality failure",
            agent_id=agent_id,
            organization_id=str(ctx.organization_id),
            issues=quality.issues[:8],
            raw_excerpt=str(raw or "")[:300],
        )
    return {
        # Compatibilidad con clientes que esperan una cadena.
        "draft": draft.purpose,
        "purpose": draft.purpose,
        "additional_instructions": draft.additional_instructions,
        "intent_summary": draft.intent_summary,
        "persona": draft.persona.model_dump(),
        "behavioral_objectives": list(draft.behavioral_objectives),
        "knowledge_boundaries": list(draft.knowledge_boundaries),
        "warnings": warnings,
        "source": source,
        "generation_source": draft.generation_source,
        "mode": mode,
        "input_purpose": str(context.purpose or ""),
        "quality": quality.to_public_dict(),
        "grounded_in": {
            "sources": list(context.source_titles)[:6],
            "source_kinds": list(context.source_kinds)[:6],
            "capabilities": sorted(context.capabilities),
            "profile_id": profile.profile_id if profile is not None else "",
            "profile_audience": profile.audience if profile is not None else "",
        },
        "saved": False,
    }


@router.post(
    "/{agent_id}/config/response-profile",
    summary="Generar perfil de respuesta con IA (§30, §32)",
)
async def generate_response_profile(
    agent_id: str, body: GenerateProfileRequest, request: Request
):
    from src.intelligence.response.generator import (
        build_profile_prompt,
        parse_profile_response,
        suggest_profile,
    )
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:write")
    agent = await _get_owned_agent(ctx, agent_id)
    context = await _agent_config_context(request, ctx, agent)
    prompt = build_profile_prompt(context)
    try:
        raw = await _generate_text(prompt, max_tokens=400)
    except Exception:  # noqa: BLE001 — fallback determinista, no error
        raw = ""
    if raw.strip():
        suggestion = parse_profile_response(raw, context)
    else:
        suggestion = suggest_profile(
            context=context,
            preset=body.preset,
            instructions=str(body.instructions or ""),
        )
    return {"draft": suggestion, "saved": False}


class SaveProfileRequest(BaseModel):
    profile: ResponseProfileConfig


@router.put(
    "/{agent_id}/config/response-profile",
    summary="Guardar sólo el perfil de respuesta, sin tocar el resto del config",
)
async def save_response_profile(agent_id: str, body: SaveProfileRequest, request: Request):
    from src.intelligence.response.profile import profile_from_config
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:write")
    agent = await _get_owned_agent(ctx, agent_id)
    resolved = profile_from_config(
        {"response_profile": body.profile.model_dump(exclude_none=True)}
    )
    config = dict(agent.config_json or {})
    config["response_profile"] = resolved.to_public_dict()
    from src.api.deps import get_agent_repo

    updated = await get_agent_repo().update_agent(
        ctx.organization_id, agent.id, config_json=config
    )
    await _audit().write(
        ctx,
        "agent.response_profile.updated",
        "agent",
        agent.id,
        metadata={"profile_id": resolved.profile_id, "version": resolved.profile_version},
    )
    return _agent_response(updated)


@router.post(
    "/{agent_id}/config/preview",
    summary="Preview de respuesta con conocimiento simulado (§34)",
)
async def preview_agent_response(agent_id: str, body: PreviewRequest, request: Request):
    """Muestra cómo respondería el agente. No ejecuta tools reales."""
    from src.intelligence.response.contract import prompt_block
    from src.intelligence.response.identity import identity_from_agent_config
    from src.intelligence.response.profile import profile_from_config
    from src.intelligence.response.quality import evaluate_response_quality
    from src.intelligence.response.wiring import compose_for_request
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:write")
    agent = await _get_owned_agent(ctx, agent_id)
    identity = identity_from_agent_config(
        agent.config_json,
        name=str(getattr(agent, "name", "") or ""),
        system_prompt=str(getattr(agent, "system_prompt", "") or ""),
    )
    temporary_profile = (
        profile_from_config(
            {"response_profile": body.profile.model_dump(exclude_none=True)}
        )
        if body.profile is not None
        else None
    )
    plan = await compose_for_request(
        question=body.question,
        config_json=agent.config_json,
        profile=temporary_profile,
        identity=identity,
        mode="rules",
        request_id=None,
        organization_id=ctx.organization_id,
    )
    mock = (
        str(body.mock_evidence or "").strip()
        or "[MOCK] Sin evidencia real: el preview muestra únicamente la forma y el estilo "
        "configurados. No hay hechos de dominio en esta respuesta."
    )
    shape = (
        prompt_block(plan.contract, profile=plan.profile, identity=plan.identity)
        if plan.contract is not None
        else ""
    )
    prompt = (
        f"PREGUNTA DEL USUARIO:\n{body.question}\n\n"
        f"EVIDENCIA DISPONIBLE (simulada, no son hechos reales):\n{mock}\n\n"
        "Responde la pregunta siguiendo la forma y el estilo indicados. "
        "Si la evidencia simulada no alcanza para responder, dilo."
    )
    try:
        draft = await _generate_text(
            f"{shape}\n\n{prompt}" if shape else prompt, max_tokens=600
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"No se pudo generar el preview: {exc}") from exc
    contract_public = (
        plan.contract.to_public_dict() if plan.contract is not None else None
    )
    quality = evaluate_response_quality(
        answer=draft,
        contract=contract_public,
        intent=(plan.user_intent.to_public_dict() if plan.user_intent else None),
        identity=(plan.identity.to_public_dict() if plan.identity else None),
    ).to_public_dict()
    return {
        "preview": draft,
        "simulated_evidence": True,
        "tools_executed": False,
        "profile_source": "temporary" if temporary_profile is not None else "saved",
        "profile": plan.profile.to_public_dict() if plan.profile is not None else None,
        "identity": plan.identity.to_public_dict() if plan.identity else None,
        "intent": plan.user_intent.to_public_dict() if plan.user_intent else None,
        "response_contract": contract_public,
        "quality": quality,
        "validation": {
            "contract_present": plan.contract is not None,
            "style_degraded": bool(plan.style_degraded),
            "style_degradation_reason": plan.style_degradation_reason,
            "semantic_evaluated": False,
        },
        "mode": plan.mode,
        "source": plan.source,
    }


@router.post(
    "/{agent_id}/config/compare",
    summary="Comparar perfiles de respuesta con la misma pregunta y evidencia",
)
async def compare_agent_profiles(agent_id: str, body: CompareRequest, request: Request):
    """A/B simulado: mismo modelo, pregunta y evidencia; sin herramientas reales."""
    import asyncio

    from src.intelligence.response.contract import prompt_block
    from src.intelligence.response.identity import identity_from_agent_config
    from src.intelligence.response.profile import RESPONSE_PROFILE_PRESETS
    from src.intelligence.response.quality import evaluate_response_quality
    from src.intelligence.response.wiring import compose_for_request
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:write")
    agent = await _get_owned_agent(ctx, agent_id)
    identity = identity_from_agent_config(
        agent.config_json,
        name=str(getattr(agent, "name", "") or ""),
        system_prompt=str(getattr(agent, "system_prompt", "") or ""),
    )
    unknown = [item for item in body.profile_ids if item not in RESPONSE_PROFILE_PRESETS]
    if unknown:
        raise HTTPException(400, {"error_code": "unknown_profile", "profiles": unknown})
    mock = (
        str(body.mock_evidence or "").strip()
        or "[MOCK] Misma evidencia simulada para todas las variantes. "
        "No hay hechos de dominio ni ejecución de herramientas."
    )

    async def run_one(profile_id: str) -> dict[str, Any]:
        profile = RESPONSE_PROFILE_PRESETS[profile_id]
        plan = await compose_for_request(
            question=body.question,
            config_json=agent.config_json,
            profile=profile,
            identity=identity,
            mode="rules",
            request_id=None,
            organization_id=ctx.organization_id,
        )
        shape = (
            prompt_block(plan.contract, profile=plan.profile, identity=plan.identity)
            if plan.contract is not None
            else ""
        )
        prompt = (
            f"PREGUNTA DEL USUARIO:\n{body.question}\n\n"
            f"EVIDENCIA DISPONIBLE (simulada, no son hechos reales):\n{mock}\n\n"
            "Responde siguiendo la forma y el estilo indicados. "
            "Si la evidencia no alcanza, dilo."
        )
        try:
            answer = await _generate_text(
                f"{shape}\n\n{prompt}" if shape else prompt,
                max_tokens=600,
                temperature=0.0,
            )
            error = ""
        except Exception as exc:  # noqa: BLE001 — una variante no tumba la comparación
            answer = ""
            error = str(exc)[:200]
        contract = plan.contract
        contract_public = contract.to_public_dict() if contract is not None else None
        quality = evaluate_response_quality(
            answer=answer,
            contract=contract_public,
            intent=(plan.user_intent.to_public_dict() if plan.user_intent else None),
            identity=(plan.identity.to_public_dict() if plan.identity else None),
        ).to_public_dict()
        return {
            "profile_id": profile_id,
            "profile": plan.profile.to_public_dict() if plan.profile is not None else None,
            "identity": plan.identity.to_public_dict() if plan.identity else None,
            "intent": plan.user_intent.to_public_dict() if plan.user_intent else None,
            "answer": answer,
            "error": error,
            "chars": len(answer),
            "sections": list(contract.sections) if contract is not None else [],
            "formatting": dict(contract.formatting) if contract is not None else {},
            "evidence": dict(contract.evidence) if contract is not None else {},
            "response_contract": contract_public,
            "quality": quality,
            "validation": {
                "contract_present": contract is not None,
                "style_degraded": bool(plan.style_degraded),
                "style_degradation_reason": plan.style_degradation_reason,
                "semantic_evaluated": False,
            },
        }

    results = await asyncio.gather(*(run_one(item) for item in body.profile_ids))
    return {
        "question": body.question,
        "identity": identity.to_public_dict(),
        "simulated_evidence": True,
        "tools_executed": False,
        "same_evidence": True,
        "results": results,
    }


async def _get_owned_agent(ctx, agent_id: str):
    from src.api.deps import get_agent_repo

    try:
        aid = UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "agent_id must be a valid UUID")
    agent = await get_agent_repo().get_agent(ctx.organization_id, aid)
    if agent is None:
        raise HTTPException(404, "Agent not found")
    return agent


@router.get("/{agent_id}/readiness", summary="Readiness score del agente (0-100)")
async def agent_readiness(
    agent_id: str,
    request: Request,
    repo: AgentRepository = Depends(get_agent_repo),
):
    from src.platform.agents.readiness import (
        READY_VERSION_STATUSES,
        AgentReadinessService,
    )
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:read")
    try:
        aid = UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "agent_id must be a valid UUID")
    agent = await repo.get_agent(ctx.organization_id, aid)
    if agent is None:
        raise HTTPException(404, "Agent not found")

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        versions = (
            await session.execute(
                text(
                    "SELECT status FROM agent_versions WHERE agent_id = :aid "
                    "AND organization_id = :oid"
                ),
                {"aid": aid, "oid": ctx.organization_id},
            )
        ).fetchall()
        deployment = (
            await session.execute(
                text(
                    "SELECT 1 FROM deployments WHERE agent_id = :aid "
                    "AND organization_id = :oid AND status = 'healthy' LIMIT 1"
                ),
                {"aid": aid, "oid": ctx.organization_id},
            )
        ).fetchone()
        _kb_count = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM knowledge_bases WHERE organization_id = :oid"
                ),
                {"oid": ctx.organization_id},
            )
        ).scalar()
        # El ciclo de vida de kb_sources (migración 025) usa
        # created/connected/discovering/profiled/ready/ingesting/indexed/error;
        # 'active' quedó obsoleto. Cuenta cualquier fuente que no esté en error.
        source_count = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM kb_sources WHERE organization_id = :oid "
                    "AND status <> 'error'"
                ),
                {"oid": ctx.organization_id},
            )
        ).scalar()
        eval_count = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM eval_datasets WHERE organization_id = :oid"
                ),
                {"oid": ctx.organization_id},
            )
        ).scalar()
    finally:
        await session.close()

    cfg = agent.config_json or {}
    kb_ids = cfg.get("knowledge_base_ids") or []
    source_ids = cfg.get("source_ids") or []
    result = AgentReadinessService.compute(
        agent,
        has_eval_dataset=int(eval_count or 0) > 0,
        has_healthy_deployment=deployment is not None,
        has_ready_version=any(v.status in READY_VERSION_STATUSES for v in versions),
        knowledge_configured=len(source_ids) > 0 or len(kb_ids) > 0,
        has_data_source=int(source_count or 0) > 0,
        sql_expert_enabled=True,
    )
    return {"agent_id": str(aid), "score": result.score, "items": result.checklist()}


@router.get(
    "/{agent_id}/intelligence-readiness",
    summary="Intelligence Readiness del agente (FASE 25, 9 dimensiones)",
)
async def agent_intelligence_readiness(
    agent_id: str,
    request: Request,
    repo: AgentRepository = Depends(get_agent_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:read")
    try:
        aid = UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "agent_id must be a valid UUID")
    agent = await repo.get_agent(ctx.organization_id, aid)
    if agent is None:
        raise HTTPException(404, "Agent not found")

    from src.api.deps import get_agent_readiness_service

    result = await get_agent_readiness_service().compute(
        ctx.organization_id, aid, agent_config=agent.config_json
    )
    return {
        "agent_id": str(aid),
        "name": agent.name,
        "overall": result["overall"],
        "score": result["score"],
        "dimensions": result["dimensions"],
    }


@router.post("/{agent_id}/archive", summary="Archivar agente")
async def archive_agent(
    agent_id: str,
    request: Request,
    repo: AgentRepository = Depends(get_agent_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:write")
    try:
        aid = UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "agent_id must be a valid UUID")
    agent = await repo.get_agent(ctx.organization_id, aid)
    if agent is None:
        raise HTTPException(404, "Agent not found")
    updated = await repo.update_agent(ctx.organization_id, aid, status="archived")
    await _audit().write(
        ctx, "agent.archived", "agent", aid, metadata={"name": agent.name}
    )
    return _agent_response(updated)


async def _require_own_workspace(ctx, workspace_id: UUID) -> None:
    from src.api.deps import get_workspace_repo
    from src.platform.workspaces.service import require_own_workspace

    try:
        await require_own_workspace(get_workspace_repo(), ctx.organization_id, workspace_id)
    except ValueError:
        raise HTTPException(404, "Workspace not found in this organization") from None


async def _require_own_project(ctx, project_id: UUID) -> None:
    from src.api.deps import get_project_repo

    project = await get_project_repo().get_project(ctx.organization_id, project_id)
    if project is None:
        raise HTTPException(404, "Project not found in this organization")


async def _require_own_kbs(ctx, knowledge_base_ids: list[UUID]) -> None:
    from src.api.deps import get_kb_repo

    repo = get_kb_repo()
    for kb_id in knowledge_base_ids:
        kb = await repo.get_kb(ctx.organization_id, kb_id)
        if kb is None:
            raise HTTPException(
                404, "Knowledge base not found in this organization"
            )


async def _require_own_sources(ctx, source_ids: list[UUID]) -> list:
    from src.api.deps import get_source_repo

    repo = get_source_repo()
    sources = []
    for source_id in source_ids:
        source = await repo.get_source(ctx.organization_id, source_id)
        if source is None:
            raise HTTPException(404, "Source not found in this organization")
        sources.append(source)
    return sources


async def _classify_source_ids(ctx, source_ids: list[UUID]) -> tuple[list, list[UUID], list[UUID]]:
    """Separa las fuentes del agente en vigentes, inexistentes y de otra organización.

    Un id **inexistente** es configuración vieja (la fuente se borró o se volvió a
    importar): se descarta con aviso, nunca se bloquea el guardado. Un id de **otra
    organización** sí es un 404: es aislamiento, no configuración.
    """
    from sqlalchemy import bindparam
    from sqlalchemy import text as sql_text

    from src.api.deps import get_source_repo
    from src.infrastructure.postgres.session import get_async_session

    repo = get_source_repo()
    found: list = []
    missing: list[UUID] = []
    foreign: list[UUID] = []
    pending: list[UUID] = []
    for source_id in source_ids:
        source = await repo.get_source(ctx.organization_id, source_id)
        if source is not None:
            found.append(source)
        else:
            pending.append(source_id)
    if not pending:
        return found, missing, foreign
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                sql_text(
                    "SELECT id::text AS id, organization_id::text AS organization_id "
                    "FROM kb_sources WHERE id::text IN :ids"
                ).bindparams(bindparam("ids", expanding=True)),
                {"ids": [str(item) for item in pending]},
            )
        ).fetchall()
    finally:
        # La función posee la sesión: se cierra siempre (antes quedaba abierta).
        await session.close()
    owners = {str(row[0]): str(row[1]) for row in rows}
    for source_id in pending:
        owner = owners.get(str(source_id))
        if owner is None:
            missing.append(source_id)
        elif owner != str(ctx.organization_id):
            foreign.append(source_id)
        else:
            # Existe y es de la organización, pero el repo no la devolvió.
            missing.append(source_id)
    return found, missing, foreign


async def _apply_knowledge_scope(
    ctx, config: AgentConfig
) -> tuple[AgentConfig, list[str]]:
    """Normaliza `knowledge_scope` (C7): ownership legacy y fail-soft.

    Los ids inválidos se descartan campo a campo en el dominio. Las fuentes y
    bases del scope se validan con el mismo criterio que el scope legacy: una
    fuente de otra organización es 404; una inexistente se descarta con aviso.
    """
    from collections.abc import Mapping

    from src.core.domain.knowledge_scope import from_config

    raw = config.knowledge_scope
    if raw is None:
        return config, []
    warnings: list[str] = []
    if not isinstance(raw, Mapping) or not raw:
        return config.model_copy(update={"knowledge_scope": None}), warnings
    scope = from_config({"knowledge_scope": raw})
    if scope.is_empty:
        logger.warning(
            "agent knowledge_scope invalid; dropped",
            organization_id=str(ctx.organization_id),
            fields=sorted(str(key) for key in raw)[:10],
        )
        warnings.append(
            "Se descartó el alcance de conocimiento: no contenía fuentes, bases "
            "ni valores válidos."
        )
        return config.model_copy(update={"knowledge_scope": None}), warnings
    if scope.source_ids:
        sources, missing, foreign = await _classify_source_ids(ctx, list(scope.source_ids))
        if foreign:
            raise HTTPException(
                404,
                "Source not found in this organization: "
                + ", ".join(str(item) for item in foreign[:5]),
            )
        if missing:
            logger.warning(
                "agent knowledge_scope referenced unknown sources; dropped",
                organization_id=str(ctx.organization_id),
                dropped=[str(item) for item in missing][:10],
                dropped_count=len(missing),
            )
            warnings.append(
                f"Se quitaron {len(missing)} fuente(s) del alcance que ya no existen "
                "en la organización. Vuelve a elegirlas en Fuentes."
            )
        scope = replace(scope, source_ids=tuple(source.id for source in sources))
    if scope.knowledge_base_ids:
        await _require_own_kbs(ctx, list(scope.knowledge_base_ids))
    if scope.is_empty:
        return config.model_copy(update={"knowledge_scope": None}), warnings
    return config.model_copy(update={"knowledge_scope": scope.to_public_dict()}), warnings


async def _apply_source_config(ctx, config: AgentConfig) -> tuple[AgentConfig, list[str]]:
    """Config con las fuentes vigentes + avisos de lo que se descartó."""
    config, warnings = await _apply_knowledge_scope(ctx, config)
    if config.source_ids:
        sources, missing, foreign = await _classify_source_ids(ctx, config.source_ids)
        if foreign:
            raise HTTPException(
                404,
                "Source not found in this organization: "
                + ", ".join(str(item) for item in foreign[:5]),
            )
        derived: list[UUID] = []
        seen: set[UUID] = set()
        for source in sources:
            kb_id = source.knowledge_base_id
            if kb_id and kb_id not in seen:
                seen.add(kb_id)
                derived.append(kb_id)
        if missing:
            logger.warning(
                "agent config referenced unknown sources; dropped",
                organization_id=str(ctx.organization_id),
                dropped=[str(item) for item in missing][:10],
                dropped_count=len(missing),
            )
            warnings.append(
                f"Se quitaron {len(missing)} fuente(s) que ya no existen en la "
                "organización. Vuelve a elegirlas en Fuentes."
            )
        kept = [source.id for source in sources]
        return (
            config.model_copy(update={"source_ids": kept, "knowledge_base_ids": derived}),
            warnings,
        )
    if config.knowledge_base_ids:
        await _require_own_kbs(ctx, config.knowledge_base_ids)
    return config, warnings

# ---------------------------------------------------------------------------
# Marketplace & Sharing (tenant)
# ---------------------------------------------------------------------------
@router.post("/{agent_id}/clone", summary="Clonar agente en la organización")
async def clone_agent_endpoint(agent_id: str, request: Request):
    from src.platform.marketplace.marketplace import clone_agent
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:write")
    try:
        aid = UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "agent_id must be a valid UUID")
    result = await clone_agent(ctx.organization_id, aid)
    if result["status"] == "agent_not_found":
        raise HTTPException(404, "Agent not found")
    return result


class ShareLinkIn(BaseModel):
    expires_days: int | None = Field(default=None, ge=1, le=365)
    max_uses: int | None = Field(default=None, ge=1, le=10000)


@router.post("/{agent_id}/share", summary="Crear link público de compartición")
async def create_share_link_endpoint(agent_id: str, body: ShareLinkIn, request: Request):
    from src.platform.marketplace.marketplace import create_share_link
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:read")
    try:
        aid = UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "agent_id must be a valid UUID")
    result = await create_share_link(
        ctx.organization_id, aid, expires_days=body.expires_days, max_uses=body.max_uses
    )
    if result["status"] == "agent_not_found":
        raise HTTPException(404, "Agent not found")
    return result


@router.get("/{agent_id}/share-links", summary="Links de compartición del agente")
async def list_share_links_endpoint(agent_id: str, request: Request):
    from src.platform.marketplace.marketplace import list_share_links
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:read")
    try:
        aid = UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "agent_id must be a valid UUID")
    links = await list_share_links(ctx.organization_id, aid)
    return {"links": links, "count": len(links)}


@router.delete("/{agent_id}/share-links/{link_id}", summary="Revocar link de compartición")
async def revoke_share_link_endpoint(agent_id: str, link_id: str, request: Request):
    from src.platform.marketplace.marketplace import revoke_share_link
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:read")
    ok = await revoke_share_link(ctx.organization_id, UUID(link_id))
    if not ok:
        raise HTTPException(404, "Link not found")
    return {"status": "revoked"}
