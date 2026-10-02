# =============================================================================
# Learning signals — qué aprendió/falta del turno (S10, C4).
# =============================================================================
from __future__ import annotations

from src.runtime.entity_resolution import (
    EntityMatch,
    EntityResolution,
    MentionResolution,
)
from src.runtime.evidence_assembly import (
    EvidenceConflict,
    EvidencePackage,
    EvidenceUnit,
)
from src.runtime.learning_signal import (
    PERSISTABLE_KINDS,
    build_learning_signals,
)
from src.runtime.verification import AnswerVerification, ClaimVerdict


def test_entidad_sin_resolver() -> None:
    entities = EntityResolution(
        mentions=(
            MentionResolution(mention="Record 99", status="unresolved", matches=()),
            MentionResolution(
                mention="Category 31",
                status="resolved",
                matches=(
                    EntityMatch(
                        mention="Category 31",
                        canonical_id="c1",
                        name="Category 31",
                        kind="entity",
                        match="exact_name",
                        confidence=0.9,
                    ),
                ),
            ),
        )
    )
    signals = build_learning_signals(entities=entities)
    assert len(signals) == 1
    assert signals[0].kind == "unresolved_entity"
    assert signals[0].concept == "Record 99"
    assert "unresolved_entity" in PERSISTABLE_KINDS


def test_conflicto_y_verificacion() -> None:
    package = EvidencePackage(
        units=(
            EvidenceUnit(unit_id="U1", kind="fact", text="A", conflict=True),
            EvidenceUnit(unit_id="U2", kind="fact", text="B", conflict=True),
        ),
        conflicts=(
            EvidenceConflict(key="c1|rule x|aplica", unit_ids=("U1", "U2"), values=("a", "b")),
        ),
    )
    verification = AnswerVerification(
        verdicts=(
            ClaimVerdict(text="Claim sin respaldo en fuentes", status="unsupported", support=0.0),
        ),
        action="revise",
        unsupported=1,
    )
    signals = build_learning_signals(package=package, verification=verification)
    kinds = [signal.kind for signal in signals]
    assert "conflict" in kinds
    assert "verification_failure" in kinds


def test_evidence_gap_solo_si_requiere_conocimiento() -> None:
    empty = EvidencePackage()
    assert build_learning_signals(package=empty, requires_knowledge=True)
    assert build_learning_signals(package=empty, requires_knowledge=False) == ()


def test_cap_y_payload() -> None:
    entities = EntityResolution(
        mentions=tuple(
            MentionResolution(mention=f"X{i}", status="unresolved", matches=())
            for i in range(10)
        )
    )
    signals = build_learning_signals(entities=entities, max_signals=3)
    assert len(signals) == 3
    payload = signals[0].to_public_dict()
    assert payload["kind"] == "unresolved_entity"
    assert payload["priority"] > 0
