# =============================================================================
# Workflow Architect — observabilidad y estados del proceso creativo.
#
# Un único lugar para:
#   * estados canónicos que consume el portal (UNDERSTANDING … BLOCKED);
#   * session id de diseño y hash del plan (para patch seguro);
#   * logging estructurado de las fases (sin prompt crudo ni secretos);
#   * feature flag de rollback UI (RAG_WORKFLOW_ARCHITECT_ENABLED).
# =============================================================================
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any
from uuid import uuid4

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

#: Versión del planificador; viaja en cada respuesta y en los logs.
PLANNER_VERSION = "architect/1.2.0"

#: Estados del proceso creativo (contrato con el portal).
STATE_UNDERSTANDING = "UNDERSTANDING"
STATE_DISCOVERING = "DISCOVERING"
STATE_PLANNING = "PLANNING"
STATE_NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
STATE_NEEDS_CONFIGURATION = "NEEDS_CONFIGURATION"
STATE_VALIDATING = "VALIDATING"
STATE_DRAFT_READY = "DRAFT_READY"
STATE_BLOCKED = "BLOCKED"

DESIGN_STATES: tuple[str, ...] = (
    STATE_UNDERSTANDING,
    STATE_DISCOVERING,
    STATE_PLANNING,
    STATE_NEEDS_CLARIFICATION,
    STATE_NEEDS_CONFIGURATION,
    STATE_VALIDATING,
    STATE_DRAFT_READY,
    STATE_BLOCKED,
)

#: Errores que representan una dependencia del tenant, no un plan inválido.
REQUIREMENT_ERROR_CODES: frozenset[str] = frozenset(
    {
        "missing.managed_db",
        "missing.agents",
        "missing.agent",
        "missing.knowledge_bases",
        "missing.integration",
        "missing.notification_channel",
        "missing.action_id",
    }
)


class PlanHashMismatch(ValueError):
    """El plan enviado por el cliente no coincide con el que se está editando."""


class ArchitectBlocked(ValueError):
    """El borrador no puede persistirse: no hay grafo compilable."""

    def __init__(
        self,
        *,
        state: str,
        issues: list[dict[str, Any]],
        requirements: list[dict[str, Any]],
        clarifications: list[dict[str, Any]],
        session_id: str,
    ) -> None:
        super().__init__("el diseño tiene bloqueos que impiden guardar el borrador")
        self.state = state
        self.issues = issues
        self.requirements = requirements
        self.clarifications = clarifications
        self.session_id = session_id

    def payload(self) -> dict[str, Any]:
        return {
            "saved": False,
            "state": self.state,
            "session_id": self.session_id,
            "issues": self.issues,
            "requirements": self.requirements,
            "clarifications": self.clarifications,
        }


def new_session_id() -> str:
    return f"ds_{uuid4().hex}"


def normalize_session_id(value: str | None) -> str:
    """Reutiliza un id de sesión válido; si no, crea uno nuevo."""
    text = str(value or "").strip()
    if text.startswith("ds_") and 6 <= len(text) <= 80 and all(
        char.isalnum() or char in "_-" for char in text
    ):
        return text
    return new_session_id()


def plan_hash(plan: Any) -> str:
    """Hash canónico del plan semántico (detecta parches sobre planes viejos)."""
    if hasattr(plan, "model_dump"):
        payload = plan.model_dump(mode="json")
    else:
        payload = plan
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(str(prompt or "").encode("utf-8")).hexdigest()


def provider_info(provider: Any, model: str | None) -> dict[str, Any]:
    """Provider/modelo para observabilidad. Nunca incluye credenciales."""
    name = type(provider).__name__ if provider is not None else None
    configured = model
    if not configured and provider is not None:
        for attr in ("model", "model_name", "default_model"):
            value = getattr(provider, attr, None)
            if isinstance(value, str) and value:
                configured = value
                break
    return {"provider": name, "model": str(configured)[:120] if configured else None}


def elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def design_state(
    *,
    graph: dict[str, Any] | None,
    issues: list[Any],
    clarifications: list[dict[str, Any]],
    requirements: list[dict[str, Any]],
    readiness: dict[str, Any] | None,
    fallback_used: bool,
) -> str:
    """Estado canónico: lo que la UI puede mostrar sin mentir.

    Reglas:
      * sin grafo y solo faltan dependencias del tenant → NEEDS_CONFIGURATION;
      * sin grafo, con preguntas → NEEDS_CLARIFICATION;
      * grafo + preguntas → NEEDS_CLARIFICATION;
      * grafo + dependencias/permisos/readiness en error → NEEDS_CONFIGURATION;
      * fallback heurístico → nunca DRAFT_READY (requiere revisión humana);
      * resto → DRAFT_READY.
    """
    errors = [issue for issue in issues if getattr(issue, "severity", "") == "error"]
    if graph is None:
        depends_on_tenant = bool(requirements) and all(
            getattr(issue, "code", "") in REQUIREMENT_ERROR_CODES
            or bool(getattr(issue, "requirement", None))
            for issue in errors
        )
        if depends_on_tenant:
            return STATE_NEEDS_CONFIGURATION
        if clarifications:
            return STATE_NEEDS_CLARIFICATION
        return STATE_BLOCKED

    if fallback_used or clarifications:
        return STATE_NEEDS_CLARIFICATION

    readiness_errors = [
        check for check in (readiness or {}).get("checks", []) if check.get("status") == "error"
    ]
    permission_issues = [
        issue for issue in issues if getattr(issue, "code", "").startswith("permission.")
    ]
    if requirements or readiness_errors or permission_issues:
        return STATE_NEEDS_CONFIGURATION
    return STATE_DRAFT_READY


def build_blockers(
    *,
    issues: list[Any],
    requirements: list[dict[str, Any]],
    readiness: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Lista única y legible de lo que impide considerar el flujo listo."""
    blockers: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, code: str, message: str, requirement: str | None = None) -> None:
        key = (code, message)
        if key in seen:
            return
        seen.add(key)
        blockers.append(
            {"kind": kind, "code": code, "message": message, "requirement": requirement}
        )

    for item in requirements:
        add(
            "requirement",
            str(item.get("code") or "requirement"),
            str(item.get("message") or item.get("requirement") or ""),
            str(item.get("requirement") or "") or None,
        )
    for issue in issues:
        code = str(getattr(issue, "code", ""))
        if getattr(issue, "severity", "") == "error" or code.startswith("permission."):
            if getattr(issue, "requirement", None):
                continue  # ya representado en requirements
            add("issue", code, str(getattr(issue, "message", "")))
    for check in (readiness or {}).get("checks", []) or []:
        if check.get("status") == "error":
            add(
                "readiness",
                str(check.get("key") or "readiness"),
                str(check.get("message") or ""),
            )
    return blockers


def fallback_payload(reason_code: str, prompt: str) -> dict[str, Any]:
    """Fallback informado (nunca silencioso) y en modo borrador."""
    limitations = [
        "El plan se generó con reglas determinísticas, no interpretando el requerimiento completo.",
        "Revisa los pasos, los datos y los destinatarios antes de publicar.",
        "La publicación requiere confirmación explícita de este borrador.",
    ]
    if reason_code == "invalid_llm_response":
        limitations.insert(0, "El modelo respondió un formato inválido; no se usó su salida.")
    else:
        limitations.insert(0, "El modelo no estuvo disponible; no se usó su salida.")
    return {
        "used": True,
        "reason_code": reason_code,
        "limitations": limitations,
        "requires_review": True,
        "publishable": False,
        "preserved_requirement": str(prompt or "")[:600],
    }


def log_design(event: str, **fields: Any) -> None:
    """Log estructurado del diseño. No incluye prompt ni credenciales."""
    try:
        logger.info(event, **{key: value for key, value in fields.items() if value is not None})
    except Exception:  # noqa: BLE001 — la observabilidad nunca rompe el diseño
        pass


def architect_ui_enabled() -> bool:
    """Feature flag de rollback del camino canónico.

    Lee el entorno en cada llamada (testeable y reversible sin reiniciar el
    proceso en desarrollo). `RAG_WORKFLOW_ARCHITECT_ENABLED=false` vuelve al
    Copilot legacy en el portal.
    """
    raw = os.getenv("RAG_WORKFLOW_ARCHITECT_ENABLED")
    if raw is None:
        try:
            from src.core.config import get_settings

            return bool(getattr(get_settings(), "WORKFLOW_ARCHITECT_ENABLED", True))
        except Exception:  # noqa: BLE001
            return True
    return raw.strip().lower() not in ("0", "false", "no", "off", "disabled")


__all__ = [
    "ArchitectBlocked",
    "DESIGN_STATES",
    "PLANNER_VERSION",
    "PlanHashMismatch",
    "STATE_BLOCKED",
    "STATE_DISCOVERING",
    "STATE_DRAFT_READY",
    "STATE_NEEDS_CLARIFICATION",
    "STATE_NEEDS_CONFIGURATION",
    "STATE_PLANNING",
    "STATE_UNDERSTANDING",
    "STATE_VALIDATING",
    "architect_ui_enabled",
    "build_blockers",
    "design_state",
    "elapsed_ms",
    "fallback_payload",
    "log_design",
    "new_session_id",
    "normalize_session_id",
    "plan_hash",
    "prompt_hash",
    "provider_info",
]
