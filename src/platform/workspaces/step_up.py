# =============================================================================
# Tenant step-up — MFA if enrolled, otherwise password re-auth
# =============================================================================
from __future__ import annotations

import time

from fastapi import HTTPException, Request

from src.platform.auth.mfa import mfa_enabled, step_up_recent
from src.platform.auth.session import SessionTokenError, decrypt_session


async def require_tenant_step_up(request: Request) -> None:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    try:
        payload = decrypt_session(auth_header[7:])
    except SessionTokenError as exc:
        raise HTTPException(401, "Session inválida") from exc
    if payload.typ != "portal":
        raise HTTPException(403, "Se requiere sesión de portal")
    if payload.user_id and await mfa_enabled(payload.user_id):
        if not step_up_recent(payload):
            raise HTTPException(
                status_code=403,
                detail={
                    "error_code": "step_up_required",
                    "message": "Confirma MFA para ejecutar esta operación.",
                },
            )
        return
    if getattr(payload, "assurance", None) in {"password", "totp"} and step_up_recent(
        payload
    ):
        return
    confirmed = getattr(payload, "mfa_confirmed_at", None)
    if (
        getattr(payload, "assurance", None) == "password"
        and confirmed
        and int(time.time()) - int(confirmed) <= 600
    ):
        return
    raise HTTPException(
        status_code=403,
        detail={
            "error_code": "step_up_required",
            "message": "Confirma tu contraseña para ejecutar esta operación.",
        },
    )
