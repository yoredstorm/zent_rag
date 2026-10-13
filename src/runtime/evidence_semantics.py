# =============================================================================
# Evidence semantics — vocabulario único de la condición de evidencia.
# =============================================================================
# Las señales de evidencia NO son sinónimos. Este módulo clasifica el estado del
# run en UNA condición canónica, con prioridad explícita y determinista, para
# que ninguna capa traduzca:
#
#   * `retrieval unavailable` como «no existe información»;
#   * `partial coverage` como certeza;
#   * una abstención genérica en contra de autoridad canónica suficiente.
#
# No decide el cierre: la resolución es de `finalization_policy`. Este módulo
# mide y publica (observabilidad + tests de transición). La condición es
# determinista: mismas señales, misma condición.
#
# Los stops del motor long-context se toman de sus constantes reales
# (`src/rag/longcontext/engine.py`); un test fija que el conjunto COMPLETE sea
# exactamente el que el orquestador trata como completitud canónica y que
# COMPLETE y PARTIAL sean disjuntos.
# =============================================================================
from __future__ import annotations

from enum import StrEnum
from typing import Any

#: Stops que declaran cobertura COMPLETA. Debe coincidir con
#: `orchestrator._CANONICAL_COMPLETE_STOPS` (test de pin).
COMPLETE_STOPS: frozenset[str] = frozenset(
    {
        "evidence_complete_initial",
        "evidence_complete",
        "confidence_threshold",
        "long_context_escalated",
    }
)

#: Stops que significan «no se buscará más» sin declarar completitud.
PARTIAL_STOPS: frozenset[str] = frozenset(
    {
        "expansion_redundant",
        "redundant_streak",
        "max_expansions",
        "max_tier_reached",
        "strategies_exhausted",
        "no_more_sources",
        "cost_limit_reached",
        "no_retrieval",
    }
)


class EvidenceCondition(StrEnum):
    RETRIEVAL_UNAVAILABLE = "RETRIEVAL_UNAVAILABLE"
    EVIDENCE_CONTRADICTORY = "EVIDENCE_CONTRADICTORY"
    CANONICAL_AUTHORITY_PRESENT = "CANONICAL_AUTHORITY_PRESENT"
    PREMISE_MISSING = "PREMISE_MISSING"
    EVIDENCE_ABSENT = "EVIDENCE_ABSENT"
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
    COVERAGE_COMPLETE = "COVERAGE_COMPLETE"
    COVERAGE_PARTIAL = "COVERAGE_PARTIAL"
    UNKNOWN = "UNKNOWN"


#: Prioridad única de clasificación (mayor manda). Documentada para que un
#: cambio de orden sea una decisión, no un accidente.
PRIORITY: tuple[EvidenceCondition, ...] = (
    EvidenceCondition.RETRIEVAL_UNAVAILABLE,
    EvidenceCondition.EVIDENCE_CONTRADICTORY,
    EvidenceCondition.CANONICAL_AUTHORITY_PRESENT,
    EvidenceCondition.PREMISE_MISSING,
    EvidenceCondition.EVIDENCE_ABSENT,
    EvidenceCondition.EVIDENCE_INSUFFICIENT,
    EvidenceCondition.COVERAGE_PARTIAL,
    EvidenceCondition.COVERAGE_COMPLETE,
    EvidenceCondition.UNKNOWN,
)

#: Condiciones que NUNCA pueden presentarse como respuesta binaria.
NON_ANSWERABLE: frozenset[EvidenceCondition] = frozenset(
    {
        EvidenceCondition.RETRIEVAL_UNAVAILABLE,
        EvidenceCondition.EVIDENCE_CONTRADICTORY,
        EvidenceCondition.EVIDENCE_ABSENT,
        EvidenceCondition.EVIDENCE_INSUFFICIENT,
        EvidenceCondition.PREMISE_MISSING,
    }
)


def _conflict_declared(answer_state: dict | None) -> bool:
    from src.runtime.answer_state import (
        ANSWER_STATE_CONFLICTING,
        ANSWER_STATE_CONFLICTING_RULE,
    )

    state = str((answer_state or {}).get("state") or "").strip()
    return state in {ANSWER_STATE_CONFLICTING, ANSWER_STATE_CONFLICTING_RULE}


def long_context_stop(state: Any) -> str:
    """Stop declarado por el motor long-context ("" si no aplicó)."""
    if not bool(getattr(state.evidence, "long_context_applied", False)):
        return ""
    return str(getattr(state.evidence, "long_context_stop", "") or "")


