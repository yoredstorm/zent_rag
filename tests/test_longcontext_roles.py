# =============================================================================
# Anchor Roles — RULE/FIELD documentables vs USER EXAMPLE (input a evaluar)
# =============================================================================
# El error que estos tests blindan: «la documentación no menciona QNNF0SME»
# no es evidencia insuficiente. La documentación prueba la REGLA y el CAMPO;
# el valor del usuario se evalúa aplicándola.
# =============================================================================
from __future__ import annotations

from src.intelligence.response.anchors import Anchor, extract_anchors
from src.rag.longcontext.coverage import anchor_coverage, requirements_satisfied
from src.rag.longcontext.requirements import (
    build_requirements,
    evaluate_requirements,
)
from src.rag.longcontext.roles import AnchorRole
from src.rag.longcontext.views import build_query_views, summarize_views_for_flow

QUESTION = "consulta si FCLAS &&&F acepta QNNF0SME"


def _kinds(question: str) -> dict[str, str]:
    return {anchor.value: anchor.kind for anchor in extract_anchors(question)}


def _roles(question: str) -> dict[str, str]:
    views = build_query_views(question)
    return {
        str(anchor.value): str(getattr(anchor, "role", "")) for anchor in views.anchors
    }


class TestGenericTechnicalDetection:
    def test_mask_forms(self) -> None:
        kinds = _kinds("máscaras &&&F y *F* y F% y Y?? y AB###")
        assert kinds["&&&F"] == "mascara"
        assert kinds["*F*"] == "mascara"
        assert kinds["F%"] == "mascara"
        assert kinds["Y??"] == "mascara"
        assert kinds["AB###"] == "mascara"

    def test_code_forms_with_separators(self) -> None:
        kinds = _kinds("códigos ABC-123 y ABC_123 y A1672STO0 y R007D03E000")
        assert kinds["ABC-123"] == "codigo"
        assert kinds["ABC_123"] == "codigo"
        assert kinds["A1672STO0"] == "codigo"
        assert kinds["R007D03E000"] == "codigo"

    def test_attached_word_digits_and_ranges(self) -> None:
        anchors = {
            anchor.value: anchor
            for anchor in extract_anchors("CAT31 Byte105 QNNF0SME en rango 12-16 y 64/67")
        }
        assert anchors["CAT31"].kind == "codigo"
        assert anchors["Byte105"].kind == "codigo"
        assert anchors["QNNF0SME"].kind == "codigo"
        assert anchors["12-16"].kind == "rango"
        assert anchors["64-67"].kind == "rango"
        assert "64/67" in anchors["64-67"].variants

    def test_non_technical_lowercase_digits_not_code(self) -> None:
        # «gpt4» sin mayúscula en la parte alfabética no es señal técnica.
        assert "gpt4" not in _kinds("modelo gpt4 disponible")


class TestRoleClassification:
    def test_mask_is_rule_and_sigla_is_field(self) -> None:
        roles = _roles(QUESTION)
        assert roles["&&&F"] == AnchorRole.RULE_ANCHOR.value
        assert roles["FCLAS"] == AnchorRole.FIELD_ANCHOR.value

    def test_code_with_evaluation_cue_is_user_example(self) -> None:
        assert _roles(QUESTION)["QNNF0SME"] == AnchorRole.EXAMPLE_VALUE.value

    def test_code_without_cue_is_reference(self) -> None:
        roles = _roles("¿dónde está documentado R007D03E000?")
        assert roles["R007D03E000"] == AnchorRole.REFERENCE.value

    def test_provider_role_and_hint_win(self) -> None:
        domain_anchor = Anchor(
            kind="mascara",
            value="&&&F",
            label="mascara &&&F",
            variants=("&&&F",),
            needles=("&&&F",),
            role="rule_anchor",
            semantic_hint="fare class positional mask",
            expansion_terms=("fare class", "positional matching"),
        )
        views = build_query_views(
            "consulta por &&&F", anchors=[domain_anchor], entities=[]
        )
        assert views.anchors[0].role == AnchorRole.RULE_ANCHOR.value
        assert "fare class positional mask" in views.semantic
        assert "fare class" in views.lexical_terms


class TestThreeChannels:
    def test_semantic_exact_and_lexical_are_parallel(self) -> None:
        views = build_query_views(QUESTION)
        # Semántica: sin la máscara (contamina el embedding).
        assert "&&&F" not in views.semantic
        assert "FCLAS" in views.semantic
        # Exact: la máscara intacta.
        assert "&&&F" in views.exact_terms
        assert "FCLAS" in views.exact_terms
        assert "QNNF0SME" in views.exact_terms
        # Léxica: campos y valores del usuario.
        assert "FCLAS" in views.lexical_terms
        assert "QNNF0SME" in views.lexical_terms
        # Ejemplo separado.
        assert views.examples == ("QNNF0SME",)

    def test_raw_query_never_changes(self) -> None:
        assert build_query_views(QUESTION).raw == QUESTION


class TestExampleValueDoesNotBlock:
    def test_requirements_complete_without_user_value_in_docs(self) -> None:
        views = build_query_views(QUESTION)
        requirements = build_requirements(
            QUESTION,
            list(views.anchors),
            list(views.entities),
            examples=list(views.examples),
        )
        coverage = evaluate_requirements(
            requirements,
            [
                # La documentación explica la regla y el campo; NO menciona
                # QNNF0SME (valor del usuario).
                type(
                    "Item",
                    (),
                    {
                        "content": (
                            "Record 2. FCLAS: fare class. El patrón &&&F exige "
                            "F en la cuarta posición del fare basis."
                        ),
                        "metadata": {},
                    },
                )(),
            ],
        )
        assert requirements_satisfied(coverage, 0.6) is True
        assert coverage.examples == ("QNNF0SME",)
        assert coverage.examples_found == ()
        assert all(
            requirement.documentable or requirement.kind == "example"
            for requirement in requirements
        )

    def test_anchor_coverage_ignores_examples(self) -> None:
        views = build_query_views(QUESTION)
        cov = anchor_coverage(
            list(views.anchors),
            [type("Item", (), {"content": "FCLAS y &&&F documentados", "metadata": {}})()],
        )
        assert cov.requested == 2  # FCLAS + &&&F; QNNF0SME no cuenta
        assert cov.found == 2
        assert cov.coverage == 1.0
        assert cov.examples == ("QNNF0SME",)
        assert cov.to_public_dict()["examples_requires_source_match"] is False


class TestFlowSummary:
    def test_summary_separates_rule_from_example(self) -> None:
        views = build_query_views(QUESTION)
        summary = summarize_views_for_flow(
            views.to_public_dict(),
            ["Record 2. FCLAS y &&&F: matching posicional del fare basis."],
        )
        assert summary is not None
        assert summary["rule_evidence"] == "complete"
        assert summary["documentable_requested"] == 2
        assert summary["documentable_found"] == 2
        examples = summary["examples"]
        assert examples and examples[0]["value"] == "QNNF0SME"
        assert examples[0]["requires_source_match"] is False
        assert "USER EXAMPLE QNNF0SME" in summary["detail"]
        assert "RULE EVIDENCE COMPLETE" in summary["detail"]

    def test_summary_incomplete_when_rule_missing(self) -> None:
        views = build_query_views(QUESTION)
        summary = summarize_views_for_flow(
            views.to_public_dict(), ["texto que sólo menciona FCLAS"]
        )
        assert summary is not None
        assert summary["rule_evidence"] == "incomplete"
        assert summary["status"] == "warn"
