# =============================================================================
# Validación de configuraciones contradictorias (P1-E del hardening).
# =============================================================================
# Inventario heredado de la fase de convergencia de autoridad: NO se inventa
# una segunda matriz de combinaciones. Las reglas de acá leen los MISMOS flags
# del inventario (`docs/architecture/ownership/07-flags-registry.md`, sección
# «Combinaciones contradictorias (pinneadas)» y `02-duplicated-authorities.md`
# P1-6) y los clasifican:
#
#   INVALID ............ postura contradictoria: la instancia NO arranca
#                        (`Settings` falla en la construcción -> composition
#                        root/API/worker no levantan).
#   DANGEROUS .......... protección declarada sin efecto: warning en dev,
#                        error en producción salvo acknowledgement explícito
#                        (`RUNTIME_CONFIG_ACK_DANGEROUS=<codes>`).
#   VALID DEGRADATION .. documentado y permitido (p. ej. canary 0 = off).
#   EXPERIMENT ......... shadow del contrato: observa, no cambia autoridad.
#
# Combinaciones resueltas POR CONSTRUCCIÓN (ya no son config inválida):
#   * `RUNTIME_RUN_STATE_STRICT=on` + override de agente `strict_run_state=false`
#     -> el piso es monotónico (P1-D): el override no debilita, se ignora.
#   * `RUNTIME_FINALIZATION_ENFORCE=...` + override de agente `false`
#     -> el piso es monotónico (P1-D): el override solo suma etapas.
#   * `JEV_SHADOW_MODE=true` + `DECISION_ROUTING_MODE=jev` -> shadow gana
#     (P1-C): el juez observa y no cambia la ejecución.
#   * override de agente `answer_gate="shadow"` -> se honra el contrato
#     documentado `on|shadow|off`.
#
# Reason codes ESTABLES: renombrar un código es un cambio de contrato.
# =============================================================================
from __future__ import annotations

import warnings
from dataclasses import dataclass

CONFIG_RULES_VERSION = "config-rules-1"

# --- Reason codes ------------------------------------------------------------
INVALID_ENFORCEMENT_STAGE_WITHOUT_JUDGE = (
    "invalid_enforcement_stage_without_judge"
)
DANGEROUS_GATE_PHASE_SKIPPED = "dangerous_gate_phase_skipped"
DANGEROUS_TERMINATION_PHASE_SKIPPED = "dangerous_termination_phase_skipped"
DANGEROUS_SHADOW_WITHOUT_JUDGE = "dangerous_shadow_without_judge"

SEVERITY_INVALID = "invalid"
SEVERITY_DANGEROUS = "dangerous"

#: Códigos que impiden arrancar (cualquier entorno).
INVALID_CODES: frozenset[str] = frozenset({INVALID_ENFORCEMENT_STAGE_WITHOUT_JUDGE})
#: Códigos que exigen acknowledgement explícito en producción.
DANGEROUS_CODES: frozenset[str] = frozenset(
    {
        DANGEROUS_GATE_PHASE_SKIPPED,
        DANGEROUS_TERMINATION_PHASE_SKIPPED,
        DANGEROUS_SHADOW_WITHOUT_JUDGE,
    }
)

# --- Clasificación del inventario (4 clases + resueltas) ---------------------
CLASS_INVALID = "INVALID"
CLASS_DANGEROUS = "DANGEROUS"
CLASS_VALID_DEGRADATION = "VALID_DEGRADATION"
CLASS_EXPERIMENT = "EXPERIMENT"
CLASS_RESOLVED = "RESOLVED"

#: Inventario heredado (07-flags-registry.md, sección «Combinaciones
#: contradictorias») con su clase. Las RESOLVED dejaron de ser contradictorias
#: por construcción (piso monotónico, shadow que no actúa, contrato del gate).
COMBINATION_CLASS: dict[str, str] = {
    "enforcement_stage_without_judge": CLASS_INVALID,
    "gate_on_phase_skipped": CLASS_DANGEROUS,
    "termination_on_phase_skipped": CLASS_DANGEROUS,
    "shadow_without_judge": CLASS_DANGEROUS,
    "canary_percentage_zero": CLASS_VALID_DEGRADATION,
    "loop_on_gate_off": CLASS_VALID_DEGRADATION,
    "agent_override_shadow": CLASS_RESOLVED,
    "agent_override_enforce_false": CLASS_RESOLVED,
    "jev_shadow_with_jev_mode": CLASS_RESOLVED,
    "strict_global_with_agent_false": CLASS_RESOLVED,
}

