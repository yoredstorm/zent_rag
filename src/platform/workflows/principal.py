# =============================================================================
# P19.1-02 - Identidad verificada para lecturas de datos.
#
# Distingue:
#   actor_id   quien inicia la ejecucion (operador/tecnico)
#   subject_id de quien son los datos (titular)
#   claims     atributos ya verificados por el canal/autenticacion
#
# No guarda JWT, passwords ni credenciales. El subject/claims nunca se toman
# del mensaje libre, del LLM ni de un campo del body HTTP.
# =============================================================================
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

PRINCIPAL_SCHEMA = "zent.workflow.principal/v1"
MAX_CLAIMS = 20


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class VerifiedPrincipal(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    principal_schema: Literal["zent.workflow.principal/v1"] = Field(
        default=PRINCIPAL_SCHEMA, alias="schema"
    )
    organization_id: UUID
    workspace_id: UUID
    actor_id: UUID
    subject_id: str = Field(min_length=1, max_length=120)
    authn_method: Literal["portal_session", "api_token", "channel_signature", "system"]
    assurance_level: Literal["low", "medium", "high"]
    verified_at: datetime
    expires_at: datetime
    claims: dict[str, str] = Field(default_factory=dict, max_length=MAX_CLAIMS)
    provenance: dict[str, str] = Field(default_factory=dict, max_length=MAX_CLAIMS)

    @field_validator("claims", "provenance")
    @classmethod
    def _safe_scalars(cls, value: dict[str, str]) -> dict[str, str]:
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 80:
                raise ValueError("claim key invalida")
            if not isinstance(item, str) or len(item) > 200:
                raise ValueError("claim value invalida")
            lowered = f"{key}={item}".lower()
            if any(token in lowered for token in ("bearer ", "password=", "secret=", "token=")):
                raise ValueError("claim contiene material secreto")
        return value

    def is_valid(self, now: datetime | None = None) -> bool:
        moment = now or _utcnow()
        return self.expires_at > moment and self.verified_at <= moment

    def claim(self, name: str) -> str | None:
        value = self.claims.get(name)
        return str(value) if value is not None and str(value).strip() else None

    def public_ref(self) -> str:
        """Hash estable para auditoria; no expone claims ni PII."""
        blob = "|".join(
            [
                str(self.organization_id),
                str(self.workspace_id),
                str(self.actor_id),
                self.subject_id,
                self.authn_method,
                self.assurance_level,
            ]
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def principal_from_tenant(
    ctx: Any,
    workspace_id: Any,
    *,
    claims: dict[str, str] | None = None,
    ttl_minutes: int = 480,
) -> VerifiedPrincipal | None:
    """Construye el principal desde TenantContext (nunca desde el body)."""
    if ctx is None or getattr(ctx, "user_id", None) is None or workspace_id is None:
        return None
    auth_type = str(getattr(ctx, "auth_type", "portal_session") or "portal_session")
    authn_method = {
        "portal_session": "portal_session",
        "api_token": "api_token",
        "platform_session": "portal_session",
    }.get(auth_type, "api_token")
    assurance = "high" if auth_type in ("portal_session", "platform_session") else "medium"
    now = _utcnow()
    safe_claims = dict(claims or {})
    return VerifiedPrincipal(
        organization_id=UUID(str(ctx.organization_id)),
        workspace_id=UUID(str(workspace_id)),
        actor_id=UUID(str(ctx.user_id)),
        subject_id=str(ctx.user_id),
        authn_method=authn_method,
        assurance_level=assurance,
        verified_at=now,
        expires_at=now + timedelta(minutes=max(1, ttl_minutes)),
        claims=safe_claims,
        provenance={key: "trusted_channel" for key in safe_claims},
    )


def validate_principal_scope(
    principal: Any | None,
    organization_id: Any,
    workspace_id: Any,
) -> None:
    if principal is None or isinstance(principal, dict):
        # Los dicts solo llegan de callers internos/tests legacy; la ruta HTTP
        # construye VerifiedPrincipal. No se aceptan dicts desde el body.
        return
    if str(principal.organization_id) != str(organization_id):
        raise ValueError("principal de otra organizacion")
    if workspace_id is not None and str(principal.workspace_id) != str(workspace_id):
        raise ValueError("principal de otro workspace")
    if not principal.is_valid():
        raise ValueError("principal expirado")


def principal_claims(principal: Any) -> dict[str, str]:
    """Adapta el principal a la forma que consume el ejecutor de planes."""
    if principal is None:
        return {}
    if isinstance(principal, dict):
        claims = principal.get("claims")
        return dict(claims) if isinstance(claims, dict) else dict(principal)
    claims = getattr(principal, "claims", None)
    return dict(claims) if isinstance(claims, dict) else {}


__all__ = [
    "PRINCIPAL_SCHEMA",
    "VerifiedPrincipal",
    "principal_claims",
    "principal_from_tenant",
    "validate_principal_scope",
]
