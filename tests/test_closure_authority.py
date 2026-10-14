# =============================================================================
# Autoridad del cierre — la fase terminal la decide la resolución, no el texto.
# =============================================================================
# Contrato (ADR-004):
#   * un cierre FINALIZED requiere que la FinalizationPolicy resuelva FINALIZE:
#     `deterministic_finalized_without_envelope` es imposible por construcción;
#   * un fallo operativo declarado por el vocabulario de respuesta (retrieval
#     unavailable, reglas, derivación) nunca se presenta como respuesta;
#   * una divergencia entre la autoridad y el oráculo legacy queda como
#     violación crítica trazable (bloqueante en modo estricto);
#   * la autoridad es determinista: mismas señales, misma fase (100 runs).
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace

from src.runtime.answer_state import (
    ANSWER_STATE_CONFLICTING,
    ANSWER_STATE_INSUFFICIENT,
    ANSWER_STATE_RETRIEVAL_UNAVAILABLE,
    ANSWER_STATE_RULE_RETRIEVAL_UNAVAILABLE,
    ANSWER_STATE_UNDETERMINED,
)
from src.runtime.finalization_policy import (
    CLOSURE_AUTHORITY_FAILED,
    CLOSURE_AUTHORITY_MISMATCH,
    CLOSURE_NOT_AUTHORIZED,
    ClosureResolution,
    FinalizationAction,
    resolve_closure_phase,
)
from src.runtime.run_state import (
    CRITICAL_INVARIANTS,
    AgentRunState,
    RunIdentity,
    RunPhase,
    finalize_state,
    strict_mode_enabled,
)

_DRAFT = "respuesta con conclusión"


def _state(
    *,
    evidence: str = "complete",
    authority: bool = False,
    requires_deterministic: bool = False,
) -> AgentRunState:
    state = AgentRunState(identity=RunIdentity(run_id="closure-test"))
    if evidence == "complete":
        state.evidence.observe(
            sufficiency=SimpleNamespace(
                evidence_complete=True,
                recommended_action="generate",
                missing_entities=(),
                missing_anchors=(),
            )
        )
    elif evidence == "insufficient":
        state.evidence.observe(
            sufficiency=SimpleNamespace(
                evidence_complete=False,
                recommended_action="retrieve_more",
                missing_entities=("premisa",),
                missing_anchors=(),
            )
        )
    elif evidence == "failed":
        state.evidence.retrieval_failed = True
    if authority:
        state.decisions.set_envelope(
            SimpleNamespace(authoritative=True, state="MATCH")
        )
    state.decisions.requires_deterministic = requires_deterministic
    return state


def _resolve(
    state: AgentRunState,
    *,
    status: str = "completed",
    answer: str = _DRAFT,
    answer_state: dict | None = None,
) -> ClosureResolution:
    return resolve_closure_phase(
        state, status=status, answer=answer, answer_state=answer_state
    )


# -----------------------------------------------------------------------------
# Status operativos: la fase la decide el resultado, no la answerability.
# -----------------------------------------------------------------------------
def test_status_operativos_no_consultan_la_politica() -> None:
    for status, expected in (
        ("error", RunPhase.FAILED),
        ("failed", RunPhase.FAILED),
        ("limit_reached", RunPhase.LIMIT_REACHED),
        ("awaiting_approval", RunPhase.BLOCKED),
        ("blocked", RunPhase.BLOCKED),
    ):
        resolution = _resolve(_state(), status=status)
        assert resolution.phase is expected, status
        assert resolution.operational is True
        assert resolution.decision is None
        assert resolution.consistent


# -----------------------------------------------------------------------------
# El cierre autorizado: la política y el oráculo coinciden.
# -----------------------------------------------------------------------------
def test_evidencia_completa_con_borrador_finaliza_consistente() -> None:
    resolution = _resolve(_state(), answer_state={"state": ""})
    assert resolution.phase is RunPhase.FINALIZED
    assert resolution.legacy_phase is RunPhase.FINALIZED
    assert resolution.consistent
    assert resolution.decision.action is FinalizationAction.FINALIZE


