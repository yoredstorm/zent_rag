# =============================================================================
# SSO OIDC — start (redirect), callback (code exchange + JIT), config endpoints
# =============================================================================
from __future__ import annotations

import secrets
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from src.core.config import get_settings

router = APIRouter(prefix="/api/v1/auth/sso", tags=["sso"])

REDIRECT_PATH = "/api/v1/auth/sso/callback"


class SsoConfigIn(BaseModel):
    enabled: bool | None = None
    issuer: str | None = Field(default=None, max_length=300)
    client_id: str | None = Field(default=None, max_length=200)
    client_secret: str | None = Field(default=None, max_length=600)
    roles_claim: str | None = Field(default=None, max_length=50)


@router.get("/{org_id}/start", summary="Iniciar flujo SSO (redirect al IdP)")
async def sso_start(org_id: str, request: Request):
    from src.platform.enterprise.sso import _oidc_discover, _sign_state, get_sso_config

    try:
        oid = UUID(org_id)
    except ValueError:
        raise HTTPException(400, "org_id must be a valid UUID")
    cfg = await get_sso_config(oid)
    if cfg is None or not cfg["sso_enabled"] or not cfg["issuer"] or not cfg["client_id"]:
        raise HTTPException(404, "SSO no configurado para esta organización")

    discovery = await _oidc_discover(cfg["issuer"])
    nonce = secrets.token_urlsafe(24)
    state = _sign_state(oid, nonce)
    redirect_uri = str(request.base_url).rstrip("/") + REDIRECT_PATH
    from urllib.parse import urlencode

    params = {
        "response_type": "code",
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
    }
    authorize = discovery["authorization_endpoint"] + "?" + urlencode(params)
    return RedirectResponse(authorize, status_code=302)


@router.get("/callback", summary="Callback SSO (code exchange + JIT provisioning)")
async def sso_callback(request: Request, code: str | None = None, state: str | None = None):
    from src.platform.auth.session import encrypt_session
    from src.platform.enterprise.sso import (
        _decrypt_secret,
        _fetch_jwks,
        _oidc_discover,
        _oidc_exchange_code,
        _to_scim_scalar,
        _verify_id_token,
        _verify_state,
        get_sso_config,
        provision_sso_user,
    )

    if not code or not state:
        return JSONResponse(
            {"error": "invalid_request", "detail": "code y state requeridos"}, status_code=400
        )
    settings = get_settings()

    # El state codifica org + nonce; lo firmamos con la misma clave de sesión.
    parts = state.split(".", 1)
    if len(parts) != 2:
        return JSONResponse({"error": "invalid_state"}, status_code=400)
    nonce = parts[0]

    # Resolver org: probamos contra cada org con SSO habilitado (state no incluye org
    # en claro para no filtrar la identidad; el HMAC liga org+nonce).
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text("SELECT id FROM organizations WHERE sso_enabled = true")
            )
        ).fetchall()
    finally:
        await session.close()
    matched = None
    for r in rows:
        if _verify_state(state, r.id):
            matched = r.id
            break
    if matched is None:
        return JSONResponse({"error": "invalid_state"}, status_code=400)
    oid = matched

    cfg = await get_sso_config(oid)
    if cfg is None or not cfg["client_secret_enc"]:
        return JSONResponse({"error": "sso_misconfigured"}, status_code=500)
    client_secret = _decrypt_secret(cfg["client_secret_enc"])
    redirect_uri = str(request.base_url).rstrip("/") + REDIRECT_PATH

    try:
        discovery = await _oidc_discover(cfg["issuer"])
        tokens = await _oidc_exchange_code(
            discovery["token_endpoint"],
            cfg["client_id"],
            client_secret,
            code,
            redirect_uri,
        )
        id_token = tokens.get("id_token")
        if not id_token:
            return JSONResponse({"error": "no_id_token"}, status_code=400)
        jwks = await _fetch_jwks(discovery["jwks_uri"])
        claims = _verify_id_token(
            id_token, jwks, expected_issuer=cfg["issuer"], expected_aud=cfg["client_id"], nonce=nonce
        )
    except Exception as exc:
        return JSONResponse(
            {"error": "sso_exchange_failed", "detail": str(exc)[:300]}, status_code=401
        )

    email = _to_scim_scalar(claims.get("email")) or _to_scim_scalar(claims.get("preferred_username"))
    if not email:
        return JSONResponse({"error": "no_email_in_token"}, status_code=400)
    sub = str(claims.get("sub") or email)
    raw_roles = claims.get(cfg["roles_claim"]) or []
    roles = (
        [_to_scim_scalar(raw_roles)] if isinstance(raw_roles, str) else list(raw_roles or [])
    )

    user_id = await provision_sso_user(oid, email, sub, roles)
    session_token = encrypt_session(user_id, oid)

    if request.query_params.get("format") == "json":
        return {
            "access_token": session_token,
            "organization_id": str(oid),
            "user_id": str(user_id),
            "email": email,
        }

    portal_base = (settings.PORTAL_BASE_URL or "http://localhost:5173").rstrip("/")
    from urllib.parse import urlencode

    return RedirectResponse(
        f"{portal_base}/sso/callback?{urlencode({'token': session_token, 'org': str(oid)})}",
        status_code=302,
    )


