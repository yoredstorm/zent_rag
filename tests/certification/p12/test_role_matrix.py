"""P12 horizontal role matrix — same engine, explicit safe boundaries."""
from __future__ import annotations

import pytest

from src.platform.studio.contracts import RoleProfileV1
from src.platform.studio.policy import capability_decision
from src.platform.studio.templates import role_template, workflow_proposal

ROLES = {
    "sales_advisor": ("durable_business_state", "require_approval", "medium"),
    "mentor": ("long_term_consent", "propose_actions", "low"),
    "tutor": ("long_term_consent", "propose_actions", "low"),
    "auditor": ("durable_business_state", "propose_actions", "high"),
    "support_agent": ("durable_business_state", "propose_actions", "medium"),
    "wellness_companion": ("session", "answer_only", "regulated"),
}


@pytest.mark.parametrize("role_id", sorted(ROLES))
def test_gold_role_contract_is_explicit_and_reusable(role_id: str) -> None:
    role = role_template(role_id)
    assert isinstance(role, RoleProfileV1)
    expected_scope, expected_autonomy, expected_risk = ROLES[role_id]
    assert role.memory_policy.scope == expected_scope
    assert role.autonomy_level == expected_autonomy
    assert role.risk_class == expected_risk
    assert role.safety.no_automatic_irreversible_action is True
    assert role.allowed_capabilities
    assert workflow_proposal(role_id) is not None


def test_wellness_is_non_clinical_and_cannot_write() -> None:
    role = role_template("wellness_companion")
    assert role is not None
    assert role.safety.no_medical_diagnosis is True
    assert role.safety.no_psychotherapy_claim is True
    assert role.safety.crisis_escalation is True
    assert "clinical.diagnose" not in role.allowed_capabilities
    assert "clinical.prescribe" not in role.allowed_capabilities
    decision = capability_decision(
        role,
        capability_ref="clinical.diagnose",
        actor_permissions=frozenset({"external_actions:execute"}),
        read_only=False,
    )
    assert decision.allowed is False


def test_regulated_roles_never_execute_irreversible_writes() -> None:
    for role_id in ("auditor", "wellness_companion"):
        role = role_template(role_id)
        assert role is not None
        decision = capability_decision(
            role,
            capability_ref="payments.checkout.create",
            actor_permissions=frozenset({"external_actions:execute"}),
            read_only=False,
        )
        assert decision.allowed is False or decision.requires_approval is True


def test_all_gold_roles_share_the_same_workflow_authority() -> None:
    # El vertical no cambia el motor: las seis plantillas son RoleProfileV1 y
    # producen propuestas sobre el mismo compilador/WorkflowGraph.
    for role_id in ROLES:
        role = role_template(role_id)
        assert role is not None
        assert role.schema_id == "zent.role/v1"
