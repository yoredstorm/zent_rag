# =============================================================================
# Phase 32B — Marketplace API
# Catálogo, instalaciones, credenciales (SecretStore), acciones (runtime
# único: workflow/agente/manual), evidencia y uso.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)
# Prefix propio: /api/v1/marketplace está ocupado por el marketplace de
# listings (ecosystem.py). Este es el Marketplace de CAPACIDADES (Phase 32B).
router = APIRouter(prefix="/api/v1/integrations", tags=["Marketplace"])


async def _workspace_id(request: Request) -> UUID | None:
    from src.platform.workspaces.context import (
        get_active_workspace_id,
        workspace_header_or_none,
    )

    ctx = getattr(request.state, "tenant_context", None)
    if ctx is None:
        return None
    header = workspace_header_or_none(request)
    if header is not None:
        return header
    try:
        active = await get_active_workspace_id(ctx.organization_id, ctx.user_id)
        if active is not None:
            return active
    except Exception:  # noqa: BLE001
        pass
    return None


def _require(request: Request, permission: str):
    from src.platform.rbac.policy import require_permission

    return require_permission(request, permission)


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------
@router.get("/catalog", summary="Catálogo de integraciones publicadas")
async def marketplace_catalog(request: Request, category: str | None = None):
    ctx = _require(request, "marketplace:read")
    from src.platform.marketplace.catalog import list_catalog

    return await list_catalog(category=category)


@router.get("/catalog/{slug}", summary="Detalle de integración (manifest + acciones)")
async def marketplace_catalog_detail(slug: str, request: Request):
    _require(request, "marketplace:read")
    from src.platform.marketplace.catalog import get_manifest

    result = await get_manifest(slug)
    if result is None:
        raise HTTPException(404, "Integración no encontrada")
    return result


@router.post("/catalog", summary="Registrar manifest (publishing DRAFT→…)", status_code=201)
async def marketplace_catalog_register(body: dict, request: Request):
    ctx = _require(request, "marketplace:manage")
    from src.platform.marketplace.catalog import register_manifest
    from src.platform.marketplace.models import ManifestValidationError

    try:
        return await register_manifest(body, ctx.user_id)
    except ManifestValidationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.patch("/actions/{action_id}/status", summary="Deprecar/activar acción (versionado)")
async def marketplace_action_status(action_id: str, body: ActionStatusIn, request: Request):
    _require(request, "marketplace:manage")
    from src.platform.marketplace.catalog import set_action_status
    from src.platform.marketplace.models import ManifestValidationError

    try:
        ok = await set_action_status(action_id, body.status)
    except ManifestValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not ok:
        raise HTTPException(404, "Acción no encontrada")
    return {"action_id": action_id, "status": body.status}


# ---------------------------------------------------------------------------
# Instalaciones
# ---------------------------------------------------------------------------
@router.get("/installs", summary="Integraciones instaladas")
async def marketplace_installs(request: Request):
    ctx = _require(request, "marketplace:read")
    from src.platform.marketplace.runtime import list_installs

    return await list_installs(ctx.organization_id, await _workspace_id(request))


@router.post("/installs", summary="Instalar integración del catálogo", status_code=201)
async def marketplace_install(body: InstallIn, request: Request):
    ctx = _require(request, "marketplace:install")
    from src.platform.marketplace.runtime import (
        MarketplaceError,
        PurposeRequiredError,
        install_integration,
    )

    try:
        result = await install_integration(
            ctx.organization_id,
            body.integration_slug,
            workspace_id=await _workspace_id(request),
            created_by=ctx.user_id,
            purpose=body.purpose,
            legal_basis_reference=body.legal_basis_reference,
        )
    except PurposeRequiredError as exc:
        raise HTTPException(422, str(exc)) from exc
    except MarketplaceError as exc:
        raise HTTPException(404, str(exc)) from exc
    return result


@router.get("/installs/{install_id}", summary="Detalle de instalación")
async def marketplace_install_detail(install_id: str, request: Request):
    ctx = _require(request, "marketplace:read")
    from src.platform.marketplace.runtime import get_install

    result = await get_install(ctx.organization_id, UUID(install_id))
    if result is None:
        raise HTTPException(404, "Instalación no encontrada")
    return result


