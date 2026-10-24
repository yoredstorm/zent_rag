# =============================================================================
# Contrato de salida tipado — un fallo no es "otro booleano".
#
# Los puertos son estables y no dependen del proveedor. El runtime y la UI
# usan el mismo catálogo; un fake, timeout o skip nunca se convierte en éxito.
# =============================================================================
from __future__ import annotations

from typing import Any

TYPED_PORTS: tuple[str, ...] = (
    "success",
    "not_found",
    "invalid_input",
    "timeout",
    "retryable_error",
    "unauthorized",
    "needs_human",
    "compensated",
)

_FAILURE_PORT: dict[str, str] = {
    "": "needs_human",
    "missing_data": "invalid_input",
    "knowledge_not_found": "not_found",
    "not_found": "not_found",
    "insufficient_evidence": "not_found",
    "contract_mismatch": "invalid_input",
    "invalid_input": "invalid_input",
    "timeout": "timeout",
    "provider_unavailable": "retryable_error",
    "retryable_error": "retryable_error",
    "unauthorized_tool": "unauthorized",
    "unauthorized": "unauthorized",
    "human_requested": "needs_human",
    "user_cancelled": "needs_human",
    "low_confidence": "needs_human",
}

_PORT_DEFAULTS: dict[str, dict[str, Any]] = {
    "success": {"retryable": False, "requires_human": False},
    "not_found": {"retryable": False, "requires_human": False},
    "invalid_input": {"retryable": False, "requires_human": True},
    "timeout": {"retryable": True, "requires_human": False},
    "retryable_error": {"retryable": True, "requires_human": False},
    "unauthorized": {"retryable": False, "requires_human": True},
    "needs_human": {"retryable": False, "requires_human": True},
    "compensated": {"retryable": False, "requires_human": False},
}


def port_for_failure(failure_mode: str | None) -> str:
    return _FAILURE_PORT.get(str(failure_mode or "").strip().lower(), "needs_human")


def port_for_message(message: str | None) -> str:
    folded = str(message or "").lower()
    if "timeout" in folded or "agotó el tiempo" in folded:
        return "timeout"
    if "permiso" in folded or "unauthorized" in folded or "no autoriz" in folded:
        return "unauthorized"
    if "no encontr" in folded or "not found" in folded or "sin evidencia" in folded:
        return "not_found"
    if "inválid" in folded or "invalid" in folded or "contrato" in folded:
        return "invalid_input"
    if "proveedor" in folded or "provider" in folded or "reintent" in folded:
        return "retryable_error"
    return "needs_human"


def typed_port_for_decision(
    decision: str,
    *, failure_mode: str | None = None, control: str | None = None
) -> str:
    kind = str(decision or "").lower()
    mode = str(failure_mode or "").strip().lower()
    if kind == "compensation":
        return "compensated"
    if kind == "transition" and not mode:
        return "success"
    if kind == "wait":
        return "needs_human"
    if kind == "intervention":
        return "needs_human"
    if kind == "clarification":
        return "invalid_input"
    if mode:
        return port_for_failure(mode)
    if str(control or "") == "stop_success":
        return "success"
    return "needs_human"


def error_contract(
    failure_mode: str | None,
    message: str = "",
    *,
    code: str | None = None,
    port: str | None = None,
    retryable: bool | None = None,
    requires_human: bool | None = None,
) -> dict[str, Any]:
    resolved = port or port_for_failure(failure_mode)
    if resolved not in TYPED_PORTS:
        resolved = "needs_human"
    defaults = _PORT_DEFAULTS[resolved]
    return {
        "typed_port": resolved,
        "code": str(code or failure_mode or resolved)[:120],
        "message": str(message or "")[:500],
        "retryable": bool(defaults["retryable"] if retryable is None else retryable),
        "requires_human": bool(
            defaults["requires_human"] if requires_human is None else requires_human
        ),
    }


def attach_typed_port(
    output: dict[str, Any] | None,
    *,
    failure_mode: str | None = None,
    port: str | None = None,
) -> dict[str, Any]:
    result = dict(output or {})
    result["typed_port"] = port or port_for_failure(failure_mode)
    return result


__all__ = [
    "TYPED_PORTS",
    "attach_typed_port",
    "error_contract",
    "port_for_failure",
    "port_for_message",
    "typed_port_for_decision",
]
