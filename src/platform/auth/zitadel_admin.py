# =============================================================================
# Administración de usuarios en Zitadel (Management API)
# =============================================================================
# Zent NO guarda contraseñas cuando Zitadel está conectado: las credenciales
# viven en Zitadel. Acá solo se orquestan altas, ediciones y reseteos con un
# service user (Personal Access Token). Si no hay token configurado, todo queda
# apagado y se sigue usando el modo mock.
from __future__ import annotations

from typing import Any

from src.core.config import get_settings


class ZitadelError(RuntimeError):
    """Error devuelto por Zitadel, con el detalle para mostrarlo al operador."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _config() -> dict[str, Any] | None:
    settings = get_settings()
    issuer = (settings.ZITADEL_ISSUER or "").strip().rstrip("/")
    token = settings.ZITADEL_API_TOKEN
    if not issuer or token is None:
        return None
    secret = token.get_secret_value().strip()
    if not secret:
        return None
    return {"issuer": issuer, "token": secret}


def is_enabled() -> bool:
    return _config() is not None


async def _request(method: str, path: str, payload: dict | None = None) -> Any:
    import httpx

    cfg = _config()
    if cfg is None:
        raise ZitadelError(503, "Zitadel no está configurado (falta ZITADEL_API_TOKEN).")
    url = cfg["issuer"] + path
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.request(
            method,
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {cfg['token']}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
    if resp.status_code >= 400:
        try:
            detail = resp.json()
            message = detail.get("message") or detail.get("details") or str(detail)
        except Exception:  # noqa: BLE001 — respuesta no JSON
            message = resp.text[:300]
        raise ZitadelError(resp.status_code, str(message))
    if not resp.content:
        return {}
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return {}


def _human(row: dict) -> dict:
    """Normaliza un usuario de Zitadel al shape que usa el Control Center."""
    human = row.get("human") or {}
    profile = human.get("profile") or {}
    email = human.get("email") or {}
    return {
        "id": str(row.get("userId") or row.get("id") or ""),
        "username": row.get("username"),
        "email": email.get("email"),
        "email_verified": bool(email.get("isVerified")),
        "given_name": profile.get("givenName"),
        "family_name": profile.get("familyName"),
        "display_name": profile.get("displayName")
        or " ".join(
            part for part in (profile.get("givenName"), profile.get("familyName")) if part
        ),
        "state": row.get("state"),
        "created_at": row.get("creationDate") or row.get("details", {}).get("creationDate"),
    }


async def list_users(search: str | None = None, limit: int = 100) -> list[dict]:
    query: list[dict] = [{"limit": limit}]
    if search:
        query = [
            {
                "emailQuery": {
                    "emailAddress": search,
                    "method": "TEXT_QUERY_METHOD_CONTAINS_IGNORE_CASE",
                }
            },
            {"limit": limit},
        ]
    data = await _request("POST", "/v2/users", {"queries": query})
    return [_human(row) for row in data.get("result") or []]


async def create_user(
    *,
    email: str,
    given_name: str,
    family_name: str,
    password: str | None = None,
    change_required: bool = True,
) -> dict:
    payload: dict[str, Any] = {
        "username": email,
        "profile": {"givenName": given_name, "familyName": family_name},
        "email": {"email": email, "isVerified": True},
    }
    if password:
        payload["password"] = {
            "password": password,
            "changeRequired": change_required,
        }
    data = await _request("POST", "/v2/users/human", payload)
    return {"id": str(data.get("userId") or data.get("id") or "")}


async def update_user(
    user_id: str,
    *,
    given_name: str | None = None,
    family_name: str | None = None,
    email: str | None = None,
) -> dict:
    payload: dict[str, Any] = {}
    profile = {
        key: value
        for key, value in (("givenName", given_name), ("familyName", family_name))
        if value
    }
    if profile:
        payload["profile"] = profile
    if email:
        payload["email"] = {"email": email, "isVerified": True}
    await _request("PUT", f"/v2/users/{user_id}", payload)
    return {"id": user_id}


async def deactivate_user(user_id: str) -> dict:
    await _request("POST", f"/v2/users/{user_id}/deactivate", {})
    return {"id": user_id, "state": "deactivated"}


async def set_password(
    user_id: str, password: str, change_required: bool = True
) -> dict:
    """Contraseña temporal con cambio obligatorio al próximo ingreso."""
    await _request(
        "POST",
        f"/v2/users/{user_id}/password",
        {"newPassword": {"password": password, "changeRequired": change_required}},
    )
    return {"id": user_id, "change_required": change_required}


async def trigger_password_reset(user_id: str) -> dict:
    """Envía el código de reseteo al email del usuario (lo gestiona Zitadel)."""
    await _request("POST", f"/v2/users/{user_id}/password/reset", {})
    return {"id": user_id, "sent": True}
