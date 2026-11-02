# =============================================================================
# P20-11 (MVP temporal) - validación manual de pago.
# =============================================================================
# NODO TEMPORAL. Se elimina cuando se integre Stripe/PSP real.
# No cobra, no crea órdenes y no acepta "ya pagué" del cliente: exige una
# aprobación humana verificable emitida por el motor de workflows.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.platform.workflows.nodes import NodeContext, NodeOutcome

MANUAL_PAYMENT_NODE_TYPE = "manual_payment_validation"
MANUAL_PAYMENT_CAPABILITY = "payments.manual.validate"
MANUAL_PAYMENT_PROVIDER = "manual_mvp"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _money_text(value: Any) -> str:
    try:
        return str(Decimal(str(value)).quantize(Decimal("0.01")))
    except (InvalidOperation, TypeError, ValueError):
        return _text(value)


async def execute_manual_payment_validation(rctx: NodeContext) -> NodeOutcome:
    """Valida un pago con aprobación humana, solo para MVP/staging."""
    from src.core.config import get_settings
    from src.platform.workflows.approvals import (
        ApprovalInvalid,
        resolve_verified_approval,
    )
    from src.platform.workflows.nodes import NodeOutcome, _create_approval, _resolve_ref

    if str(get_settings().ENVIRONMENT or "").lower() == "production":
        return NodeOutcome(
            error=(
                "MANUAL_PAYMENT_DISABLED_IN_PRODUCTION: usa el proveedor de "
                "pagos real"
            )
        )

    cfg = rctx.node.config or {}
    order_id = _text(_resolve_ref(cfg.get("order_id") or "", rctx))
    amount = _money_text(_resolve_ref(cfg.get("amount") or "", rctx))
    currency = _text(_resolve_ref(cfg.get("currency") or "PEN", rctx)) or "PEN"
    payment_reference = _text(
        _resolve_ref(cfg.get("payment_reference") or "", rctx)
    )
    instructions = _text(
        _resolve_ref(
            cfg.get("instructions")
            or "Pago manual MVP: verifica el abono y aprueba este paso.",
            rctx,
        )
    )
    if not order_id:
        return NodeOutcome(
            error="MANUAL_PAYMENT_ORDER_REQUIRED: falta order_id para validar"
        )
    try:
        expires_minutes = max(1, int(cfg.get("expires_minutes") or 1440))
    except (TypeError, ValueError):
        expires_minutes = 1440

    payload = {
        "mode": "manual_mvp",
        "temporary": True,
        "provider": MANUAL_PAYMENT_PROVIDER,
        "order_id": order_id,
        "amount": amount,
        "currency": currency,
        "payment_reference": payment_reference,
        "instructions": instructions,
        "disclosure": (
            "VALIDACIÓN MANUAL TEMPORAL. Reemplazar por Stripe/PSP real."
        ),
    }

    if rctx.simulate:
        return NodeOutcome(
            simulated=True,
            planned={
                "kind": "manual_payment_validation",
                "order_id": order_id,
                "amount": amount,
                "currency": currency,
            },
            output={
                **payload,
                "status": "pending",
                "approval_id": f"sim-manual-payment-{rctx.node_id}",
                "simulated": True,
            },
            control="wait_approval",
        )

    try:
        approval = await resolve_verified_approval(
            rctx,
            rctx.node,
            capability_ref=MANUAL_PAYMENT_CAPABILITY,
            consume=True,
        )
    except ApprovalInvalid as exc:
        if exc.code == "approval_already_consumed":
            return NodeOutcome(
                error=(
                    "MANUAL_PAYMENT_ALREADY_CONSUMED: la aprobación ya se usó "
                    "para este nodo"
                )
            )
        approval_id = await _create_approval(
            rctx.execution,
            rctx.node_id,
            action="Validar pago manual (MVP temporal)",
            summary=(
                f"Validar pago manual {currency} {amount} "
                f"para pedido {order_id}"
            )[:400],
            requested_by=rctx.execution.actor_id,
            expires_minutes=expires_minutes,
            context=payload,
            capability_ref=MANUAL_PAYMENT_CAPABILITY,
            target_node_id=rctx.node_id,
            approval_scope={
                "scope_type": "node",
                "node_id": rctx.node_id,
                "order_id": order_id,
                "amount": amount,
                "currency": currency,
            },
        )
        return NodeOutcome(
            output={
                **payload,
                "status": "pending",
                "approval_id": str(approval_id),
            },
            control="wait_approval",
        )

    return NodeOutcome(
        output={
            **payload,
            "status": "paid",
            "approval_id": approval.approval_id,
            "verified_by": approval.decided_by,
            "validated_at": datetime.now(timezone.utc).isoformat(),
            "payment_reference": payment_reference or approval.approval_id,
        }
    )


def register_manual_payment_node(registry) -> None:
    """Registra el nodo temporal. Quitar esta llamada al integrar Stripe."""
    from src.platform.workflows.node_catalog import metadata_for
    from src.platform.workflows.nodes import NEEDS_APPROVAL

    registry.register(
        MANUAL_PAYMENT_NODE_TYPE,
        version=1,
        label="Validación manual de pago (MVP temporal)",
        category="business",
        risk_level="critical",
        capabilities=frozenset({NEEDS_APPROVAL}),
        inputs={"in": {"type": "json"}},
        outputs={"out": {"type": "json"}},
        execute=execute_manual_payment_validation,
        **metadata_for(MANUAL_PAYMENT_NODE_TYPE),
    )
