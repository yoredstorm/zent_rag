# =============================================================================
# Phase 32B — Marketplace como tool de agente
#
# Las acciones instaladas aparecen como tools del agente AUTOMÁTICAMENTE:
# un solo runtime (validation/budget/circuit/evidence/ledger) compartido con
# workflow y API. La política auto_use_policy de la instalación gobierna:
#   NEVER_AUTO        → nunca invocable por el agente
#   AUTO_READ_ONLY    → solo acciones read_only sin aprobación
#   REQUIRE_APPROVAL  → requiere aprobación humana (no auto)
#   WORKFLOW_ONLY     → solo desde workflows (denegado en el agente)
# =============================================================================
from __future__ import annotations

import json

from src.agents.tools.base import Tool, ToolContext, ToolInputError, ToolPermissionError, ToolResult


class MarketplaceActionTool(Tool):
    """Ejecuta una acción de integración instalada (mismo runtime que workflow/API)."""

    name = "marketplace_action"
    description = (
        "Ejecuta una capacidad externa instalada en el Marketplace (SUNAT, identidad, "
        "tasas, etc.) para obtener evidencia verificada del mundo exterior. "
        "Recibe `integration` (slug de la integración instalada, ej. 'sunat'), `action` "
        "(action_id estable, ej. 'peru.taxpayer.lookup'), `inputs` (objeto con los "
        "parámetros que pide la acción) y opcional `purpose`. Nunca inventar datos: "
        "si la acción falla, reporta el error devuelto."
    )
    input_schema = {
        "type": "object",
        "required": ["integration", "action"],
        "properties": {
            "integration": {"type": "string", "minLength": 1},
            "action": {"type": "string", "minLength": 1},
            "inputs": {"type": "object"},
            "purpose": {"type": "string"},
        },
    }
    permission = "external_actions:execute"
    timeout_seconds = 15.0

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        from src.platform.marketplace import catalog
        from src.platform.marketplace import runtime as mkt

        integration_slug = str(arguments.get("integration") or "")
        action_id = str(arguments.get("action") or "")
        inputs = arguments.get("inputs") or {}
        if not isinstance(inputs, dict):
            raise ToolInputError("inputs debe ser un objeto")
        purpose = str(arguments.get("purpose") or "") or None

        action = await catalog.get_action(action_id)
        if action is None:
            return ToolResult(output="", error="acción no encontrada en el catálogo")
        manifest = await catalog.get_manifest(integration_slug)
        if manifest is None or action.get("integration_slug") != integration_slug:
            return ToolResult(output="", error=f"integración '{integration_slug}' no existe o la acción no pertenece")

        installs = await mkt.list_installs(ctx.tenant_id)
        install = next(
            (i for i in installs["installs"] if i["integration"]["slug"] == integration_slug),
            None,
        )
        if install is None:
            return ToolResult(
                output="",
                error=f"integración '{integration_slug}' no está instalada en este workspace",
            )

        policy = (install.get("auto_use_policy") or {}).get(action_id)
        if policy == "NEVER_AUTO":
            raise ToolPermissionError("acción marcada NEVER_AUTO: no es invocable por el agente")
        if policy in ("WORKFLOW_ONLY", "REQUIRE_APPROVAL"):
            raise ToolPermissionError(
                f"acción {action_id} requiere {policy.lower()}: no se ejecuta automáticamente"
            )
        # default: AUTO_READ_ONLY → solo read_only sin aprobación.
        if not bool(action.get("read_only")) or bool(action.get("requires_approval")):
            raise ToolPermissionError("solo acciones read_only pre-aprobadas son automáticas")

        outcome = await mkt.execute_action(
            ctx.tenant_id,
            __import__("uuid").UUID(install["id"]),
            action_id,
            inputs,
            workspace_id=None,
            purpose=purpose,
            agent_run_id=ctx.conversation_id,
            source="agent",
            actor_type="agent",
        )
        if not outcome.ok:
            return ToolResult(
                output=f"{outcome.error_code}: {outcome.error_message}",
                error=outcome.error_message,
                latency_ms=outcome.latency_ms,
            )
        evidence_line = (
            f"[evidence:{outcome.evidence_id}] " if outcome.evidence_id else ""
        )
        payload = {
            k: v for k, v in outcome.data.items()
            if k not in ("retrieved_at", "source")
        }
        return ToolResult(
            output=(
                f"{evidence_line}Resultado verificado de {action.get('integration_name')} "
                f"({action_id}):\n{json.dumps(payload, ensure_ascii=False, default=str)}"
            ),
            latency_ms=outcome.latency_ms,
        )


def register() -> None:
    from src.agents.tools.registry import register_tool

    register_tool(MarketplaceActionTool())
