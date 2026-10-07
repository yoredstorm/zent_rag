# =============================================================================
# Separación DECISIÓN vs NARRATIVA — regresión del caso &&&F vs ABCFGEGE
# =============================================================================
# La decisión determinista (DecisionEnvelope autoritativo + DerivedClaim
# determinista SUPPORTED) se verifica por código. La narrativa generada se
# verifica aparte: max_tokens, citas colgantes o un verificador caído afectan
# la EXPLICACIÓN, nunca la DECISIÓN.
# =============================================================================
from __future__ import annotations

from src.rag.trace_diagnostics import run_invariants
from src.rag.traceability import build_traceability
from src.runtime.decision_verification import (
    DECISION_NOT_VERIFIED,
    DECISION_UNDETERMINED,
    DECISION_VERIFIED,
    NARRATIVE_PARTIAL,
    NARRATIVE_TRUNCATED,
    NARRATIVE_UNVERIFIED,
    NARRATIVE_VERIFIED,
    compose_verification_split,
)

RECORD_PATTERN = "&&&F"
FARE_BASIS = "ABCFGEGE"
QUESTION = (
    f"yo tengo en el record 2 {RECORD_PATTERN} y en el farebasis me viene "
    f"{FARE_BASIS} cumple o no cumple"
)


def _item(**overrides):
    item = {
        "evidence_id": "E1",
        "document_id": "doc-1",
        "chunk_id": "chunk-1",
        "original_filename": "atpco-rules.pdf",
        "page": 1,
        "excerpt": "El patrón posicional del record 2 se compara contra el fare basis.",
        "status": "USED",
        "score": 0.9,
        "doc_index": 1,
    }
    item.update(overrides)
    return item


def _flow(**overrides):
    flow = {
        "status": "completed",
        "method": "agent",
        "question": QUESTION,
        "generation": {"skipped": False},
        "sources": [],
        "fallbacks": [],
        "timings": {},
        "retrieval": {"used": True, "chunks": 1, "attempts": 1, "rounds": []},
    }
    flow.update(overrides)
    return flow


def _envelope(**overrides):
    envelope = {
        "authoritative": True,
        "operation": "POSITIONAL_MATCH",
        "result": "MATCH",
        "canonical_rule_ids": ["rule:atpco:positional-match"],
        "evidence_refs": ["E1"],
        "premises": [
            {
                "statement": f"record 2 contiene {RECORD_PATTERN}",
                "origin": "source",
                "evidence_refs": ["E1"],
            }
        ],
        "statement": f"{RECORD_PATTERN} coincide posicionalmente con {FARE_BASIS}",
    }
    envelope.update(overrides)
    return envelope


def _claim(**overrides):
    claim = {
        "deterministic": True,
        "verification_status": "SUPPORTED",
        "operation": "POSITIONAL_MATCH",
        "result": "MATCH",
        "canonical_rule_ids": ["rule:atpco:positional-match"],
        "evidence_refs": ["E1"],
        "statement": f"{RECORD_PATTERN} coincide posicionalmente con {FARE_BASIS}",
        "premises": [
            {"statement": f"record 2 contiene {RECORD_PATTERN}", "origin": "source"}
        ],
    }
    claim.update(overrides)
    return claim


def _authoritative_flow(
    *,
    grounded: bool = True,
    claim: dict | None = None,
    envelope: dict | None = None,
    checks: list[dict] | None = None,
    steps_extra: list[dict] | None = None,
    **overrides,
):
    steps = [
        {
            "id": "s1",
            "type": "grounded_reasoning",
            "status": "ok",
            "answerability": "ANSWERABLE_DERIVED",
            "derived_claim": claim if claim is not None else _claim(),
            "decision_envelope": envelope if envelope is not None else _envelope(),
        },
        {
            "id": "s2",
            "type": "final_authority_lock",
            "authoritative": True,
            "operation": "POSITIONAL_MATCH",
            "result": "MATCH",
            "lock_action": "preserved",
        },
    ]
    steps.extend(steps_extra or [])
    flow = _flow(
        steps=steps,
        grounding={"grounded": grounded, "score": 0.8 if grounded else 0.1},
        verification={
            "overall": "verified" if grounded else "partial",
            "checks": checks
            if checks is not None
            else [{"key": "grounding", "state": "ok" if grounded else "blocked"}],
        },
        **overrides,
    )
    return flow


