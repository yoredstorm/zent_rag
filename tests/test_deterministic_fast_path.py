# =============================================================================
# Deterministic Fast Path — responder sin LLM cuando la autoridad existe
# =============================================================================
# A: SUPPORTED ejecutable MATCH -> fast path
# B: SUPPORTED ejecutable NO_MATCH -> fast path
# C: missing premise -> pipeline normal
# D: conflicto -> pipeline normal / fail closed
# E: range soportado -> fast path
# F: enum soportado -> fast path
# G: date compare soportado -> fast path
# H: 100 corridas -> mismo resultado y mismos hechos de explicación
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.rag.traceability import build_traceability
from src.runtime.decision_envelope import build_decision_envelope
from src.runtime.fast_path import (
    CONFLICTS,
    EXECUTION_MODE_FAST_PATH,
    MISSING_PREMISES,
    NOT_EXECUTABLE,
    UNRESOLVED_EVALUATION,
    evaluate_deterministic_fast_path,
    fast_path_metrics,
    render_deterministic_answer,
    verify_deterministic_answer,
)


def _claim(**overrides) -> dict:
    claim = {
        "deterministic": True,
        "verification_status": "SUPPORTED",
        "operation": "POSITIONAL_MATCH",
        "result": True,
        "canonical_rule_ids": ["rule:posmatch"],
        "evidence_refs": ["E1"],
    }
    claim.update(overrides)
    return claim


def _grounded(
    *,
    operation: str = "POSITIONAL_MATCH",
    result: bool = True,
    status: str = "MATCH",
    conflicts: list | None = None,
    missing_premises: list | None = None,
    checks: list | None = None,
) -> dict:
    rule_id = f"rule:{operation.lower()}"
    return {
        "answerability": "ANSWERABLE_DERIVED",
        "canonical_rules_used": [
            {
                "rule_id": rule_id,
                "verification_state": "SUPPORTED",
                "executable": True,
                "conflicts_with": [],
                "evidence_ids": ["E1"],
            }
        ],
        "canonical_rule_flow": [
            {
                "rule_id": rule_id,
                "status": status,
                "operation": operation,
                "result": result,
                "checks": checks
                or [{"name": "check-1", "status": "ok", "result": result}],
                "evidence_refs": ["E1"],
                "missing_premises": [],
            }
        ],
        "derived_claim": _claim(operation=operation, result=result),
        "derivations": {"claims": [_claim(operation=operation, result=result)]},
        "semantics": {"intent": "APPLY_RULE", "runtime_inputs": [{"value": "X"}]},
        "runtime_inputs": ["value=X", "pattern=&&&F"],
        "missing_premises": list(missing_premises or []),
        "conflicts": list(conflicts or []),
    }


def _evaluate(grounded: dict, *, executable: bool = True):
    envelope = build_decision_envelope(grounded)
    claims = list((grounded.get("derivations") or {}).get("claims") or ())
    return evaluate_deterministic_fast_path(
        requires_deterministic=executable,
        envelope=envelope,
        grounded=grounded,
        claims=claims,
    )


# ---------------------------------------------------------------------------
# A / B — MATCH y NO_MATCH soportados
# ---------------------------------------------------------------------------


def test_a_match_soportado_entra_al_fast_path() -> None:
    decision = _evaluate(_grounded(operation="POSITIONAL_MATCH", result=True))
    assert decision.eligible is True
    assert decision.operation == "POSITIONAL_MATCH"
    assert decision.result == "MATCH"
    assert decision.premise_status == "SATISFIED"


def test_b_no_match_soportado_entra_al_fast_path() -> None:
    decision = _evaluate(_grounded(operation="POSITIONAL_MATCH", result=False, status="NO_MATCH"))
    assert decision.eligible is True
    assert decision.result == "NO_MATCH"
    envelope = build_decision_envelope(_grounded(operation="POSITIONAL_MATCH", result=False, status="NO_MATCH"))
    assert render_deterministic_answer(envelope).startswith("No, no cumple.")


# ---------------------------------------------------------------------------
# C / D — sin premisa y con conflicto: pipeline normal
# ---------------------------------------------------------------------------


