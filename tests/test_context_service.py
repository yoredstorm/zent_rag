from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.core.domain.memory import MemoryRecord, MemoryStatus, MemoryType
from src.memory.repository import InMemoryMemoryRepository
from src.memory.service import MemoryFoundationService
from src.platform.studio.contracts import MemoryPolicy, RoleProfileV1
from src.platform.workflows.context_service import assemble_memory_context


def _role(scope: str, **overrides) -> RoleProfileV1:
    return RoleProfileV1(
        role_id=f"role_{scope}",
        name="Rol de prueba",
        mission="Probar política de memoria",
        memory_policy=MemoryPolicy(scope=scope, **overrides),
    )


def _record(
    *,
    organization_id,
    scope: str,
    workspace_id=None,
    subject_id=None,
    conversation_id=None,
    title="recuerdo",
    consent=True,
    expires_in_days: int | None = 30,
    status: MemoryStatus = MemoryStatus.ACTIVE,
) -> MemoryRecord:
    now = datetime.now(timezone.utc)
    return MemoryRecord(
        organization_id=organization_id,
        memory_type=MemoryType.OPERATIONAL,
        title=title,
        description="detalle privado",
        pattern_key=f"key_{uuid4().hex[:8]}",
        pattern_signature=f"sig_{uuid4().hex}",
        status=status,
        confidence=0.8,
        workspace_id=workspace_id,
        subject_id=subject_id,
        scope=scope,
        consent_at=now if consent else None,
        expires_at=(
            now + timedelta(days=expires_in_days)
            if expires_in_days is not None
            else None
        ),
        created_from_conversation_id=conversation_id,
        updated_at=now,
    )


def _stack() -> tuple[InMemoryMemoryRepository, MemoryFoundationService]:
    repo = InMemoryMemoryRepository()
    return repo, MemoryFoundationService(repo)


def test_gold_roles_declare_explicit_memory_policy() -> None:
    from src.platform.studio.templates import role_template

    expected = {
        "mentor": "long_term_consent",
        "tutor": "long_term_consent",
        "sales_advisor": "durable_business_state",
        "support_agent": "durable_business_state",
        "auditor": "durable_business_state",
        "wellness_companion": "session",
    }
    for template_id, scope in expected.items():
        role = role_template(template_id)
        assert role is not None
        assert role.memory_policy.scope == scope
    wellness = role_template("wellness_companion")
    assert wellness is not None
    assert wellness.memory_policy.pii_masking is True
    assert wellness.memory_policy.retention_days == 0


@pytest.mark.asyncio
async def test_none_policy_never_reads_memory() -> None:
    org = uuid4()
    repo, service = _stack()
    await repo.insert(_record(organization_id=org, scope="tenant"))
    result = await assemble_memory_context(
        organization_id=org,
        workspace_id=None,
        role=_role("none"),
        service=service,
    )
    assert result.items == ()
    assert result.policy == "none"


@pytest.mark.asyncio
async def test_long_term_consent_requires_consent_expiry_and_subject() -> None:
    org = uuid4()
    ws = uuid4()
    subject = "participant-1"
    repo, service = _stack()
    good = _record(
        organization_id=org,
        scope="long_term_consent",
        workspace_id=ws,
        subject_id=subject,
        title="progreso consentido",
    )
    other_workspace = _record(
        organization_id=org,
        scope="long_term_consent",
        workspace_id=uuid4(),
        subject_id=subject,
        title="otro workspace",
    )
    no_consent = _record(
        organization_id=org,
        scope="long_term_consent",
        workspace_id=ws,
        subject_id=subject,
        title="sin consentimiento",
        consent=False,
    )
    expired = _record(
        organization_id=org,
        scope="long_term_consent",
        workspace_id=ws,
        subject_id=subject,
        title="expirado",
        expires_in_days=-1,
    )
    other_subject = _record(
        organization_id=org,
        scope="long_term_consent",
        workspace_id=ws,
        subject_id="otro",
        title="otro sujeto",
    )
    for record in (good, other_workspace, no_consent, expired, other_subject):
        await repo.insert(record)

    result = await assemble_memory_context(
        organization_id=org,
        workspace_id=ws,
        role=_role("long_term_consent"),
        subject_id=subject,
        conversation_id=None,
        service=service,
    )
    ids = {item["memory_id"] for item in result.items}
    assert ids == {str(good.id)}
    reasons = {item["reason"] for item in result.omitted}
    assert "missing_consent" in reasons
    assert "workspace_mismatch" in reasons
    assert "subject_mismatch" in reasons
    assert "expired_or_deleted" in reasons


@pytest.mark.asyncio
async def test_session_memory_is_conversation_bound_and_masked_for_wellness() -> None:
    org = uuid4()
    ws = uuid4()
    conversation = uuid4()
    repo, service = _stack()
    current = _record(
        organization_id=org,
        scope="session",
        workspace_id=ws,
        conversation_id=conversation,
        title="sesión actual",
    )
    other = _record(
        organization_id=org,
        scope="session",
        workspace_id=ws,
        conversation_id=uuid4(),
        title="otra sesión",
    )
    durable = _record(
        organization_id=org,
        scope="long_term_consent",
        workspace_id=ws,
        conversation_id=conversation,
        title="largo plazo",
    )
    for record in (current, other, durable):
        await repo.insert(record)

    result = await assemble_memory_context(
        organization_id=org,
        workspace_id=ws,
        role=_role("session", consent_required=True, pii_masking=True),
        conversation_id=conversation,
        service=service,
    )
    assert [item["memory_id"] for item in result.items] == [str(current.id)]
    assert "description" not in result.items[0]
    assert any(item["reason"] == "conversation_mismatch" for item in result.omitted)


@pytest.mark.asyncio
async def test_session_without_conversation_fails_closed() -> None:
    org = uuid4()
    repo, service = _stack()
    await repo.insert(_record(organization_id=org, scope="session"))
    result = await assemble_memory_context(
        organization_id=org,
        workspace_id=None,
        role=_role("session"),
        service=service,
    )
    assert result.items == ()
    assert result.omitted[0]["reason"] == "session_without_conversation"


@pytest.mark.asyncio
async def test_workspace_policy_excludes_other_workspace_but_allows_tenant_global() -> None:
    org = uuid4()
    ws = uuid4()
    repo, service = _stack()
    local = _record(
        organization_id=org, scope="workspace", workspace_id=ws, title="local"
    )
    global_record = _record(
        organization_id=org, scope="tenant", workspace_id=None, title="global"
    )
    foreign = _record(
        organization_id=org, scope="workspace", workspace_id=uuid4(), title="ajeno"
    )
    for record in (local, global_record, foreign):
        await repo.insert(record)

    result = await assemble_memory_context(
        organization_id=org,
        workspace_id=ws,
        role=_role("workspace"),
        service=service,
    )
    ids = {item["memory_id"] for item in result.items}
    assert ids == {str(local.id), str(global_record.id)}
