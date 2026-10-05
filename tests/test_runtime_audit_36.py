# =============================================================================
# Auditoría 36 tests — comportamiento end-to-end del contrato de grounding
# =============================================================================
# No se confía en unit tests aislados ni en nombres: cada test usa el motor
# determinista real y, donde importa, el MISMO pipeline del chat
# (RAGOrchestrator.execute con providers fake) hasta el texto final.
# =============================================================================
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from src.core.domain.entities import RetrievalChunk, RetrievalContext
from src.intelligence.query_semantics import (
    QueryIntent,
    QuerySemanticRole,
    classify_query_semantics,
)
from src.intelligence.reasoning.grounded_engine import (
    ANSWERABLE_DERIVED,
    NOT_APPLICABLE,
    UNANSWERABLE_CONFLICT,
    UNANSWERABLE_MISSING_PREMISE,
    reason_over_evidence,
)
from src.rag.evaluation.grounded_benchmark import (
    BENCHMARK_CASES,
    compare_baselines,
    evaluate_runner,
    intent_accuracy,
    query_role_accuracy,
    run_grounded,
)
from src.rag.longcontext.coverage import build_evidence_state
from src.rag.longcontext.package import build_generation_package
from src.runtime.evidence import assess_sufficiency
from tests.test_runtime_literalness_e2e import (
    GRAMMAR_DOC,
    FakeVectorStore,
    GroundedFakeLLM,
    _enable,
    _orchestrator,
    _steps,
)
from tests.test_runtime_literalness_e2e import (
    QUESTION as CANONICAL,
)

PATTERN_PREFIX = (
    "& represents one alphanumeric position. Matching is positional from the "
    "start (prefix). Literal characters must match exactly."
)
PATTERN_LENGTH = (
    "& represents one alphanumeric position. Matching is positional. "
    "The pattern and the value must have the same length."
)
GENERIC_GRAMMAR = (
    "& represents one alphanumeric position. # represents one digit. Matching "
    "is positional. The pattern and the value must have the same length."
)
FORBIDDEN_IN_ANSWER = (
    "no aparece",
    "no tengo suficiente información",
    "no menciona",
    "no está en la documentación",
    "necesito que",
)


class _Item:
    def __init__(self, content: str, evidence_id: str = "E1") -> None:
        self.content = content
        self.evidence_id = evidence_id
        self.label = evidence_id
        self.score = 0.5


def _run(question: str, docs: list[str]):
    return reason_over_evidence(
        question=question,
        evidence_items=[_Item(doc, f"E{i + 1}") for i, doc in enumerate(docs)],
    )


def _roles(question: str) -> dict[str, str]:
    return {
        obj.value: obj.semantic_role for obj in classify_query_semantics(question).objects
    }


def _assert_no_user_blame(answer: str) -> None:
    lowered = answer.lower()
    for phrase in FORBIDDEN_IN_ANSWER:
        assert phrase not in lowered, f"respuesta culpó al dato: {phrase!r} :: {answer!r}"


# =============================================================================
# TEST 1 — Canónico
# =============================================================================
class Test01Canonical:
    def test_roles_and_requirements(self) -> None:
        semantics = classify_query_semantics(CANONICAL)
        roles = {obj.value: obj.semantic_role for obj in semantics.objects}
        assert roles["ASDFGRE"] == QuerySemanticRole.USER_INPUT.value
        assert roles["&&&F"] == QuerySemanticRole.RUNTIME_PATTERN.value

        state = build_evidence_state(CANONICAL, [_Item(GRAMMAR_DOC)])
        missing = list(state.missing_documentable_evidence)
        assert "ASDFGRE" not in missing
        assert "&&&F" not in missing
        assert state.evidence_complete is True

        suff = assess_sufficiency([_Item(GRAMMAR_DOC)], CANONICAL)
        assert "ASDFGRE" not in suff.missing_anchors
        assert "&&&F" not in suff.missing_anchors

    def test_derivation_and_e2e_answer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = _run(CANONICAL, [GRAMMAR_DOC])
        assert result.answerability == ANSWERABLE_DERIVED
        claim = result.derivations.derived_results[0]
        assert claim.result == "MATCH"
        assert all("ASDFGRE" not in p.statement for p in claim.premises)

        _enable(monkeypatch)
        llm = GroundedFakeLLM()
        orchestrator = _orchestrator(FakeVectorStore(_retrieval(GRAMMAR_DOC)), llm)

        outcome = asyncio.run(
            orchestrator.execute(
                organization_id=orchestrator._organization_repo.organization.id,
                user_id=uuid4(),
                query=CANONICAL,
                role="admin",
                model="fake-llm",
            )
        )
        answer = str(outcome.llm_response.content or "")
        _assert_no_user_blame(answer)
        assert "cumple" in answer.lower()


