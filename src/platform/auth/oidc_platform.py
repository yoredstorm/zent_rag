# =============================================================================
# Login del Control Center con Zitadel (OIDC Authorization Code)
# =============================================================================
# Zitadel autentica; Zent sigue autorizando. El id_token se valida con el JWKS
# del issuer y de él solo se usan sub/email y el claim de roles para mapear a
# los roles internos. La sesión que emite Zent es la misma de siempre
# (encrypt_session typ="platform"), así que el resto del panel no cambia.
from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from src.core.config import get_settings
from src.platform.enterprise.sso import (
    _fetch_jwks,
    _oidc_discover,
    _oidc_exchange_code,
    _verify_id_token,
)

# Identificador fijo para firmar el `state` con el mismo esquema del SSO de
# organizaciones (HMAC con PORTAL_SESSION_KEY).
_STATE_ID = UUID("00000000-0000-0000-0000-0000000000cc")
SCOPES = "openid profile email"


def oidc_config() -> dict[str, Any] | None:
    """Config efectiva o None si el SSO no está habilitado."""
    settings = get_settings()
    issuer = (settings.ZITADEL_ISSUER or "").strip().rstrip("/")
    client_id = (settings.ZITADEL_CLIENT_ID or "").strip()
    if not issuer or not client_id:
        return None
    secret = settings.ZITADEL_CLIENT_SECRET
    return {
        "issuer": issuer,
        "client_id": client_id,
        "client_secret": secret.get_secret_value() if secret else "",
        "redirect_uri": settings.ZITADEL_REDIRECT_URI,
        "portal_url": settings.ZITADEL_PORTAL_URL.rstrip("/"),
        "roles_claim": settings.ZITADEL_ROLES_CLAIM or "roles",
    }


def public_config() -> dict[str, Any]:
    """Lo que el portal puede ver (sin secreto)."""
    cfg = oidc_config()
    if cfg is None:
        return {"enabled": False}
    return {
        "enabled": True,
        "issuer": cfg["issuer"],
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "scopes": SCOPES,
    }


def new_state() -> tuple[str, str]:
    """Devuelve (state, nonce) firmados con HMAC y un nonce aleatorio."""
    from src.platform.enterprise.sso import _sign_state

    nonce = secrets.token_urlsafe(16)
    return _sign_state(_STATE_ID, nonce), nonce


def verify_state(state: str) -> bool:
    from src.platform.enterprise.sso import _verify_state

    return _verify_state(state, _STATE_ID)


async def authorize_url(state: str, nonce: str) -> str:
    cfg = oidc_config()
    if cfg is None:
        raise RuntimeError("OIDC no configurado")
    discovery = await _oidc_discover(cfg["issuer"])
    params = {
        "response_type": "code",
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "scope": SCOPES,
        "state": state,
        "nonce": nonce,
    }
    return discovery["authorization_endpoint"] + "?" + urlencode(params)


async def exchange_and_validate(code: str, state: str) -> dict[str, Any]:
    """Intercambia el code y devuelve los claims del id_token validado."""
    cfg = oidc_config()
    if cfg is None:
        raise RuntimeError("OIDC no configurado")
    nonce = state.split(".", 1)[0]
    discovery = await _oidc_discover(cfg["issuer"])
    tokens = await _oidc_exchange_code(
        discovery["token_endpoint"],
        cfg["client_id"],
        cfg["client_secret"],
        code,
        cfg["redirect_uri"],
    )
    id_token = tokens.get("id_token")
    if not id_token:
        raise ValueError("El proveedor no devolvió id_token")
    jwks = await _fetch_jwks(discovery["jwks_uri"])
    return _verify_id_token(
        id_token,
        jwks,
        expected_issuer=cfg["issuer"],
        expected_aud=cfg["client_id"],
        nonce=nonce,
    )


def claim_roles(claims: dict[str, Any], claim_name: str) -> list[str]:
    raw = claims.get(claim_name)
    if isinstance(raw, list):
        return [str(item) for item in raw]
    if isinstance(raw, dict):
        # Zitadel: {"admin": {"org-id": "domain"}}
        return [str(key) for key in raw.keys()]
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    return []


def map_role(roles: list[str]) -> str | None:
    """Mapea los roles del IdP a los roles internos de Zent."""
    normalized = {role.strip().lower() for role in roles}
    if normalized & {"superadmin", "super_admin", "super-admin"}:
        return "super_admin"
    if normalized & {"admin", "administrator", "administrador"}:
        return "admin"
    if normalized & {"operador", "operator", "ops"}:
        return "operador"
    return None
