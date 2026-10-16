# =============================================================================
# Conversation Router — un mensaje de una conversación con un proceso durable
# vivo reanuda la instancia en vez de reinterpretarse desde cero.
#
# Regla: ANTES de dejar que el Decision Engine / turn intent trate cada
# mensaje como solicitud independiente, se verifica si existe una
# WorkflowInstance WAITING para conversation_id esperando conversation.message.
# Si existe: signal + resume (el workflow continúa donde estaba).
# Si no existe: el routing normal decide (y puede iniciar un proceso).
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import UUID

from src.infrastructure.observability.logging_config import get_logger
from src.platform.workflows.instances import (
    find_waiting_instance_by_conversation,
    get_instance,
    signal_workflow_instance,
)

logger = get_logger(__name__)

CONVERSATION_EVENT = "conversation.message"


def extract_run_answer(run_body: dict[str, Any] | None) -> str | None:
    """Respuesta del segmento reanudado (último texto emitido por los nodos)."""
    if not isinstance(run_body, dict):
        return None
    result = run_body.get("result") or {}
    summary = result.get("summary") or []
    if summary:
        return str(summary[-1])
    if run_body.get("error"):
        return None
    return None


async def resume_conversation_message(
    *,
    organization_id: UUID,
    conversation_id: UUID | str,
    message: str,
    user_id: UUID | str | None = None,
    participant_id: str | None = None,
    channel: str = "chat",
    message_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Reanuda la instancia de esta conversación si espera el mensaje.

    Devuelve None cuando no hay proceso vivo (el caller sigue con el routing
    normal)."""
    try:
        cid = UUID(str(conversation_id))
    except (ValueError, TypeError):
        return None
    instance = await find_waiting_instance_by_conversation(organization_id, cid)
    if instance is None:
        return None
    payload: dict[str, Any] = {
        "text": message,
        "conversation_id": str(cid),
        "channel": channel,
    }
    if user_id is not None:
        payload["user_id"] = str(user_id)
    if participant_id:
        payload["participant_id"] = participant_id
    if extra:
        payload.update({k: v for k, v in extra.items() if k not in payload})
    out = await signal_workflow_instance(
        organization_id=organization_id,
        event_type=CONVERSATION_EVENT,
        correlation={"conversation_id": str(cid)},
        payload=payload,
        idempotency_key=f"msg:{message_id}" if message_id else None,
        source="conversation",
    )
    results = out.get("results") or []
    run = (results[0].get("run") if results else None) or {}
    fresh = await get_instance(organization_id, UUID(str(instance["id"])))
    return {
        "instance_id": instance["id"],
        "signal_id": out.get("signal_id"),
        "signal_status": out.get("status"),
        "run_id": run.get("run_id"),
        "run_status": run.get("status"),
        "answer": extract_run_answer(run),
        "instance_status": (fresh or {}).get("status"),
        "instance": fresh,
    }