#: Clases de la clasificación (P1-E). Toda combinación del inventario cae en
#: una; EXPERIMENT queda declarada como clase para los rollouts con contrato
#: propio (canary/shadow) sin regla activa hoy.
ALL_CONFIG_CLASSES: frozenset[str] = frozenset(
    {
        CLASS_INVALID,
        CLASS_DANGEROUS,
        CLASS_VALID_DEGRADATION,
        CLASS_EXPERIMENT,
        CLASS_RESOLVED,
    }
)

#: Clases que pueden aparecer en config vigente (las RESOLVED ya no aplican).
ALLOWED_CLASSES: frozenset[str] = frozenset(
    {CLASS_VALID_DEGRADATION, CLASS_EXPERIMENT}
)


#: Flag de acknowledgement (solo para DANGEROUS; nunca para INVALID).
ACK_ENV = "RUNTIME_CONFIG_ACK_DANGEROUS"

#: Fases JEV que puede saltar la calibración (mismo vocabulario que
#: `RUNTIME_JEV_SKIP_PHASES`).
_SKIPPABLE_PHASES: frozenset[str] = frozenset(
    {"answer_gate", "agent_step", "termination"}
)
#: Estados de la tabla de guards: los que la política resuelve por etapa.
_ENFORCE_STAGES: frozenset[str] = frozenset(
    {"termination_trigger", "draft_gate", "answer_gate"}
)
_OFF_VALUES: frozenset[str] = frozenset({"", "off", "0", "false", "no"})


@dataclass(frozen=True)
class ConfigFinding:
    """Hallazgo de configuración: código estable + severidad + detalle."""

    code: str
    severity: str
    detail: str

    def to_public_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "detail": self.detail,
            "version": CONFIG_RULES_VERSION,
        }


def _flag(settings: object, name: str, default: str = "") -> str:
    return str(getattr(settings, name, default) or default).strip().lower()


def _parse_stages(raw: object) -> frozenset[str]:
    text = str(raw or "").strip().lower()
    if text in _OFF_VALUES:
        return frozenset()
    return (
        frozenset(part.strip() for part in text.split(",") if part.strip())
        & _ENFORCE_STAGES
    )


def _armed_stages(settings: object) -> frozenset[str]:
    """Etapas armadas en la configuración GLOBAL (misma unión que P1-D).

    Los scopes por org/env/agente no se pueden enumerar en startup; se validan
    los globales, que son el piso que un scope normal no puede debilitar.
    """
    stages: set[str] = set(
        _parse_stages(getattr(settings, "RUNTIME_FINALIZATION_ENFORCE", ""))
    )
    for part in str(getattr(settings, "RUNTIME_FINALIZATION_ENFORCE_BY_ENV", "") or "").split(";"):
        _, _, raw = part.partition("=")
        stages |= set(_parse_stages(raw))
    for part in str(getattr(settings, "RUNTIME_FINALIZATION_ENFORCE_ORGS", "") or "").split(";"):
        _, _, raw = part.partition("=")
        stages |= set(_parse_stages(raw))
    return frozenset(stages)


def _skip_phases(settings: object) -> frozenset[str]:
    raw = str(getattr(settings, "RUNTIME_JEV_SKIP_PHASES", "") or "")
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


def _gate_can_judge(settings: object) -> bool:
    """¿Existe alguna vía por la que el gate de respuesta juzgue?

    El modo del gate (`on`/`shadow`) o el loop JEV activo (fuerza `on` en
    agentes de conocimiento) pueden producir veredicto; la fase saltada lo
    anula para todos los scopes (`phase_skipped` se evalúa antes del modo).
    """
    gate_mode = _flag(settings, "RUNTIME_ANSWER_GATE", "off")
    loop_mode = _flag(settings, "RUNTIME_AGENT_JEV_LOOP", "on")
    has_mode = gate_mode in ("on", "shadow") or loop_mode in ("on", "canary")
    return has_mode and "answer_gate" not in _skip_phases(settings)