# =============================================================================
# TEST 2 — Valor alfanumérico QNNF0SME
# =============================================================================
class Test02AlphanumericValue:
    def test_equivalent_to_alpha_only(self) -> None:
        question = (
            "si tengo un farebasis en el boleto QNNF0SME y en el record 2 me "
            "viene &&&F cumple o no?"
        )
        roles = _roles(question)
        assert roles["QNNF0SME"] == QuerySemanticRole.USER_INPUT.value
        assert roles["&&&F"] == QuerySemanticRole.RUNTIME_PATTERN.value
        result = _run(question, [PATTERN_PREFIX])
        assert result.answerability == ANSWERABLE_DERIVED
        assert result.derivations.derived_results[0].result == "MATCH"


# =============================================================================
# TEST 3/4 — PREMIUM como runtime y como source lookup
# =============================================================================
class Test03PureAlphaValue:
    def test_premium_is_runtime_input_not_field(self) -> None:
        question = "mi farebasis es PREMIUM, ¿cumple con &&&F?"
        roles = _roles(question)
        assert roles["PREMIUM"] == QuerySemanticRole.USER_INPUT.value
        result = _run(question, [PATTERN_PREFIX])
        assert result.answerability == ANSWERABLE_DERIVED
        # PREMIUM no tiene F en la 4ª posición: el resultado se DERIVA, no se busca.
        assert result.derivations.derived_results[0].result == "NO_MATCH"


class Test04SourceLookupPremium:
    def test_premium_becomes_source_requirement(self) -> None:
        semantics = classify_query_semantics(
            "¿PREMIUM aparece literalmente en la fuente?"
        )
        assert semantics.intent == QueryIntent.SOURCE_LOOKUP.value
        roles = {obj.value: obj.semantic_role for obj in semantics.objects}
        assert roles["PREMIUM"] == QuerySemanticRole.SOURCE_REQUIREMENT.value
        state = build_evidence_state(
            "¿PREMIUM aparece literalmente en la fuente?",
            [_Item("no such value here")],
        )
        assert "PREMIUM" in " ".join(state.missing_documentable_evidence)


# =============================================================================
# TEST 5/6/25 — Matemática
# =============================================================================
class Test05SimpleMath:
    def test_three_plus_three_without_corpus(self) -> None:
        result = _run("3 + 3", [])
        assert result.answerability == ANSWERABLE_DERIVED
        assert result.derivations.derived_results[0].result == 6
        assert result.runtime_inputs == ()


class Test06SourcePlusMath:
    def test_tax_18_percent(self) -> None:
        result = _run("price = 100; total with tax?", ["tax rate = 18%"])
        assert result.answerability == ANSWERABLE_DERIVED
        claim = result.derivations.derived_results[0]
        assert claim.result == 118
        origins = {p.origin for p in claim.premises}
        assert "SOURCE" in origins and "USER" in origins
        source_premises = [p for p in claim.premises if p.origin == "SOURCE"]
        assert any("18%" in p.statement for p in source_premises)
        assert claim.evidence_refs


class Test25ArithmeticNeedsNoRetrieval:
    def test_derivation_with_zero_evidence(self) -> None:
        for question, expected in (("3 + 3", 6), ("10 - 4", 6), ("6 * 7", 42)):
            result = _run(question, [])
            assert result.answerability == ANSWERABLE_DERIVED
            assert result.derivations.derived_results[0].result == expected


