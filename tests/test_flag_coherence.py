# =============================================================================
# Coherencia de flags — combinaciones que apagan autoridad sin decirlo.
# =============================================================================
# Contrato (Parte J): cada combinación contradictoria detectada en el recon
# queda PINNEADA con su comportamiento real, para que no derive en silencio y
# para que la adopción por canary tenga el dato. Las correcciones de producto
# (no encender un gate sin juez, no dejar que un agente desarme el fail-closed
# global) son decisiones con datos, no cambios silenciosos.
#
# Flags cubiertos: RUNTIME_ANSWER_GATE, RUNTIME_JEV_SKIP_PHASES,
# RUNTIME_JEV_SKIP_SHADOW, RUNTIME_TERMINATION_GATE, RUNTIME_AGENT_JEV_LOOP(_CANARY),
# RUNTIME_FINALIZATION_ENFORCE, RUNTIME_RUN_STATE_STRICT(_ORGS),
# RUNTIME_RUN_GUARDS_ENFORCE, RUNTIME_RUN_STATE_STRICT.
# =============================================================================
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agents.runtime.agent_runtime import _canary_allows
from src.decision.routing import in_canary
from src.runtime.answer_gate import judge_answer
from src.runtime.enforcement import enforcement_stages, should_hold_trigger
from src.runtime.finalization_policy import (
    FinalizationAction,
    FinalizationDecision,
)
from src.runtime.jev_value import skip_phases_from_settings, skip_shadow_enabled
from src.runtime.run_state import strict_mode_enabled
from src.runtime.termination import gate_enabled, original_request_satisfied

ROOT = Path(__file__).resolve().parents[1]


