# =============================================================================
# SSO OIDC — discovery, auth-code flow, validación JWT RS256, JIT provisioning
# =============================================================================
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Any
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)


# --------------------------------------------------------------------------
# Cifrado del client secret en reposo (AES-256-GCM, misma técnica que sesiones)
# --------------------------------------------------------------------------
def _encrypt_secret(secret: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = hashlib.sha256(
        get_settings().CONNECTOR_SECRETS_KEY.get_secret_value().encode()
    ).digest()
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, secret.encode(), None)
    return base64.urlsafe_b64encode(nonce + ct).decode()


def _decrypt_secret(blob: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = hashlib.sha256(
        get_settings().CONNECTOR_SECRETS_KEY.get_secret_value().encode()
    ).digest()
    raw = base64.urlsafe_b64decode(blob.encode())
    return AESGCM(key).decrypt(raw[:12], raw[12:], None).decode()


# --------------------------------------------------------------------------
# Estado SSO: HMAC(org, nonce) firmado con PORTAL_SESSION_KEY
# --------------------------------------------------------------------------
def _sign_state(organization_id: UUID, nonce: str) -> str:
    key = get_settings().PORTAL_SESSION_KEY.get_secret_value().encode()
    payload = f"{organization_id}:{nonce}".encode()
    return f"{nonce}.{hmac.new(key, payload, hashlib.sha256).hexdigest()}"


def _verify_state(state: str, organization_id: UUID) -> bool:
    key = get_settings().PORTAL_SESSION_KEY.get_secret_value().encode()
    try:
        nonce, sig = state.split(".", 1)
        expected = hmac.new(key, f"{organization_id}:{nonce}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)
    except (ValueError, TypeError):
        return False


async def get_sso_config(organization_id: UUID) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT sso_enabled, sso_oidc_issuer, sso_oidc_client_id, "
                    "sso_oidc_client_secret_enc, sso_oidc_roles_claim, "
                    "scim_enabled, scim_token_hash, key_max_age_days "
                    "FROM organizations WHERE id = :oid"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    return {
        "sso_enabled": bool(row.sso_enabled),
        "issuer": row.sso_oidc_issuer,
        "client_id": row.sso_oidc_client_id,
        "client_secret_enc": row.sso_oidc_client_secret_enc,
        "roles_claim": row.sso_oidc_roles_claim or "roles",
        "scim_enabled": bool(row.scim_enabled),
        "scim_token_prefix": (
            (row.scim_token_hash or "")[:8] if row.scim_token_hash else None
        ),
        "key_max_age_days": row.key_max_age_days,
    }


async def save_sso_config(
    organization_id: UUID,
    *,
    enabled: bool | None = None,
    issuer: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
    roles_claim: str | None = None,
) -> None:
    session = await get_async_session()
    try:
        sets: list[str] = []
        params: dict[str, Any] = {"oid": organization_id}
        if enabled is not None:
            sets.append("sso_enabled = :enabled")
            params["enabled"] = enabled
        if issuer is not None:
            sets.append("sso_oidc_issuer = :issuer")
            params["issuer"] = issuer
        if client_id is not None:
            sets.append("sso_oidc_client_id = :client_id")
            params["client_id"] = client_id
        if client_secret is not None:
            sets.append("sso_oidc_client_secret_enc = :secret_enc")
            params["secret_enc"] = _encrypt_secret(client_secret)
        if roles_claim is not None:
            sets.append("sso_oidc_roles_claim = :roles_claim")
            params["roles_claim"] = roles_claim
        if sets:
            await session.execute(
                text(
                    f"UPDATE organizations SET {', '.join(sets)} WHERE id = :oid"  # noqa: S608 (sets whitelisted)
                ),
                params,
            )
            await session.commit()
    finally:
        await session.close()


async def set_scim_token(organization_id: UUID, token: str | None) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE organizations SET scim_token_hash = :hash, "
                "scim_enabled = :enabled WHERE id = :oid"
            ),
            {
                "hash": hashlib.sha256(token.encode()).hexdigest() if token else None,
                "enabled": token is not None,
                "oid": organization_id,
            },
        )
        await session.commit()
    finally:
        await session.close()


