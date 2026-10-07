# =============================================================================
# Fast path — renderer user-facing: natural, genérico, sin códigos internos
# =============================================================================
from __future__ import annotations

from src.runtime.decision_envelope import (
    build_decision_envelope,
    build_operation_explanation,
)
from src.runtime.fast_path import (
    build_user_deterministic_explanation,
    render_deterministic_answer,
)


def _grounded(operation: str, result: bool, *, checks=None) -> dict:
    return {
        "answerability": "ANSWERABLE_DERIVED",
        "canonical_rules_used": [
            {
                "rule_id": "rule:ab6ca79697adf400e210add7",
                "verification_state": "SUPPORTED",
                "executable": True,
            }
        ],
        "canonical_rule_flow": [
            {
                "rule_id": "rule:ab6ca79697adf400e210add7",
                "status": "MATCH" if result else "NO_MATCH",
                "operation": operation,
                "result": result,
                "checks": checks or [],
                "missing_premises": [],
            }
        ],
        "derived_claim": {
            "deterministic": True,
            "verification_status": "SUPPORTED",
            "operation": operation,
            "result": result,
            "canonical_rule_ids": ["rule:ab6ca79697adf400e210add7"],
        },
        "derivations": {
            "claims": [
                {
                    "deterministic": True,
                    "verification_status": "SUPPORTED",
                    "operation": operation,
                    "result": result,
                    "canonical_rule_ids": ["rule:ab6ca79697adf400e210add7"],
                    "statement": "Matching is positional, left to right.",
                }
            ]
        },
        "semantics": {"intent": "APPLY_RULE", "runtime_inputs": [{"value": "X"}]},
        "runtime_inputs": ["pattern=&&&F", "value=ABCFGEGE"],
        "missing_premises": [],
        "conflicts": [],
    }


_CHECKS = [
    {
        "name": "matching",
        "operation": "POSITIONAL_MATCH",
        "status": "MATCH",
        "result": "MATCH",
        "detail": "derived_from_documented_grammar",
    },
    {
        "name": "length",
        "operation": "COMPARISON",
        "status": "MATCH",
        "result": True,
        "detail": "MIN_LENGTH: length=8 8.0 >= 4.0 is True",
    },
]

_CITATION = {
    "evidence_id": "18d90a0b-9751-438d-a3c5-98af8c8d974e",
    "document_name": "Rec2_Rules_dapp_C.pdf",
    "page": 11,
    "section_path": ["Matching"],
}


def test_positional_match_snapshot_natural() -> None:
    grounded = _grounded("POSITIONAL_MATCH", True, checks=_CHECKS)
    envelope = build_decision_envelope(grounded)
    answer = render_deterministic_answer(
        envelope,
        grounded=grounded,
        checks=_CHECKS,
        runtime_inputs=grounded["runtime_inputs"],
        citations=[_CITATION],
    )
    expected = (
        "Sí, cumple.\n\n"
        "El patrón `&&&F` exige que posición 1 admite un carácter, "
        "posición 2 admite un carácter, posición 3 admite un carácter, "
        "posición 4 debe ser «F».\n\n"
        "`ABCFGEGE` comienza con `ABCF`, por lo que satisface esas posiciones.\n\n"
        "La política de longitud documentada permite caracteres adicionales "
        "después de las posiciones del patrón.\n\n"
        "Resultado: cumple.\n\n"
        "Fuente: Rec2_Rules_dapp_C.pdf · pág. 11 · Matching"
    )
    assert answer == expected


def test_no_match_natural() -> None:
    grounded = _grounded("POSITIONAL_MATCH", False, checks=_CHECKS)
    envelope = build_decision_envelope(grounded)
    answer = render_deterministic_answer(
        envelope, grounded=grounded, checks=_CHECKS,
        runtime_inputs=grounded["runtime_inputs"],
    )
    assert answer.startswith("No, no cumple.")
    assert "no satisface todas las posiciones del patrón" in answer
    assert answer.rstrip().endswith("Resultado: no cumple.")


def test_respuesta_no_expone_ids_ni_codigos() -> None:
    grounded = _grounded("POSITIONAL_MATCH", True, checks=_CHECKS)
    envelope = build_decision_envelope(grounded)
    answer = render_deterministic_answer(
        envelope, grounded=grounded, checks=_CHECKS,
        runtime_inputs=grounded["runtime_inputs"], citations=[_CITATION],
    )
    for forbidden in (
        "rule:",
        "derived_from_documented_grammar",
        "18d90a0b-9751",
        "VERIFIED",
        "DecisionEnvelope",
        "POSITIONAL_MATCH",
        "MIN_LENGTH",
    ):
        assert forbidden not in answer
    # P1.7: sin barras invertidas sueltas entre líneas.
    assert "\\\n" not in answer
    assert not any(line.endswith("\\") for line in answer.splitlines())


def test_renderer_generico_por_operacion() -> None:
    cases = {
        "RANGE_CHECK": ("rango documentado", "válido"),
        "ENUM_CHECK": ("valores documentados", "válido"),
        "SET_MEMBERSHIP": ("valores documentados", "válido"),
        "DATE_COMPARE": ("condición temporal", "válido"),
        "BOOLEAN": ("verdadera", "verdadero"),
        "FORMULA": ("fórmula documentada", "verdadero"),
    }
    for operation, (fragment, result_word) in cases.items():
        grounded = _grounded(operation, True)
        envelope = build_decision_envelope(grounded)
        answer = render_deterministic_answer(
            envelope, grounded=grounded, runtime_inputs=grounded["runtime_inputs"]
        )
        assert fragment in answer, operation
        assert f"Resultado: {result_word}" in answer, operation
        assert "rule:" not in answer
        assert "UUID" not in answer


def test_subject_tecnico_no_aparece_en_user_facing() -> None:
    grounded = _grounded("POSITIONAL_MATCH", True, checks=_CHECKS)
    grounded["canonical_rules_used"][0]["subject"] = (
        "Fare Family Match using Hyphen (-)"
    )
    envelope = build_decision_envelope(grounded)
    user = build_user_deterministic_explanation(
        envelope, grounded=grounded, checks=_CHECKS,
        runtime_inputs=grounded["runtime_inputs"],
    )
    technical = build_operation_explanation(envelope)
    assert "Fare Family Match using Hyphen" not in user
    assert "Regla canónica" in technical