def _verification(trace):
    return trace["verification"]


def _codes(trace):
    return [item.get("code") for item in trace["verification"]["explanation_codes"]]


# ---------------------------------------------------------------------------
# A — MATCH autoritativo + narrativa completamente verificada
# ---------------------------------------------------------------------------


def test_a_match_autoritativo_narrativa_verificada() -> None:
    trace = build_traceability(_authoritative_flow(grounded=True))
    verification = _verification(trace)
    assert verification["decision_verification"]["status"] == DECISION_VERIFIED
    assert verification["decision_verification"]["operation"] == "POSITIONAL_MATCH"
    assert verification["decision_verification"]["result"] == "MATCH"
    assert verification["decision_verification"]["premise_status"] == "SATISFIED"
    assert verification["narrative_verification"]["status"] == NARRATIVE_VERIFIED
    assert verification["status"] == "VERIFIED"
    assert verification["decision_grounding"] == "CONFIRMED"
    assert trace["presentation"]["headline"]["code"] == "RESPONSE_VERIFIED"


# ---------------------------------------------------------------------------
# B — MATCH autoritativo + MAX_TOKENS: sólo se trunca la narrativa
# ---------------------------------------------------------------------------


def test_b_match_autoritativo_max_tokens() -> None:
    flow = _authoritative_flow(
        grounded=True,
        steps_extra=[
            {"id": "guard-1", "type": "guardrail", "detail": "max_tokens exceeded"}
        ],
    )
    flow["generation"] = {"skipped": False, "finish_reason": "length"}
    trace = build_traceability(flow)
    verification = _verification(trace)

    assert verification["decision_verification"]["status"] == DECISION_VERIFIED
    assert verification["narrative_verification"]["status"] == NARRATIVE_TRUNCATED
    assert verification["narrative_verification"]["truncated"] is True
    assert verification["status"] == "PARTIALLY_VERIFIED"
    assert "MAX_TOKENS_REACHED" in verification["narrative_verification"]["warnings"]
    truncated = next(
        item for item in verification["explanation_codes"] if item["code"] == "NARRATIVE_TRUNCATED"
    )
    assert "el resultado determinista no fue afectado" in truncated["warning"]
    assert trace["presentation"]["headline"]["code"] == (
        "RESPONSE_DECISION_VERIFIED_NARRATIVE_PARTIAL"
    )
    # Invariantes: ni la consistencia de decisión ni la separación se violan.
    invariant_codes = [item["code"] for item in trace["diagnostics"]["invariants"]]
    assert "DECISION_VERIFICATION_CONSISTENCY" not in invariant_codes
    assert "DECISION_NARRATIVE_SEPARATION" not in invariant_codes
    assert "VERIFIED_WITH_MATERIAL_DEGRADATION" not in invariant_codes


# ---------------------------------------------------------------------------
# C — MATCH autoritativo + cita colgante: narrativa parcial
# ---------------------------------------------------------------------------


def test_c_match_autoritativo_cita_colgante() -> None:
    # La cita colgante es un hecho del evidence section (cited id fuera del
    # universo canónico); se prueba la composición con ese hecho ya medido.
    from src.rag.traceability import build_verification_section

    flow = _authoritative_flow(grounded=True)
    evidence = {
        "counts": {"evidence_used": 1},
        "collection": "complete",
        "citations_summary": {
            "references": 2,
            "unique_cited": 2,
            "dangling": ["E9"],
        },
    }
    verification = build_verification_section(flow, evidence, {}, {})

    assert verification["decision_verification"]["status"] == DECISION_VERIFIED
    assert verification["narrative_verification"]["status"] == NARRATIVE_PARTIAL
    assert verification["narrative_verification"]["citations_valid"] is False
    assert "CITATIONS_DANGLING" in verification["narrative_verification"]["warnings"]
    assert verification["status"] != "UNVERIFIED"

    # Extremo a extremo: aunque el evidence section no produzca dangling acá,
    # una cita colgante medida jamás degrada la decisión.
    trace_flow = _authoritative_flow(grounded=True)
    trace = build_traceability(trace_flow)
    assert trace["verification"]["decision_verification"]["status"] == DECISION_VERIFIED
    assert trace["presentation"]["headline"]["code"] in {
        "RESPONSE_VERIFIED",
        "RESPONSE_DECISION_VERIFIED_NARRATIVE_PARTIAL",
    }