def test_c_missing_premise_no_entra() -> None:
    decision = _evaluate(_grounded(missing_premises=["matching.operator"]))
    assert decision.eligible is False
    assert decision.reason == MISSING_PREMISES


def test_d_conflicto_no_entra() -> None:
    decision = _evaluate(_grounded(conflicts=["regla en conflicto"]))
    assert decision.eligible is False
    assert decision.reason == CONFLICTS


def test_d2_evaluacion_indeterminada_no_entra() -> None:
    grounded = _grounded()
    grounded["canonical_rule_flow"][0]["status"] = "UNDETERMINED"
    grounded["canonical_rule_flow"][0]["result"] = None
    grounded["derived_claim"]["result"] = None
    decision = _evaluate(grounded)
    assert decision.eligible is False
    assert decision.reason in {UNRESOLVED_EVALUATION, "NO_RESULT"}


def test_d3_no_ejecutable_no_entra() -> None:
    decision = _evaluate(_grounded(), executable=False)
    assert decision.eligible is False
    assert decision.reason == NOT_EXECUTABLE


# ---------------------------------------------------------------------------
# E / F / G — operaciones soportadas por el motor
# ---------------------------------------------------------------------------


def test_e_range_soportado_entra() -> None:
    decision = _evaluate(_grounded(operation="RANGE_CHECK", result=True))
    assert decision.eligible is True
    assert decision.operation == "RANGE_CHECK"
    assert decision.result == "VALID"


def test_f_enum_soportado_entra() -> None:
    decision = _evaluate(_grounded(operation="ENUM_CHECK", result=True))
    assert decision.eligible is True
    assert decision.result == "VALID"


def test_g_date_compare_soportado_entra() -> None:
    decision = _evaluate(_grounded(operation="DATE_COMPARE", result=True))
    assert decision.eligible is True
    assert decision.operation == "DATE_COMPARE"
    assert decision.result == "VALID"


# ---------------------------------------------------------------------------
# H — determinismo: 100 corridas, mismos hechos
# ---------------------------------------------------------------------------


def test_h_100_corridas_identicas() -> None:
    grounded = _grounded()
    envelope = build_decision_envelope(grounded)
    claims = list((grounded.get("derivations") or {}).get("claims") or ())
    baseline_decision = _evaluate(grounded).to_public_dict()
    baseline_answer = render_deterministic_answer(envelope)
    baseline_verification = verify_deterministic_answer(
        envelope=envelope,
        grounded=grounded,
        claims=claims,
        citations=[{"evidence_id": "E1"}],
        evidence_ids=["E1"],
    )
    for _ in range(100):
        assert _evaluate(grounded).to_public_dict() == baseline_decision
        assert render_deterministic_answer(envelope) == baseline_answer
        assert (
            verify_deterministic_answer(
                envelope=envelope,
                grounded=grounded,
                claims=claims,
                citations=[{"evidence_id": "E1"}],
                evidence_ids=["E1"],
            )
            == baseline_verification
        )


# ---------------------------------------------------------------------------
# §6 — verificador determinista
# ---------------------------------------------------------------------------


def test_verificador_determinista_aprueba_y_rechaza_cita_inexistente() -> None:
    grounded = _grounded()
    envelope = build_decision_envelope(grounded)
    claims = list((grounded.get("derivations") or {}).get("claims") or ())
    ok = verify_deterministic_answer(
        envelope=envelope,
        grounded=grounded,
        claims=claims,
        citations=[{"evidence_id": "E1"}],
        evidence_ids=["E1"],
    )
    assert ok["verified"] is True
    assert ok["status"] == "VERIFIED_DETERMINISTIC"
    bad = verify_deterministic_answer(
        envelope=envelope,
        grounded=grounded,
        claims=claims,
        citations=[{"evidence_id": "E9"}],
        evidence_ids=["E1"],
    )
    assert bad["verified"] is False
    assert any(problem.startswith("citation_ref_missing") for problem in bad["problems"])


# ---------------------------------------------------------------------------
# §10 — telemetría de ahorro
# ---------------------------------------------------------------------------


