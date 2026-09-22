# =============================================================================
# Event judgment — el Judgment Fabric consume eventos YA normalizados.
# =============================================================================
# JEV no escucha infraestructura (NATS, colas, webhooks): el dispatcher de
# eventos de Zent normaliza el evento y, sólo si hace falta juicio, llama acá.
#
# Orden no negociable:
#   condiciones determinísticas  →  (si alcanza) acción determinística
#   ↓ si necesita juicio
#   JEV (CandidateSet autorizado)  →  policy  →  el caller ejecuta
#   ↓ si necesita razonamiento
#   AgentRuntime
#
# Este módulo NUNCA ejecuta ni autoriza por sí mismo: devuelve una decisión
# con política aplicada para que el caller (event dispatcher) ejecute.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from src.decision.candidates import CandidateKind, candidate_kind_for_capability

ACTION_DETERMINISTIC = "deterministic"
ACTION_START_WORKFLOW = "start_workflow"
ACTION_ESCALATE_AGENT = "escalate_agent"
ACTION_EXECUTE_TOOL = "execute_tool"
ACTION_CLARIFY = "ask_clarification"
ACTION_HUMAN = "human_review"
ACTION_IGNORE = "ignore"

_KIND_ACTION = {
    CandidateKind.WORKFLOW.value: ACTION_START_WORKFLOW,
    CandidateKind.AGENT.value: ACTION_ESCALATE_AGENT,
    CandidateKind.TOOL.value: ACTION_EXECUTE_TOOL,
}


@dataclass(frozen=True, kw_only=True)
class EventJudgment:
    """Qué hacer con un evento normalizado. El caller ejecuta; acá no se corre."""

    event_type: str
    action: str
    capability: str | None = None
    target_id: str | None = None
    confidence: float = 0.0
    reason: str = ""
    organization_id: str | None = None
    selection: dict[str, Any] | None = None
    policy: dict[str, Any] | None = None
    requires_human: bool = False
    deterministic: bool = False
    jev_used: bool = False
    notes: tuple[str, ...] = ()

    @property
    def executable(self) -> bool:
        return self.action in {
            ACTION_START_WORKFLOW,
            ACTION_ESCALATE_AGENT,
            ACTION_EXECUTE_TOOL,
        } and bool(self.target_id)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "action": self.action,
            "capability": self.capability,
            "target_id": self.target_id,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "executable": self.executable,
            "requires_human": self.requires_human,
            "deterministic": self.deterministic,
            "jev_used": self.jev_used,
            "selection": self.selection,
            "policy": self.policy,
            "notes": list(self.notes),
        }


def normalized_event_type(event: dict[str, Any] | None) -> str:
    """Sólo el tipo normalizado: `inventory.stock.low@v2` → `inventory.stock.low`."""
    raw = str((event or {}).get("event_type") or (event or {}).get("type") or "")
    return raw.split("@v", 1)[0][:120]


