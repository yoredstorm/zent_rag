# =============================================================================
# Fail-closed determinista — una consulta ejecutable jamás la decide el LLM
# =============================================================================
# Regresión del fallo de producción observado:
#
#   La MISMA pregunta ejecutable («&&&F / ABCFGEGE») terminó en MATCH una vez y
#   NO_MATCH otra porque el pipeline determinista falló (excepción en
#   `reason_over_evidence`) y el runtime siguió en modo fail-open: el generador
#   decidió libremente.
#
# Contrato que estos tests fijan:
#   1. `requires_deterministic_decision` reconoce intents ejecutables generales
#      (sin vocabulario de dominio).
#   2. Cada etapa determinista emite telemetría aunque falle (rule_retrieval se
#      conserva si ground) falla).
#   3. Una consulta ejecutable sin DecisionEnvelope autoritativo NUNCA expone
#      una conclusión binaria: estado no concluyente construido por código.
#   4. MAX_TOKENS no puede invertir la decisión.
#   5. Invariantes de evidencia: cited ⊆ used ⊆ selected.
#
# ATPCO (&&&F / ABCFGEGE) se usa SOLO como fixture de regresión, nunca como
# lógica de producción.
# =============================================================================
from __future__ import annotations

import random
from uuid import uuid4

import pytest

from src.core.domain.entities import Agent, LLMResponse
from src.core.ports import LLMProvider
from src.intelligence.reasoning.grounded_engine import reason_over_evidence
from src.knowledge.compiler.model import EvidenceRef, SemanticUnit, SourceLocator
from src.knowledge.rule_compiler import CanonicalRule, SemanticRuleCompiler

DOC = uuid4()
ORG = uuid4()

OBSERVED_QUESTION = (
    "yo tengo en el record 2 &&&F y en el farebasis me viene ABCFGEGE "
    "cumple o no cumple"
)
CLEAN_QUESTION = "¿ABCFGEGE cumple el patrón &&&F?"


# -----------------------------------------------------------------------------
# Fixtures de dominio neutro
# -----------------------------------------------------------------------------


def unit(
    kind: str,
    text: str,
    *,
    page: int = 1,
    section: tuple[str, ...] = ("General",),
) -> SemanticUnit:
    return SemanticUnit(
        kind=kind,
        key=f"{kind}:{text[:24]}",
        label=text[:24],
        text=text,
        confidence=0.8,
        evidence=EvidenceRef(
            locator=SourceLocator(
                document_id=DOC,
                document_title="Manual",
                page=page,
                section_path=section,
            ),
            excerpt=text,
        ),
    )


def compile_pattern_rules() -> list[CanonicalRule]:
    return SemanticRuleCompiler().compile(
        document_id=str(DOC),
        document_title="Manual",
        organization_id=str(ORG),
        units=[
            unit(
                "definition",
                "The value may contain more characters than the pattern.",
                page=1,
                section=("Matching",),
            ),
            unit(
                "definition",
                "The symbol & represents one alphanumeric position.",
                page=7,
                section=("Kinds of characters",),
            ),
            unit(
                "reference",
                "Matching is positional, left to right. "
                "Literal characters must match exactly at their position.",
                page=2,
                section=("Matching",),
            ),
        ],
    ).canonical_rules


class _Item:
    """Evidencia recuperada mínima (RetrievalChunk-compatible)."""

    def __init__(
        self,
        content: str = "",
        *,
        evidence_id: str = "E1",
        metadata: dict | None = None,
    ) -> None:
        self.content = content
        self.evidence_id = evidence_id
        self.metadata = metadata or {}


# -----------------------------------------------------------------------------
# FakeLLM / Agent mínimos (mismo contrato que tests/test_agent_runtime.py)
# -----------------------------------------------------------------------------


