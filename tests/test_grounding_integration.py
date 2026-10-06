# =============================================================================
# Grounding integration — EvidenceState, package, graph, answerability, prompts
# =============================================================================
# El contrato conceptual debe estar cableado en el runtime:
#   - un dato del usuario no aparece como evidencia faltante;
#   - un patrón de runtime exige semántica (missing_premises), no literalidad;
#   - el paquete de generación lleva premisas, inputs, claims derivados;
#   - el prompt del sistema ya no dice «sólo lo que está en el contexto».
# =============================================================================
from __future__ import annotations

from src.core.domain.adaptive import EvidenceItem
from src.rag.longcontext.coverage import build_evidence_state
from src.rag.longcontext.package import (
    build_generation_package,
    render_evidence_state_block,
    render_grounding_block,
)
from src.rag.longcontext.requirement_graph import (
    RequirementNodeType,
    build_requirement_graph,
)
from src.runtime.evidence import (
    ACTION_ABSTAIN,
    ACTION_GENERATE,
    assess_sufficiency,
)

CANONICAL = (
    "si tengo un farebasis en el boleto ASDFGRE y en el record 2 me viene "
    "&&&F cumple o no?"
)
GRAMMAR = (
    "Record 2: & represents one alphanumeric position. Matching is positional "
    "from the start (prefix). El fare basis viene del boleto y cumple la regla."
)
NO_GRAMMAR = "patterns are supported for the field"


def _item(content: str, evidence_id: str = "E1") -> EvidenceItem:
    return EvidenceItem(source_type="document", content=content, score=0.5, evidence_id=evidence_id)


class TestSufficiency:
    def test_runtime_values_never_missing(self) -> None:
        suff = assess_sufficiency([_item("record 2 general text")], CANONICAL)
        assert "ASDFGRE" not in suff.missing_anchors
        assert "ASDFGRE" not in suff.missing_entities
        assert "ASDFGRE" in suff.examples_asked
        assert "&&&F" in suff.runtime_patterns_asked

    def test_missing_grammar_is_missing_premise(self) -> None:
        suff = assess_sufficiency([_item(NO_GRAMMAR)], CANONICAL, retrieval_rounds_left=0)
        assert suff.recommended_action == ACTION_ABSTAIN
        assert suff.reason == "missing_domain_premise"
        assert any("definition:symbol:&" in item for item in suff.missing_premises)

    def test_documented_grammar_generates(self) -> None:
        suff = assess_sufficiency([_item(GRAMMAR)], CANONICAL, retrieval_rounds_left=0)
        assert suff.recommended_action == ACTION_GENERATE
        assert suff.missing_premises == ()

    def test_literal_mask_without_grammar_is_not_a_missing_anchor(self) -> None:
        suff = assess_sufficiency(
            [_item("La máscara &&&F exige que el fare basis tenga longitud fija.")],
            "¿qué significa FCLAS &&&F en el Record 2?",
            retrieval_rounds_left=0,
        )
        # La instancia está documentada: no es «anchor faltante».
        assert "mascara &&&F" not in suff.missing_anchors

    def test_alpha_only_user_value_not_missing(self) -> None:
        suff = assess_sufficiency(
            [_item("documento sin ese valor")],
            "mi farebasis es PREMIUM, ¿cumple la regla?",
        )
        assert "PREMIUM" not in suff.missing_anchors

    def test_public_dict_separates_runtime(self) -> None:
        suff = assess_sufficiency([_item(GRAMMAR)], CANONICAL)
        public = suff.to_public_dict()
        assert public["runtime_patterns_requires_literal_match"] is False
        assert public["examples_requires_source_match"] is False


class TestEvidenceState:
    def test_runtime_inputs_and_patterns_separated(self) -> None:
        state = build_evidence_state(CANONICAL, [_item(GRAMMAR)])
        assert state.runtime_input_coverage == 1.0
        assert state.domain_requirement_coverage > 0.0
        assert state.evidence_complete is True
        public = state.to_public_dict()
        assert public["runtime_patterns"] == ["&&&F"]
        assert public["runtime_values_requires_source_match"] is False

    def test_missing_grammar_declares_premise(self) -> None:
        state = build_evidence_state(CANONICAL, [_item(NO_GRAMMAR)])
        assert state.evidence_complete is False
        assert state.missing_premises
        assert "ASDFGRE" not in " ".join(state.missing_documentable_evidence)
        assert "ASDFGRE" not in " ".join(state.missing_premises)

    def test_domain_coverage_not_polluted_by_runtime(self) -> None:
        state = build_evidence_state(
            "mi código es ASDFGRE, ¿cumple la regla FCLAS?",
            [_item("FCLAS: fare class field definition.")],
        )
        # El dato del usuario no entra en la cobertura del dominio.
        assert state.runtime_input_coverage == 1.0
        assert all(
            str(getattr(anchor, "value", "")) != "ASDFGRE"
            for anchor in state.documentable_anchors
        )