async def set_key_policy(organization_id: UUID, max_age_days: int | None) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text("UPDATE organizations SET key_max_age_days = :days WHERE id = :oid"),
            {"days": max_age_days, "oid": organization_id},
        )
        await session.commit()
    finally:
        await session.close()


# --------------------------------------------------------------------------
# OIDC discovery + token + JWKS
# --------------------------------------------------------------------------
async def _oidc_discover(issuer: str) -> dict:
    import httpx

    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def _oidc_exchange_code(
    token_endpoint: str, client_id: str, client_secret: str, code: str, redirect_uri: str
) -> dict:
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()


async def _fetch_jwks(jwks_uri: str) -> list[dict]:
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(jwks_uri)
        resp.raise_for_status()
        return resp.json().get("keys", [])


def _build_rsa_public_key(jwk: dict) -> rsa.RSAPublicKey:
    n = int.from_bytes(base64.urlsafe_b64decode(jwk["n"] + "=="), "big")
    e = int.from_bytes(base64.urlsafe_b64decode(jwk["e"] + "=="), "big")
    pub = rsa.RSAPublicNumbers(e, n).public_key()
    return pub


def _verify_id_token(
    id_token: str, jwks: list[dict], expected_issuer: str, expected_aud: str, nonce: str
) -> dict:
    import jwt

    header = jwt.get_unverified_header(id_token)
    kid = header.get("kid")
    jwk = next((k for k in jwks if k.get("kid") == kid), None)
    if jwk is None and jwks:
        jwk = jwks[0]
    if jwk is None:
        raise ValueError("No suitable JWK found for id_token")
    if jwk.get("kty") == "RSA":
        public_key = _build_rsa_public_key(jwk)
    elif jwk.get("kty") == "EC":
        public_key = _build_ec_public_key(jwk)
    else:
        raise ValueError(f"Unsupported kty: {jwk.get('kty')}")
    claims = jwt.decode(
        id_token,
        public_key,
        algorithms=[header.get("alg", "RS256")],
        issuer=expected_issuer,
        audience=expected_aud,
        options={"require": ["exp", "iat", "iss", "aud"]},
    )
    if nonce and claims.get("nonce") != nonce:
        raise ValueError("Nonce mismatch")
    return claims


def _build_ec_public_key(jwk: dict) -> Any:
    from cryptography.hazmat.primitives.asymmetric import ec

    x = int.from_bytes(base64.urlsafe_b64decode(jwk["x"] + "=="), "big")
    y = int.from_bytes(base64.urlsafe_b64decode(jwk["y"] + "=="), "big")
    curve = ec.SECP256R1() if jwk.get("crv") == "P-256" else ec.SECP384R1()
    return ec.EllipticCurvePublicNumbers(x, y, curve).public_key()


def _to_scim_scalar(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


async def provision_sso_user(
    organization_id: UUID, email: str, sub: str, roles: list[str]
) -> UUID:
    """JIT: upsert usuario por email + external_id sso:<sub> + rol de la org."""
    from src.infrastructure.postgres.relational_db import (
        PostgresMembershipRepository,
        PostgresUserRepository,
    )

    user_repo = PostgresUserRepository()
    existing = await user_repo.get_by_email(email)
    if existing is not None and str(existing.organization_id) == str(organization_id):
        # Re-uso la cuenta; actualizo external_id si cambió el sub.
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE users SET external_id = :ext, last_active_at = NOW() "
                    "WHERE id = :uid AND external_id <> :ext"
                ),
                {"ext": f"sso:{sub}", "uid": existing.id},
            )
            await session.commit()
        finally:
            await session.close()
        user_id = existing.id
    else:
        user_id = await user_repo.create_sso_user(
            organization_id, email, external_id=f"sso:{sub}"
        )

    role = "member"
    if roles:
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT display_name, role_name FROM scim_groups "
                        "WHERE organization_id = :oid"
                    ),
                    {"oid": organization_id},
                )
            ).fetchall()
        finally:
            await session.close()
        mapping = {r.display_name.lower(): r.role_name for r in rows}
        for claim_role in roles:
            rname = mapping.get(claim_role.lower())
            if rname:
                role = rname
                break
    try:
        await PostgresMembershipRepository().assign_role(organization_id, user_id, role)
    except ValueError:
        await PostgresMembershipRepository().assign_role(organization_id, user_id, "member")
    return user_id
