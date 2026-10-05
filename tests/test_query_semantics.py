# =============================================================================
# Query semantics — la FORMA del token no decide sola el rol
# =============================================================================
# Regresiones canónicas:
#   - ASDFGRE (misma silueta que FCLAS) es USER_INPUT cuando el contexto lo
#     declara dato del escenario, y SOURCE_REQUIREMENT cuando se pregunta si
#     aparece literalmente en el documento.
#   - &&&F es RUNTIME_PATTERN cuando «me viene»/«me llega», y RULE_REQUIREMENT
#     cuando se pregunta qué significa según el documento.
#   - Los valores numéricos del usuario (20) no son anchors de fuente; el
#     umbral documentado (18) sí.
# =============================================================================
from __future__ import annotations

import pytest

from src.intelligence.query_semantics import (
    ContextualQueryRoleClassifier,
    QueryIntent,
    QuerySemanticRole,
    build_classifier_prompt,
    classify_query_semantics,
    detect_query_intent,
    extract_runtime_parameters,
    parse_classifier_response,
    pattern_semantic_requirements,
)


def _roles(question: str) -> dict[str, str]:
    return {
        obj.value: obj.semantic_role
        for obj in classify_query_semantics(question).objects
    }


CANONICAL = (
    "si tengo un farebasis en el boleto ASDFGRE y en el record 2 me viene "
    "&&&F cumple o no?"
)


class TestCanonicalClassification:
    def test_canonical_question(self) -> None:
        roles = _roles(CANONICAL)
        assert roles["ASDFGRE"] == QuerySemanticRole.USER_INPUT.value
        assert roles["&&&F"] == QuerySemanticRole.RUNTIME_PATTERN.value

    def test_canonical_intent_is_validate(self) -> None:
        semantics = classify_query_semantics(CANONICAL)
        assert semantics.intent == QueryIntent.VALIDATE.value
        assert semantics.requires_reasoning is True

    def test_pattern_requires_semantics_not_literal(self) -> None:
        semantics = classify_query_semantics(CANONICAL)
        pattern = semantics.runtime_patterns[0]
        assert pattern.evidence_required is False
        assert pattern.runtime_value is True
        assert "definition:symbol:&" in pattern.requires_semantics
        assert "matching_policy" in pattern.requires_semantics
        assert "length_semantics" in pattern.requires_semantics

    def test_runtime_inputs_do_not_require_evidence(self) -> None:
        semantics = classify_query_semantics(CANONICAL)
        asdfgre = next(obj for obj in semantics.objects if obj.value == "ASDFGRE")
        assert asdfgre.documentable is False
        assert asdfgre.runtime is True


class TestFormIsNotAuthority:
    @pytest.mark.parametrize(
        "question,expected",
        [
            ("mi farebasis es ASDFGRE", QuerySemanticRole.USER_INPUT.value),
            ("en el boleto ASDFGRE", QuerySemanticRole.USER_INPUT.value),
            ("¿ASDFGRE aparece literalmente en el documento?", QuerySemanticRole.SOURCE_REQUIREMENT.value),
            ("¿dónde está documentado ASDFGRE?", QuerySemanticRole.SOURCE_REQUIREMENT.value),
            ("¿qué significa ASDFGRE?", QuerySemanticRole.DEFINITION_REQUIREMENT.value),
            ("mi código es ASDFGRE, ¿cumple esta regla?", QuerySemanticRole.USER_INPUT.value),
        ],
    )
    def test_same_shape_different_roles(self, question: str, expected: str) -> None:
        assert _roles(question)["ASDFGRE"] == expected

    @pytest.mark.parametrize("value", ["ABCDEFG", "PREMIUM", "ECONOMY", "MEXICO", "ABCDEF"])
    def test_alpha_only_user_values_are_runtime(self, value: str) -> None:
        roles = _roles(f"mi farebasis es {value}, ¿cumple?")
        assert roles[value] == QuerySemanticRole.USER_INPUT.value

    def test_legacy_field_pattern_question_keeps_roles(self) -> None:
        roles = _roles("consulta si FCLAS &&&F acepta QNNF0SME")
        assert roles["FCLAS"] == QuerySemanticRole.FIELD_REQUIREMENT.value
        assert roles["&&&F"] == QuerySemanticRole.RULE_REQUIREMENT.value
        assert roles["QNNF0SME"] == QuerySemanticRole.USER_INPUT.value

    def test_pattern_definition_question_is_source_requirement(self) -> None:
        roles = _roles("¿qué significa &&&F según el documento?")
        assert roles["&&&F"] == QuerySemanticRole.RULE_REQUIREMENT.value

    def test_runtime_pattern_arrival_wins_over_definition_cue(self) -> None:
        roles = _roles(
            "me llegó &&&F; según la regla documentada, ¿qué significa?"
        )
        assert roles["&&&F"] == QuerySemanticRole.RUNTIME_PATTERN.value


