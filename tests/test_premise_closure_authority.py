# =============================================================================
# Premise Closure dentro de prepare_derived_authority — cableado real
# =============================================================================
# Contrato:
#   1. con premisas faltantes, la fase premise_closure se ejecuta y emite
#      telemetría (requirement_graph + premise_closure) sin romper el run;
#   2. si la búsqueda dirigida cierra las premisas, el envelope autoritativo
#      manda y has_authority=True;
#   3. si no cierra nada, el fail-closed se conserva: UNDETERMINED, sin
#      conclusión binaria libre;
#   4. el retrieval de la ronda lo decide el Requirement Graph, no la pregunta
#      original repetida.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.runtime import premise_search, rule_retrieval
from src.runtime.deterministic_authority import (
    STAGE_PREMISE_CLOSURE,
    STAGE_REQUIREMENT_GRAPH,
    prepare_derived_authority,
)

ORG = uuid4()
QUESTION = (
    "yo tengo en el record 2 &&&F y en el farebasis me viene ABCFGEGE "
    "cumple o no cumple"
)
SYMBOL_SENTENCE = (
    "The Exclamation Point (!) or Ampersand (&) is used in conjunction with "
    "alphanumeric characters in the fare family match process to positionally "
    "match fare class characters."
)
LENGTH_SENTENCE = (
    "When using special characters “!” or “&”, a fare class must contain at "
    "least the number of characters referenced in the fare class field "
    "(additional characters may follow)."
)


class _Item:
    def __init__(self, content: str, evidence_id: str) -> None:
        self.content = content
        self.evidence_id = evidence_id
        self.source_id = "source-1"
        self.document_id = "doc-1"
        self.page = 10
        self.section_path = ("Matching",)
        self.metadata = {
            "document_id": "doc-1",
            "source_id": "source-1",
            "page": 10,
            "section_path": ["Matching"],
        }