@router.patch("/installs/{install_id}", summary="Configurar instalación")
async def marketplace_install_update(install_id: str, body: InstallUpdateIn, request: Request):
    ctx = _require(request, "marketplace:manage")
    from src.platform.marketplace.runtime import MarketplaceError, update_install

    try:
        result = await update_install(
            ctx.organization_id,
            UUID(install_id),
            enabled_actions=body.enabled_actions,
            auto_use_policy=body.auto_use_policy,
            spend_limit=body.spend_limit,
            purpose=body.purpose,
            legal_basis_reference=body.legal_basis_reference,
            status=body.status,
        )
    except MarketplaceError as exc:
        raise HTTPException(400, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Instalación no encontrada")
    return result


@router.delete("/installs/{install_id}", summary="Desinstalar")
async def marketplace_install_delete(install_id: str, request: Request):
    ctx = _require(request, "marketplace:manage")
    from src.platform.marketplace.runtime import delete_install

    if not await delete_install(ctx.organization_id, UUID(install_id)):
        raise HTTPException(404, "Instalación no encontrada")
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Credenciales (SecretStore — nunca expuestas)
# ---------------------------------------------------------------------------
@router.post("/installs/{install_id}/credentials", summary="Conectar credenciales (SecretStore)")
async def marketplace_install_credentials(install_id: str, body: CredentialsIn, request: Request):
    ctx = _require(request, "integration_credentials:manage")
    from src.platform.marketplace.runtime import MarketplaceError, set_credentials

    # Sanidad: nunca aceptar valores con estructura de "secreto entero".
    allowed_keys = ("api_key", "oauth_token", "client_cert_pem", "endpoint_base_url",
                    "base_url", "headers", "client_id", "client_secret")
    secrets = {k: v for k, v in (body.secrets or {}).items() if k in allowed_keys}
    try:
        return await set_credentials(
            ctx.organization_id,
            UUID(install_id),
            body.auth_mode,
            body.cred_type,
            secrets,
            workspace_id=await _workspace_id(request),
            provider_account_id=body.provider_account_id,
        )
    except MarketplaceError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/installs/{install_id}/test", summary="Probar conexión (read-only)")
async def marketplace_install_test(install_id: str, request: Request):
    ctx = _require(request, "marketplace:manage")
    from src.platform.marketplace import catalog
    from src.platform.marketplace.runtime import execute_action, get_install

    install = await get_install(ctx.organization_id, UUID(install_id))
    if install is None:
        raise HTTPException(404, "Instalación no encontrada")
    manifest = await catalog.get_manifest(install["integration"]["slug"])
    test_action = None
    for cap in manifest.get("capabilities") or []:
        for action in cap.get("actions") or []:
            if action.get("read_only") and not action.get("requires_approval"):
                test_action = action
                break
        if test_action:
            break
    if test_action is None:
        return {"ok": True, "note": "sin acción de prueba read-only"}
    sample_inputs = _sample_inputs(test_action.get("input_schema") or {})
    outcome = await execute_action(
        ctx.organization_id,
        UUID(install_id),
        test_action["action_id"],
        sample_inputs,
        workspace_id=await _workspace_id(request),
        actor_id=ctx.user_id,
        source="test",
    )
    return {
        "ok": outcome.ok,
        "action": test_action["action_id"],
        "error_code": outcome.error_code,
        "message": outcome.error_message,
        "latency_ms": round(outcome.latency_ms, 1),
        "cached": outcome.cached,
    }


def _sample_inputs(schema: dict) -> dict:
    props = schema.get("properties") or {}
    return {
        k: ("12345678" if v.get("type") == "string" and v.get("minLength") == 8 else "demo")
        for k, v in props.items()
    }


# ---------------------------------------------------------------------------
# Ejecución de acciones (workflow/agente/manual/API — mismo runtime)
# ---------------------------------------------------------------------------
@router.post("/installs/{install_id}/actions/{action_id}/execute", summary="Ejecutar acción")
async def marketplace_action_execute(
    install_id: str, action_id: str, body: ActionExecuteIn, request: Request
):
    ctx = _require(request, "external_actions:execute")
    from src.platform.marketplace.runtime import execute_action

    outcome = await execute_action(
        ctx.organization_id,
        UUID(install_id),
        action_id,
        body.inputs or {},
        workspace_id=await _workspace_id(request),
        purpose=body.purpose,
        workflow_id=UUID(body.workflow_id) if body.workflow_id else None,
        run_id=UUID(body.run_id) if body.run_id else None,
        actor_id=ctx.user_id,
        force_refresh=bool(body.force_refresh),
        source="api",
    )
    return {
        "ok": outcome.ok,
        "error_code": outcome.error_code,
        "message": outcome.error_message,
        "data": outcome.data,
        "evidence_id": str(outcome.evidence_id) if outcome.evidence_id else None,
        "cached": outcome.cached,
        "cost": outcome.customer_cost,
        "currency": outcome.currency,
        "units": outcome.units,
        "latency_ms": round(outcome.latency_ms, 1),
    }


# ---------------------------------------------------------------------------
# Uso y evidencia
# ---------------------------------------------------------------------------
@router.get("/installs/{install_id}/usage", summary="Ledger de uso")
async def marketplace_install_usage(install_id: str, request: Request, limit: int = 50):
    ctx = _require(request, "marketplace:read")
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT created_at, action_id, units, provider_cost, customer_cost, "
                    "currency, status, workflow_id, run_id, purpose "
                    "FROM integration_usage_ledger "
                    "WHERE organization_id = :oid AND (install_id = :iid OR install_id IS NULL) "
                    "ORDER BY created_at DESC LIMIT :lim"
                ),
                {"oid": ctx.organization_id, "iid": UUID(install_id), "lim": min(int(limit), 200)},
            )
        ).fetchall()
        totals = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS calls, COALESCE(SUM(customer_cost),0) AS spend "
                    "FROM integration_usage_ledger "
                    "WHERE organization_id = :oid AND (install_id = :iid OR install_id IS NULL)"
                ),
                {"oid": ctx.organization_id, "iid": UUID(install_id)},
            )
        ).fetchone()
    finally:
        await session.close()
    return {
        "calls": int(totals.calls or 0),
        "total_spend": float(totals.spend or 0),
        "entries": [
            {
                "created_at": r.created_at.isoformat(),
                "action_id": r.action_id,
                "units": int(r.units),
                "provider_cost": float(r.provider_cost),
                "customer_cost": float(r.customer_cost),
                "currency": r.currency,
                "status": r.status,
                "workflow_id": str(r.workflow_id) if r.workflow_id else None,
                "purpose": r.purpose,
            }
            for r in rows
        ],
    }


