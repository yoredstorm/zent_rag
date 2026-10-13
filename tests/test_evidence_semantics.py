# =============================================================================
# Semántica de evidencia — condiciones que NO son sinónimos.
# =============================================================================
# Contrato (Parte F):
#   * `retrieval unavailable` jamás se traduce como «no existe información»;
#   * `partial coverage` jamás se presenta como certeza;
#   * una abstención genérica no invalida una respuesta con autoridad canónica;
#   * ausencia, insuficiencia, contradicción y premisa faltante son condiciones
#     distintas y transitables;
#   * el vocabulario de stops del motor long-context está fijado: COMPLETE debe
#     coincidir con el conjunto canónico del orquestador y ser disjunto de
#     PARTIAL.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace

from src.runtime.answer_state import (
    ANSWER_STATE_CONFLICTING_RULE,
    ANSWER_STATE_INSUFFICIENT,
)
from src.runtime.evidence_semantics import (
    COMPLETE_STOPS,
    NON_ANSWERABLE,
    PARTIAL_STOPS,
    PRIORITY,
    EvidenceCondition,
    classify_evidence_condition,
    condition_conflict,
)
from src.runtime.run_state import AgentRunState, RunIdentity


def _state(
    *,
    evidence: str = "unknown",
    conflicting: int | None = None,
    missing_premises: tuple[str, ...] = (),
    authority: bool = False,
    external: str = "",
    long_context: str = "",
    canonical: dict | None = None,
) -> AgentRunState:
    state = AgentRunState(identity=RunIdentity(run_id="evidence-semantics"))
    sufficiency = None
    if evidence == "complete":
        sufficiency = SimpleNamespace(
            has_evidence=True,
            supporting_chunks=4,
            evidence_complete=True,
            recommended_action="generate",
            missing_entities=(),
            missing_anchors=(),
            documentable_missing=(),
            missing_premises=missing_premises,
            conflicting_chunks=conflicting,
        )
    elif evidence == "insufficient":
        sufficiency = SimpleNamespace(
            has_evidence=True,
            supporting_chunks=2,
            evidence_complete=False,
            recommended_action="retrieve_more",
            missing_entities=("efectividad",),
            missing_anchors=(),
            documentable_missing=("efectividad",),
            missing_premises=missing_premises,
            conflicting_chunks=conflicting,
        )
    elif evidence == "absent":
        sufficiency = SimpleNamespace(
            has_evidence=False,
            supporting_chunks=0,
            evidence_complete=False,
            recommended_action="abstain",
            missing_entities=(),
            missing_anchors=(),
            documentable_missing=(),
            missing_premises=missing_premises,
            conflicting_chunks=conflicting,
        )
    elif evidence == "chunks_only":
        sufficiency = SimpleNamespace(
            has_evidence=True,
            supporting_chunks=3,
            evidence_complete=False,
            recommended_action="retrieve_more",
            missing_entities=(),
            missing_anchors=(),
            documentable_missing=(),
            missing_premises=missing_premises,
            conflicting_chunks=conflicting,
        )
    if sufficiency is not None:
        state.evidence.observe(sufficiency=sufficiency)
    if canonical is not None:
        state.evidence.observe(canonical_state=canonical)
    if authority:
        state.decisions.set_envelope(
            SimpleNamespace(authoritative=True, state="MATCH")
        )
    if external:
        state.decisions.observe_external_authority(external)
    if long_context:
        state.evidence.long_context_applied = True
        state.evidence.long_context_stop = long_context
    return state


# -----------------------------------------------------------------------------
# Condiciones canónicas.
# -----------------------------------------------------------------------------
def test_retrieval_unavailable_no_es_ausencia() -> None:
    state = _state(evidence="insufficient")
    state.evidence.retrieval_failed = True
    assert (
        classify_evidence_condition(state)
        is EvidenceCondition.RETRIEVAL_UNAVAILABLE
    )
    assert EvidenceCondition.RETRIEVAL_UNAVAILABLE in NON_ANSWERABLE
    assert EvidenceCondition.EVIDENCE_ABSENT in NON_ANSWERABLE


def test_ausencia_e_insuficiencia_son_distintas() -> None:
    assert (
        classify_evidence_condition(_state(evidence="absent"))
        is EvidenceCondition.EVIDENCE_ABSENT
    )
    assert (
        classify_evidence_condition(_state(evidence="insufficient"))
        is EvidenceCondition.EVIDENCE_INSUFFICIENT
    )


def test_contradiccion_de_fuentes_gana_a_la_completitud() -> None:
    state = _state(evidence="complete", conflicting=2)
    assert (
        classify_evidence_condition(state)
        is EvidenceCondition.EVIDENCE_CONTRADICTORY
    )


def test_contradiccion_declarada_por_el_estado_de_respuesta() -> None:
    state = _state(evidence="complete")
    assert (
        classify_evidence_condition(
            state, answer_state={"state": ANSWER_STATE_CONFLICTING_RULE}
        )
        is EvidenceCondition.EVIDENCE_CONTRADICTORY
    )


def test_autoridad_canonica_gana_a_la_insuficiencia() -> None:
    state = _state(evidence="insufficient", authority=True)
    assert (
        classify_evidence_condition(state)
        is EvidenceCondition.CANONICAL_AUTHORITY_PRESENT
    )
    assert EvidenceCondition.CANONICAL_AUTHORITY_PRESENT not in NON_ANSWERABLE