def test_evidencia_insuficiente_con_borrador_cierra_con_limites() -> None:
    resolution = _resolve(_state(evidence="insufficient"))
    assert resolution.phase is RunPhase.FINALIZED
    assert resolution.consistent
    assert resolution.decision.limited is True


def test_autoridad_determinista_finaliza_aunque_la_evidencia_sea_parcial() -> None:
    resolution = _resolve(_state(evidence="failed", authority=True))
    assert resolution.phase is RunPhase.FINALIZED
    assert resolution.decision.authority.value == "DETERMINISTIC"


# -----------------------------------------------------------------------------
# Fallos operativos: nunca una respuesta.
# -----------------------------------------------------------------------------
def test_retrieval_unavailable_declarado_nunca_finaliza() -> None:
    state = _state(evidence="failed")
    resolution = _resolve(
        state, answer_state={"state": ANSWER_STATE_RETRIEVAL_UNAVAILABLE}
    )
    assert resolution.phase is RunPhase.BLOCKED
    assert resolution.legacy_phase is RunPhase.BLOCKED
    assert resolution.consistent


def test_fallo_operativo_con_familia_y_evidencia_completa_bloquea() -> None:
    """Evidencia completa no convierte un fallo operativo en respuesta."""
    state = _state(evidence="complete", authority=True)
    resolution = _resolve(
        state, answer_state={"state": ANSWER_STATE_RULE_RETRIEVAL_UNAVAILABLE}
    )
    assert resolution.phase is RunPhase.BLOCKED
    assert resolution.kind == CLOSURE_AUTHORITY_MISMATCH
    assert resolution.mismatch.startswith(CLOSURE_AUTHORITY_MISMATCH)
    assert resolution.mismatch.split(":")[1] == "policy_finalize_over_operational_failure"


def test_retrieval_failed_sin_borrador_bloquea_sin_mismatch() -> None:
    resolution = _resolve(_state(evidence="failed"), answer="")
    assert resolution.phase is RunPhase.BLOCKED
    assert resolution.consistent
    assert resolution.decision.action is FinalizationAction.BLOCK


# -----------------------------------------------------------------------------
# El oráculo legacy no autoriza nada por sí mismo.
# -----------------------------------------------------------------------------
def test_retrieval_fallido_con_texto_no_finaliza() -> None:
    """Hay texto, pero el retrieval falló: no es una respuesta."""
    state = _state(evidence="failed")
    resolution = _resolve(state)
    assert resolution.legacy_phase is RunPhase.FINALIZED
    assert resolution.phase is RunPhase.BLOCKED
    assert resolution.kind == CLOSURE_AUTHORITY_MISMATCH
    assert resolution.mismatch.startswith(CLOSURE_AUTHORITY_MISMATCH)


def test_politica_sin_cierre_convierte_finalized_en_blocked() -> None:
    """Análisis complejo incompleto: la política no autoriza el cierre."""
    state = _state(evidence="complete")
    state.reasoning.run = SimpleNamespace(
        enabled=True,
        is_complex=True,
        analysis_complete=False,
        blocks_early_answer=True,
    )
    resolution = _resolve(state)
    assert resolution.legacy_phase is RunPhase.FINALIZED
    assert resolution.phase is RunPhase.BLOCKED
    assert resolution.kind == CLOSURE_NOT_AUTHORIZED
    assert resolution.mismatch.startswith(CLOSURE_NOT_AUTHORIZED)


def test_abstencion_legacy_con_autoridad_determinista_finaliza_con_limites() -> None:
    """La política manda: evidencia canónica suficiente responde, no abstiene."""
    state = _state(evidence="complete", authority=True)
    resolution = _resolve(state, answer_state={"state": ANSWER_STATE_INSUFFICIENT})
    assert resolution.legacy_phase is RunPhase.ABSTAINED
    assert resolution.phase is RunPhase.FINALIZED
    assert resolution.kind == CLOSURE_AUTHORITY_MISMATCH
    assert resolution.mismatch.startswith(CLOSURE_AUTHORITY_MISMATCH)


