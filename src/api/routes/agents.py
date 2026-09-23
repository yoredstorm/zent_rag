# =============================================================================
# Agents Routes — CRUD de agentes (organization-scoped, project opcional)
# =============================================================================
from __future__ import annotations

from dataclasses import replace
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


class AgentConfig(BaseModel):
    purpose: str | None = Field(default=None, max_length=2000)
    temperature: float = Field(default=0.2, ge=0, le=1)
    tone: str = Field(default="professional", pattern="^(professional|friendly|concise)$")
    knowledge_base_ids: list[UUID] = Field(default_factory=list, max_length=50)
    source_ids: list[UUID] = Field(default_factory=list)
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


def _agent_response(agent) -> dict:
    return {
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
        "config": parse_agent_config(agent.config_json),
    }


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
    if body.config is not None:
        config = await _apply_source_config(ctx, body.config)
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
                    "Abrilo para editarlo o elegí otro nombre."
                ),
            },
        ) from exc
    await _audit().write(ctx, "agent.created", "agent", agent.id, metadata={"name": agent.name})
    try:
        from src.platform.onboardingv2.onboarding import sync_progress

        await sync_progress(ctx.organization_id)
    except Exception:  # noqa: BLE001
        pass
    return _agent_response(agent)


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
    if "config" in fields:
        if body.config is not None:
            applied = await _apply_source_config(ctx, body.config)
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
    return _agent_response(agent)


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
    from src.intelligence.response.blueprints import public_blueprints
    from src.intelligence.response.profile import public_presets

    return {
        "presets": public_presets(),
        "blueprints": public_blueprints(),
        "defaults": ResponseProfileConfig().model_dump(),
    }


class GeneratePurposeRequest(BaseModel):
    instructions: str | None = Field(default=None, max_length=1000)


class GenerateProfileRequest(BaseModel):
    preset: str | None = Field(default=None, max_length=40)
    instructions: str | None = Field(default=None, max_length=1000)


class PreviewRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    mock_evidence: str | None = Field(default=None, max_length=4000)


async def _agent_config_context(request: Request, ctx, agent) -> object:
    """Contexto del configurador: sólo datos reales del agente (§31, §33)."""
    from src.intelligence.response.generator import context_from_agent

    source_kinds: list[str] = []
    source_titles: list[str] = []
    try:
        from src.api.deps import get_source_repo

        config = agent.config_json or {}
        source_ids = list(config.get("source_ids") or [])[:20]
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


async def _generate_text(prompt: str, *, max_tokens: int = 400) -> str:
    """Generación corta para el configurador. Fail-soft: sin LLM, sin draft."""
    from src.api.deps import get_llm_provider
    from src.core.config import get_settings

    settings = get_settings()
    provider = get_llm_provider()
    model = getattr(settings, "LITELLM_DEFAULT_MODEL", None)
    response = await provider.generate(
        prompt=prompt, model=model, max_tokens=max_tokens, temperature=0.2
    )
    return str(getattr(response, "content", "") or "")


@router.post("/{agent_id}/config/purpose", summary="Generar propósito con IA (§30-§31)")
async def generate_agent_purpose(agent_id: str, body: GeneratePurposeRequest, request: Request):
    from src.intelligence.response.generator import (
        build_purpose_prompt,
        validate_purpose,
    )
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:write")
    agent = await _get_owned_agent(ctx, agent_id)
    context = await _agent_config_context(request, ctx, agent)
    if body.instructions:
        context = replace(context, purpose=str(body.instructions)[:500])
    prompt = build_purpose_prompt(context)
    try:
        raw = await _generate_text(prompt, max_tokens=300)
    except Exception as exc:  # noqa: BLE001 — el usuario puede escribirlo a mano
        raise HTTPException(503, f"No se pudo generar el propósito: {exc}") from exc
    purpose, warnings = validate_purpose(raw, context)
    if not purpose:
        raise HTTPException(502, "El borrador no pasó la validación (mencionaba capacidades no configuradas).")
    return {
        "draft": purpose,
        "warnings": warnings,
        "grounded_in": {
            "sources": list(context.source_titles)[:6],
            "source_kinds": list(context.source_kinds)[:6],
            "tools": list(context.tools)[:10],
            "capabilities": sorted(context.capabilities),
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


@router.post(
    "/{agent_id}/config/preview",
    summary="Preview de respuesta con conocimiento simulado (§34)",
)
async def preview_agent_response(agent_id: str, body: PreviewRequest, request: Request):
    """Muestra cómo respondería el agente. No ejecuta tools reales."""
    from src.intelligence.response.contract import prompt_block
    from src.intelligence.response.wiring import compose_for_request
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:write")
    agent = await _get_owned_agent(ctx, agent_id)
    plan = await compose_for_request(
        question=body.question,
        config_json=agent.config_json,
        mode="rules",
        request_id=None,
        organization_id=ctx.organization_id,
    )
    mock = (
        str(body.mock_evidence or "").strip()
        or "[MOCK] Sin evidencia real: el preview muestra únicamente la forma y el estilo "
        "configurados. No hay hechos de dominio en esta respuesta."
    )
    shape = prompt_block(plan.contract) if plan.contract is not None else ""
    prompt = (
        f"PREGUNTA DEL USUARIO:\n{body.question}\n\n"
        f"EVIDENCIA DISPONIBLE (simulada, no son hechos reales):\n{mock}\n\n"
        "Respondé la pregunta siguiendo la forma y el estilo indicados. "
        "Si la evidencia simulada no alcanza para responder, decilo."
    )
    try:
        draft = await _generate_text(
            f"{shape}\n\n{prompt}" if shape else prompt, max_tokens=600
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"No se pudo generar el preview: {exc}") from exc
    return {
        "preview": draft,
        "simulated_evidence": True,
        "response_contract": plan.contract.to_public_dict() if plan.contract is not None else None,
        "mode": plan.mode,
        "source": plan.source,
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
        source_count = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM kb_sources WHERE organization_id = :oid "
                    "AND status = 'active'"
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


async def _apply_source_config(ctx, config: AgentConfig) -> AgentConfig:
    if config.source_ids:
        sources = await _require_own_sources(ctx, config.source_ids)
        derived: list[UUID] = []
        seen: set[UUID] = set()
        for source in sources:
            kb_id = source.knowledge_base_id
            if kb_id and kb_id not in seen:
                seen.add(kb_id)
                derived.append(kb_id)
        return config.model_copy(update={"knowledge_base_ids": derived})
    if config.knowledge_base_ids:
        await _require_own_kbs(ctx, config.knowledge_base_ids)
    return config

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