# ---------------------------------------------------------------------------
# D — MATCH autoritativo + verificador narrativo caído: narrativa parcial
# ---------------------------------------------------------------------------


def test_d_match_autoritativo_verifier_timeout() -> None:
    trace = build_traceability(
        _authoritative_flow(
            grounded=True,
            checks=[
                {"key": "grounding", "state": "ok"},
                {"key": "answer_gate", "state": "not_observed"},
            ],
        )
    )
    verification = _verification(trace)
    assert verification["decision_verification"]["status"] == DECISION_VERIFIED
    assert verification["narrative_verification"]["status"] == NARRATIVE_PARTIAL
    assert "VERIFIER_NOT_AVAILABLE" in verification["narrative_verification"]["warnings"]
    assert verification["status"] == "PARTIALLY_VERIFIED"


def test_d2_match_autoritativo_jev_pidio_mas_evidencia_antes() -> None:
    """JEV pudo pedir más evidencia antes: la decisión ya verificada no cambia."""
    flow = _authoritative_flow(
        grounded=True,
        steps_extra=[
            {
                "id": "jev-1",
                "type": "agent_step",
                "next_action": "retrieve_more",
                "action_reason": "falta evidencia documental",
            },
            {
                "id": "ret-1",
                "type": "jev_retrieval",
                "round": 1,
                "reason": "missing_evidence",
            },
        ],
    )
    trace = build_traceability(flow)
    verification = _verification(trace)
    assert verification["decision_verification"]["status"] == DECISION_VERIFIED
    assert verification["status"] == "VERIFIED"
    assert trace["presentation"]["headline"]["code"] == "RESPONSE_VERIFIED"


# ---------------------------------------------------------------------------
# E — Sin DerivedClaim: nunca se fabrica decision VERIFIED
# ---------------------------------------------------------------------------


def test_e_sin_derived_claim_no_fabrica_verificada() -> None:
    flow = _flow(
        grounded={"grounded": True, "score": 0.9},
        steps=[],
        sources=[_item(evidence_id="E1")],
        evidence={"items": 1, "counts": {"evidence_retrieved": 1}},
        citations=[{"index": 1, "evidence_id": "E1", "cited": True}],
        verification={
            "overall": "verified",
            "checks": [{"key": "grounding", "state": "ok"}],
        },
    )
    trace = build_traceability(flow)
    verification = _verification(trace)
    assert verification["decision_verification"]["status"] == DECISION_UNDETERMINED
    assert verification["status"] == "VERIFIED"  # histórico documental intacto
    assert trace["presentation"]["headline"]["code"] == "RESPONSE_SUPPORTED"


# ---------------------------------------------------------------------------
# F — DerivedClaim CONFLICTING: fail closed
# ---------------------------------------------------------------------------


def test_f_derived_claim_conflicting_fail_closed() -> None:
    conflicting = _claim(
        verification_status="CONFLICTING",
        conflicts=["premisa en conflicto con la regla"],
    )
    conflicting["canonical_rule_ids"] = []
    trace = build_traceability(_authoritative_flow(grounded=True, claim=conflicting))
    verification = _verification(trace)
    assert verification["decision_verification"]["status"] == DECISION_NOT_VERIFIED
    assert verification["decision_verification"]["premise_status"] == "CONFLICTING"
    assert verification["status"] == "UNVERIFIED"
    assert "DECISION_NOT_VERIFIED" in _codes(trace)
    assert trace["presentation"]["headline"]["code"] == "RESPONSE_DECISION_NOT_VERIFIED"


