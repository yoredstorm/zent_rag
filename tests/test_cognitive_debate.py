# =============================================================================
# Critique + bounded debate — dominio puro (Phase 6)
# =============================================================================
from __future__ import annotations

from uuid import uuid4

from src.core.domain.debate import (
    DebateOutcomeKind,
    build_critique,
    evidence_support_ratio,
    run_debate_round,
)
from src.core.domain.evidence import (
    ClaimRecord,
    ClaimVerificationStatus,
    EvidenceRecord,
)
from src.core.domain.temporal_conflict import ClaimTemporalState


def _claim(**overrides) -> ClaimRecord:
    base = dict(
        organization_id=uuid4(),
        text="La penalidad del contrato ACME es 5%.",
        normalized_subject="penalidad contrato acme",
        normalized_predicate="es",
        normalized_object="5%",
    )
    base.update(overrides)
    return ClaimRecord(**base)


def _evidence(excerpt: str, *, score: float | None = 0.9) -> EvidenceRecord:
    return EvidenceRecord(
        organization_id=uuid4(),
        excerpt=excerpt,
        content_hash="hash",
        retrieval_score=score,
    )


def test_build_critique_flags_concrete_problems() -> None:
    short_record = _evidence("La penalidad es 5%.")  # < 80 chars → weak
    supported = _claim(evidence_ids=(short_record.id,))
    no_evidence = _claim(
        text="El plazo de pago es 30 días.", normalized_object="30 dias"
    )
    historical = _claim(temporal_scope="2024")
    conflicted = _claim(
        status=ClaimVerificationStatus.CONFLICTED, normalized_object="7%"
    )
    conflict = {
        "claims": [str(conflicted.id)],
        "reason": "valores distintos",
    }

    report = build_critique(
        claims=[supported, no_evidence, historical, conflicted],
        evidence=[short_record],
        temporal={historical.id: ClaimTemporalState.HISTORICAL},
        conflicts=[conflict],
    )

    kinds = {issue.kind.value for issue in report.issues}
    assert "missing_evidence" in kinds
    assert "weak_citation" in kinds
    assert "temporal_assumption" in kinds
    assert "unresolved_conflict" in kinds
    assert report.checked_claims == 4
    assert report.unresolved_conflicts == 1
    assert "Critique:" in report.summary


def test_evidence_support_ratio_is_deterministic() -> None:
    assert evidence_support_ratio("penalidad 5%", "La penalidad es 5%.") == 1.0
    assert evidence_support_ratio("plazo de pago", "penalidad") == 0.0
    assert evidence_support_ratio("", "algo") == 0.0


def test_run_debate_round_defends_or_upholds_with_max_rounds() -> None:
    defended_record = _evidence("La penalidad del contrato ACME es 5%.")
    defended = _claim(evidence_ids=(defended_record.id,))
    challenged = _claim(
        text="El plazo de pago es 30 días.", normalized_object="30 dias"
    )
    report = build_critique(
        claims=[defended, challenged],
        evidence=[defended_record],
        temporal={},
        conflicts=[],
    )

    outcomes = run_debate_round(
        report=report,
        claims={defended.id: defended, challenged.id: challenged},
        evidence=[defended_record],
        max_rounds=1,
    )
    by_claim = {outcome.claim_id: outcome for outcome in outcomes}
    assert by_claim[defended.id].kind is DebateOutcomeKind.DEFENDED
    assert by_claim[challenged.id].kind is DebateOutcomeKind.UPHELD
    assert by_claim[challenged.id].requires_review is True
    # un challenge → UNA respuesta (sin ping-pong)
    assert len(outcomes) == len({outcome.claim_id for outcome in outcomes})

    assert (
        run_debate_round(
            report=report,
            claims={defended.id: defended},
            evidence=[defended_record],
            max_rounds=0,
        )
        == ()
    )