def test_metricas_de_ahorro() -> None:
    metrics = fast_path_metrics(latency_ms=120.5, llm_calls_avoided=2, tokens_avoided=4000)
    assert metrics["execution_mode"] == EXECUTION_MODE_FAST_PATH
    assert metrics["llm_calls"] == 0
    assert metrics["llm_calls_avoided"] == 2
    assert metrics["tokens_avoided"] == 4000
    assert metrics["latency_ms"] == 120.5
    unknown = fast_path_metrics(latency_ms=10.0, llm_calls_avoided=2)
    assert "tokens_avoided" not in unknown  # UNKNOWN != ZERO


# ---------------------------------------------------------------------------
# §13 — ATPCO como regresión del motor real (sin hardcode)
# ---------------------------------------------------------------------------


def _real_grounded():
    from src.intelligence.reasoning.grounded_engine import reason_over_evidence
    from src.knowledge.compiler.model import EvidenceRef, SemanticUnit, SourceLocator
    from src.knowledge.rule_compiler import SemanticRuleCompiler

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
            _unit("definition", "The symbol & represents one alphanumeric position.", 7),
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
            self.evidence_id = "E1"
            self.metadata: dict = {}

    grounded = reason_over_evidence(
        question=(
            "yo tengo en el record 2 &&&F y en el farebasis me viene "
            "ABCFGEGE cumple o no cumple"
        ),
        evidence_items=[_Item("Matching is positional, left to right.")],
        canonical_rules=rules,
    )
    return grounded


def test_atpco_regresion_fast_path_sin_hardcode() -> None:
    grounded = _real_grounded()
    envelope = build_decision_envelope(grounded)
    assert envelope is not None
    assert envelope.operation == "POSITIONAL_MATCH"
    assert envelope.normalized_result == "MATCH"
    public = grounded.to_public_dict()
    claims = list((public.get("derivations") or {}).get("claims") or ())
    decision = evaluate_deterministic_fast_path(
        requires_deterministic=True,
        envelope=envelope,
        grounded=public,
        claims=claims,
    )
    assert decision.eligible is True
    answer = render_deterministic_answer(envelope)
    assert answer.startswith("Sí, cumple.")
    verification = verify_deterministic_answer(
        envelope=envelope,
        grounded=public,
        claims=claims,
        evidence_ids=["E1"],
    )
    assert verification["verified"] is True
    assert verification["status"] == "VERIFIED_DETERMINISTIC"


# ---------------------------------------------------------------------------
# Trace: modo de ejecución y narrativa determinista
# ---------------------------------------------------------------------------


def test_trace_muestra_fast_path_y_narrativa_determinista() -> None:
    grounded = _grounded()
    envelope = build_decision_envelope(grounded)
    public = grounded
    flow = {
        "status": "completed",
        "method": "agent",
        "question": "¿ABCFGEGE cumple &&&F?",
        "generation": {},
        "sources": [],
        "fallbacks": [],
        "timings": {},
        "execution_mode": EXECUTION_MODE_FAST_PATH,
        "fast_path": {
            **fast_path_metrics(latency_ms=85.0, llm_calls_avoided=2, tokens_avoided=3500),
            "reason": "SUPPORTED_DECISION",
            "operation": envelope.operation,
            "result": envelope.normalized_result,
        },
        "steps": [
            {"id": "s1", "type": "grounded_reasoning", "status": "ok", **public},
            {
                "id": "s2",
                "type": "deterministic_verifier",
                "status": "ok",
                "verified": True,
                "status_code": "VERIFIED_DETERMINISTIC",
            },
            {
                "id": "s3",
                "type": "final_authority_lock",
                "authoritative": True,
                "operation": envelope.operation,
                "result": envelope.normalized_result,
                "lock_action": "preserved",
            },
            {"id": "s4", "type": "final", "status": "ok", "answer": "Sí, cumple."},
        ],
    }
    trace = build_traceability(flow)
    assert trace["execution"]["mode"] == EXECUTION_MODE_FAST_PATH
    assert trace["execution"]["fast_path"]["llm_calls_avoided"] == 2
    verification = trace["verification"]
    assert verification["decision_verification"]["status"] == "VERIFIED"
    assert verification["narrative_verification"]["status"] == "VERIFIED_DETERMINISTIC"
    assert verification["status"] == "VERIFIED"
    assert trace["presentation"]["headline"]["code"] == "RESPONSE_VERIFIED"
    assert "NARRATIVE_VERIFIED_DETERMINISTIC" in [
        item["code"] for item in verification["explanation_codes"]
    ]