def test_no_concluyentes_distintos_son_refinamiento_no_conflicto() -> None:
    """ABSTAINED vs BLOCKED sin respuesta afirmada no es conflicto crítico."""
    state = _state(evidence="insufficient")
    resolution = _resolve(state, answer="")
    assert resolution.legacy_phase is RunPhase.BLOCKED
    assert resolution.phase is RunPhase.ABSTAINED
    assert resolution.kind == "classification_refined"
    assert resolution.consistent


def test_estado_undetermined_se_conserva() -> None:
    state = _state(evidence="complete", requires_deterministic=True)
    resolution = _resolve(state, answer_state={"state": ANSWER_STATE_UNDETERMINED})
    assert resolution.phase is RunPhase.UNDETERMINED
    assert resolution.legacy_phase is RunPhase.UNDETERMINED
    assert resolution.consistent


def test_conflicto_de_fuentes_veta_la_respuesta_y_registra_conflicto() -> None:
    """Un conflicto declarado no se responde aunque la política vea evidencia."""
    state = _state(evidence="complete")
    resolution = _resolve(state, answer_state={"state": ANSWER_STATE_CONFLICTING})
    assert resolution.phase is RunPhase.ABSTAINED
    assert resolution.legacy_phase is RunPhase.ABSTAINED
    assert resolution.kind == CLOSURE_AUTHORITY_MISMATCH
    assert resolution.mismatch.split(":")[1] == "policy_finalize_over_conflict"


def test_conflicto_de_fuentes_sin_borrador_es_consistente() -> None:
    state = _state(evidence="insufficient")
    resolution = _resolve(
        state, answer="", answer_state={"state": ANSWER_STATE_CONFLICTING}
    )
    assert resolution.phase is RunPhase.ABSTAINED
    assert resolution.consistent


def test_conflicto_de_reglas_no_concluye() -> None:
    state = _state(evidence="complete")
    resolution = _resolve(
        state, answer_state={"state": "CONFLICTING_RULE"}
    )
    assert resolution.phase is RunPhase.UNDETERMINED
    assert resolution.legacy_phase is RunPhase.UNDETERMINED


# -----------------------------------------------------------------------------
# Propiedades del reducer.
# -----------------------------------------------------------------------------
def test_propiedad_finalized_requiere_autorizacion_de_cierre() -> None:
    """Ninguna combinación produce FINALIZED sin FINALIZE de la política."""
    statuses = ("completed", "error", "limit_reached", "blocked")
    evidences = ("complete", "insufficient", "failed", "unknown")
    families = (
        "",
        ANSWER_STATE_INSUFFICIENT,
        ANSWER_STATE_CONFLICTING,
        ANSWER_STATE_UNDETERMINED,
        ANSWER_STATE_RETRIEVAL_UNAVAILABLE,
        ANSWER_STATE_RULE_RETRIEVAL_UNAVAILABLE,
    )
    drafts = ("", _DRAFT)
    checked = 0
    for status in statuses:
        for evidence in evidences:
            for family in families:
                for draft in drafts:
                    for authority in (False, True):
                        for requires in (False, True):
                            state = _state(
                                evidence=evidence,
                                authority=authority,
                                requires_deterministic=requires,
                            )
                            resolution = resolve_closure_phase(
                                state,
                                status=status,
                                answer=draft,
                                answer_state={"state": family} if family else None,
                            )
                            checked += 1
                            if resolution.phase is RunPhase.FINALIZED:
                                assert resolution.decision is not None
                                assert (
                                    resolution.decision.action
                                    is FinalizationAction.FINALIZE
                                ), (status, evidence, family, draft, authority)
    assert checked >= 700


def test_estabilidad_cien_runs_misma_resolucion() -> None:
    state = _state(evidence="complete")
    first = _resolve(state, answer_state={"state": ANSWER_STATE_INSUFFICIENT})
    for _ in range(100):
        again = _resolve(state, answer_state={"state": ANSWER_STATE_INSUFFICIENT})
        assert again.phase is first.phase
        assert again.kind == first.kind
        assert again.mismatch == first.mismatch