def classify_evidence_condition(
    state: Any, *, answer_state: dict | None = None
) -> EvidenceCondition:
    """Clasifica la condición de evidencia del run (determinista, sin I/O)."""
    evidence = state.evidence
    sufficiency = getattr(evidence, "sufficiency", None)
    complete = bool(getattr(evidence, "complete", False))
    retrieval_failed = bool(getattr(evidence, "retrieval_failed", False))
    canonical = getattr(evidence, "canonical_state", None)
    decisions = state.decisions
    stop = long_context_stop(state)

    # 1. Fallo operativo: no se pudo buscar. Jamás «no hay información».
    if retrieval_failed and not complete:
        return EvidenceCondition.RETRIEVAL_UNAVAILABLE

    # 2. Contradicción declarada (fuentes o reglas): no hay respuesta binaria.
    conflicting = getattr(sufficiency, "conflicting_chunks", None)
    if (isinstance(conflicting, int) and conflicting > 0) or _conflict_declared(
        answer_state
    ):
        return EvidenceCondition.EVIDENCE_CONTRADICTORY

    # 3. Autoridad determinista presente: la abstención genérica no la invalida.
    if bool(getattr(decisions, "authoritative", False)) or str(
        getattr(decisions, "external_authority", "") or ""
    ):
        return EvidenceCondition.CANONICAL_AUTHORITY_PRESENT

    # 4. Premisas faltantes: falta semántica, no documentación.
    if tuple(getattr(sufficiency, "missing_premises", ()) or ()):
        return EvidenceCondition.PREMISE_MISSING

    # 5. Ausencia vs insuficiencia (realidades distintas).
    supporting = int(getattr(sufficiency, "supporting_chunks", 0) or 0)
    has_evidence = bool(getattr(sufficiency, "has_evidence", False))
    documentable_missing = tuple(
        getattr(sufficiency, "documentable_missing", ()) or ()
    )
    if (
        sufficiency is not None
        and supporting <= 0
        and not has_evidence
        and not complete
    ):
        return EvidenceCondition.EVIDENCE_ABSENT
    if documentable_missing or (
        sufficiency is not None and not complete and supporting > 0
    ):
        return EvidenceCondition.EVIDENCE_INSUFFICIENT

    # 6. El motor declaró «no buscaré más» sin completitud: cobertura parcial.
    if stop and stop in PARTIAL_STOPS:
        return EvidenceCondition.COVERAGE_PARTIAL

    # 7. Cobertura completa declarada (motor o estado canónico).
    if complete or (
        isinstance(canonical, dict)
        and str(canonical.get("generation_mode") or "") == "generate_full"
    ):
        return EvidenceCondition.COVERAGE_COMPLETE
    if isinstance(canonical, dict) and canonical:
        mode = str(canonical.get("generation_mode") or "")
        if mode and mode != "generate_full":
            return EvidenceCondition.COVERAGE_PARTIAL

    return EvidenceCondition.UNKNOWN


def condition_conflict(state: Any, condition: EvidenceCondition) -> str:
    """Conflicto entre la condición medida y lo que el run declara.

    Devuelve "" si no hay conflicto. Casos que importan:
      * cobertura parcial presentada como completa (evidencia parcial convertida
        en certeza);
      * fallo de retrieval traducido como insuficiencia documental.
    """
    complete = bool(getattr(state.evidence, "complete", False))
    stop = long_context_stop(state)
    if condition is EvidenceCondition.COVERAGE_PARTIAL and (
        complete or (stop and stop in COMPLETE_STOPS)
    ):
        return "partial_coverage_declared_complete"
    if condition is EvidenceCondition.RETRIEVAL_UNAVAILABLE and str(
        getattr(state.decisions, "final_state", "") or ""
    ) in {"INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE"}:
        return "retrieval_failure_reported_as_insufficiency"
    return ""


def observe_condition(state: Any, condition: Any, *, conflict: str = "") -> None:
    """Publica la condición de evidencia y sus conflictos (fail-soft)."""
    try:
        from src.infrastructure.observability.metrics import (
            zent_evidence_condition_conflicts_total,
            zent_evidence_condition_total,
        )

        path = str(getattr(getattr(state, "identity", None), "kind", "") or "unknown")
        text = str(condition or "")
        if not text:
            return
        zent_evidence_condition_total.labels(path=path, condition=text).inc()
        if conflict:
            zent_evidence_condition_conflicts_total.labels(
                path=path, condition=text, kind=str(conflict)
            ).inc()
    except Exception:  # noqa: BLE001 — observabilidad, nunca rompe el cierre
        pass


__all__ = [
    "COMPLETE_STOPS",
    "NON_ANSWERABLE",
    "PARTIAL_STOPS",
    "PRIORITY",
    "EvidenceCondition",
    "classify_evidence_condition",
    "condition_conflict",
    "long_context_stop",
    "observe_condition",
]