class _FakeLLM(LLMProvider):
    def __init__(self, contents: list[str], tokens: int = 10) -> None:
        self.contents = contents
        self.tokens = tokens
        self.calls = 0

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        index = min(self.calls, len(self.contents) - 1)
        self.calls += 1
        return LLMResponse(
            content=self.contents[index],
            model="fake",
            prompt_tokens=self.tokens,
            completion_tokens=self.tokens,
            total_tokens=self.tokens * 2,
        )

    async def generate_stream(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def embed(self, text, model=None):  # pragma: no cover
        raise NotImplementedError

    async def rerank(self, query, documents, model=None, top_n=None):  # pragma: no cover
        return []


def _agent(**overrides) -> Agent:
    params: dict = {
        "id": uuid4(),
        "organization_id": ORG,
        "name": "test-agent",
        "tools": ["search_knowledge"],
    }
    params.update(overrides)
    return Agent(**params)


def _request(agent: Agent, message: str):
    from src.agents.runtime.agent_runtime import AgentRunRequest

    return AgentRunRequest(agent=agent, message=message, role="admin")


@pytest.fixture(autouse=True)
def _runtime_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "RUNTIME_TOOL_ROUTING_MODE", "off")
    monkeypatch.setattr(settings, "RUNTIME_TERMINATION_GATE", "off")
    monkeypatch.setattr(settings, "RUNTIME_AGENT_JEV_LOOP", "off")
    monkeypatch.setattr(settings, "RUNTIME_SOURCE_AWARE_TOOLS", False)


# -----------------------------------------------------------------------------
# 1 — Identificación de consultas ejecutables (sin dominio hardcodeado)
# -----------------------------------------------------------------------------


class TestRequiresDeterministicDecision:
    @pytest.mark.parametrize(
        "question",
        [
            # patrón/máscara de producto
            "¿mi valor ABCD contra el patrón ????",
            # elegibilidad de seguro
            "¿el solicitante con valor 25 es elegible para la cobertura?",
            # rango numérico
            "¿el valor 15 cumple el rango permitido entre 10 y 20?",
            # regla contractual
            "¿aplica la excepción del contrato para este fee?",
            # fecha / vigencia
            "¿la regla está vigente el 2027-06-01?",
            # enum
            "¿el estado ACTIVE está permitido por la regla?",
            # fórmula
            "calcula el total con subtotal=100 aplicando la fórmula documentada",
            # dominio inventado
            "¿el valor ABCU cumple el patrón @@?",
            # caso observado
            OBSERVED_QUESTION,
        ],
    )
    def test_executable_questions(self, question: str) -> None:
        from src.runtime.deterministic_authority import (
            requires_deterministic_decision,
        )

        assert requires_deterministic_decision(question) is True

    @pytest.mark.parametrize(
        "question",
        [
            "¿qué es un farebasis?",
            "explícame el significado del símbolo & en el manual",
            "hola, ¿cómo estás?",
            "¿cuál es el rango permitido de edades?",
            "resume este documento",
        ],
    )
    def test_lookup_questions_are_not_forced(self, question: str) -> None:
        from src.runtime.deterministic_authority import (
            requires_deterministic_decision,
        )

        assert requires_deterministic_decision(question) is False

    def test_accepts_query_semantics_object(self) -> None:
        from src.intelligence.query_semantics import classify_query_semantics
        from src.runtime.deterministic_authority import (
            requires_deterministic_decision,
        )

        semantics = classify_query_semantics(OBSERVED_QUESTION)
        assert requires_deterministic_decision(semantics) is True


# -----------------------------------------------------------------------------
# 2 — Fases deterministas: telemetría aunque una fase posterior falle
# -----------------------------------------------------------------------------