class TestIntentModel:
    @pytest.mark.parametrize(
        "question,intent",
        [
            ("¿qué significa FCLAS?", QueryIntent.DEFINITION.value),
            ("¿FCLAS aparece en el documento?", QueryIntent.SOURCE_LOOKUP.value),
            ("¿ASDFGRE cumple &&&F?", QueryIntent.VALIDATE.value),
            ("mi valor ABCFXYZ contra &&&F", QueryIntent.APPLY_RULE.value),
            ("¿cuánto es el total con impuesto?", QueryIntent.CALCULATE.value),
            ("compara el precio A contra el precio B", QueryIntent.COMPARE.value),
            ("convierte el código a mayúsculas", QueryIntent.TRANSFORM.value),
            ("resume el documento", QueryIntent.SUMMARIZE.value),
            ("¿cómo llegaste a esa conclusión?", QueryIntent.TRACE.value),
        ],
    )
    def test_deterministic_intent(self, question: str, intent: str) -> None:
        assert detect_query_intent(question)[0] == intent

    def test_reasoning_intents_are_not_lookups(self) -> None:
        from src.intelligence.query_semantics import REASONING_INTENTS

        for intent in (
            QueryIntent.APPLY_RULE,
            QueryIntent.VALIDATE,
            QueryIntent.CALCULATE,
            QueryIntent.COMPARE,
            QueryIntent.TRANSFORM,
            QueryIntent.INFER,
        ):
            assert intent.value in REASONING_INTENTS


class TestRuntimeParameters:
    def test_threshold_vs_user_value(self) -> None:
        params = extract_runtime_parameters("la edad mínima es 18, tengo 20, ¿cumplo?")
        values = {obj.value for obj in params}
        assert "20" in values
        assert "18" not in values

    @pytest.mark.parametrize(
        "question,name,value",
        [
            ("base=100 surcharge=20", "base", "100"),
            ("precio=100", "precio", "100"),
            ("tax_rate=0.18", "tax_rate", "0.18"),
            ("age 20", "age", "20"),
            ("status ACTIVE", "status", "ACTIVE"),
        ],
    )
    def test_named_parameters(self, question: str, name: str, value: str) -> None:
        params = extract_runtime_parameters(question)
        assert any(obj.value == value for obj in params)

    def test_structural_names_are_not_parameters(self) -> None:
        params = extract_runtime_parameters("en el record 2 me viene &&&F")
        assert all(obj.value != "2" for obj in params)

    def test_numeric_values_are_not_source_anchors(self) -> None:
        semantics = classify_query_semantics("la edad mínima es 18, tengo 20, ¿cumplo?")
        assert all(
            obj.semantic_role != QuerySemanticRole.SOURCE_REQUIREMENT.value
            for obj in semantics.objects
            if obj.value in ("18", "20")
        )


class TestPatternSemanticRequirements:
    def test_requirements_are_about_semantics_not_instance(self) -> None:
        requirements = pattern_semantic_requirements("&&&F")
        assert "symbol:&" in requirements
        assert "definition:symbol:&" in requirements
        assert "matching_policy" in requirements
        assert all("&&&F" not in item for item in requirements)

    def test_generic_product_pattern(self) -> None:
        requirements = pattern_semantic_requirements("AAA-###")
        assert "symbol:#" in requirements
        assert "definition:symbol:#" in requirements


class TestProviderHints:
    def test_provider_role_wins(self) -> None:
        from src.intelligence.response.anchors import Anchor

        anchor = Anchor(
            kind="mascara",
            value="&&&F",
            label="mascara &&&F",
            variants=("&&&F",),
            needles=("&&&F",),
            role="rule_anchor",
        )
        semantics = ContextualQueryRoleClassifier().classify("&&&F", [anchor])
        assert semantics.objects[0].semantic_role == QuerySemanticRole.RULE_REQUIREMENT.value
        assert semantics.objects[0].decided_by == "provider"


class TestOptionalLlmClassifier:
    def test_prompt_is_structured_and_short(self) -> None:
        prompt = build_classifier_prompt("mi valor ABCFXYZ contra &&&F")
        assert "JSON" in prompt
        assert "chain" not in prompt.lower()

    def test_parse_valid_response(self) -> None:
        payload = (
            '{"intent": "APPLY_RULE", "confidence": 0.8, "objects": ['
            '{"value": "ABCFXYZ", "role": "USER_INPUT", "confidence": 0.9},'
            '{"value": "&&&F", "role": "RUNTIME_PATTERN", "confidence": 0.9}]}'
        )
        semantics = parse_classifier_response(payload)
        assert semantics is not None
        assert semantics.decided_by == "llm"
        roles = {obj.value: obj.semantic_role for obj in semantics.objects}
        assert roles["ABCFXYZ"] == QuerySemanticRole.USER_INPUT.value
        assert roles["&&&F"] == QuerySemanticRole.RUNTIME_PATTERN.value

    def test_parse_invalid_returns_fallback(self) -> None:
        fallback = classify_query_semantics("hola")
        assert parse_classifier_response("no soy json", fallback=fallback) is fallback
        assert parse_classifier_response("{invalido}", fallback=fallback) is fallback
