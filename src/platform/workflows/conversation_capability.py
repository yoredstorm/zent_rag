# =============================================================================
# Capability `conversation.send` — mensaje saliente al cliente
# =============================================================================
# Un workflow portable declara `conversation.send` (y el evento
# `conversation.message`), nunca "WhatsApp" ni "webhook del canal". El binding
# del tenant resuelve el canal: hoy in_app/email/webhook vía notifyv2 y los
# canales externos cuando estén conectados (nunca se simula un envío que no
# existe: se devuelve NEEDS_CONFIGURATION).
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import UUID

from src.platform.workflows.bindings import BindingError

#: Canales soportados por el executor v1 (el resto es NEEDS_CONFIGURATION).
SUPPORTED_CHANNELS: tuple[str, ...] = ("in_app", "email", "webhook", "all")

CHANNEL_LABELS: dict[str, str] = {
    "slack": "Slack",
    "microsoft-teams": "Microsoft Teams",
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
    "messenger": "Messenger",
}


async def execute_conversation_capability(
    organization_id: UUID,
    capability_ref: str,
    inputs: dict[str, Any],
    *,
    workspace_id: UUID | None = None,
    instance_id: Any = None,
    node_id: str | None = None,
    workflow_id: Any = None,
    run_id: Any = None,
    binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`conversation.send` → notificación/mensaje al cliente del proceso."""
    if capability_ref != "conversation.send":
        raise BindingError(
            "CAPABILITY_UNKNOWN", f"capacidad de conversación no soportada: {capability_ref}"
        )
    config = dict((binding or {}).get("config") or {})
    channel = str(inputs.get("channel") or config.get("channel") or "in_app").lower()
    if channel not in SUPPORTED_CHANNELS:
        label = CHANNEL_LABELS.get(channel, channel)
        raise BindingError(
            "NEEDS_CONFIGURATION",
            f"Necesitas conectar {label} para enviar por ese canal.",
        )
    message = str(inputs.get("message") or inputs.get("text") or "").strip()
    if not message:
        raise BindingError("CONTRACT_INVALID", "conversation.send requiere message")
    title = str(inputs.get("title") or config.get("title") or "Mensaje")
    conversation_id = inputs.get("conversation_id") or (
        str(instance_id) if instance_id else None
    )
    from src.platform.notifyv2.notifications import notify

    channels = None if channel == "all" else {channel}
    try:
        result = await notify(
            organization_id,
            str(inputs.get("event_type") or "workflow.message"),
            title,
            message,
            {"conversation_id": conversation_id, "workflow_instance_id": str(instance_id or "")},
            channels=channels,
        )
    except Exception as exc:  # noqa: BLE001
        raise BindingError("PROVIDER_ERROR", f"envío falló: {str(exc)[:200]}") from exc
    return {
        "sent": bool(
            result.get("in_app") or result.get("email") or result.get("webhook_deliveries")
        ),
        "channel": channel,
        "conversation_id": conversation_id,
        "message": message,
    }
