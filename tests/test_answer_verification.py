# =============================================================================
# AnswerVerifier — verificación determinista respuesta vs evidencia (C4).
# =============================================================================
from __future__ import annotations

from src.runtime.evidence_assembly import EvidencePackage, EvidenceUnit
from src.runtime.verification import extract_claims, verify_answer


def _package() -> EvidencePackage:
    return EvidencePackage(
        units=(
            EvidenceUnit(
                unit_id="U1",
                kind="excerpt",
                text="El campo FCLAS determina la clase tarifaria del registro",
                evidence_ids=("E1",),
                score=0.9,
            ),
            EvidenceUnit(
                unit_id="U2",
                kind="fact",
                text="Rule X aplica Category 31",
                canonical_ids=("c1",),
                validity="historical",
                score=0.8,
            ),
            EvidenceUnit(
                unit_id="U3",
                kind="fact",
                text="Rule X aplica Category 32",
                canonical_ids=("c1",),
                validity="current",
                conflict=True,
                score=0.8,
            ),
        ),
        conflicts=(),
    )


def test_claim_soportado() -> None:
    report = verify_answer(
        "El campo FCLAS determina la clase tarifaria del registro.", _package()
    )
    assert report.verdicts[0].status == "supported"
    assert report.action == "approve"


def test_claim_no_soportado() -> None:
    report = verify_answer("El sistema usa blockchain cuántico.", _package())
    assert report.verdicts[0].status == "unsupported"


def test_claim_conflictuado() -> None:
    report = verify_answer(
        "Rule X aplica Category 32 en la actualidad.", _package()
    )
    assert report.verdicts[0].status == "conflicted"
    assert report.action == "answer_with_limits"


def test_claim_desactualizado() -> None:
    historical = EvidencePackage(
        units=(
            EvidenceUnit(
                unit_id="U1",
                kind="fact",
                text="Rule X aplica Category 31",
                canonical_ids=("c1",),
                validity="historical",
                score=0.8,
            ),
        )
    )
    report = verify_answer("Rule X aplica Category 31.", historical)
    assert report.verdicts[0].status == "outdated"
    assert report.action == "answer_with_limits"


def test_accion_revise_y_abstain() -> None:
    revise = verify_answer(
        "El sistema usa blockchain cuántico. "
        "La plataforma vuela drones autónomos. "
        "El campo FCLAS determina la clase tarifaria del registro.",
        _package(),
    )
    assert revise.action == "revise"
    abstain = verify_answer(
        "El sistema usa blockchain cuántico. "
        "La plataforma vuela drones autónomos. "
        "El clima marciano es seco.",
        _package(),
    )
    assert abstain.action == "abstain"


def test_answer_vacio_y_claims() -> None:
    empty = verify_answer("", _package())
    assert empty.verdicts == ()
    assert empty.action == "approve"
    claims = extract_claims(
        "El campo FCLAS determina la clase. La regla aplica al registro.",
        max_claims=1,
    )
    assert claims == ("El campo FCLAS determina la clase.",)


def test_payload_publico_serializable() -> None:
    import json

    payload = verify_answer(
        "El campo FCLAS determina la clase tarifaria del registro.", _package()
    ).to_public_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert payload["action"] == "approve"
    assert payload["supported"] == 1


def test_limits_note_vacia_en_approve() -> None:
    from src.runtime.verification import limits_note

    assert limits_note(verify_answer("", _package())) == ""


def test_limits_note_declara_faltantes() -> None:
    from src.runtime.verification import limits_note

    report = verify_answer(
        "El sistema usa blockchain cuántico.", _package()
    )
    note = limits_note(report)
    assert note.startswith("Límites de esta respuesta:")
    assert "sin respaldo" in note