class TestGenerationPackage:
    def test_package_carries_grounding_state(self) -> None:
        from src.intelligence.reasoning.grounded_engine import reason_over_evidence

        items = [_item(GRAMMAR)]
        state = build_evidence_state(CANONICAL, items)
        grounded = reason_over_evidence(question=CANONICAL, evidence_items=items)
        package = build_generation_package(
            question=CANONICAL,
            evidence_state=state,
            grounded_reasoning=grounded,
        )
        public = package.to_public_dict()
        assert public["grounding_mode"] == "grounded_reasoning"
        assert public["runtime_inputs"] == ["ASDFGRE"]
        assert public["runtime_patterns"] == ["&&&F"]
        assert public["derived_claims"]
        assert public["answerability"] == "ANSWERABLE_DERIVED"
        assert public["allowed_operations"]

    def test_grounding_block_result_first(self) -> None:
        from src.intelligence.reasoning.grounded_engine import reason_over_evidence

        grounded = reason_over_evidence(
            question=CANONICAL, evidence_items=[_item(GRAMMAR)]
        )
        block = render_grounding_block(grounded.to_public_dict())
        # Claim determinista SUPPORTED: el bloque autoritativo (código decide,
        # el generador explica y cita). El viejo RESULT FIRST aplicaba a claims
        # no deterministas.
        assert "AUTHORITATIVE DERIVED RESULTS" in block
        assert "RESULT: MATCH" in block
        assert "never reinterpret" in block
        assert "do NOT search them as source evidence" in block
        assert "chain" not in block.lower()

    def test_evidence_block_shows_runtime_pattern_status(self) -> None:
        state = build_evidence_state(CANONICAL, [_item(GRAMMAR)])
        block = render_evidence_state_block(state.to_public_dict())
        assert "Runtime pattern" in block
        assert "literal match required: NO" in block
        assert "ASDFGRE" in block
        assert "source match required: NO" in block


class TestRequirementGraph:
    def test_runtime_pattern_node_never_missing(self) -> None:
        graph = build_requirement_graph(
            question=CANONICAL,
            runtime_inputs=["ASDFGRE"],
            runtime_patterns=["&&&F"],
        )
        public = graph.to_public_dict()
        assert public["missing"] == []
        by_type = public["by_type"]
        assert by_type.get(RequirementNodeType.RUNTIME_INPUT.value) == 1
        assert by_type.get(RequirementNodeType.RUNTIME_PATTERN.value) == 1

    def test_evidence_state_missing_premise_is_a_node(self) -> None:
        state = build_evidence_state(CANONICAL, [_item(NO_GRAMMAR)])
        graph = build_requirement_graph(
            question=CANONICAL, evidence_state=state
        )
        public = graph.to_public_dict()
        assert any(
            "&&&F" not in item or "semántica" in item
            for item in public["missing"]
        )
        assert public["missing"]


class TestAnswerabilityMapping:
    def test_derived_maps_to_answerable_derived(self) -> None:
        from src.core.domain.intelligence import AnswerabilityStatus
        from src.intelligence.answerability import answerability_from_grounding
        from src.intelligence.reasoning.grounded_engine import reason_over_evidence

        grounded = reason_over_evidence(
            question=CANONICAL, evidence_items=[_item(GRAMMAR)]
        )
        decision = answerability_from_grounding(grounded)
        assert decision is not None
        assert decision.status == AnswerabilityStatus.ANSWERABLE_DERIVED
        assert decision.answerable is True
        assert "DERIVED_FROM_GROUNDED_PREMISES" in decision.reason_codes

    def test_missing_premise_maps_to_unanswerable(self) -> None:
        from src.core.domain.intelligence import AnswerabilityStatus
        from src.intelligence.answerability import answerability_from_grounding
        from src.intelligence.reasoning.grounded_engine import reason_over_evidence

        grounded = reason_over_evidence(
            question=CANONICAL, evidence_items=[_item(NO_GRAMMAR)]
        )
        decision = answerability_from_grounding(grounded)
        assert decision is not None
        assert decision.status == AnswerabilityStatus.UNANSWERABLE_MISSING_PREMISE
        assert decision.answerable is False
        assert "símbolo" in (decision.message or "")

    def test_data_missing_is_corrected_by_derivation(self) -> None:
        from src.core.domain.intelligence import (
            AnswerabilityStatus,
            ConfidenceLevel,
        )
        from src.intelligence.answerability import apply_grounded_reasoning
        from src.intelligence.reasoning.grounded_engine import reason_over_evidence

        grounded = reason_over_evidence(
            question=CANONICAL, evidence_items=[_item(GRAMMAR)]
        )
        from src.core.domain.intelligence import AnswerabilityDecision

        legacy = AnswerabilityDecision(
            status=AnswerabilityStatus.DATA_MISSING,
            answerable=False,
            confidence_level=ConfidenceLevel.INSUFFICIENT,
        )
        corrected = apply_grounded_reasoning(legacy, grounded)
        assert corrected.status == AnswerabilityStatus.ANSWERABLE_DERIVED


class TestPromptContract:
    def test_general_prompt_has_no_literal_only_rule(self) -> None:
        from src.agents.runtime.orchestrator import (
            RAG_SYSTEM_PROMPT,
            RAG_SYSTEM_PROMPT_CUSTOMER,
        )

        assert "EXCLUSIVAMENTE" not in RAG_SYSTEM_PROMPT
        assert "usando SOLO la información" not in RAG_SYSTEM_PROMPT_CUSTOMER
        assert "datos que aporta el usuario" in RAG_SYSTEM_PROMPT
        assert "conclusiones derivadas" in RAG_SYSTEM_PROMPT.lower()
        assert "premisas" in RAG_SYSTEM_PROMPT_CUSTOMER

    def test_response_contract_grounding_rule(self) -> None:
        from src.intelligence.response.contract import GROUNDING_RULE

        assert "premisas del dominio" in GROUNDING_RULE
        assert "datos que aporta el usuario" in GROUNDING_RULE
        assert "conocimiento propio" in GROUNDING_RULE

    def test_agent_runtime_finalize_rule(self) -> None:
        from src.agents.runtime.agent_runtime import _FINALIZE_TEMPLATE

        assert "valid scenario data" in _FINALIZE_TEMPLATE
        assert "model knowledge" in _FINALIZE_TEMPLATE