class TestPrepareAuthorityStages:
    @pytest.mark.asyncio
    async def test_rule_retrieval_survives_grounding_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.intelligence.reasoning import grounded_engine as engine_module
        from src.runtime import rule_retrieval as retrieval_module
        from src.runtime.deterministic_authority import prepare_derived_authority

        async def fake_retrieve(organization_id, question, evidence_items=(), **kwargs):
            return retrieval_module.RuleRetrievalResult(strategy="canonical_first")

        def boom(**kwargs):
            raise RuntimeError("grounded engine crash")

        monkeypatch.setattr(retrieval_module, "retrieve_canonical_rules", fake_retrieve)
        monkeypatch.setattr(engine_module, "reason_over_evidence", boom)

        prep = await prepare_derived_authority(
            organization_id=ORG,
            question=OBSERVED_QUESTION,
            evidence_items=[],
        )

        assert prep.status == "error"
        assert prep.error_stage == "grounding"
        assert prep.error_code == "GROUNDING_ENGINE_FAILED"
        assert prep.grounded_reasoning is None
        steps = {step["type"]: step for step in prep.steps}
        # La etapa anterior NO desaparece cuando falla la siguiente.
        assert steps["rule_retrieval"]["status"] == "ok"
        assert steps["grounding"]["status"] == "error"
        assert steps["grounding"]["error_code"] == "GROUNDING_ENGINE_FAILED"
        assert steps["rule_evaluation"]["status"] == "not_run"
        state, message = prep.answer_state()
        assert state == "GROUNDING_ENGINE_FAILED"
        assert message

    @pytest.mark.asyncio
    async def test_derivation_failure_is_explicit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.intelligence.reasoning import grounded_engine as engine_module
        from src.runtime import decision_envelope as envelope_module
        from src.runtime import rule_retrieval as retrieval_module
        from src.runtime.deterministic_authority import prepare_derived_authority

        async def fake_retrieve(organization_id, question, evidence_items=(), **kwargs):
            return retrieval_module.RuleRetrievalResult(strategy="none")

        grounded = reason_over_evidence(question=CLEAN_QUESTION, evidence_items=[])

        monkeypatch.setattr(retrieval_module, "retrieve_canonical_rules", fake_retrieve)
        monkeypatch.setattr(
            engine_module, "reason_over_evidence", lambda **kwargs: grounded
        )
        monkeypatch.setattr(
            envelope_module,
            "build_decision_envelope",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("envelope crash")),
        )

        prep = await prepare_derived_authority(
            organization_id=ORG,
            question=CLEAN_QUESTION,
            evidence_items=[],
        )
        assert prep.status == "error"
        assert prep.error_code == "DERIVATION_FAILED"
        assert not prep.has_authority


# -----------------------------------------------------------------------------
# 3 — Finalize: la única salida para consultas ejecutables
# -----------------------------------------------------------------------------


class TestFinalizeContract:
    def test_grounding_failure_never_exposes_binary(self) -> None:
        from src.runtime.decision_envelope import finalize_authoritative_answer

        final = finalize_authoritative_answer(
            "No cumple: ABCFGEGE y &&&F tienen distinta longitud.",
            None,
            requires_deterministic_decision=True,
            failure_code="GROUNDING_ENGINE_FAILED",
            failure_stage="grounding",
        )
        assert final.blocked is True
        assert final.changed is True
        assert final.state == "GROUNDING_ENGINE_FAILED"
        assert "No cumple" not in final.answer
        assert "distinta longitud" not in final.answer

    def test_missing_premise_is_undetermined_not_negative(self) -> None:
        from src.runtime.decision_envelope import finalize_authoritative_answer

        final = finalize_authoritative_answer(
            "Sí, cumple.",
            None,
            requires_deterministic_decision=True,
            missing_premises=("rule:not_determined",),
        )
        assert final.blocked is True
        assert final.state == "UNDETERMINED_RULE"
        assert "No puedo determinarlo" in final.answer
        assert "Sí, cumple." not in final.answer

    def test_envelope_beats_executable_flag(self) -> None:
        from src.runtime.decision_envelope import (
            build_decision_envelope,
            finalize_authoritative_answer,
        )

        grounded = reason_over_evidence(
            question=CLEAN_QUESTION,
            evidence_items=[_Item("Matching is positional.")],
            canonical_rules=compile_pattern_rules(),
        )
        envelope = build_decision_envelope(grounded)
        assert envelope is not None
        final = finalize_authoritative_answer(
            "NO_MATCH: no cumple.",
            grounded,
            envelope=envelope,
            requires_deterministic_decision=True,
        )
        assert final.blocked is False
        assert final.envelope is not None
        assert final.envelope.normalized_result == "MATCH"
        assert final.answer.startswith("Sí, cumple.")

    def test_non_executable_answer_passthrough(self) -> None:
        from src.runtime.decision_envelope import finalize_authoritative_answer

        text = "El farebasis es el conjunto de reglas tarifarias del boleto."
        final = finalize_authoritative_answer(
            text, None, requires_deterministic_decision=False
        )
        assert final.blocked is False
        assert final.answer == text