# ---------------------------------------------------------------------------
# E2E — AgentRuntime responde sin llamar al LLM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_runtime_no_llama_al_modelo(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.agents.runtime import agent_runtime as runtime_module
    from src.agents.runtime.agent_runtime import AgentRunRequest, AgentRuntime
    from src.core.config import get_settings
    from src.core.domain.entities import Agent, LLMResponse
    from src.core.ports import LLMProvider
    from src.runtime.deterministic_authority import DerivedPreparationResult

    settings = get_settings()
    monkeypatch.setattr(settings, "RUNTIME_TOOL_ROUTING_MODE", "off")
    monkeypatch.setattr(settings, "RUNTIME_TERMINATION_GATE", "off")
    monkeypatch.setattr(settings, "RUNTIME_ANSWER_GATE", "off")
    monkeypatch.setattr(settings, "RUNTIME_AGENT_JEV_LOOP", "off")
    monkeypatch.setattr(settings, "RUNTIME_SOURCE_AWARE_TOOLS", False)
    monkeypatch.setattr(settings, "RUNTIME_FAST_PATH", "on")
    monkeypatch.setattr(settings, "RUNTIME_FAST_PATH_ESTIMATED_TOKENS", 3500)

    grounded = _real_grounded()
    envelope = build_decision_envelope(grounded)
    assert envelope is not None
    public = grounded.to_public_dict()

    async def _fake_prepare(**kwargs):
        return DerivedPreparationResult(
            status="ok",
            question=str(kwargs.get("question") or ""),
            requires_deterministic_decision=True,
            grounded_reasoning=grounded,
            derived_claims=list(grounded.derivations.claims),
            authoritative_envelope=envelope,
        )

    monkeypatch.setattr(runtime_module, "prepare_derived_authority", _fake_prepare)
    monkeypatch.setattr(
        "src.runtime.premise_retriever.build_premise_evidence_search_result",
        lambda *args, **kwargs: SimpleNamespace(
            available=False,
            adapter=None,
            to_public_dict=lambda: {"available": False},
        ),
    )

    class _NoCallLLM(LLMProvider):
        def __init__(self) -> None:
            self.calls = 0

        async def generate(self, prompt: str, **kwargs) -> LLMResponse:  # pragma: no cover
            self.calls += 1
            raise AssertionError("el fast path no debe llamar al LLM")

        async def generate_stream(self, *args, **kwargs):  # pragma: no cover
            raise NotImplementedError

        async def embed(self, text, model=None):  # pragma: no cover
            raise NotImplementedError

        async def rerank(self, query, documents, model=None, top_n=None):  # pragma: no cover
            return []

    llm = _NoCallLLM()
    agent = Agent(
        id=uuid4(),
        organization_id=uuid4(),
        name="fast-agent",
        tools=[],
        config_json={"runtime": {"answer_gate": "off"}},
    )
    runtime = AgentRuntime(llm_provider=llm)
    result = await runtime.run(
        AgentRunRequest(
            agent=agent,
            message="¿ABCFGEGE cumple el patrón &&&F?",
            role="admin",
        )
    )

    assert llm.calls == 0
    assert result.status == "completed"
    assert result.execution_mode == EXECUTION_MODE_FAST_PATH
    assert result.fast_path is not None
    assert result.fast_path["llm_calls"] == 0
    assert result.fast_path["llm_calls_avoided"] == 2
    assert result.decision_envelope is not None
    assert result.decision_envelope["result"] == "MATCH"
    assert result.answer.startswith("Sí, cumple.")
    step_types = [step.get("type") for step in result.steps]
    assert "fast_path" in step_types
    assert "deterministic_verifier" in step_types
    assert "final_authority_lock" in step_types
    assert not any(step.get("type") == "llm" for step in result.steps)