# =============================================================================
# TEST 7/8/9 — Boolean, enum, range
# =============================================================================
class Test07BooleanLogic:
    def test_active_and_verified(self) -> None:
        result = _run(
            "active=true verified=true, ¿es eligible?",
            ["active AND verified -> eligible"],
        )
        assert result.answerability == ANSWERABLE_DERIVED
        assert result.derivations.derived_results[0].result is True

    def test_not_eligible_when_condition_false(self) -> None:
        result = _run(
            "active=true verified=false, ¿es eligible?",
            ["active AND verified -> eligible"],
        )
        assert result.answerability == ANSWERABLE_DERIVED
        assert result.derivations.derived_results[0].result is False


class Test08Enum:
    def test_status_active_allowed(self) -> None:
        result = _run("status ACTIVE", ["allowed statuses: ACTIVE, PENDING"])
        assert result.answerability == ANSWERABLE_DERIVED
        assert result.derivations.derived_results[0].result is True


class Test09Range:
    def test_age_20_minimum_18(self) -> None:
        result = _run("age=20", ["minimum=18"])
        assert result.answerability == ANSWERABLE_DERIVED
        assert result.derivations.derived_results[0].result is True


# =============================================================================
# TEST 10/11 — Premisa faltante: política y símbolo propietario
# =============================================================================
class Test10MissingRule:
    def test_policy_x_absent_abstains_naming_it(self) -> None:
        result = _run("status ACTIVE", ["status must follow policy X"])
        assert result.answerability == UNANSWERABLE_MISSING_PREMISE
        assert "definition:policy:X" in result.missing_premises
        assert "política X" in result.abstention_message
        assert "ACTIVE" not in result.abstention_message


class Test11ProprietarySymbol:
    def test_at_symbol_undefined(self) -> None:
        result = _run("mi valor AB@C contra @@#C", ["patterns are supported"])
        assert result.answerability == UNANSWERABLE_MISSING_PREMISE
        assert any("definition:symbol:@" in item for item in result.missing_premises)
        assert "símbolo" in result.abstention_message


# =============================================================================
# TEST 12 — Gramática genérica + patrón nuevo del usuario
# =============================================================================
class Test12PatternGrammar:
    def test_new_pattern_never_in_source(self) -> None:
        assert "&&##" not in GENERIC_GRAMMAR
        result = _run("mi valor AB12 contra &&##", [GENERIC_GRAMMAR])
        assert result.answerability == ANSWERABLE_DERIVED
        assert result.derivations.derived_results[0].result == "MATCH"

        bad = _run("mi valor ABC2 contra &&##", [GENERIC_GRAMMAR])
        assert bad.answerability == ANSWERABLE_DERIVED
        assert bad.derivations.derived_results[0].result == "NO_MATCH"


# =============================================================================
# TEST 13/27/28/29 — Citas y orígenes
# =============================================================================
class Test13DerivedClaimCitations:
    def test_citations_support_premises(self) -> None:
        result = _run(CANONICAL, [GRAMMAR_DOC])
        claim = result.derivations.derived_results[0]
        assert claim.evidence_refs == ("E1",)
        # La cita apunta a la premisa, no a una oración con la conclusión.
        assert all("ASDFGRE" not in p.statement for p in claim.premises)
        assert any("alphanumeric" in p.statement for p in claim.premises)


class Test27DerivedOrigin:
    def test_claim_origin_is_derived(self) -> None:
        result = _run(CANONICAL, [GRAMMAR_DOC])
        claim = result.derivations.derived_results[0]
        assert claim.origin == "DERIVED"
        assert claim.to_public_dict()["origin"] == "DERIVED"


class Test28UserOrigin:
    def test_user_premise_origin(self) -> None:
        result = _run("price = 100; total with tax?", ["tax rate = 18%"])
        claim = result.derivations.derived_results[0]
        assert any(p.origin == "USER" for p in claim.premises)