# -----------------------------------------------------------------------------
# Integración: `finalize_state` aplica la resolución y publica la trazabilidad.
# -----------------------------------------------------------------------------
def test_trazabilidad_de_cierre_en_el_estado() -> None:
    state = _state(evidence="failed")
    violations = finalize_state(
        state, status="completed", answer=_DRAFT, answer_state=None
    )
    assert state.phase is RunPhase.BLOCKED
    assert state.decisions.closure is not None
    assert state.decisions.closure["phase"] == "BLOCKED"
    assert state.decisions.closure["legacy_phase"] == "FINALIZED"
    assert state.decisions.closure["consistent"] is False
    assert any(v.startswith(CLOSURE_AUTHORITY_MISMATCH) for v in violations)
    assert "closure_oracle:FINALIZED->BLOCKED" in state.trace.notes


def test_finalize_state_cierre_normal_es_consistente() -> None:
    state = _state(evidence="complete")
    violations = finalize_state(
        state, status="completed", answer=_DRAFT, answer_state=None
    )
    assert state.phase is RunPhase.FINALIZED
    assert state.decisions.closure["consistent"] is True
    assert violations == ()


def test_kinds_del_cierre_son_invariantes_criticos() -> None:
    assert CLOSURE_NOT_AUTHORIZED in CRITICAL_INVARIANTS
    assert CLOSURE_AUTHORITY_MISMATCH in CRITICAL_INVARIANTS
    assert CLOSURE_AUTHORITY_FAILED in CRITICAL_INVARIANTS


def test_los_literales_del_ratchet_coinciden_con_la_politica() -> None:
    """Los literales de `run_state` y las constantes de la política no divergen."""
    from src.runtime import finalization_policy as policy

    assert CLOSURE_NOT_AUTHORIZED == policy.CLOSURE_NOT_AUTHORIZED
    assert CLOSURE_AUTHORITY_MISMATCH == policy.CLOSURE_AUTHORITY_MISMATCH
    assert CLOSURE_AUTHORITY_FAILED == policy.CLOSURE_AUTHORITY_FAILED