async def judge_event(
    event: dict[str, Any] | None,
    *,
    dispatcher: Any,
    deterministic: bool | None = None,
) -> EventJudgment:
    """Juzga un evento normalizado. Sin juicio → acción determinística/ignore."""
    data = dict(event or {})
    event_type = normalized_event_type(data)
    org_raw = data.get("organization_id")
    organization_id = str(org_raw) if org_raw else None
    if not event_type:
        return EventJudgment(
            event_type="",
            action=ACTION_IGNORE,
            reason="missing_event_type",
            organization_id=organization_id,
        )
    # 1) Determinístico primero: si el trigger ya resolvió, no se gasta juicio.
    declared = data.get("deterministic_action")
    is_deterministic = deterministic if deterministic is not None else bool(declared)
    if is_deterministic:
        return EventJudgment(
            event_type=event_type,
            action=ACTION_DETERMINISTIC,
            capability=str(declared or data.get("capability") or "") or None,
            target_id=str(data.get("target_id") or "") or None,
            reason="deterministic_conditions",
            organization_id=organization_id,
            deterministic=True,
        )
    request = str(
        data.get("request") or data.get("question") or data.get("message") or ""
    ).strip()
    if not request:
        return EventJudgment(
            event_type=event_type,
            action=ACTION_IGNORE,
            reason="no_request_in_event",
            organization_id=organization_id,
        )
    capability = str(data.get("capability") or "").strip()
    target_kind = str(data.get("target_kind") or "").strip()
    if not capability and target_kind:
        capability = {
            CandidateKind.AGENT.value: "agent.execute",
            CandidateKind.WORKFLOW.value: "workflow.start",
            CandidateKind.TOOL.value: "tool.execute",
        }.get(target_kind, "")
    if not capability or candidate_kind_for_capability(capability) is None:
        return EventJudgment(
            event_type=event_type,
            action=ACTION_IGNORE,
            capability=capability or None,
            reason="no_capability_hint",
            organization_id=organization_id,
            notes=("el normalizador debe declarar capability o target_kind",),
        )
    if dispatcher is None or organization_id is None:
        return EventJudgment(
            event_type=event_type,
            action=ACTION_IGNORE,
            capability=capability,
            reason="fabric_unavailable",
            organization_id=organization_id,
        )
    from src.runtime.dispatcher import DispatchRequest

    try:
        org_uuid = UUID(organization_id)
    except (ValueError, TypeError):
        return EventJudgment(
            event_type=event_type,
            action=ACTION_IGNORE,
            capability=capability,
            reason="invalid_organization_id",
        )
    request_obj = DispatchRequest(
        organization_id=org_uuid,
        query=request[:2000],
        permissions=frozenset(str(x) for x in (data.get("permissions") or ())),
        role=str(data.get("role") or "system"),
        tenant_policy=dict(data.get("tenant_policy") or {}),
        budget=dict(data.get("budget") or {}),
        request_id=None,
    )
    decision = _event_decision(capability, data)
    resolution = await dispatcher.resolve_target(decision, request_obj)
    if resolution is None or not resolution.executable:
        reason = (
            getattr(resolution, "policy", None).reason
            if resolution is not None and getattr(resolution, "policy", None) is not None
            else "no_resolution"
        )
        action = (
            ACTION_HUMAN
            if getattr(resolution, "selection", None) is not None
            and resolution.selection.policy_action == "human_review"
            else ACTION_CLARIFY
            if getattr(resolution, "selection", None) is not None
            and resolution.selection.policy_action == "ask_clarification"
            else ACTION_IGNORE
        )
        return EventJudgment(
            event_type=event_type,
            action=action,
            capability=capability,
            reason=str(reason or "selection_not_authorized"),
            organization_id=organization_id,
            confidence=float(
                getattr(getattr(resolution, "selection", None), "confidence", 0.0) or 0.0
            ),
            selection=(
                resolution.selection.to_public_dict() if resolution is not None else None
            ),
            policy=(
                resolution.policy.to_public_dict()
                if resolution is not None and resolution.policy is not None
                else None
            ),
            requires_human=action == ACTION_HUMAN,
        )
    selection = resolution.selection
    kind = selection.kind
    return EventJudgment(
        event_type=event_type,
        action=_KIND_ACTION.get(kind, ACTION_IGNORE),
        capability=capability,
        target_id=selection.target_id,
        confidence=selection.confidence,
        reason=selection.reason,
        organization_id=organization_id,
        selection=selection.to_public_dict(),
        policy=(
            resolution.policy.to_public_dict() if resolution.policy is not None else None
        ),
        requires_human=bool(
            resolution.policy is not None and resolution.policy.requires_human
        ),
        jev_used=selection.jev_used,
        notes=("el caller ejecuta; este módulo no corre acciones",),
    )


def _event_decision(capability: str, event: dict[str, Any]):
    from src.core.domain.decision import ComplexityLevel, RiskLevel, RoutingDecision

    risk_raw = str(event.get("risk") or "").lower()
    risk = RiskLevel.MEDIUM
    for level in RiskLevel:
        if level.value == risk_raw:
            risk = level
            break
    return RoutingDecision(
        capability=capability,
        resolved=True,
        provider="event",
        confidence=1.0,
        complexity=ComplexityLevel.BOUNDED,
        risk=risk,
        metadata={"source": "event_judgment"},
    )