# -----------------------------------------------------------------------------
# 4 — Regresión del bug: grounding lanza y el LLM intenta decidir
# -----------------------------------------------------------------------------


class TestRuntimeGroundingFailure:
    @pytest.mark.asyncio
    async def test_no_binary_when_grounding_engine_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.agents.runtime.agent_runtime import AgentRuntime
        from src.core.config import get_settings
        from src.intelligence.reasoning import grounded_engine as engine_module
        from src.runtime import rule_retrieval as retrieval_module

        settings = get_settings()
        monkeypatch.setattr(settings, "RUNTIME_ANSWER_GATE", "on")

        async def fake_retrieve(organization_id, question, evidence_items=(), **kwargs):
            return retrieval_module.RuleRetrievalResult(strategy="canonical_first")

        def boom(**kwargs):
            raise RuntimeError("grounding engine exploded")

        monkeypatch.setattr(retrieval_module, "retrieve_canonical_rules", fake_retrieve)
        monkeypatch.setattr(engine_module, "reason_over_evidence", boom)

        judged: dict[str, int] = {"calls": 0}

        async def fake_judge(*args, **kwargs):
            judged["calls"] += 1
            return {"answers": {}}

        monkeypatch.setattr("src.runtime.answer_gate.call_judge", fake_judge)

        llm = _FakeLLM(
            [
                '{"answer": "No cumple: ABCFGEGE y &&&F tienen distinta longitud."}',
            ]
        )
        result = await AgentRuntime(llm_provider=llm).run(
            _request(_agent(), OBSERVED_QUESTION)
        )

        assert "No cumple" not in result.answer
        assert result.answer_state is not None
        assert result.answer_state["state"] == "GROUNDING_ENGINE_FAILED"
        assert result.answer_state["error_code"] == "GROUNDING_ENGINE_FAILED"
        # JEV no fue consultado: no hay autoridad que arbitrar.
        assert judged["calls"] == 0
        by_type = {step.get("type"): step for step in result.steps}
        assert by_type["rule_retrieval"]["status"] == "ok"
        assert by_type["grounding"]["status"] == "error"
        assert "answer_state" in by_type
        assert "build" in by_type


# -----------------------------------------------------------------------------
# 5 — MAX_TOKENS no cambia la decisión
# -----------------------------------------------------------------------------