def _settings(**overrides):
    base = {
        "RUNTIME_ANSWER_GATE": "off",
        "RUNTIME_JEV_SKIP_PHASES": "",
        "RUNTIME_JEV_SKIP_SHADOW": "off",
        "RUNTIME_TERMINATION_GATE": "off",
        "RUNTIME_AGENT_JEV_LOOP": "on",
        "RUNTIME_AGENT_JEV_LOOP_CANARY_PERCENTAGE": 0,
        "RUNTIME_FINALIZATION_ENFORCE": "",
        "RUNTIME_FINALIZATION_ENFORCE_ORGS": "",
        "RUNTIME_FINALIZATION_ENFORCE_BY_ENV": "",
        "RUNTIME_RUN_GUARDS_ENFORCE": "off",
        "RUNTIME_RUN_STATE_STRICT": "off",
        "RUNTIME_RUN_STATE_STRICT_ORGS": "",
        "ENVIRONMENT": "development",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# -----------------------------------------------------------------------------
# 1. Gate encendido + fase salteada: el gate nunca juzga.
# -----------------------------------------------------------------------------
def test_gate_on_con_fase_salteada_no_juzga(monkeypatch) -> None:
    import src.core.config as config_module

    settings = _settings(
        RUNTIME_ANSWER_GATE="on", RUNTIME_JEV_SKIP_PHASES="answer_gate"
    )
    monkeypatch.setattr(config_module, "get_settings", lambda: settings)
    assert "answer_gate" in skip_phases_from_settings(settings)

    result = asyncio.run(
        judge_answer(
            engine=SimpleNamespace(),  # motor presente: no es la causa del skip
            mode="on",
            user_request="¿cuánto vendimos?",
            draft="borrador",
            settings=settings,
        )
    )
    assert result.provider == "skip_config"
    assert result.verdict in ("", "skipped")
    # Consecuencia documentada: la etapa answer_gate del enforcement no puede
    # dispararse porque el hold exige un veredicto juzgado.
    decision = FinalizationDecision(
        action=FinalizationAction.RETRIEVE_MORE,
        reason_code="EVIDENCE_INCOMPLETE",
        authority="EVIDENCE",
    )
    assert should_hold_trigger(
        decision, stage="answer_gate", enforced=frozenset({"answer_gate"})
    )
    assert result.provider != "jev"


def test_shadow_con_skip_shadow_no_paga_la_llamada(monkeypatch) -> None:
    import src.core.config as config_module

    settings = _settings(RUNTIME_JEV_SKIP_SHADOW="on")
    monkeypatch.setattr(config_module, "get_settings", lambda: settings)
    assert skip_shadow_enabled(settings)
    result = asyncio.run(
        judge_answer(
            engine=SimpleNamespace(),
            mode="shadow",
            user_request="q",
            draft="d",
            settings=settings,
        )
    )
    assert result.provider == "skip_shadow"


# -----------------------------------------------------------------------------
# 2. Termination gate + fase salteada: el gate no corta.
# -----------------------------------------------------------------------------
def test_termination_gate_on_con_fase_salteada_no_corta(monkeypatch) -> None:
    import src.core.config as config_module

    settings = _settings(
        RUNTIME_TERMINATION_GATE="on", RUNTIME_JEV_SKIP_PHASES="termination"
    )
    monkeypatch.setattr(config_module, "get_settings", lambda: settings)
    assert gate_enabled(settings) is True

    outcome = asyncio.run(
        original_request_satisfied(
            engine=SimpleNamespace(),
            user_request="resumen",
            history=["OBSERVATION"],
            tool_calls=2,
        )
    )
    assert outcome["provider"] == "skip_config"
    assert outcome["stop"] is False


def test_termination_gate_por_agente_manda(monkeypatch) -> None:
    assert gate_enabled(_settings(RUNTIME_TERMINATION_GATE="off"), {"runtime": {"termination_gate": True}}) is True
    assert gate_enabled(_settings(RUNTIME_TERMINATION_GATE="on"), {"runtime": {"termination_gate": False}}) is False


# -----------------------------------------------------------------------------
# 3. Canary con porcentaje 0: equivale a off (sin shadow, sin juicio).
# -----------------------------------------------------------------------------
def test_canary_cero_equivale_a_off() -> None:
    assert _canary_allows(_settings(RUNTIME_AGENT_JEV_LOOP_CANARY_PERCENTAGE=0), "run-1") is False
    assert _canary_allows(_settings(RUNTIME_AGENT_JEV_LOOP_CANARY_PERCENTAGE=100), "run-1") is True
    assert _canary_allows(_settings(RUNTIME_AGENT_JEV_LOOP_CANARY_PERCENTAGE=50), "") is False


def test_canary_es_estable_por_run() -> None:
    percent = 50
    first = in_canary("run-estable", percent)
    assert all(in_canary("run-estable", percent) is first for _ in range(50))


# -----------------------------------------------------------------------------
# 4. Enforcement armado sin gate: no-op silencioso (deuda medida).
# -----------------------------------------------------------------------------
def test_enforcement_de_answer_gate_requiere_gate_encendido() -> None:
    settings = _settings(RUNTIME_FINALIZATION_ENFORCE="answer_gate")
    assert enforcement_stages(settings) == frozenset({"answer_gate"})
    # La etapa armada solo actúa con un veredicto juzgado; con el gate en off el
    # veredicto es "skipped" y el hold nunca corre. Documentado como P1-6.
    decision = FinalizationDecision(
        action=FinalizationAction.RETRIEVE_MORE,
        reason_code="EVIDENCE_INCOMPLETE",
        authority="EVIDENCE",
    )
    assert should_hold_trigger(decision, stage="answer_gate", enforced=frozenset({"answer_gate"}))
    assert should_hold_trigger(
        decision, stage="answer_gate", enforced=frozenset({"answer_gate"}), holds_used=1
    ) is False


def test_enforcement_global_por_org_y_environment() -> None:
    settings = _settings(
        RUNTIME_FINALIZATION_ENFORCE="termination_trigger",
        RUNTIME_FINALIZATION_ENFORCE_ORGS="org-1=answer_gate;org-2",
        RUNTIME_FINALIZATION_ENFORCE_BY_ENV="production=draft_gate",
        ENVIRONMENT="production",
    )
    assert enforcement_stages(settings, organization_id="org-1") == frozenset(
        {"answer_gate"}
    )
    assert enforcement_stages(settings, organization_id="org-2") == frozenset(
        {"termination_trigger"}
    )
    # Precedencia documentada: agente > org > environment > global.
    assert enforcement_stages(settings, organization_id="org-3") == frozenset(
        {"draft_gate"}
    )
    assert enforcement_stages(settings) == frozenset({"draft_gate"})
    staging = _settings(
        RUNTIME_FINALIZATION_ENFORCE="termination_trigger",
        RUNTIME_FINALIZATION_ENFORCE_ORGS="org-1=answer_gate;org-2",
        RUNTIME_FINALIZATION_ENFORCE_BY_ENV="production=draft_gate",
        ENVIRONMENT="staging",
    )
    assert enforcement_stages(staging) == frozenset({"termination_trigger"})
    assert enforcement_stages(staging, organization_id="org-1") == frozenset(
        {"answer_gate"}
    )


def test_agente_puede_desarmar_el_enforcement_global() -> None:
    """Deuda P1-3 medida: el override del agente tiene prioridad absoluta."""
    settings = _settings(RUNTIME_FINALIZATION_ENFORCE="termination_trigger,draft_gate")
    assert enforcement_stages(
        settings, config_json={"runtime": {"finalization_enforce": False}}
    ) == frozenset()
    assert enforcement_stages(
        settings, config_json={"runtime": {"finalization_enforce": "answer_gate"}}
    ) == frozenset({"answer_gate"})


# -----------------------------------------------------------------------------
# 5. Fail-closed del estado: global, canary por org y override por agente.
# -----------------------------------------------------------------------------
def test_estricto_global_canary_y_agente() -> None:
    assert strict_mode_enabled(_settings()) is False
    assert strict_mode_enabled(_settings(RUNTIME_RUN_STATE_STRICT="on")) is True
    assert (
        strict_mode_enabled(
            _settings(RUNTIME_RUN_STATE_STRICT_ORGS="org-a"),
            organization_id="org-a",
        )
        is True
    )
    assert (
        strict_mode_enabled(
            _settings(), config_json={"runtime": {"strict_run_state": True}}
        )
        is True
    )
    assert (
        strict_mode_enabled(
            _settings(RUNTIME_RUN_STATE_STRICT="on"),
            config_json={"runtime": {"strict_run_state": False}},
        )
        is False
    )


def test_strict_invalido_no_activa_fail_closed() -> None:
    assert strict_mode_enabled(_settings(RUNTIME_RUN_STATE_STRICT="quizas")) is False
    assert strict_mode_enabled(_settings(RUNTIME_RUN_STATE_STRICT="ON")) is True


# -----------------------------------------------------------------------------
# 6. El modo de respuesta del gate: flag global vs override del agente.
# -----------------------------------------------------------------------------
def test_override_del_agente_es_bool_only() -> None:
    """El string `shadow` documentado NO se honra: solo bool (deuda P1-3)."""
    from src.runtime.answer_gate import answer_gate_mode

    settings = _settings(RUNTIME_ANSWER_GATE="on")
    assert answer_gate_mode(settings, {"runtime": {"answer_gate": False}}) == "off"
    assert answer_gate_mode(settings, {"runtime": {"answer_gate": True}}) == "on"
    # Documentado como `on|shadow|off`; el código ignora el string y cae al global.
    assert answer_gate_mode(settings, {"runtime": {"answer_gate": "shadow"}}) == "on"


def test_flag_global_invalido_cae_a_off() -> None:
    from src.runtime.answer_gate import answer_gate_mode

    assert answer_gate_mode(_settings(RUNTIME_ANSWER_GATE="quizas"), None) == "off"


def test_loop_jev_activo_fuerza_el_gate_en_agentes_de_conocimiento() -> None:
    """Con loop JEV activo el gate juzga aunque el flag global diga off.

    Deuda P1-6: el operador no puede apagar el gate globalmente cuando el loop
    está activo y el agente no declara override.
    """
    source = (
        ROOT / "src" / "agents" / "runtime" / "agent_runtime.py"
    ).read_text(encoding="utf-8", errors="replace")
    assert 'answer_mode = "on"' in source
    assert "answer_mode = answer_gate_mode(settings, request.agent.config_json)" in source


def test_guards_enforce_es_un_flag_booleano_documentado() -> None:
    from src.agents.runtime.agent_runtime import guards_enforced

    assert guards_enforced(_settings(RUNTIME_RUN_GUARDS_ENFORCE="off")) is False
    assert guards_enforced(_settings(RUNTIME_RUN_GUARDS_ENFORCE="on")) is True
    assert guards_enforced(_settings(RUNTIME_RUN_GUARDS_ENFORCE="quizas")) is False


@pytest.mark.parametrize(
    "flag,value,expected",
    [
        ("RUNTIME_JEV_SKIP_PHASES", "answer_gate,agent_step,termination", 3),
        ("RUNTIME_JEV_SKIP_PHASES", "ANSWER_GATE", 1),
        ("RUNTIME_JEV_SKIP_PHASES", "", 0),
    ],
)
def test_fases_salteadas_se_normalizan(flag, value, expected) -> None:
    assert len(skip_phases_from_settings(_settings(**{flag: value}))) == expected
