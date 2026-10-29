# =============================================================================
# P18.3-03 - Contrato de verificación: decisión no aplicable vs narrativa
# =============================================================================
from __future__ import annotations

from src.runtime.agent_flow import verification_summary
from src.runtime.decision_verification import NarrativeVerificationInput


def _narrative(status: str = "VERIFIED") -> dict:
    return {
        "type": "narrative_evidence",
        "query_mode": "INFORMATIONAL",
        "verification_input": NarrativeVerificationInput(
            verification=status,
            grounding="COMPLETE" if status == "VERIFIED" else "PARTIAL",
            citations_valid=True if status == "VERIFIED" else False,
            supports=(
                {
                    "claim": "Debe cuidar la flor.",
                    "status": "SUPPORTED" if status == "VERIFIED" else "PARTIAL",
                    "evidence_id": "E1",
                },
            ),
            cited_evidence_ids=("E1",),
            used_evidence_ids=("E1",),
            query_mode="INFORMATIONAL",
        ).to_public_dict(),
    }


def test_skipped_answer_gate_does_not_fake_blocked_grounding() -> None:
    steps = [
        {
            "type": "answer_gate",
            "provider": "skip",
            "mode": "on",
            "verdict": "skipped",
            "grounded": False,
            "complete": False,
        },
        _narrative("VERIFIED"),
    ]
    summary = verification_summary(steps, {})
    grounding = next(
        (check for check in summary["checks"] if check["key"] == "grounding"), None
    )
    assert grounding is None
    assert summary["overall"] == "verified"
    assert summary["overall_verification"] == "RESPALDO_CONFIRMADO"


def test_real_gate_without_grounding_still_blocks() -> None:
    steps = [
        {
            "type": "answer_gate",
            "provider": "jev",
            "mode": "on",
            "verdict": "approve",
            "grounded": False,
            "complete": True,
        },
        _narrative("VERIFIED"),
    ]
    summary = verification_summary(steps, {})
    assert summary["overall"] == "blocked"


def test_narrative_partial_keeps_partial_even_if_gate_skipped() -> None:
    steps = [
        {
            "type": "answer_gate",
            "provider": "skip",
            "mode": "on",
            "verdict": "skipped",
            "grounded": False,
        },
        _narrative("PARTIAL"),
    ]
    summary = verification_summary(steps, {})
    assert summary["overall"] == "partial"
    assert summary["overall_verification"] == "PARTIALLY_GROUNDED"
