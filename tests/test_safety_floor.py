# =============================================================================
# Safety Floor (P1-D) — el piso global de seguridad es monotónico.
# =============================================================================
# Clasificación de configuraciones que el hardening fija:
#   PRODUCT BEHAVIOR .. el tenant/agente decide comportamiento de producto
#                       (p. ej. `runtime.answer_gate`: señal JEV, no autorización).
#   SAFETY FLOOR ...... protección global; cualquier scope normal puede SUMAR,
#                       nunca restar.
#   EXPERIMENT ........ shadow/canary; no cambia autoridad.
#   BREAK-GLASS ....... downgrade operacional auditado; ZENT no lo necesita hoy
#                       => el downgrade está prohibido (no se construye).
#
# Ratchet behavioral: la tabla de abajo es la prueba mínima pedida
# (global+agente, global+org, en ambas direcciones).
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace

from src.runtime.enforcement import enforcement_stages
from src.runtime.run_state import strict_mode_enabled


def _strict_settings(*, global_on: bool, orgs: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        RUNTIME_RUN_STATE_STRICT="on" if global_on else "off",
        RUNTIME_RUN_STATE_STRICT_ORGS=orgs,
    )


def _enforce_settings(*, global_stages: str, orgs: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        RUNTIME_FINALIZATION_ENFORCE=global_stages,
        RUNTIME_FINALIZATION_ENFORCE_ORGS=orgs,
        RUNTIME_FINALIZATION_ENFORCE_BY_ENV="",
        ENVIRONMENT="development",
    )


# -----------------------------------------------------------------------------
# Fail-closed estricto (RUNTIME_RUN_STATE_STRICT)
# -----------------------------------------------------------------------------
def test_global_on_agente_false_sigue_on() -> None:
    assert (
        strict_mode_enabled(
            _strict_settings(global_on=True),
            config_json={"runtime": {"strict_run_state": False}},
        )
        is True
    )


def test_global_on_org_false_sigue_on() -> None:
    # Una organización fuera del canary no apaga el global.
    assert (
        strict_mode_enabled(
            _strict_settings(global_on=True, orgs="org-canary"),
            organization_id="org-otra",
        )
        is True
    )


def test_global_off_agente_true_enciende() -> None:
    assert (
        strict_mode_enabled(
            _strict_settings(global_on=False),
            config_json={"runtime": {"strict_run_state": True}},
        )
        is True
    )


def test_global_off_org_canary_enciende() -> None:
    assert (
        strict_mode_enabled(
            _strict_settings(global_on=False, orgs="org-canary"),
            organization_id="org-canary",
        )
        is True
    )


def test_agente_no_debilita_el_piso_enforcement() -> None:
    settings = _enforce_settings(global_stages="termination_trigger,draft_gate")
    assert enforcement_stages(
        settings, config_json={"runtime": {"finalization_enforce": False}}
    ) == frozenset({"termination_trigger", "draft_gate"})


def test_org_no_debilita_el_piso_enforcement() -> None:
    settings = _enforce_settings(
        global_stages="termination_trigger",
        orgs="org-1",  # sin valor: hereda (suma cero)
    )
    assert enforcement_stages(settings, organization_id="org-1") == frozenset(
        {"termination_trigger"}
    )
    assert enforcement_stages(settings, organization_id="org-2") == frozenset(
        {"termination_trigger"}
    )


def test_agente_y_org_solo_suman_enforcement() -> None:
    settings = _enforce_settings(
        global_stages="termination_trigger",
        orgs="org-1=answer_gate",
    )
    assert enforcement_stages(
        settings,
        organization_id="org-1",
        config_json={"runtime": {"finalization_enforce": "draft_gate"}},
    ) == frozenset({"termination_trigger", "answer_gate", "draft_gate"})


def test_flag_invalido_no_enciende_y_no_apaga_nada_por_si_solo() -> None:
    assert strict_mode_enabled(_strict_settings(global_on=False)) is False
    settings = _enforce_settings(global_stages="")
    assert enforcement_stages(settings, config_json={}) == frozenset()