def test_autoridad_externa_tambien_cuenta() -> None:
    state = _state(evidence="insufficient", external="sql")
    assert (
        classify_evidence_condition(state)
        is EvidenceCondition.CANONICAL_AUTHORITY_PRESENT
    )


def test_premisa_faltante_no_es_insuficiencia_documental() -> None:
    state = _state(evidence="complete", missing_premises=("ratio",))
    assert (
        classify_evidence_condition(state) is EvidenceCondition.PREMISE_MISSING
    )


def test_cobertura_completa_y_parcial_se_distinguen() -> None:
    assert (
        classify_evidence_condition(_state(evidence="complete"))
        is EvidenceCondition.COVERAGE_COMPLETE
    )
    # El motor declaró un stop SIN completitud: la condición es parcial aunque
    # la suficiencia documental diga completa (se mide, no se enmascara).
    assert (
        classify_evidence_condition(
            _state(evidence="complete", long_context="no_more_sources")
        )
        is EvidenceCondition.COVERAGE_PARTIAL
    )


def test_sin_senales_es_unknown() -> None:
    assert (
        classify_evidence_condition(_state())
        is EvidenceCondition.UNKNOWN
    )


def test_generation_mode_de_limites_es_cobertura_parcial() -> None:
    state = _state(canonical={"generation_mode": "generate_with_limits"})
    assert (
        classify_evidence_condition(state) is EvidenceCondition.COVERAGE_PARTIAL
    )


# -----------------------------------------------------------------------------
# Conflictos medidos (sin cambiar la respuesta).
# -----------------------------------------------------------------------------
def test_fallo_de_retrieval_reportado_como_insuficiencia() -> None:
    state = _state(evidence="insufficient")
    state.evidence.retrieval_failed = True
    state.decisions.final_state = ANSWER_STATE_INSUFFICIENT
    condition = classify_evidence_condition(state)
    assert (
        condition_conflict(state, condition)
        == "retrieval_failure_reported_as_insufficiency"
    )


def test_cobertura_parcial_declarada_completa_se_marca() -> None:
    """El caso de certeza falsa: el motor paró sin completitud pero el run
    declara evidencia completa."""
    state = _state(evidence="complete", long_context="no_more_sources")
    state.evidence.observe(
        canonical_state={"generation_mode": "generate_full"}
    )
    condition = classify_evidence_condition(state)
    assert condition is EvidenceCondition.COVERAGE_PARTIAL
    assert (
        condition_conflict(state, condition)
        == "partial_coverage_declared_complete"
    )


def test_condicion_sin_conflicto_no_marca_nada() -> None:
    state = _state(evidence="complete")
    condition = classify_evidence_condition(state)
    assert condition_conflict(state, condition) == ""


# -----------------------------------------------------------------------------
# El vocabulario de stops está fijado (ratchet contra deriva).
# -----------------------------------------------------------------------------
def test_complete_stops_coincide_con_el_orquestador() -> None:
    from src.agents.runtime.orchestrator import _CANONICAL_COMPLETE_STOPS

    assert COMPLETE_STOPS == frozenset(_CANONICAL_COMPLETE_STOPS), (
        "El conjunto de stops que declaran completitud canónica divergió: "
        "actualizá evidence_semantics y el orquestador en el mismo commit."
    )


def test_complete_y_partial_son_disjuntos() -> None:
    assert not (COMPLETE_STOPS & PARTIAL_STOPS)


def test_partial_stops_son_stops_reales_del_motor() -> None:
    from src.rag.longcontext import engine

    real = {
        value
        for name, value in vars(engine).items()
        if name.startswith("STOP_") and isinstance(value, str)
    }
    assert PARTIAL_STOPS <= real, sorted(PARTIAL_STOPS - real)
    assert COMPLETE_STOPS <= real, sorted(COMPLETE_STOPS - real)
    assert real == COMPLETE_STOPS | PARTIAL_STOPS, sorted(
        real - COMPLETE_STOPS - PARTIAL_STOPS
    )


def test_prioridad_cubre_todas_las_condiciones() -> None:
    assert set(PRIORITY) == set(EvidenceCondition)
    assert len(PRIORITY) == len(set(PRIORITY))


# -----------------------------------------------------------------------------
# Determinismo y estabilidad.
# -----------------------------------------------------------------------------
def test_estabilidad_cien_runs() -> None:
    state = _state(evidence="insufficient", long_context="no_more_sources")
    first = classify_evidence_condition(state)
    for _ in range(100):
        assert classify_evidence_condition(state) is first


def test_matriz_de_condiciones_es_determinista() -> None:
    cases = [
        dict(evidence="complete"),
        dict(evidence="insufficient"),
        dict(evidence="absent"),
        dict(evidence="chunks_only"),
        dict(evidence="complete", conflicting=1),
        dict(evidence="complete", missing_premises=("x",)),
        dict(evidence="insufficient", authority=True),
        dict(evidence="insufficient", external="cognitive_deep"),
        dict(evidence="chunks_only", long_context="max_tier_reached"),
        dict(canonical={"generation_mode": "generate_full"}),
        dict(canonical={"generation_mode": "retrieve_more"}),
    ]
    seen: list[str] = []
    for kwargs in cases:
        state = _state(**kwargs)
        condition = classify_evidence_condition(state)
        seen.append(str(condition))
        for _ in range(20):
            assert classify_evidence_condition(state) is condition
    assert len(seen) >= 8