class TestMaxTokensCannotChangeDecision:
    @pytest.mark.asyncio
    async def test_match_survives_max_tokens(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.agents.runtime.agent_runtime import AgentRuntime
        from src.runtime import rule_retrieval as retrieval_module

        rules = compile_pattern_rules()

        async def fake_retrieve(organization_id, question, evidence_items=(), **kwargs):
            return retrieval_module.RuleRetrievalResult(
                strategy="canonical_first",
                supported_rules=list(rules),
                candidate_rules=list(rules),
            )

        monkeypatch.setattr(retrieval_module, "retrieve_canonical_rules", fake_retrieve)

        agent = _agent(config_json={"limits": {"max_tokens": 1}})
        llm = _FakeLLM(['{"answer": "No cumple: longitudes distintas."}'])
        result = await AgentRuntime(llm_provider=llm).run(
            _request(agent, CLEAN_QUESTION)
        )

        assert result.answer.startswith("Sí, cumple.")
        assert "No cumple" not in result.answer
        assert result.decision_envelope is not None
        assert result.decision_envelope["result"] == "MATCH"
        by_type = {step.get("type"): step for step in result.steps}
        assert "finalization" in by_type
        assert by_type["finalization"]["authoritative"] is True

    @pytest.mark.asyncio
    async def test_no_claim_with_max_tokens_is_undetermined(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.agents.runtime.agent_runtime import AgentRuntime
        from src.runtime import rule_retrieval as retrieval_module

        async def fake_retrieve(organization_id, question, evidence_items=(), **kwargs):
            return retrieval_module.RuleRetrievalResult(strategy="none")

        monkeypatch.setattr(retrieval_module, "retrieve_canonical_rules", fake_retrieve)

        agent = _agent(config_json={"limits": {"max_tokens": 1}})
        llm = _FakeLLM(['{"answer": "No cumple: 25 está fuera del rango."}'])
        result = await AgentRuntime(llm_provider=llm).run(
            _request(agent, "¿el valor 25 cumple el rango permitido?")
        )

        assert "No cumple" not in result.answer
        assert result.answer_state is not None
        assert result.answer_state["state"] in (
            "UNDETERMINED_RULE",
            "RULE_RETRIEVAL_UNAVAILABLE",
        )
        assert result.decision_envelope is None


# -----------------------------------------------------------------------------
# 6 — JEV satisfied=no + consulta ejecutable
# -----------------------------------------------------------------------------


class TestJevSatisfiedNo:
    def test_executable_gate_action_never_frees_llm(self) -> None:
        from src.runtime.deterministic_authority import executable_gate_action

        # Sin autoridad y con presupuesto: buscar más.
        assert (
            executable_gate_action(
                verdict="revise",
                has_authority=False,
                rounds_left=2,
                final=False,
                exhausted=False,
            )
            == "retrieve_more"
        )
        # Sin autoridad y sin rondas: estado no concluyente (nunca revise libre).
        assert (
            executable_gate_action(
                verdict="revise",
                has_authority=False,
                rounds_left=0,
                final=False,
                exhausted=False,
            )
            == "abstain"
        )
        assert (
            executable_gate_action(
                verdict="approve",
                has_authority=False,
                rounds_left=1,
                final=True,
                exhausted=False,
            )
            == "abstain"
        )
        # Con autoridad, el veredicto de JEV se conserva (el guard decide).
        assert (
            executable_gate_action(
                verdict="approve",
                has_authority=True,
                rounds_left=0,
                final=True,
                exhausted=False,
            )
            == "approve"
        )

    def test_satisfied_no_maps_to_undetermined_rule(self) -> None:
        from src.runtime.answer_gate import resolve_answer_state

        state, message = resolve_answer_state(
            is_knowledge_question=True,
            missing_premises=["rule:not_determined"],
        )
        assert state == "UNDETERMINED_RULE"
        assert message


# -----------------------------------------------------------------------------
# 7 — Invariantes de evidencia: cited ⊆ used ⊆ selected
# -----------------------------------------------------------------------------


class TestEvidenceInvariants:
    def _registry(self):
        from src.core.domain.adaptive import EvidenceItem
        from src.runtime.evidence import EvidenceRegistry

        registry = EvidenceRegistry()
        items = [
            EvidenceItem(
                source_type="qdrant",
                content=f"fragmento {index}",
                document_id=str(uuid4()),
                chunk_id=str(uuid4()),
                title=f"doc-{index}",
            )
            for index in range(5)
        ]
        registry.add(items)
        return registry

    def test_cited_counts_as_used(self) -> None:
        from src.runtime.evidence import evidence_invariants

        registry = self._registry()
        ids = list(registry.ids())
        public = registry.to_public_dict(
            selected_ids=[],  # observado en producción: used=0
            cited_ids=ids[:2],  # ... pero cited=2
        )
        assert public["cited_count"] == 2
        assert public["used_count"] >= public["cited_count"]
        assert evidence_invariants(public) == []

    def test_bad_payload_fails_invariant(self) -> None:
        from src.runtime.evidence import evidence_invariants

        bad = {
            "retrieved_count": 5,
            "selected_count": 5,
            "used_count": 0,
            "cited_count": 2,
            "items": [
                {
                    "evidence_id": "E1",
                    "selected": True,
                    "used": False,
                    "cited": True,
                },
                {
                    "evidence_id": "E2",
                    "selected": True,
                    "used": False,
                    "cited": True,
                },
            ],
        }
        violations = evidence_invariants(bad)
        assert any("cited_not_used" in item for item in violations)
        assert any("used_lt_cited" in item for item in violations)


# -----------------------------------------------------------------------------
# 8 — 100 ejecuciones: misma decisión o UNDETERMINED, nunca binario variable
# -----------------------------------------------------------------------------


class TestHundredRunConsistency:
    def test_mixed_perturbation_never_flips_decision(self) -> None:
        from src.runtime.decision_envelope import (
            build_decision_envelope,
            finalize_authoritative_answer,
        )

        rules = compile_pattern_rules()
        assert [rule for rule in rules if rule.executable]
        rng = random.Random(20261006)  # noqa: S311 — reproducibilidad del test
        contradictory = (
            "NO_MATCH: no cumple, las longitudes difieren.",
            "No cumple: ABCFGEGE y &&&F tienen distinta longitud.",
            "FALSE. The lengths are not equal.",
            "Sí, cumple, aunque no puedo verificarlo.",
        )
        decisions: list[tuple[str, bool]] = []
        undetermined: list[str] = []
        for index in range(100):
            items = [
                _Item("Matching is positional, left to right.", evidence_id=f"a{index}"),
                _Item("The symbol & represents one position.", evidence_id=f"b{index}"),
                _Item("The value may be longer than the pattern.", evidence_id=f"c{index}"),
            ]
            rng.shuffle(items)
            subset = items[: rng.randint(1, len(items))]

            # Escenario 1: autoridad determinista => resultado idéntico siempre.
            grounded = reason_over_evidence(
                question=CLEAN_QUESTION,
                evidence_items=subset,
                canonical_rules=rules,
            )
            envelope = build_decision_envelope(grounded)
            assert envelope is not None, f"run {index}: sin envelope"
            final = finalize_authoritative_answer(
                rng.choice(contradictory),
                grounded,
                envelope=envelope,
                requires_deterministic_decision=True,
            )
            decisions.append((str(final.envelope.normalized_result), final.blocked))

            # Escenario 2: sin autoridad determinista => UNDETERMINED idéntico.
            bare = finalize_authoritative_answer(
                rng.choice(contradictory),
                None,
                requires_deterministic_decision=True,
                failure_code="GROUNDING_ENGINE_FAILED" if index % 2 else "",
            )
            assert bare.blocked is True
            undetermined.append(bare.answer)

        assert all(item == ("MATCH", False) for item in decisions)
        assert len(set(undetermined)) == 1
        # El mensaje de estado no concluyente nunca afirma el resultado; la
        # frase «no voy a afirmar si cumple o no cumple» es parte del contrato.
        assert not any(
            answer.lower().lstrip().startswith(
                ("no cumple", "no, no cumple", "sí cumple", "si cumple", "false", "no_match")
            )
            for answer in undetermined
        )


# -----------------------------------------------------------------------------
# 9 — Telemetría de build
# -----------------------------------------------------------------------------


class TestBuildTelemetry:
    def test_build_info_has_versions_and_sha(self) -> None:
        from src.runtime.build_info import build_info

        info = build_info()
        for key in (
            "git_sha",
            "build_timestamp",
            "rule_retrieval_version",
            "rule_compiler_version",
            "grounding_version",
            "decision_envelope_version",
            "derived_guard_version",
        ):
            assert key in info, key
        assert info["rule_retrieval_version"]
        assert info["decision_envelope_version"]