def validate_runtime_config(settings: object) -> tuple[ConfigFinding, ...]:
    """Clasifica la configuración vigente. Vacío = postura coherente.

    No lanza y no advierte: solo clasifica (lo consumen startup, ops y tests).
    """
    findings: list[ConfigFinding] = []
    stages = _armed_stages(settings)
    skipped = _skip_phases(settings)

    if "answer_gate" in stages and not _gate_can_judge(settings):
        findings.append(
            ConfigFinding(
                code=INVALID_ENFORCEMENT_STAGE_WITHOUT_JUDGE,
                severity=SEVERITY_INVALID,
                detail=(
                    "RUNTIME_FINALIZATION_ENFORCE arma la etapa answer_gate pero "
                    "ninguna vía produce veredicto (gate off/shadow sin juez, loop "
                    "off o fase saltada): el hold fail-closed sería inalcanzable."
                ),
            )
        )

    gate_mode = _flag(settings, "RUNTIME_ANSWER_GATE", "off")
    if gate_mode == "on" and "answer_gate" in skipped:
        findings.append(
            ConfigFinding(
                code=DANGEROUS_GATE_PHASE_SKIPPED,
                severity=SEVERITY_DANGEROUS,
                detail=(
                    "RUNTIME_ANSWER_GATE=on con 'answer_gate' en "
                    "RUNTIME_JEV_SKIP_PHASES: el gate declara juicio y nunca juzga."
                ),
            )
        )
    if _flag(settings, "RUNTIME_TERMINATION_GATE", "off") == "on" and "termination" in skipped:
        findings.append(
            ConfigFinding(
                code=DANGEROUS_TERMINATION_PHASE_SKIPPED,
                severity=SEVERITY_DANGEROUS,
                detail=(
                    "RUNTIME_TERMINATION_GATE=on con 'termination' en "
                    "RUNTIME_JEV_SKIP_PHASES: el gate no puede cortar el loop."
                ),
            )
        )
    shadow_skip = _flag(settings, "RUNTIME_JEV_SKIP_SHADOW", "off") in (
        "on",
        "1",
        "true",
        "yes",
    )
    if gate_mode == "shadow" and shadow_skip:
        findings.append(
            ConfigFinding(
                code=DANGEROUS_SHADOW_WITHOUT_JUDGE,
                severity=SEVERITY_DANGEROUS,
                detail=(
                    "RUNTIME_ANSWER_GATE=shadow con RUNTIME_JEV_SKIP_SHADOW=on: "
                    "shadow declara observación y no hay llamada al juez."
                ),
            )
        )
    return tuple(findings)


def acknowledged_codes(settings: object) -> frozenset[str]:
    raw = str(getattr(settings, ACK_ENV, "") or "")
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def assert_runtime_config(settings: object) -> tuple[ConfigFinding, ...]:
    """Valida en startup: INVALID siempre falla; DANGEROUS falla en producción.

    Devuelve los hallazgos (para trazas/métricas); lanza `ValueError` cuando la
    postura es inválida o cuando producción no reconoció explícitamente el
    riesgo (`RUNTIME_CONFIG_ACK_DANGEROUS`).
    """
    findings = validate_runtime_config(settings)
    if not findings:
        return ()
    production = _flag(settings, "ENVIRONMENT", "development") in ("production", "prod")
    acknowledged = acknowledged_codes(settings)
    blocking: list[ConfigFinding] = []
    for finding in findings:
        if finding.severity == SEVERITY_INVALID:
            blocking.append(finding)
        elif production and finding.code not in acknowledged:
            blocking.append(finding)
        else:
            warnings.warn(
                f"CONFIG: {finding.code} — {finding.detail}",
                stacklevel=2,
            )
    if blocking:
        codes = ",".join(sorted({finding.code for finding in blocking}))
        raise ValueError(
            "configuración contradictoria (P1-E): "
            + "; ".join(
                f"{finding.code}: {finding.detail}" for finding in blocking
            )
            + f" [códigos: {codes}]"
        )
    return findings


__all__ = [
    "ACK_ENV",
    "ALLOWED_CLASSES",
    "ALL_CONFIG_CLASSES",
    "CLASS_DANGEROUS",
    "CLASS_EXPERIMENT",
    "CLASS_INVALID",
    "CLASS_RESOLVED",
    "CLASS_VALID_DEGRADATION",
    "COMBINATION_CLASS",
    "CONFIG_RULES_VERSION",
    "DANGEROUS_CODES",
    "DANGEROUS_GATE_PHASE_SKIPPED",
    "DANGEROUS_SHADOW_WITHOUT_JUDGE",
    "DANGEROUS_TERMINATION_PHASE_SKIPPED",
    "INVALID_CODES",
    "INVALID_ENFORCEMENT_STAGE_WITHOUT_JUDGE",
    "SEVERITY_DANGEROUS",
    "SEVERITY_INVALID",
    "ConfigFinding",
    "acknowledged_codes",
    "assert_runtime_config",
    "validate_runtime_config",
]