class Test29SourceOrigin:
    def test_source_premise_origin(self) -> None:
        result = _run("price = 100; total with tax?", ["tax rate = 18%"])
        claim = result.derivations.derived_results[0]
        source = [p for p in claim.premises if p.origin == "SOURCE"]
        assert source and all(p.evidence_refs for p in source)


# =============================================================================
# TEST 14 — Source fact directo
# =============================================================================
class _SourceFactLLM:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate(self, **kwargs):
        from src.core.domain.entities import LLMResponse

        self.calls.append(kwargs)
        combined = f"{kwargs.get('system_prompt') or ''}\n{kwargs.get('prompt') or ''}"
        if "Delivery takes 5 days" in combined:
            content = "El plazo de entrega es de 5 días. [Doc: 1]"
        else:
            content = "No tengo suficiente información para responder esta pregunta."
        return LLMResponse(content=content, model="fake-llm", total_tokens=8, latency_ms=1.0)


class Test14SourceFact:
    def test_direct_fact_uses_source_without_reasoning(self) -> None:
        question = "¿cuál es el plazo de entrega?"
        docs = ["Delivery takes 5 days."]
        result = _run(question, docs)
        assert result.answerability == NOT_APPLICABLE
        assert result.derivations.claims == ()


        llm = _SourceFactLLM()
        orchestrator = _orchestrator(FakeVectorStore(_retrieval("Delivery takes 5 days.")), llm)
        outcome = asyncio.run(
            orchestrator.execute(
                organization_id=orchestrator._organization_repo.organization.id,
                user_id=uuid4(),
                query=question,
                role="admin",
                model="fake-llm",
            )
        )
        answer = str(outcome.llm_response.content or "")
        assert "5 días" in answer
        assert "[Doc: 1]" in answer


# =============================================================================
# TEST 15/16/17 — Conflicto, temporal, fecha del usuario
# =============================================================================
class Test15Conflict:
    def test_conflicting_rules_do_not_derive(self) -> None:
        result = _run("age 20, ¿cumple?", ["minimum age is >=21.", "minimum age is >=18."])
        assert result.answerability == UNANSWERABLE_CONFLICT
        assert result.derivations.derived_results == ()

    def test_conflicting_formulas_do_not_derive(self) -> None:
        result = _run(
            "price=100 tax_rate=0.1",
            ["total = price * (1 + tax_rate)", "total = price * tax_rate"],
        )
        assert result.answerability == UNANSWERABLE_CONFLICT


class Test16Temporal:
    def test_current_rule_selected_by_user_date(self) -> None:
        docs = [
            "minimum age is >=18 effective until 2025-12-31.",
            "minimum age is >=21 effective from 2026-01-01.",
        ]
        result = _run("date 2026-10-04, age 20, ¿cumple?", docs)
        assert result.answerability == ANSWERABLE_DERIVED
        assert result.derivations.derived_results[0].result is False

    def test_old_rule_selected_for_old_date(self) -> None:
        docs = [
            "minimum age is >=18 effective until 2025-12-31.",
            "minimum age is >=21 effective from 2026-01-01.",
        ]
        result = _run("date 2025-06-01, age 20, ¿cumple?", docs)
        assert result.answerability == ANSWERABLE_DERIVED
        assert result.derivations.derived_results[0].result is True


class Test17UserDate:
    def test_user_date_is_runtime_not_source(self) -> None:
        semantics = classify_query_semantics("date 2026-10-04, age 20, ¿cumple?")
        dates = [
            obj
            for obj in semantics.runtime_inputs
            if obj.semantic_type == "date"
        ]
        assert dates and dates[0].value == "2026-10-04"
        assert dates[0].evidence_required is False


# =============================================================================
# TEST 18 — Número que parece identificador
# =============================================================================
class Test18NumberResemblesIdentifier:
    def test_assigned_number_is_runtime(self) -> None:
        roles = _roles("account=12345678, ¿el saldo alcanza?")
        assert roles["12345678"] == QuerySemanticRole.RUNTIME_PARAMETER.value

    def test_source_lookup_keeps_literal_requirement(self) -> None:
        roles = _roles("¿la fuente menciona la cuenta 12345678?")
        assert roles["12345678"] == QuerySemanticRole.SOURCE_REQUIREMENT.value


