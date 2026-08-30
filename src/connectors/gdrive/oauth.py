# =============================================================================
# Google Drive OAuth — state HMAC atado a organization_id + connector_id
# =============================================================================
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode
from uuid import UUID

from src.connectors.gdrive.client import DRIVE_READONLY_SCOPE
from src.core.config import get_settings

_STATE_TTL_SECONDS = 600


class DriveOAuthError(ValueError):
    """State inválido, expirado o malformado."""


def _state_key() -> bytes:
    raw = get_settings().CONNECTOR_SECRETS_KEY.get_secret_value()
    return hashlib.sha256(raw.encode("utf-8")).digest()


def sign_drive_oauth_state(
    *,
    organization_id: UUID | str,
    connector_id: UUID | str,
    ttl_seconds: int = _STATE_TTL_SECONDS,
) -> str:
    payload = {
        "organization_id": str(organization_id),
        "connector_id": str(connector_id),
        "exp": int(time.time()) + ttl_seconds,
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(_state_key(), body, hashlib.sha256).hexdigest()
    token = base64.urlsafe_b64encode(body).decode("ascii").rstrip("=")
    return f"{token}.{sig}"


def verify_drive_oauth_state(state: str) -> dict:
    if not state or "." not in state:
        raise DriveOAuthError("invalid state")
    token, sig = state.rsplit(".", 1)
    pad = "=" * (-len(token) % 4)
    try:
        body = base64.urlsafe_b64decode(token + pad)
    except Exception as exc:
        raise DriveOAuthError("invalid state") from exc
    expected = hmac.new(_state_key(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise DriveOAuthError("invalid state")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise DriveOAuthError("invalid state") from exc
    if int(payload.get("exp") or 0) < int(time.time()):
        raise DriveOAuthError("expired state")
    if not payload.get("organization_id") or not payload.get("connector_id"):
        raise DriveOAuthError("invalid state")
    return payload


def build_drive_authorization_url(state: str) -> str:
    settings = get_settings()
    client_id = (settings.GOOGLE_OAUTH_CLIENT_ID or "").strip()
    if not client_id:
        raise DriveOAuthError("Google Drive OAuth is not configured")
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": DRIVE_READONLY_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "include_granted_scopes": "true",
        }
    )
    return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"
