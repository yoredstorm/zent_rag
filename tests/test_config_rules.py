# =============================================================================
# Combinaciones de flags contradictorias (P1-E): startup fail-closed.
# =============================================================================
# Contrato:
#   INVALID    -> la instancia no arranca (cualquier entorno);
#   DANGEROUS  -> warning en dev; error en producción salvo acknowledgement
#                 explícito (`RUNTIME_CONFIG_ACK_DANGEROUS`);
#   VALID DEGRADATION / EXPERIMENT -> permitidos (no generan hallazgo).
#
# Los códigos son estables: renombrarlos es un cambio de contrato.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.config_rules import (
    ACK_ENV,
    CONFIG_RULES_VERSION,
    DANGEROUS_CODES,
    DANGEROUS_GATE_PHASE_SKIPPED,
    DANGEROUS_SHADOW_WITHOUT_JUDGE,
    DANGEROUS_TERMINATION_PHASE_SKIPPED,
    INVALID_CODES,
    INVALID_ENFORCEMENT_STAGE_WITHOUT_JUDGE,
    SEVERITY_DANGEROUS,
    SEVERITY_INVALID,
    assert_runtime_config,
    validate_runtime_config,
)


def _settings(**overrides) -> SimpleNamespace:
    """Defaults coherentes (los mismos del código) + overrides."""
    base = {
        "ENVIRONMENT": "development",
        "RUNTIME_FINALIZATION_ENFORCE": "termination_trigger,draft_gate",
        "RUNTIME_FINALIZATION_ENFORCE_ORGS": "",
        "RUNTIME_FINALIZATION_ENFORCE_BY_ENV": "",
        "RUNTIME_ANSWER_GATE": "off",
        "RUNTIME_AGENT_JEV_LOOP": "on",
        "RUNTIME_TERMINATION_GATE": "off",
        "RUNTIME_JEV_SKIP_PHASES": "",
        "RUNTIME_JEV_SKIP_SHADOW": "off",
        "RUNTIME_RUN_STATE_STRICT": "off",
        "RUNTIME_RUN_GUARDS_ENFORCE": "off",
        ACK_ENV: "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# -----------------------------------------------------------------------------
# Postura coherente: cero hallazgos.
# -----------------------------------------------------------------------------
def test_configuracion_por_defecto_es_coherente() -> None:
    assert validate_runtime_config(_settings()) == ()
    assert assert_runtime_config(_settings()) == ()


def test_degradaciones_validas_no_generan_hallazgo() -> None:
    """Canary 0, shadow observacional y skip de fases sin gate: permitidos."""
    assert (
        validate_runtime_config(
            _settings(RUNTIME_FINALIZATION_ENFORCE="", RUNTIME_ANSWER_GATE="off")
        )
        == ()
    )
    assert (
        validate_runtime_config(
            _settings(RUNTIME_JEV_SKIP_PHASES="agent_step,termination")
        )
        == ()
    )
    assert (
        validate_runtime_config(
            _settings(RUNTIME_ANSWER_GATE="shadow", RUNTIME_JEV_SKIP_SHADOW="off")
        )
        == ()
    )


# -----------------------------------------------------------------------------
# INVALID: etapa armada sin veredicto posible -> startup failure.
# -----------------------------------------------------------------------------
class TestInvalid:
    @pytest.mark.parametrize(
        "overrides",
        [
            {
                "RUNTIME_FINALIZATION_ENFORCE": "answer_gate",
                "RUNTIME_ANSWER_GATE": "off",
                "RUNTIME_AGENT_JEV_LOOP": "off",
            },
            {
                "RUNTIME_FINALIZATION_ENFORCE": "termination_trigger,answer_gate",
                "RUNTIME_ANSWER_GATE": "off",
                "RUNTIME_AGENT_JEV_LOOP": "off",
            },
            {
                "RUNTIME_FINALIZATION_ENFORCE": "answer_gate",
                "RUNTIME_ANSWER_GATE": "on",
                "RUNTIME_JEV_SKIP_PHASES": "answer_gate",
            },
            {
                "RUNTIME_FINALIZATION_ENFORCE_ORGS": "org-1=answer_gate",
                "RUNTIME_ANSWER_GATE": "off",
                "RUNTIME_AGENT_JEV_LOOP": "off",
            },
            {
                "RUNTIME_FINALIZATION_ENFORCE_BY_ENV": "production=answer_gate",
                "RUNTIME_ANSWER_GATE": "off",
                "RUNTIME_AGENT_JEV_LOOP": "off",
            },
        ],
    )
    def test_etapa_sin_juez_es_invalid(self, overrides) -> None:
        findings = validate_runtime_config(_settings(**overrides))
        codes = {finding.code for finding in findings}
        assert INVALID_ENFORCEMENT_STAGE_WITHOUT_JUDGE in codes
        assert any(f.severity == SEVERITY_INVALID for f in findings)
        with pytest.raises(ValueError, match=INVALID_ENFORCEMENT_STAGE_WITHOUT_JUDGE):
            assert_runtime_config(_settings(**overrides))

    def test_invalid_no_se_reconoce_ni_con_ack(self) -> None:
        settings = _settings(
            RUNTIME_FINALIZATION_ENFORCE="answer_gate",
            RUNTIME_ANSWER_GATE="off",
            RUNTIME_AGENT_JEV_LOOP="off",
            **{ACK_ENV: INVALID_ENFORCEMENT_STAGE_WITHOUT_JUDGE},
        )
        with pytest.raises(ValueError):
            assert_runtime_config(settings)

    def test_loop_activo_hace_que_el_gate_pueda_juzgar(self) -> None:
        """El loop JEV fuerza el gate en agentes de conocimiento: no es invalid."""
        settings = _settings(
            RUNTIME_FINALIZATION_ENFORCE="answer_gate",
            RUNTIME_ANSWER_GATE="off",
            RUNTIME_AGENT_JEV_LOOP="on",
        )
        assert validate_runtime_config(settings) == ()


# -----------------------------------------------------------------------------
# DANGEROUS: protección declarada sin efecto.
# -----------------------------------------------------------------------------
class TestDangerous:
    def test_gate_on_con_fase_salteada(self) -> None:
        settings = _settings(
            RUNTIME_ANSWER_GATE="on", RUNTIME_JEV_SKIP_PHASES="answer_gate"
        )
        findings = validate_runtime_config(settings)
        assert {f.code for f in findings} == {DANGEROUS_GATE_PHASE_SKIPPED}
        assert findings[0].severity == SEVERITY_DANGEROUS
        # Dev: warning, no error.
        with pytest.warns(UserWarning, match=DANGEROUS_GATE_PHASE_SKIPPED):
            assert assert_runtime_config(settings)

    def test_termination_on_con_fase_salteada(self) -> None:
        settings = _settings(
            RUNTIME_TERMINATION_GATE="on", RUNTIME_JEV_SKIP_PHASES="termination"
        )
        findings = validate_runtime_config(settings)
        assert {f.code for f in findings} == {DANGEROUS_TERMINATION_PHASE_SKIPPED}

    def test_shadow_con_skip_shadow_no_llama_al_juez(self) -> None:
        settings = _settings(
            RUNTIME_ANSWER_GATE="shadow", RUNTIME_JEV_SKIP_SHADOW="on"
        )
        findings = validate_runtime_config(settings)
        assert {f.code for f in findings} == {DANGEROUS_SHADOW_WITHOUT_JUDGE}

    def test_produccion_no_arranca_sin_ack(self) -> None:
        settings = _settings(
            ENVIRONMENT="production",
            RUNTIME_ANSWER_GATE="on",
            RUNTIME_JEV_SKIP_PHASES="answer_gate",
        )
        with pytest.raises(ValueError, match=DANGEROUS_GATE_PHASE_SKIPPED):
            assert_runtime_config(settings)

    def test_produccion_arranca_con_ack_explicito(self) -> None:
        settings = _settings(
            ENVIRONMENT="production",
            RUNTIME_ANSWER_GATE="on",
            RUNTIME_JEV_SKIP_PHASES="answer_gate",
            **{ACK_ENV: DANGEROUS_GATE_PHASE_SKIPPED},
        )
        with pytest.warns(UserWarning):
            findings = assert_runtime_config(settings)
        assert findings


# -----------------------------------------------------------------------------
# Contrato de los códigos y de la superficie pública.
# -----------------------------------------------------------------------------
def test_codigos_estables_y_clasificados() -> None:
    assert INVALID_CODES == {INVALID_ENFORCEMENT_STAGE_WITHOUT_JUDGE}
    assert DANGEROUS_CODES == {
        DANGEROUS_GATE_PHASE_SKIPPED,
        DANGEROUS_TERMINATION_PHASE_SKIPPED,
        DANGEROUS_SHADOW_WITHOUT_JUDGE,
    }
    assert INVALID_CODES.isdisjoint(DANGEROUS_CODES)
    assert CONFIG_RULES_VERSION == "config-rules-1"


def test_inventario_clasificado_en_las_cuatro_clases() -> None:
    """Cada combinación del inventario declara su clase (P1-E)."""
    from src.core.config_rules import (
        ALL_CONFIG_CLASSES,
        CLASS_DANGEROUS,
        CLASS_INVALID,
        COMBINATION_CLASS,
    )

    assert ALL_CONFIG_CLASSES == {
        "INVALID",
        "DANGEROUS",
        "VALID_DEGRADATION",
        "EXPERIMENT",
        "RESOLVED",
    }
    assert set(COMBINATION_CLASS.values()) <= ALL_CONFIG_CLASSES
    invalids = {"enforcement_stage_without_judge"}
    dangerous = {
        "gate_on_phase_skipped",
        "termination_on_phase_skipped",
        "shadow_without_judge",
    }
    assert invalids <= set(COMBINATION_CLASS)
    assert dangerous <= set(COMBINATION_CLASS)
    assert all(COMBINATION_CLASS[name] == CLASS_INVALID for name in invalids)
    assert all(COMBINATION_CLASS[name] == CLASS_DANGEROUS for name in dangerous)


def test_settings_expone_ack_y_valida_en_startup() -> None:
    """La validación corre en la construcción de Settings (startup), no en runtime."""
    from src.core.config import Settings

    assert ACK_ENV in Settings.model_fields
    with pytest.raises(ValueError, match=INVALID_ENFORCEMENT_STAGE_WITHOUT_JUDGE):
        Settings(
            _env_file=None,
            RUNTIME_FINALIZATION_ENFORCE="answer_gate",
            RUNTIME_ANSWER_GATE="off",
            RUNTIME_AGENT_JEV_LOOP="off",
        )
