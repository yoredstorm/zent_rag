# =============================================================================
# Enforcement de la FinalizationPolicy — etapas armadas y holds.
# =============================================================================
# Un stage armado hace que el trigger vigente ESPERE (fail-closed) cuando la
# política resuelve RETRIEVE_MORE, en vez de cerrar con evidencia incompleta y
# búsqueda todavía disponible. Los holds están acotados por etapa.
#
# Scopes de activación (SAFETY FLOOR monotónico, P1-D):
#   effective = global ∪ environment ∪ organización ∪ agente
# Cada scope SUMA etapas; ninguno puede desarmar una etapa armada por otro.
# Una configuración normal (org/agente/workflow/request) no debilita el piso:
# para un downgrade operacional haría falta un mecanismo break-glass explícito
# (no existe: el downgrade está prohibido por construcción).
#
# `closure` NO se arma acá: su fail-closed es el modo estricto del estado
# (`RUNTIME_RUN_STATE_STRICT` / orgs canary), campo real desde S2 de la fase de
# convergencia de autoridad. La fase terminal la aplica la resolución del cierre
# (`finalization_policy.resolve_closure_phase`), no el hold de un trigger.
# =============================================================================
from __future__ import annotations

from typing import Any

#: Etapas que pueden armarse por configuración.
ENFORCE_STAGES: frozenset[str] = frozenset(
    {"termination_trigger", "draft_gate", "answer_gate"}
)

_OFF = {"", "off", "0", "false", "no"}


def parse_stages(raw: Any) -> frozenset[str]:
    """'a,b' -> {a,b} ∩ ENFORCE_STAGES. Vacío/off/apagado = set().

    Un valor desconocido no arma nada (fail-closed del lado seguro).
    """
    if isinstance(raw, bool):
        return ENFORCE_STAGES if raw else frozenset()
    text = str(raw or "").strip()
    if text.lower() in _OFF:
        return frozenset()
    return (
        frozenset(part.strip() for part in text.split(",") if part.strip())
        & ENFORCE_STAGES
    )


def _parse_surface(raw: Any) -> dict[str, str]:
    """'clave=a,b;clave2' -> {clave: 'a,b', clave2: ''}.

    La clave vacía se ignora; el valor vacío significa «usar las etapas
    heredadas» (globales).
    """
    entries: dict[str, str] = {}
    for part in str(raw or "").split(";"):
        item = part.strip()
        if not item:
            continue
        key, _, stages = item.partition("=")
        key = key.strip()
        if key:
            entries[key] = stages.strip()
    return entries


def enforcement_stages(
    settings: Any,
    *,
    config_json: Any = None,
    organization_id: Any = None,
) -> frozenset[str]:
    """Etapas con enforcement activo. SAFETY FLOOR monotónico.

    effective = global ∪ environment ∪ organización ∪ agente.

    Cada scope SUMA etapas: una configuración normal no puede apagar una etapa
    que un scope superior armó (antes el scope más específico reemplazaba al
    global, y `finalization_enforce=false` del agente desarmaba el fail-closed).
    El valor vacío o `false` de un scope no aporta etapas; nunca resta.
    """
    global_stages = parse_stages(getattr(settings, "RUNTIME_FINALIZATION_ENFORCE", ""))
    stages: set[str] = set(global_stages)

    by_env = _parse_surface(
        getattr(settings, "RUNTIME_FINALIZATION_ENFORCE_BY_ENV", "")
    )
    env_name = str(getattr(settings, "ENVIRONMENT", "") or "").strip()
    if env_name and env_name in by_env:
        raw = by_env[env_name]
        stages |= set(parse_stages(raw) if raw else global_stages)

    overrides = _parse_surface(
        getattr(settings, "RUNTIME_FINALIZATION_ENFORCE_ORGS", "")
    )
    if organization_id is not None and str(organization_id) in overrides:
        raw = overrides[str(organization_id)]
        stages |= set(parse_stages(raw) if raw else global_stages)

    runtime = config_json.get("runtime") if isinstance(config_json, dict) else None
    if isinstance(runtime, dict) and runtime.get("finalization_enforce") is not None:
        stages |= set(parse_stages(runtime.get("finalization_enforce")))

    return frozenset(stages)


def should_hold_trigger(
    decision: Any,
    *,
    stage: str,
    enforced: frozenset[str],
    holds_used: int = 0,
    max_holds: int = 1,
) -> bool:
    """¿El trigger debe esperar en vez de cerrar? (enforcement, fail-closed)

    Se espera solo cuando la política resuelve RETRIEVE_MORE (evidencia
    incompleta y búsqueda disponible) y la etapa está armada. Acotado por
    `max_holds`: un trigger nunca queda bloqueado más de lo permitido.
    """
    return bool(
        stage in enforced
        and decision is not None
        and str(getattr(decision, "action", "")) == "RETRIEVE_MORE"
        and int(holds_used) < int(max_holds)
    )


__all__ = [
    "ENFORCE_STAGES",
    "enforcement_stages",
    "parse_stages",
    "should_hold_trigger",
]