# =============================================================================
# TEST 19/20/21 — Paráfrasis, sin palabras mágicas, ambigüedad
# =============================================================================
class Test19Paraphrases:
    @pytest.mark.parametrize(
        "question",
        [
            "¿ASDFGRE cumple &&&F?",
            "would it pass the mask &&&F?",
            "is it valid against &&&F?",
            "hace match con &&&F?",
            "¿aplica la regla &&&F?",
            "¿acepta el patrón &&&F?",
        ],
    )
    def test_same_intent_and_derivation(self, question: str) -> None:
        semantics = classify_query_semantics(question)
        assert semantics.intent in ("VALIDATE", "APPLY_RULE")
        # Sin valor de runtime no hay derivación: se pide el dato, no se inventa.
        result = _run(question, [PATTERN_PREFIX])
        assert result.answerability in (
            UNANSWERABLE_MISSING_PREMISE,
            NOT_APPLICABLE,
            ANSWERABLE_DERIVED,
        )

    def test_with_value_all_paraphrases_derive(self) -> None:
        for question in (
            "¿ABCF cumple &&&F?",
            "does ABCF pass the mask &&&F?",
            "¿ABCF es válido contra &&&F?",
            "¿ABCF hace match con &&&F?",
        ):
            result = _run(question, [PATTERN_PREFIX])
            assert result.answerability == ANSWERABLE_DERIVED, question
            assert result.derivations.derived_results[0].result == "MATCH", question


class Test20NoMagicKeywords:
    def test_result_question_infers_apply_rule(self) -> None:
        question = "Tengo ABCF y la máscara &&&F. ¿Resultado?"
        semantics = classify_query_semantics(question)
        assert semantics.intent in ("APPLY_RULE", "VALIDATE")
        result = _run(question, [PATTERN_PREFIX])
        assert result.answerability == ANSWERABLE_DERIVED
        assert result.derivations.derived_results[0].result == "MATCH"


class Test21Ambiguity:
    def test_bare_sigla_low_confidence(self) -> None:
        semantics = classify_query_semantics("ASDFGRE")
        assert semantics.decided_by == "low_confidence"
        assert semantics.intent_confidence < 1.0


# =============================================================================
# TEST 22 — Historial
# =============================================================================
class Test22History:
    def test_previous_runtime_value_is_preserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable(monkeypatch)
        llm = GroundedFakeLLM()
        orchestrator = _orchestrator(FakeVectorStore(_retrieval(GRAMMAR_DOC)), llm)

        org = orchestrator._organization_repo.organization.id
        user = uuid4()
        conversation_id = uuid4()
        asyncio.run(
            orchestrator.execute(
                organization_id=org,
                user_id=user,
                query="mi farebasis es ASDFGRE",
                role="admin",
                model="fake-llm",
                conversation_id=conversation_id,
            )
        )
        second = asyncio.run(
            orchestrator.execute(
                organization_id=org,
                user_id=user,
                query="¿cumple con &&&F?",
                role="admin",
                model="fake-llm",
                conversation_id=conversation_id,
            )
        )
        steps = _steps(second)
        grounded = next((s for s in steps if s.get("type") == "grounded_reasoning"), None)
        assert grounded is not None
        assert "ASDFGRE" in grounded["runtime_inputs"], grounded
        assert grounded["answerability"] == ANSWERABLE_DERIVED
        answer = str(second.llm_response.content or "")
        _assert_no_user_blame(answer)
        assert "cumple" in answer.lower()