# ---------------------------------------------------------------------------
# §11 — regresión del caso real: grounding narrativo bloqueado no degrada
# ---------------------------------------------------------------------------


def test_regresion_e2e_motor_real_hasta_trace() -> None:
    """&&&F vs ABCFGEGE por el motor determinista real, publicado al trace.

    Es el caso reportado: DecisionEnvelope autoritativo + POSITIONAL_MATCH=MATCH
    con grounding narrativo bloqueado y max_tokens material. La UI no puede
    mostrar `Sin respaldo confirmado` ni un estado UNVERIFIED.
    """
    from uuid import uuid4

    from src.intelligence.reasoning.grounded_engine import reason_over_evidence
    from src.knowledge.compiler.model import EvidenceRef, SemanticUnit, SourceLocator
    from src.knowledge.rule_compiler import SemanticRuleCompiler
    from src.runtime.decision_envelope import build_decision_envelope

    document_id = str(uuid4())
    organization_id = str(uuid4())

    def _unit(kind: str, text: str, page: int) -> SemanticUnit:
        return SemanticUnit(
            kind=kind,
            key=f"{kind}:{text[:24]}",
            label=text[:24],
            text=text,
            confidence=0.8,
            evidence=EvidenceRef(
                locator=SourceLocator(
                    document_id=document_id,
                    document_title="Manual",
                    page=page,
                    section_path=("Matching",),
                ),
                excerpt=text,
            ),
        )

    rules = SemanticRuleCompiler().compile(
        document_id=document_id,
        document_title="Manual",
        organization_id=organization_id,
        units=[
            _unit(
                "definition",
                "The value may contain more characters than the pattern.",
                1,
            ),
            _unit(
                "definition",
                "The symbol & represents one alphanumeric position.",
                7,
            ),
            _unit(
                "reference",
                "Matching is positional, left to right. Literal characters must "
                "match exactly at their position.",
                2,
            ),
        ],
    ).canonical_rules
    assert any(rule.executable for rule in rules)

    class _Item:
        def __init__(self, content: str) -> None:
            self.content = content
            self.evidence_id = "ev_1"
            self.metadata: dict = {}

    grounded = reason_over_evidence(
        question=QUESTION,
        evidence_items=[_Item("Matching is positional, left to right.")],
        canonical_rules=rules,
    )
    envelope = build_decision_envelope(grounded)
    assert envelope is not None
    assert envelope.operation == "POSITIONAL_MATCH"
    assert envelope.normalized_result == "MATCH"
    assert envelope.authoritative is True

    # El runtime publica el motor grounded en un step y la narrativa queda
    # bloqueada (grounding del texto) + max_tokens material.
    flow = _flow(
        question=QUESTION,
        grounding={"grounded": False, "score": 0.0, "policy": "strict_source"},
        generation={"skipped": False, "finish_reason": "length"},
        verification={
            "overall": "blocked",
            "checks": [
                {"key": "answer_gate", "state": "warn"},
                {"key": "grounding", "state": "blocked"},
            ],
        },
        steps=[
            {
                "id": "s1",
                "type": "grounded_reasoning",
                "status": "ok",
                **grounded.to_public_dict(),
            },
            {
                "id": "guard-1",
                "type": "guardrail",
                "detail": "max_tokens exceeded",
            },
            {
                "id": "s2",
                "type": "final_authority_lock",
                "authoritative": True,
                "operation": envelope.operation,
                "result": envelope.normalized_result,
                "lock_action": "preserved",
            },
        ],
    )
    trace = build_traceability(flow)
    verification = _verification(trace)

    assert verification["decision_verification"]["status"] == DECISION_VERIFIED
    assert verification["decision_verification"]["result"] == "MATCH"
    assert verification["decision_grounding"] == "CONFIRMED"
    assert verification["narrative_verification"]["status"] in {
        NARRATIVE_TRUNCATED,
        NARRATIVE_PARTIAL,
    }
    assert verification["narrative_grounding"] == "BLOCKED"
    assert verification["status"] != "UNVERIFIED"
    assert trace["presentation"]["headline"]["code"] != "RESPONSE_UNVERIFIED"
    assert "DECISION_VERIFIED" in _codes(trace)


