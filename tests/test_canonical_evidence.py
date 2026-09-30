# =============================================================================
# Autoridad canónica de evidencia — una sola interpretación, una sola decisión
# =============================================================================
# Blindajes:
#   - QNNF0SME (EXAMPLE_VALUE) jamás es evidencia faltante ni en el prompt.
#   - La decisión de generar sale SOLO del EvidenceState canónico.
#   - Orchestrator y AgentRuntime consumen la misma autoridad.
#   - Si falta la regla &&&F: RETRIEVE_MORE si hay retrieval; si no, límites.
#   - Citas: sólo el citation_map final es citable.
#   - El runtime no contiene referencias a coverage_note.
# =============================================================================
from __future__ import annotations

from pathlib import Path

from src.core.domain.adaptive import EvidenceQuality
from src.rag.longcontext.coverage import (
    ABSTAIN,
    GENERATE_FULL,
    GENERATE_WITH_LIMITS,
    RETRIEVE_MORE,
    build_evidence_state,
    decide_generation_mode,
)
from src.rag.longcontext.package import (
    build_generation_package,
    render_evidence_state_block,
    validate_doc_citations,
)
from src.rag.longcontext.roles import AnchorRole

QUESTION = (
    "consulta si me viene en el record 2 esto en FCLAS &&&F quiere decir que "
    "el farebasis debe ser de ese tamaño? en el boleto viene asi QNNF0SME cumplira?"
)

RULE_EVIDENCE = (
    "Record 2: FCLAS indica la clase tarifaria del fare basis. La máscara &&&F "
    "exige que el fare basis tenga la longitud indicada; los caracteres "
    "posteriores a && restringen el tamaño."
)

_FIELD_ONLY = "Record 2: FCLAS indica la clase tarifaria del fare basis."


def _state(evidence: str, *, retrieval_available: bool = False):
    return build_evidence_state(
        QUESTION,
        [evidence],
        quality=EvidenceQuality(sufficient=True, score=0.9, reason="test"),
        stop_reason="evidence_complete",
        retrieval_available=retrieval_available,
    )


class TestCanonicalDecision:
    def test_qnnf0sme_generate_full(self) -> None:
        state = _state(RULE_EVIDENCE)
        roles = {str(getattr(a, "value", "")): str(getattr(a, "role", "")) for a in state.example_values}
        assert roles.get("QNNF0SME") == AnchorRole.EXAMPLE_VALUE.value
        assert state.evidence_complete is True
        assert state.missing_documentable_evidence == ()
        assert state.generation_mode == GENERATE_FULL
        assert "QNNF0SME" not in state.missing_documentable_evidence

    def test_missing_rule_is_documentable_missing(self) -> None:
        state = _state(_FIELD_ONLY)
        assert state.evidence_complete is False
        missing = " ".join(state.missing_documentable_evidence)
        assert "&&&F" in missing
        assert "QNNF0SME" not in missing

    def test_retrieve_more_before_disclaimer(self) -> None:
        state = _state(_FIELD_ONLY, retrieval_available=True)
        assert state.generation_mode == RETRIEVE_MORE
        exhausted = _state(_FIELD_ONLY, retrieval_available=False)
        assert exhausted.generation_mode == GENERATE_WITH_LIMITS

    def test_mode_matrix(self) -> None:
        complete = _state(RULE_EVIDENCE)
        assert decide_generation_mode(complete, retrieval_available=False) == (
            GENERATE_FULL,
            "requirements complete; no conflicts",
        )
        incomplete = _state(_FIELD_ONLY)
        assert decide_generation_mode(incomplete, retrieval_available=True)[0] == RETRIEVE_MORE
        assert decide_generation_mode(incomplete, retrieval_available=False)[0] == (
            GENERATE_WITH_LIMITS
        )

    def test_empty_query_does_not_generate_full(self) -> None:
        state = build_evidence_state("hola", [], retrieval_available=False)
        assert state.generation_mode in (ABSTAIN, GENERATE_WITH_LIMITS)
        assert state.generation_mode != GENERATE_FULL