# -----------------------------------------------------------------------------
# P1-A: un fallo de la autoridad del cierre es FAIL-CLOSED, nunca legacy.
# -----------------------------------------------------------------------------
class TestAutoridadDeCierreFailClosed:
    """Contrato: `closure_authority_failed` -> fallo operativo + motivo + traza.

    Un fallo del reducer NO puede terminar en FINALIZED por la existencia de
    texto ni por ningún dato legacy (`status`, `answer_state`).
    """

    @staticmethod
    def _fail(monkeypatch) -> None:
        import src.runtime.finalization_policy as policy

        def boom(*args, **kwargs):
            raise RuntimeError("reducer caido")

        monkeypatch.setattr(policy, "resolve_closure_phase", boom)

    def test_fallo_del_reducer_no_finaliza_por_texto(self, monkeypatch) -> None:
        self._fail(monkeypatch)
        state = _state(evidence="complete")
        violations = finalize_state(
            state, status="completed", answer=_DRAFT, answer_state=None
        )
        assert state.phase is RunPhase.FAILED
        assert state.terminal is True
        # Motivo estructurado (no solo texto de nota).
        assert any(v.startswith(CLOSURE_AUTHORITY_FAILED) for v in violations)
        closure = state.decisions.closure or {}
        assert closure["phase"] == "FAILED"
        assert closure["kind"] == CLOSURE_AUTHORITY_FAILED
        assert closure["reason_code"] == CLOSURE_AUTHORITY_FAILED
        assert closure["operational"] is True
        # El oráculo legacy sí ve texto: la divergencia es dato, no autoridad.
        assert closure["legacy_phase"] == "FINALIZED"
        assert closure["consistent"] is False
        # Traza observable del fallo.
        assert any(
            note.startswith("closure_authority_failed:")
            for note in state.trace.notes
        )
        assert "closure_oracle:FINALIZED->FAILED" in state.trace.notes
        # El bloqueo estricto lo consume como invariante crítico.
        assert state.critical_violations()

    def test_answer_state_aparentemente_valido_tampoco_finaliza(self, monkeypatch) -> None:
        self._fail(monkeypatch)
        from src.runtime.answer_state import ANSWER_STATE_DERIVED

        state = _state(evidence="complete", authority=True)
        violations = finalize_state(
            state,
            status="completed",
            answer=_DRAFT,
            answer_state={"state": ANSWER_STATE_DERIVED},
        )
        assert state.phase is RunPhase.FAILED
        assert any(v.startswith(CLOSURE_AUTHORITY_FAILED) for v in violations)

    def test_ningun_dato_legacy_convierte_fallo_en_success(self, monkeypatch) -> None:
        """Barrido de combinaciones: el fallo de autoridad jamás da FINALIZED."""
        self._fail(monkeypatch)
        from src.runtime.answer_state import (
            ANSWER_STATE_DERIVED,
            ANSWER_STATE_INSUFFICIENT,
        )

        statuses = ("completed", "error", "limit_reached", "blocked", "failed")
        families = (
            None,
            {"state": ""},
            {"state": ANSWER_STATE_DERIVED},
            {"state": ANSWER_STATE_INSUFFICIENT},
        )
        drafts = ("", _DRAFT)
        checked = 0
        for status in statuses:
            for family in families:
                for draft in drafts:
                    state = _state(evidence="complete")
                    finalize_state(
                        state,
                        status=status,
                        answer=draft,
                        answer_state=family,
                    )
                    checked += 1
                    assert state.phase is not RunPhase.FINALIZED, (
                        status,
                        family,
                        draft,
                    )
                    assert state.phase is RunPhase.FAILED
        assert checked >= 40

    def test_finish_sin_resolucion_cae_a_fallo_operativo(self) -> None:
        """Defensa en profundidad: `finish()` sin autoridad no usa el mapper."""
        state = _state(evidence="complete")
        phase = state.finish(status="completed", answer=_DRAFT, answer_state=None)
        assert phase is RunPhase.FAILED
        assert state.phase is RunPhase.FAILED
        assert any(
            note.startswith("closure_authority_missing:")
            for note in state.trace.notes
        )

    def test_finish_ignora_fase_no_terminal_como_autoridad(self) -> None:
        state = _state()
        phase = state.finish(
            status="completed",
            answer=_DRAFT,
            answer_state=None,
            phase_override=RunPhase.REASONING,
        )
        assert phase is RunPhase.FAILED

    def test_override_post_cierre_solo_acepta_fases_no_concluyentes(self) -> None:
        state = _state(evidence="complete")
        finalize_state(state, status="completed", answer=_DRAFT, answer_state=None)
        assert state.phase is RunPhase.FINALIZED
        assert (
            state.apply_closure_override(
                RunPhase.FINALIZED, reason_code="strict_block"
            )
            is False
        )
        assert state.phase is RunPhase.FINALIZED
        assert state.apply_closure_override(
            RunPhase.UNDETERMINED, reason_code="strict_block"
        ) is True
        assert state.phase is RunPhase.UNDETERMINED
        assert any(
            note.startswith("terminal_overridden:FINALIZED->UNDETERMINED")
            for note in state.trace.notes
        )


# -----------------------------------------------------------------------------
# Modo estricto: el bloqueo consume la resolución (fail-closed documentado).
# -----------------------------------------------------------------------------
def test_modo_estricto_global_existe_y_es_apagable() -> None:
    assert strict_mode_enabled(
        SimpleNamespace(RUNTIME_RUN_STATE_STRICT="on", RUNTIME_RUN_STATE_STRICT_ORGS="")
    )
    assert not strict_mode_enabled(
        SimpleNamespace(RUNTIME_RUN_STATE_STRICT="off", RUNTIME_RUN_STATE_STRICT_ORGS="")
    )


def test_modo_estricto_por_org_canary_sigue_mandando() -> None:
    assert strict_mode_enabled(
        SimpleNamespace(
            RUNTIME_RUN_STATE_STRICT="off",
            RUNTIME_RUN_STATE_STRICT_ORGS="org-canary",
        ),
        organization_id="org-canary",
    )


def test_config_declara_el_flag_estricto_global() -> None:
    """El flag documentado existe en Settings (el `getattr` ya no cae al default)."""
    from src.core.config import Settings

    assert "RUNTIME_RUN_STATE_STRICT" in Settings.model_fields
    field = Settings.model_fields["RUNTIME_RUN_STATE_STRICT"]
    assert field.default == "off"