def test_regresion_record_ampersand_vs_fare_basis() -> None:
    flow = _authoritative_flow(
        grounded=False,
        checks=[
            {"key": "answer_gate", "state": "warn"},
            {"key": "grounding", "state": "blocked"},
        ],
    )
    trace = build_traceability(flow)
    verification = _verification(trace)

    assert verification["decision_verification"]["status"] == DECISION_VERIFIED
    assert verification["status"] != "UNVERIFIED"
    assert trace["presentation"]["headline"]["code"] != "RESPONSE_UNVERIFIED"
    assert trace["presentation"]["headline"]["code"] == (
        "RESPONSE_DECISION_VERIFIED_NARRATIVE_PARTIAL"
    )
    assert "DECISION_VERIFIED" in _codes(trace)
    assert verification["decision_grounding"] == "CONFIRMED"
    assert verification["narrative_grounding"] == "BLOCKED"
    assert "SUPPORT_NOT_CONFIRMED" not in _codes(trace)


# ---------------------------------------------------------------------------
# Invariantes DECISION_VERIFICATION_CONSISTENCY / DECISION_NARRATIVE_SEPARATION
# ---------------------------------------------------------------------------


def test_invariante_consistencia_de_decision() -> None:
    verification = {
        "status": "UNVERIFIED",
        "decision_verification": {"status": DECISION_UNDETERMINED},
        "narrative_verification": {"status": NARRATIVE_PARTIAL},
        "decision_envelope": _envelope(),
        "derived_claims": [_claim()],
    }
    found = run_invariants(
        evidence={},
        jev={},
        generation={},
        controls={},
        verification=verification,
        timeline=[],
    )
    codes = [item["code"] for item in found]
    assert "DECISION_VERIFICATION_CONSISTENCY" in codes
    assert "DECISION_NARRATIVE_SEPARATION" not in codes


def test_invariante_separacion_de_decision() -> None:
    verification = {
        "status": "UNVERIFIED",
        "decision_verification": {"status": DECISION_VERIFIED},
        "narrative_verification": {"status": NARRATIVE_PARTIAL},
        "decision_envelope": _envelope(),
        "derived_claims": [_claim()],
    }
    found = run_invariants(
        evidence={},
        jev={},
        generation={},
        controls={},
        verification=verification,
        timeline=[],
    )
    codes = [item["code"] for item in found]
    assert "DECISION_NARRATIVE_SEPARATION" in codes
    assert "DECISION_VERIFICATION_CONSISTENCY" not in codes


def test_invariante_separacion_ok_no_reporta() -> None:
    trace = build_traceability(
        _authoritative_flow(
            grounded=False,
            checks=[{"key": "grounding", "state": "blocked"}],
        )
    )
    codes = [item["code"] for item in trace["diagnostics"]["invariants"]]
    assert "DECISION_VERIFICATION_CONSISTENCY" not in codes
    assert "DECISION_NARRATIVE_SEPARATION" not in codes


# ---------------------------------------------------------------------------
# Modelo: precedencias y límites de la composición
# ---------------------------------------------------------------------------


def test_composicion_precedencias_de_narrativa() -> None:
    envelope = _envelope()
    claims = [_claim()]
    truncated = compose_verification_split(
        envelope=envelope,
        claims=claims,
        grounded=False,
        generation_warnings=[
            {"code": "MAX_TOKENS_REACHED", "impact": "POSSIBLY_INCOMPLETE", "material_effect": True}
        ],
    )
    assert truncated["decision_verification"]["status"] == DECISION_VERIFIED
    assert truncated["narrative_verification"]["status"] == NARRATIVE_TRUNCATED
    assert truncated["narrative_grounding"] == "BLOCKED"

    unsupported = compose_verification_split(
        envelope=envelope,
        claims=claims,
        grounded=False,
        grounding_verdict="UNSUPPORTED",
    )
    assert unsupported["decision_verification"]["status"] == DECISION_VERIFIED
    assert unsupported["narrative_verification"]["status"] == NARRATIVE_UNVERIFIED