@pytest.fixture(autouse=True)
def _no_db_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_index_search(self, request):
        del self, request
        return []

    monkeypatch.setattr(rule_retrieval.PostgresRuleIndex, "search", fake_index_search)

    async def fake_load_document_rules(*args, **kwargs):
        del args, kwargs
        return []

    async def fake_noop_expander(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr(
        premise_search, "load_document_rules", fake_load_document_rules
    )
    monkeypatch.setattr(
        premise_search, "make_fabric_expander", lambda *a, **k: fake_noop_expander
    )


def _fake_retrieval():
    async def fake_retrieve(organization_id, question, evidence_items=(), **kwargs):
        del organization_id, question, evidence_items, kwargs
        return rule_retrieval.RuleRetrievalResult(strategy="none")

    return fake_retrieve


class TestPremiseClosureStage:
    @pytest.mark.asyncio
    async def test_pattern_premises_recover_grammar_missing_from_evidence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Caso vivo: reglas persistidas no ejecutables (EXAMPLE) + evidencia del
        turno SIN gramática `&`. El grounding solo reporta `rule:*` (no
        buscable); las premisas del patrón siembran la closure dirigida y la
        gramática se recupera: POSITIONAL_MATCH/MATCH."""
        from src.core.domain.rule_semantics import MatchOperator, VerificationState
        from src.knowledge.rule_compiler.model import CanonicalRule, RuleProperty

        rule = CanonicalRule(
            rule_id="rule:example-fare-family",
            statement="Example 1: W&C&M can be used to match WBCDM (no definition).",
            properties={
                "matching.symbol.&": RuleProperty(
                    name="matching.symbol.&",
                    value="example text",
                    state=VerificationState.SUPPORTED.value,
                    evidence=["ev:ex"],
                ),
                "matching.operator": RuleProperty(
                    name="matching.operator",
                    value=MatchOperator.POSITIONAL.value,
                    state=VerificationState.SUPPORTED.value,
                    evidence=["ev:ex"],
                ),
            },
            verification_state=VerificationState.SUPPORTED.value,
            executable=False,
        )

        async def fake_retrieve(organization_id, question, evidence_items=(), **kwargs):
            del organization_id, question, evidence_items, kwargs
            return rule_retrieval.RuleRetrievalResult(
                strategy="canonical_first",
                compatibility_applied=True,
                compatible_rules=[rule],
                supported_rules=[rule],
            )

        monkeypatch.setattr(
            rule_retrieval, "retrieve_canonical_rules", fake_retrieve
        )

        calls: list[str] = []

        async def evidence_search(query, scope, limit):
            del scope, limit
            calls.append(query)
            lowered = query.lower()
            if "length" in lowered or "longitud" in lowered:
                return [_Item(LENGTH_SENTENCE, "ev:length")]
            if "&" in query or "symbol" in lowered or "definition" in lowered:
                return [_Item(SYMBOL_SENTENCE, "ev:symbol")]
            return []

        footnote = _Item(
            "The matching of the footnote field on the Footnote Record 2 is "
            "done against the Fare and is an exact match.",
            "ev:footnote",
        )

        prep = await prepare_derived_authority(
            organization_id=ORG,
            question=QUESTION,
            evidence_items=[footnote],
            enable_premise_closure=True,
            premise_evidence_search=evidence_search,
        )

        assert prep.premise_closure is not None, (
            "las premisas del patrón deben sembrar la closure aunque el "
            "grounding solo reporte rule:*"
        )
        assert prep.premise_closure.termination == "SATISFIED"
        assert prep.has_authority
        assert prep.authoritative_envelope is not None
        assert prep.authoritative_envelope.operation == "POSITIONAL_MATCH"
        assert prep.authoritative_envelope.normalized_result == "MATCH"
        assert prep.missing_premises == ()
        # La búsqueda dirigida usó las premisas del patrón, no repitió la pregunta.
        assert calls
        assert all(QUESTION not in query for query in calls)
        assert any("&" in query for query in calls)
        assert any("length" in query.lower() for query in calls)

    @pytest.mark.asyncio
    async def test_pattern_premises_without_recoverable_evidence_fail_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sin gramática recuperable se mantiene el fail-closed (nunca MATCH)."""
        from src.core.domain.rule_semantics import MatchOperator, VerificationState
        from src.knowledge.rule_compiler.model import CanonicalRule, RuleProperty

        rule = CanonicalRule(
            rule_id="rule:example-fare-family",
            statement="Example 1: W&C&M can be used to match WBCDM (no definition).",
            properties={
                "matching.symbol.&": RuleProperty(
                    name="matching.symbol.&",
                    value="example text",
                    state=VerificationState.SUPPORTED.value,
                    evidence=["ev:ex"],
                ),
                "matching.operator": RuleProperty(
                    name="matching.operator",
                    value=MatchOperator.POSITIONAL.value,
                    state=VerificationState.SUPPORTED.value,
                    evidence=["ev:ex"],
                ),
            },
            verification_state=VerificationState.SUPPORTED.value,
            executable=False,
        )

        async def fake_retrieve(organization_id, question, evidence_items=(), **kwargs):
            del organization_id, question, evidence_items, kwargs
            return rule_retrieval.RuleRetrievalResult(
                strategy="canonical_first",
                compatibility_applied=True,
                compatible_rules=[rule],
                supported_rules=[rule],
            )

        monkeypatch.setattr(
            rule_retrieval, "retrieve_canonical_rules", fake_retrieve
        )

        async def empty_search(query, scope, limit):
            del query, scope, limit
            return []

        footnote = _Item(
            "Ticket on/before 01Jan 99 Match the IF and apply the THEN.",
            "ev:footnote",
        )
        prep = await prepare_derived_authority(
            organization_id=ORG,
            question=QUESTION,
            evidence_items=[footnote],
            enable_premise_closure=True,
            premise_evidence_search=empty_search,
        )

        assert not prep.has_authority
        assert prep.premise_closure is not None
        assert prep.premise_closure.termination in (
            "NO_INFORMATION_GAIN",
            "BUDGET_EXHAUSTED",
        )
        state, message = prep.answer_state()
        assert state != "DERIVED"
        assert "No puedo determinarlo" in message
        assert "MATCH" not in message

    @pytest.mark.asyncio
    async def test_targeted_search_closes_premises_and_authorizes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            rule_retrieval, "retrieve_canonical_rules", _fake_retrieval()
        )

        calls: list[str] = []

        async def evidence_search(query, scope, limit):
            del scope, limit
            calls.append(query)
            lowered = query.lower()
            if "length" in lowered or "longitud" in lowered:
                return [_Item(LENGTH_SENTENCE, "ev:length")]
            if "&" in query or "symbol" in lowered or "definition" in lowered:
                return [_Item(SYMBOL_SENTENCE, "ev:symbol")]
            return []

        prep = await prepare_derived_authority(
            organization_id=ORG,
            question=QUESTION,
            evidence_items=[],
            enable_premise_closure=True,
            premise_evidence_search=evidence_search,
        )

        assert prep.premise_closure is not None
        assert prep.premise_closure.termination == "SATISFIED"
        assert prep.missing_premises == ()
        assert prep.has_authority
        assert prep.authoritative_envelope is not None
        state, _ = prep.answer_state()
        from src.runtime.answer_gate import ANSWER_STATE_DERIVED

        assert state == ANSWER_STATE_DERIVED
        step_types = [step["type"] for step in prep.steps]
        assert STAGE_REQUIREMENT_GRAPH in step_types
        assert STAGE_PREMISE_CLOSURE in step_types
        # La ronda buscó por premisas, no repitió la pregunta original.
        assert calls
        assert all(QUESTION not in query for query in calls)
        assert any("&" in query for query in calls)
        closure_step = next(
            step for step in prep.steps if step["type"] == STAGE_PREMISE_CLOSURE
        )
        assert closure_step["status"] == "ok"
        assert closure_step["information_gain"] >= 1
        # La evidencia que cerró premisas cuenta como usada para razonar,
        # aunque la respuesta final no la cite.
        assert prep.evidence_counters["used_for_reasoning"] >= 1
        assert prep.evidence_counters["retrieved"] >= 0

    @pytest.mark.asyncio
    async def test_without_evidence_fail_closed_is_preserved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            rule_retrieval, "retrieve_canonical_rules", _fake_retrieval()
        )

        async def empty_search(query, scope, limit):
            del query, scope, limit
            return []

        prep = await prepare_derived_authority(
            organization_id=ORG,
            question=QUESTION,
            evidence_items=[],
            enable_premise_closure=True,
            premise_evidence_search=empty_search,
        )

        assert prep.premise_closure is not None
        assert prep.premise_closure.termination in (
            "NO_INFORMATION_GAIN",
            "BUDGET_EXHAUSTED",
        )
        assert not prep.has_authority
        state, message = prep.answer_state()
        assert state != "DERIVED"
        assert "No puedo determinarlo" in message or "no pude completar" in message.lower()
        closure_step = next(
            step for step in prep.steps if step["type"] == STAGE_PREMISE_CLOSURE
        )
        assert closure_step["status"] == "warn"

    @pytest.mark.asyncio
    async def test_closure_disabled_keeps_previous_behavior(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            rule_retrieval, "retrieve_canonical_rules", _fake_retrieval()
        )
        prep = await prepare_derived_authority(
            organization_id=ORG,
            question=QUESTION,
            evidence_items=[],
        )
        assert prep.premise_closure is None
        assert all(step["type"] != STAGE_PREMISE_CLOSURE for step in prep.steps)
