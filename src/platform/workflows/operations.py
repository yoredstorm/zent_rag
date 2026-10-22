# =============================================================================
# Consola de operación. No guarda estados nuevos ni abre otro bus.
#
# Los estados de pantalla salen de workflow_instances.status y, si el WAIT lo
# dice, de waiting_event_type / waiting_for. La señal temprana queda en
# workflow_signals (status pending) hasta que el proceso espera.
# =============================================================================
from __future__ import annotations

from typing import Any

STORED_STATUSES = frozenset(
    {"NEW", "RUNNING", "WAITING", "SUSPENDED", "COMPLETED", "FAILED", "CANCELLED", "EXPIRED"}
)

VIEW_STATUSES = (
    "running",
    "waiting",
    "pending_approval",
    "completed",
    "failed",
    "cancelled",
    "expired",
    "needs_human",
    "retry_scheduled",
)

_APPROVAL_EVENTS = frozenset({"approval.decided", "workflow.approval"})
_HUMAN_EVENTS = frozenset({"human", "workflow.human"})

ACTION_PERMISSION = {
    "cancel": "workflows:run",
    "suspend": "workflows:run",
    "resume": "workflows:run",
    "expire": "workflows:run",
    "sandbox_replay": "workflows:run",
}

_OPS_METRICS: dict[str, Any] = {}


def operational_status(instance: dict[str, Any]) -> str:
    """Vista de operación. Si el estado guardado no es del motor, se devuelve tal cual."""
    stored = str(instance.get("status") or "")
    if stored not in STORED_STATUSES:
        return stored or "unknown"
    event = str(instance.get("waiting_event_type") or "")
    waiting = instance.get("waiting_for") if isinstance(instance.get("waiting_for"), dict) else {}
    if stored == "WAITING" and event in _APPROVAL_EVENTS:
        return "pending_approval"
    if stored == "SUSPENDED" or (stored == "WAITING" and event in _HUMAN_EVENTS):
        return "needs_human"
    if stored == "WAITING" and waiting.get("retry_at"):
        return "retry_scheduled"
    return {
        "NEW": "running",
        "RUNNING": "running",
        "WAITING": "waiting",
        "COMPLETED": "completed",
        "FAILED": "failed",
        "CANCELLED": "cancelled",
        "EXPIRED": "expired",
    }[stored]


def classify_fault(text: str) -> str:
    folded = str(text or "").lower()
    if any(token in folded for token in ("permiso", "policy", "unauthorized", "política")):
        return "policy"
    if any(token in folded for token in ("contract", "contrato", "contract_mismatch")):
        return "contract"
    if any(token in folded for token in ("confidence", "confianza", "low_confidence")):
        return "low_confidence"
    if any(token in folded for token in ("config", "credencial", "needs_configuration")):
        return "configuration"
    return "technical"


def signal_decision(
    *,
    instance_status: str,
    duplicate: bool,
    correlation_matches: bool,
    event_matches: bool,
) -> str:
    """Decisión del inbox real. No ejecuta el workflow dos veces."""
    if duplicate:
        return "duplicate_ignored"
    if not correlation_matches:
        return "correlation_mismatch"
    if not event_matches:
        return "event_mismatch"
    if instance_status != "WAITING":
        return "queued"
    return "resume_once"


def authorize_action(action: str, permissions: frozenset[str] | set[str]) -> bool:
    needed = ACTION_PERMISSION.get(action)
    if not needed:
        return False
    granted = set(permissions)
    return needed in granted or "admin:*" in granted


def sandbox_replay_allowed(*, sandbox: bool) -> bool:
    """Depurar no reejecuta pagos ni escrituras de producción."""
    return bool(sandbox)


def redact_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in (payload or {}).items():
        folded = str(key).lower()
        if any(part in folded for part in ("password", "secret", "token", "api_key", "authorization")):
            clean[str(key)] = "[redactado]"
        elif isinstance(value, dict):
            clean[str(key)] = redact_payload(value)
        else:
            clean[str(key)] = value
    return clean


def project_business_timeline(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    """trigger, señal, reanudación y resultado a partir de runs y signals ya persistidos."""
    steps: list[dict[str, Any]] = []
    for run in timeline.get("runs") or []:
        seq = int(run.get("instance_seq") or 1)
        steps.append(
            {
                "step": "trigger" if seq <= 1 else "resume",
                "at": run.get("started_at"),
                "status": run.get("status"),
                "duration_ms": run.get("duration_ms"),
                "fault": classify_fault(str(run.get("error") or "")) if run.get("error") else None,
            }
        )
    for signal in timeline.get("signals") or []:
        steps.append(
            {
                "step": "signal",
                "at": signal.get("received_at"),
                "event_type": signal.get("event_type"),
                "status": signal.get("status"),
                "payload": redact_payload(signal.get("payload") if isinstance(signal.get("payload"), dict) else {}),
            }
        )
        if signal.get("status") == "consumed":
            steps.append(
                {
                    "step": "resume_signal",
                    "at": signal.get("consumed_at"),
                    "event_type": signal.get("event_type"),
                }
            )
    for event in timeline.get("events") or []:
        kind = str(event.get("kind") or "")
        step = "decision" if kind in {"causal_link", "adaptive_route"} else "event"
        steps.append(
            {
                "step": step,
                "at": event.get("created_at"),
                "kind": kind,
                "node_id": event.get("node_id"),
                "payload": redact_payload(event.get("payload") if isinstance(event.get("payload"), dict) else {}),
            }
        )
    return steps


def chaos_observation(name: str, *, dependency_available: bool) -> dict[str, Any]:
    """Si Redis, la DB o el proveedor no están, el ensayo no se marca como pase."""
    if not dependency_available:
        return {
            "name": name,
            "result": "UNVERIFIED",
            "passed": False,
            "reason": "la dependencia no está disponible; no se inventa un éxito",
        }
    return {
        "name": name,
        "result": "OBSERVED",
        "passed": False,
        "reason": "hace falta el motor y el inbox reales para afirmar el desenlace",
    }


def record_transition(status: str) -> None:
    """Métricas Prometheus ya usadas por el proceso. No despliega un colector nuevo."""
    event = {
        "RUNNING": "workflow_start",
        "COMPLETED": "workflow_success",
        "FAILED": "workflow_failure",
        "WAITING": "workflow_waits",
        "EXPIRED": "workflow_expired",
        "CANCELLED": "workflow_cancelled",
    }.get(str(status))
    if event is None:
        return
    try:
        if "ops" not in _OPS_METRICS:
            from prometheus_client import Counter

            _OPS_METRICS["ops"] = Counter(
                "zent_workflow_operations_total",
                "Operación de procesos durables",
                ["event"],
            )
        _OPS_METRICS["ops"].labels(event=event).inc()
    except Exception:  # noqa: BLE001 — la métrica no tumba el proceso
        return