# =============================================================================
# TEST 23 — Premisas entre fuentes
# =============================================================================
class Test23CrossSourcePremises:
    CROSS_QUESTION = (
        "mi valor ASDFGRE en el campo FCLAS contra &&&F, ¿cumple?"
    )

    def test_rule_and_grammar_from_different_sources(self) -> None:
        docs = [
            "Record 2 field FCLAS: fare class applies to the fare basis.",
            "& represents one alphanumeric position. Matching is positional from the start (prefix).",
        ]
        result = _run(self.CROSS_QUESTION, docs)
        assert result.answerability == ANSWERABLE_DERIVED
        claim = result.derivations.derived_results[0]
        assert set(claim.evidence_refs) == {"E1", "E2"}

    def test_incompatible_scope_does_not_mix(self) -> None:
        # Sólo el campo, sin gramática: no se inventa la semántica.
        result = _run(
            self.CROSS_QUESTION,
            ["Record 2 field FCLAS applies to the fare basis."],
        )
        assert result.answerability == UNANSWERABLE_MISSING_PREMISE
        assert "definition:symbol:&" in result.missing_premises


# =============================================================================
# TEST 24/26 — Conocimiento general vs semántica de dominio
# =============================================================================
class Test24GeneralKnowledge:
    def test_general_knowledge_not_silent_source(self) -> None:
        from src.core.domain.grounding import GroundingContract, GroundingMode

        contract = GroundingContract(mode=GroundingMode.GROUNDED_REASONING.value)
        requirement = contract.requirement_for("MODEL_GENERAL_KNOWLEDGE")
        assert requirement.allowed is False
        # El motor no completa la semántica propietaria con conocimiento propio.
        result = _run("mi valor AB@C contra @@#C", ["patterns are supported"])
        assert result.answerability == UNANSWERABLE_MISSING_PREMISE


class Test26DomainSemanticsRequireSource:
    def test_proprietary_field_semantics_require_evidence(self) -> None:
        result = _run("¿qué significa FCLAS?", [])
        state = build_evidence_state("¿qué significa FCLAS?", [_Item("texto sin el campo")])
        assert "FCLAS" in " ".join(state.missing_documentable_evidence)
        assert result.answerability == NOT_APPLICABLE


