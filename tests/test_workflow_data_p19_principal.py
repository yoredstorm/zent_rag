# =============================================================================
# P19.1-02 - Principal verificado: vigencia, scope y claims sin secretos.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.platform.workflows.principal import (
    VerifiedPrincipal,
    principal_claims,
    principal_from_tenant,
    validate_principal_scope,
)


def _principal(**overrides):
    now = datetime.now(timezone.utc)
    data = {
        "organization_id": uuid4(),
        "workspace_id": uuid4(),
        "actor_id": uuid4(),
        "subject_id": "CUST-A",
        "authn_method": "portal_session",
        "assurance_level": "high",
        "verified_at": now,
        "expires_at": now + timedelta(minutes=10),
        "claims": {"customer_ref": "CUST-A"},
        "provenance": {"customer_ref": "portal_session"},
    }
    data.update(overrides)
    return VerifiedPrincipal(**data)


def test_valid_and_expired_principal() -> None:
    principal = _principal()
    assert principal.is_valid() is True
    assert principal.claim("customer_ref") == "CUST-A"

    expired = _principal(
        verified_at=datetime.now(timezone.utc) - timedelta(hours=2),
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    assert expired.is_valid() is False


def test_scope_mismatch_is_rejected() -> None:
    principal = _principal()
    validate_principal_scope(principal, principal.organization_id, principal.workspace_id)
    with pytest.raises(ValueError):
        validate_principal_scope(principal, uuid4(), principal.workspace_id)
    with pytest.raises(ValueError):
        validate_principal_scope(principal, principal.organization_id, uuid4())
    with pytest.raises(ValueError):
        validate_principal_scope(_principal(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)), principal.organization_id, principal.workspace_id)


def test_principal_rejects_secret_material_in_claims() -> None:
    with pytest.raises(ValidationError):
        _principal(claims={"authorization": "bearer abc.def.ghi"})
    with pytest.raises(ValidationError):
        _principal(claims={"password": "password=super-secret"})


def test_public_ref_does_not_expose_claims() -> None:
    principal = _principal(claims={"customer_ref": "CUST-A", "email": "a@example.com"})
    ref = principal.public_ref()
    assert len(ref) == 64
    assert "CUST-A" not in ref
    assert "a@example.com" not in ref


def test_principal_claims_only_returns_verified_claims() -> None:
    principal = _principal()
    claims = principal_claims(principal)
    assert claims == {"customer_ref": "CUST-A"}
    assert "actor_id" not in claims
    assert principal_claims(None) == {}


def test_principal_from_tenant_uses_authenticated_identity() -> None:
    org_id = uuid4()
    workspace_id = uuid4()
    user_id = uuid4()
    ctx = SimpleNamespace(
        organization_id=org_id,
        user_id=user_id,
        auth_type="portal_session",
    )
    principal = principal_from_tenant(ctx, workspace_id)
    assert principal is not None
    assert principal.organization_id == org_id
    assert principal.workspace_id == workspace_id
    assert principal.subject_id == str(user_id)
    assert principal.actor_id == user_id
    assert principal.claims == {}

    anonymous = principal_from_tenant(SimpleNamespace(organization_id=org_id, user_id=None), workspace_id)
    assert anonymous is None