class TestCanonicalPromptBlock:
    def test_block_never_declares_example_missing(self) -> None:
        state = _state(RULE_EVIDENCE)
        package = build_generation_package(
            question=QUESTION, evidence_state=state, selection=None
        )
        public = package.to_public_dict()
        block = render_evidence_state_block(public)
        assert "QNNF0SME" in block
        assert "source match required: NO" in block
        assert "Missing documentable evidence: none" in block
        assert "No lo expliques de memoria" not in block
        assert "no menciona" not in block.lower()
        assert public["evidence"]["legacy_coverage"] == "disabled"

    def test_package_missing_comes_from_state_only(self) -> None:
        state = _state(_FIELD_ONLY)
        package = build_generation_package(
            question=QUESTION,
            evidence_state=state,
            selection=None,
            extra_missing=("basura legacy",),
        )
        public = package.to_public_dict()
        assert not any("basura legacy" in item for item in public["missing_evidence"])
        assert not any("QNNF0SME" in item for item in public["missing_evidence"])
        assert any("&&&F" in item for item in public["missing_evidence"])
        assert public["mode"] == GENERATE_WITH_LIMITS


class TestLegacyHasNoAuthority:
    def test_legacy_function_no_longer_flags_example(self) -> None:
        from src.intelligence.response.entities import _uncovered_anchors

        labels = _uncovered_anchors(QUESTION, RULE_EVIDENCE)
        assert not any("QNNF0SME" in label for label in labels)

    def test_runtime_sources_do_not_reference_coverage_note(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src"
        for relative in (
            "agents/runtime/orchestrator.py",
            "agents/runtime/agent_runtime.py",
        ):
            source = (root / relative).read_text(encoding="utf-8")
            assert "coverage_note" not in source, relative
            assert "entities_covered=_entities_covered" not in source, relative

    def test_orchestrator_uses_evidence_complete_not_entity_match(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src"
        source = (root / "agents/runtime/orchestrator.py").read_text(encoding="utf-8")
        assert "def _evidence_complete(" in source
        assert "evidence_complete=_evidence_complete(adaptive)" in source
        # La decisión de disclaimer no consulta exact_entity_match.
        block = source.split("def _contradictory_disclaimer")[1].split("def ")[0]
        assert "exact_entity_match" not in block


class TestAgentRuntimeSameAuthority:
    def test_agent_coverage_note_is_canonical(self) -> None:
        from src.agents.runtime.agent_runtime import _coverage_history_note

        note = _coverage_history_note(QUESTION, RULE_EVIDENCE)
        assert "EVIDENCE STATE" in note
        assert "source match required: NO" in note
        assert "no menciona" not in note.lower()

    def test_agent_completeness_signal(self) -> None:
        from src.agents.runtime.agent_runtime import _sufficiency_complete

        class _Suff:
            def __init__(self, missing_anchors=(), missing_entities=()):
                self.missing_anchors = missing_anchors
                self.missing_entities = missing_entities

        assert _sufficiency_complete(_Suff()) is True
        assert _sufficiency_complete(_Suff(missing_anchors=("&&&F",))) is False
        assert _sufficiency_complete(None) is False


class TestDisclaimersUseCanonical:
    def test_disclaimer_uses_evidence_complete(self) -> None:
        from src.intelligence.response.entities import (
            self_contradicting_disclaimer,
            strip_contradicting_disclaimer,
        )

        answer = "La información disponible no contiene la regla. Igual, acá va el detalle."
        assert self_contradicting_disclaimer(answer, evidence_complete=True)
        assert self_contradicting_disclaimer(answer, evidence_complete=False) == ""
        limpio, quitadas = strip_contradicting_disclaimer(
            answer, evidence_complete=True
        )
        assert quitadas >= 1 and "no contiene la regla" not in limpio


class TestCitationValidation:
    def test_out_of_package_citation_is_invalid(self) -> None:
        citation_map = [{"evidence_id": "E1"}, {"evidence_id": "E2"}]
        assert validate_doc_citations("ver [Doc: 1] y [Doc: 2]", citation_map) == []
        assert validate_doc_citations("ver [Doc: 3]", citation_map) == [3]
        assert validate_doc_citations("nada", citation_map) == []