@router.get("/config", summary="Config SSO de la organización")
async def sso_config_get(request: Request):
    from src.platform.enterprise.sso import get_sso_config
    from src.platform.rbac.policy import require_organization_admin

    ctx = require_organization_admin(request)
    cfg = await get_sso_config(ctx.organization_id)
    if cfg is None:
        raise HTTPException(404, "Organization not found")
    cfg.pop("client_secret_enc", None)
    cfg["client_secret_set"] = True
    return cfg


@router.put("/config", summary="Guardar configuración SSO")
async def sso_config_put(body: SsoConfigIn, request: Request):
    from src.platform.enterprise.sso import save_sso_config
    from src.platform.rbac.policy import require_organization_admin

    ctx = require_organization_admin(request)
    await save_sso_config(
        ctx.organization_id,
        enabled=body.enabled,
        issuer=body.issuer,
        client_id=body.client_id,
        client_secret=body.client_secret,
        roles_claim=body.roles_claim,
    )
    return {"status": "saved"}


@router.post("/test", summary="Probar conectividad con el IdP")
async def sso_test(body: SsoConfigIn, request: Request):
    from src.platform.enterprise.sso import _fetch_jwks, _oidc_discover
    from src.platform.rbac.policy import require_organization_admin

    ctx = require_organization_admin(request)
    issuer = body.issuer
    if not issuer:
        raise HTTPException(400, "issuer requerido")
    try:
        discovery = await _oidc_discover(issuer)
        keys = await _fetch_jwks(discovery["jwks_uri"])
        return {
            "status": "ok",
            "authorization_endpoint": discovery["authorization_endpoint"],
            "token_endpoint": discovery["token_endpoint"],
            "jwks_keys": len(keys),
        }
    except Exception as exc:
        return JSONResponse(
            {"status": "failed", "detail": str(exc)[:300]}, status_code=502
        )


@router.post("/scim-token", summary="Generar/rotar token SCIM de la organización")
async def sso_scim_token(request: Request):
    from src.platform.enterprise.sso import set_scim_token
    from src.platform.rbac.policy import require_organization_admin

    ctx = require_organization_admin(request)
    token = "zent_scim_" + secrets.token_urlsafe(32)
    await set_scim_token(ctx.organization_id, token)
    return {"status": "created", "token": token, "enabled": True}


@router.delete("/scim-token", summary="Deshabilitar SCIM")
async def sso_scim_token_delete(request: Request):
    from src.platform.enterprise.sso import set_scim_token
    from src.platform.rbac.policy import require_organization_admin

    ctx = require_organization_admin(request)
    await set_scim_token(ctx.organization_id, None)
    return {"status": "disabled"}


@router.put("/key-policy", summary="Política de expiración forzada de API keys")
async def sso_key_policy(body: dict, request: Request):
    from src.platform.enterprise.sso import set_key_policy
    from src.platform.rbac.policy import require_organization_admin

    ctx = require_organization_admin(request)
    days = body.get("max_age_days")
    if days is not None and (not isinstance(days, int) or days < 1 or days > 3650):
        raise HTTPException(400, "max_age_days debe ser 1-3650 o null")
    await set_key_policy(ctx.organization_id, days)
    return {"status": "saved", "max_age_days": days}