@router.get("/evidence", summary="Evidencia externa de entidades")
async def marketplace_evidence(
    request: Request,
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = 20,
):
    ctx = _require(request, "evidence:read")
    from src.platform.marketplace.runtime import list_evidence

    return await list_evidence(
        ctx.organization_id,
        entity_type=entity_type,
        entity_id=entity_id,
        workspace_id=await _workspace_id(request),
        limit=limit,
    )


class InstallIn(BaseModel):
    integration_slug: str = Field(min_length=1, max_length=80)
    purpose: str | None = Field(default=None, max_length=80)
    legal_basis_reference: str | None = Field(default=None, max_length=200)


class InstallUpdateIn(BaseModel):
    enabled_actions: list[str] | None = None
    auto_use_policy: dict[str, str] | None = None
    spend_limit: dict | None = None
    purpose: str | None = Field(default=None, max_length=80)
    legal_basis_reference: str | None = Field(default=None, max_length=200)
    status: str | None = None


class CredentialsIn(BaseModel):
    auth_mode: str = Field(default="BYOC", max_length=30)
    cred_type: str = Field(default="API_KEY", max_length=30)
    provider_account_id: str | None = Field(default=None, max_length=160)
    secrets: dict | None = None


class ActionExecuteIn(BaseModel):
    inputs: dict | None = None
    purpose: str | None = None
    workflow_id: str | None = None
    run_id: str | None = None
    force_refresh: bool = False


class ActionStatusIn(BaseModel):
    status: str = Field(pattern="^(ACTIVE|DEPRECATED|END_OF_LIFE)$")