# =============================================================================
# TEST 30 — System prompt efectivo
# =============================================================================
class Test30SystemPrompt:
    def test_effective_prompt_has_no_literal_only_rule(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable(monkeypatch)
        llm = GroundedFakeLLM()
        orchestrator = _orchestrator(FakeVectorStore(_retrieval(GRAMMAR_DOC)), llm)

        asyncio.run(
            orchestrator.execute(
                organization_id=orchestrator._organization_repo.organization.id,
                user_id=uuid4(),
                query=CANONICAL,
                role="admin",
                model="fake-llm",
            )
        )
        systems = "\n".join(str(call.get("system_prompt") or "") for call in llm.calls)
        lowered = systems.lower()
        for forbidden in (
            "exclusivamente",
            "usando solo la información",
            "solo puedes afirmar lo que la evidencia sostiene",
            "answer itself must exist",
        ):
            assert forbidden not in lowered, forbidden
        assert "user-provided values are valid scenario data" in lowered
        assert "derived conclusions" in lowered
        assert "domain-specific facts and rules must be supported" in lowered


# =============================================================================
# TEST 31 — Consistencia de gates
# =============================================================================
class Test31GateConsistency:
    def test_all_layers_agree_on_runtime_data(self) -> None:
        semantics = classify_query_semantics(CANONICAL)
        state = build_evidence_state(CANONICAL, [_Item(GRAMMAR_DOC)])
        grounded = _run(CANONICAL, [GRAMMAR_DOC])
        package = build_generation_package(
            question=CANONICAL,
            evidence_state=state,
            grounded_reasoning=grounded,
        )
        public = package.to_public_dict()

        for layer_missing in (
            list(state.missing_documentable_evidence),
            list(grounded.missing_premises),
            list(public["missing_evidence"]),
            list(public["missing_premises"]),
        ):
            joined = " ".join(layer_missing)
            assert "ASDFGRE" not in joined, layer_missing
            assert "&&&F" not in joined, layer_missing

        assert public["runtime_inputs"] == ["ASDFGRE"]
        assert public["runtime_patterns"] == ["&&&F"]
        assert public["answerability"] == ANSWERABLE_DERIVED
        assert state.evidence_complete is True
        assert [obj.value for obj in semantics.runtime_inputs] == ["ASDFGRE"]
        assert [obj.value for obj in semantics.runtime_patterns] == ["&&&F"]


# =============================================================================
# TEST 32/33/34 — Golden set y métricas
# =============================================================================
class Test32GoldenSet:
    def test_at_least_100_cases_with_categories(self) -> None:
        assert len(BENCHMARK_CASES) >= 100
        counts: dict[str, int] = {}
        for case in BENCHMARK_CASES:
            counts[case.category] = counts.get(case.category, 0) + 1
        assert counts.get("direct_lookup", 0) >= 20
        assert counts.get("rule_application", 0) + counts.get("patterns", 0) >= 20
        assert counts.get("calculation", 0) + counts.get("formulas", 0) >= 15
        assert counts.get("range", 0) + counts.get("enum", 0) + counts.get("numeric", 0) >= 15
        assert counts.get("transformation", 0) >= 10
        assert counts.get("missing_premise", 0) >= 10
        assert counts.get("source_lookup", 0) >= 10


class Test33Metrics:
    def test_key_metrics(self) -> None:
        metrics = evaluate_runner(BENCHMARK_CASES, run_grounded)
        assert metrics["over_abstention_rate"] <= 0.05
        assert metrics["under_abstention_rate"] == 0.0
        assert metrics["runtime_input_false_missing_rate"] == 0.0
        assert metrics["derived_answer_accuracy"] >= 0.95
        assert metrics["premise_grounding_accuracy"] >= 0.95
        assert metrics["citation_precision"] >= 0.95
        assert metrics["hallucination_rate"] == 0.0
        assert intent_accuracy()["intent_accuracy"] >= 0.9
        assert query_role_accuracy()["query_role_accuracy"] >= 0.9


class Test34ExpectedImprovement:
    def test_over_abstention_drops_without_unsupported_claims(self) -> None:
        comparison = compare_baselines(BENCHMARK_CASES, observe=False)
        legacy = comparison["legacy_literal"]
        grounded = comparison["grounded_reasoning"]
        assert legacy["over_abstention_rate"] >= 0.5
        assert grounded["over_abstention_rate"] < legacy["over_abstention_rate"]
        assert grounded["hallucination_rate"] <= legacy["hallucination_rate"]
        assert grounded["premise_grounding_accuracy"] >= 0.95


# =============================================================================
# TEST 35/36 — Calidad de respuesta y de fallo
# =============================================================================
class Test35CanonicalAnswerQuality:
    def test_structure_direct_result_application_citation_no_complaint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enable(monkeypatch)
        llm = GroundedFakeLLM()
        orchestrator = _orchestrator(FakeVectorStore(_retrieval(GRAMMAR_DOC)), llm)

        outcome = asyncio.run(
            orchestrator.execute(
                organization_id=orchestrator._organization_repo.organization.id,
                user_id=uuid4(),
                query=CANONICAL,
                role="admin",
                model="fake-llm",
            )
        )
        answer = str(outcome.llm_response.content or "")
        assert answer.lower().startswith("sí")
        _assert_no_user_blame(answer)
        assert "[Doc: 1]" in answer
        prompt = "\n".join(
            f"{call.get('system_prompt') or ''}\n{call.get('prompt') or ''}"
            for call in llm.calls
        )
        assert "RESULT FIRST" in prompt


class Test36FailureQuality:
    def test_missing_semantics_message_names_the_premise(self) -> None:
        result = _run(CANONICAL, ["patterns are supported for the field"])
        assert result.answerability == UNANSWERABLE_MISSING_PREMISE
        message = result.abstention_message
        assert "definición necesaria del símbolo" in message
        assert "&" in message
        assert "ASDFGRE" not in message
        assert "&&&F" not in message


# =============================================================================
# Helpers locales
# =============================================================================
def _retrieval(content: str) -> RetrievalContext:
    return RetrievalContext(
        chunks=[
            RetrievalChunk(
                document_id=uuid4(),
                content=content,
                score=0.9,
                metadata={"filename": "manual.pdf", "source_id": "s1"},
            )
        ],
        query_embedding=[0.1] * 8,
        retrieval_latency_ms=1.0,
    )
