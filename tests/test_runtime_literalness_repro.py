# =============================================================================
# P0.1 — Reproducción de la regresión de literalidad (ASDFGRE / &&&F)
# =============================================================================
# Escenario EXACTO:
#   «si tengo un farebasis ASDFGRE y en Record 2 me viene &&&F, ¿cumple?»
#
# Comportamiento viejo (HEAD 72aa036):
#   ASDFGRE -> field_anchor documentable
#   &&&F    -> rule_anchor documentable
#   missing_documentable_evidence = [ASDFGRE, &&&F]
#   generation_mode = generate_with_limits
#
# Comportamiento nuevo:
#   ASDFGRE -> example_value (USER_INPUT, no exige match)
#   &&&F    -> runtime_pattern (exige semántica, no literalidad)
#   missing_documentable_evidence = [] (con gramática documentada)
#   missing_premises = [definition:symbol:&, ...] (sin gramática)
#
# Este archivo importa SÓLO módulos estables: se puede correr contra HEAD para
# demostrar el fallo y contra el árbol corregido para demostrar el arreglo.
# =============================================================================
from __future__ import annotations

from src.rag.longcontext.coverage import build_evidence_state
from src.rag.longcontext.views import build_query_views

QUESTION = "si tengo un farebasis ASDFGRE y en Record 2 me viene &&&F, ¿cumple?"

GRAMMAR_DOC = (
    "Record 2: & represents one alphanumeric position. Matching is positional "
    "from the start (prefix). El fare basis se evalúa contra el patrón del record."
)
NO_GRAMMAR_DOC = "Record 2: patterns are supported for the fare basis field."


class _Item:
    def __init__(self, content: str, evidence_id: str = "E1") -> None:
        self.content = content
        self.evidence_id = evidence_id


def diagnose(question: str, evidence: str) -> dict:
    """Registra anchors, roles, requirements, missing y generation mode."""
    views = build_query_views(question)
    state = build_evidence_state(question, [_Item(evidence)])
    public = state.to_public_dict()
    return {
        "anchors": [(a.value, a.kind) for a in views.anchors],
        "roles": {
            str(getattr(a, "value", "")): str(getattr(a, "role", ""))
            for a in views.anchors
        },
        "requirements": [
            (r.kind, r.state, r.description)
            for r in state.requirements.requirements
        ],
        "missing_documentable": list(state.missing_documentable_evidence),
        "missing_premises": list(state.missing_premises),
        "runtime_patterns": list(public.get("runtime_patterns") or ()),
        "runtime_values": list(public.get("runtime_values") or ()),
        "example_values": list(public.get("example_values") or ()),
        "generation_mode": state.generation_mode,
        "evidence_complete": state.evidence_complete,
    }


class TestReproductionDiagnostic:
    def test_asdfgre_is_user_input_not_source_requirement(self) -> None:
        diag = diagnose(QUESTION, GRAMMAR_DOC)
        # HEAD: "field_anchor". Nuevo: "example_value" (USER_INPUT).
        assert diag["roles"]["ASDFGRE"] == "example_value", diag
        assert "ASDFGRE" not in diag["missing_documentable"], diag
        assert "ASDFGRE" in diag["example_values"], diag

    def test_mask_is_runtime_pattern_not_literal_requirement(self) -> None:
        diag = diagnose(QUESTION, GRAMMAR_DOC)
        # HEAD: "rule_anchor" documentable. Nuevo: "runtime_pattern".
        assert diag["roles"]["&&&F"] == "runtime_pattern", diag
        assert "&&&F" not in diag["missing_documentable"], diag
        assert "&&&F" in diag["runtime_patterns"], diag

    def test_documented_grammar_generates_without_literal_values(self) -> None:
        diag = diagnose(QUESTION, GRAMMAR_DOC)
        assert diag["evidence_complete"] is True, diag
        assert diag["generation_mode"] == "generate_full", diag
        assert diag["missing_documentable"] == [], diag

    def test_missing_grammar_names_the_symbol_premise_not_the_value(self) -> None:
        diag = diagnose(QUESTION, NO_GRAMMAR_DOC)
        assert diag["evidence_complete"] is False, diag
        # La abstención correcta nombra la premisa del dominio, jamás el dato.
        assert any("definition:symbol:&" in item for item in diag["missing_premises"]), diag
        assert "ASDFGRE" not in " ".join(diag["missing_premises"]), diag
        assert "&&&F" not in " ".join(diag["missing_premises"]), diag

    def test_source_lookup_contrast_keeps_literal_requirement(self) -> None:
        """P0.17: preguntar si aparece es source lookup (exigencia literal)."""
        diag = diagnose("¿ASDFGRE aparece en el documento?", GRAMMAR_DOC)
        assert diag["roles"]["ASDFGRE"] == "reference", diag
        assert "ASDFGRE" in diag["missing_documentable"], diag

    def test_pattern_instance_contrast_keeps_definition_requirement(self) -> None:
        """P0.18: preguntar si el texto contiene el patrón es source lookup."""
        diag = diagnose("¿el documento menciona &&&F?", GRAMMAR_DOC)
        assert diag["roles"]["&&&F"] in ("rule_anchor", "reference"), diag
        assert "&&&F" in diag["missing_documentable"], diag
