# =============================================================================
# FINAL_AUTHORITY_LOCK — el texto final no puede contradecir la autoridad
# =============================================================================
# Con DecisionEnvelope.authoritative=true, ninguna oración puede dudar
# (incertidumbre epistémica) ni invertir la polaridad del resultado.
# Invariante AUTHORITATIVE_RESPONSE_CONSISTENCY.
# =============================================================================
from __future__ import annotations

import random

import pytest

from src.runtime.decision_envelope import (
    DecisionEnvelope,
    build_operation_explanation,
    finalize_authoritative_answer,
)
from src.runtime.derived_guard import (
    contains_epistemic_uncertainty,
    contradicts_authoritative_result,
    enforce_derived_result,
)

MATCH_ENVELOPE = DecisionEnvelope(
    state="ANSWERABLE_DERIVED",
    operation="POSITIONAL_MATCH",
    result="MATCH",
    authoritative=True,
    statement="la regla compilada «Record 2» se cumple",
    runtime_inputs=("pattern=&&&F", "value=ABCFGEGE"),
    evidence_refs=("ev:1",),
)
NO_MATCH_ENVELOPE = DecisionEnvelope(
    state="ANSWERABLE_DERIVED",
    operation="POSITIONAL_MATCH",
    result="NO_MATCH",
    authoritative=True,
)

EPISTEMIC_DRAFTS = (
    "No se puede determinar si cumple: falta la premisa de dominio que define "
    "qué significa el patrón.",
    "No puedo determinarlo porque falta en las fuentes la definición necesaria "
    "del símbolo «&».",
    "La evidencia es insuficiente para concluir.",
    "No es evaluable con los datos disponibles.",
    "No puedo concluir si cumple.",
    "Cannot determine whether it matches.",
    "Insufficient evidence to decide.",
    "missing premise: definition of the symbol.",
)


def _headline_of(answer: str) -> str:
    return answer.splitlines()[0].strip() if answer.strip() else ""


def _assert_locked(answer: str, envelope: DecisionEnvelope) -> None:
    assert _headline_of(answer) == envelope.headline
    assert contains_epistemic_uncertainty(answer) == ""
    assert contradicts_authoritative_result(answer, envelope.normalized_result) == ""


# ---------------------------------------------------------------------------
# A / B: la contradicción epistémica invalida el borrador (ambas polaridades)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("envelope", [MATCH_ENVELOPE, NO_MATCH_ENVELOPE])
def test_epistemic_draft_is_overridden(envelope: DecisionEnvelope) -> None:
    draft = (
        "No se puede determinar si cumple: falta la premisa de dominio que "
        "define qué significa el patrón."
    )
    final = finalize_authoritative_answer(draft, envelope=envelope)
    assert final.overridden is True
    assert final.lock_action == "rebuilt"
    _assert_locked(final.answer, envelope)
    # La explicación determinista reemplaza al borrador contradictorio.
    assert build_operation_explanation(envelope).splitlines()[0] in final.answer


def test_missing_premise_draft_is_overridden() -> None:
    final = finalize_authoritative_answer(
        "Sí, cumple. Falta una premisa para estar seguros.",
        envelope=MATCH_ENVELOPE,
    )
    assert final.overridden is True
    _assert_locked(final.answer, MATCH_ENVELOPE)


def test_reported_bug_no_longer_concatenates_contradiction() -> None:
    """Bug P0: «Sí, cumple.» seguido del texto «No se puede determinar...»."""
    draft = (
        "No se puede determinar si cumple: falta la premisa de dominio que "
        "define qué significa el patrón."
    )
    final = finalize_authoritative_answer(draft, envelope=MATCH_ENVELOPE)
    assert "No se puede determinar" not in final.answer
    assert final.answer.startswith("Sí, cumple.")
    assert "no se puede" not in final.answer.lower()


# ---------------------------------------------------------------------------
# D / E: borradores compatibles se preservan
# ---------------------------------------------------------------------------


def test_compatible_explanation_is_preserved() -> None:
    draft = "El valor ABCFGEGE cumple el patrón &&&F posición a posición."
    final = finalize_authoritative_answer(draft, envelope=MATCH_ENVELOPE)
    assert final.overridden is False
    assert final.lock_action == "preserved"
    assert "posición a posición" in final.answer
    _assert_locked(final.answer, MATCH_ENVELOPE)


def test_unrelated_caveat_is_preserved() -> None:
    draft = (
        "Sí, cumple.\n\nEl valor ABCFGEGE satisface el patrón &&&F. "
        "La respuesta aplica a tarifas vigentes en 2026."
    )
    final = finalize_authoritative_answer(draft, envelope=MATCH_ENVELOPE)
    assert final.overridden is False
    assert "tarifas vigentes en 2026" in final.answer
    _assert_locked(final.answer, MATCH_ENVELOPE)


# ---------------------------------------------------------------------------
# Guard: la detección epistémica también vive en el guard
# ---------------------------------------------------------------------------


def test_guard_detects_epistemic_uncertainty() -> None:
    claim = {
        "deterministic": True,
        "verification_status": "SUPPORTED",
        "result": True,
        "operation": "POSITIONAL_MATCH",
        "user_inputs": ["pattern=&&&F", "value=ABCFGEGE"],
        "canonical_rule_ids": ["rule:x"],
    }
    verdict = enforce_derived_result(
        "No se puede determinar si cumple: falta la premisa.", [claim]
    )
    assert verdict.overridden is True
    assert verdict.contradictions


def test_epistemic_never_classified_as_positive_alignment() -> None:
    # «no se puede determinar si cumple» contiene «cumple» pero NO es positiva.
    assert contains_epistemic_uncertainty("No se puede determinar si cumple.")
    assert contradicts_authoritative_result("No se puede determinar si cumple.", "MATCH")


# ---------------------------------------------------------------------------
# F: 100 borradores adversariales — headline y cuerpo siempre compatibles
# ---------------------------------------------------------------------------


def test_100_adversarial_drafts_stay_consistent() -> None:
    rng = random.Random(20261007)  # noqa: S311 — test determinista, no criptográfico
    positive = (
        "Sí, cumple.",
        "El valor ABCFGEGE cumple el patrón &&&F.",
        "Resultado: MATCH posición a posición.",
    )
    negative = (
        "No cumple.",
        "El valor no coincide con el patrón.",
        "Resultado: NO_MATCH.",
    )
    neutral = (
        "El patrón tiene cuatro posiciones.",
        "Se comparó el fare basis con la máscara.",
        "La regla compilada proviene de Record 2.",
    )
    for _ in range(100):
        envelope = rng.choice((MATCH_ENVELOPE, NO_MATCH_ENVELOPE))
        parts: list[str] = []
        for _ in range(rng.randint(1, 3)):
            pool = rng.choice(
                (
                    positive,
                    negative,
                    neutral,
                    EPISTEMIC_DRAFTS,
                )
            )
            parts.append(rng.choice(pool))
        draft = " ".join(parts)
        final = finalize_authoritative_answer(draft, envelope=envelope)
        _assert_locked(final.answer, envelope)
