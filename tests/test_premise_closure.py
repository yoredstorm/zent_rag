# =============================================================================
# Premise Closure — retrieval dirigido por premisas faltantes
# =============================================================================
# Contrato:
#   1. cada premisa tiene ontología de consulta GENERAL (sin dominio);
#   2. los símbolos se buscan exacto/léxico ANTES que dense;
#   3. una premisa puede requerir varias consultas pequeñas (nunca una gigante);
#   4. las rondas se miden por information_gain real; sin gain, se termina;
#   5. si la evidencia cubre la premisa y el compilador no la representó, se
#      reporta COMPILATION_GAP + feedback (nunca se rellena con heurística);
#   6. source-local y graph expansion se aplican antes de volver a búsqueda
#      global;
#   7. terminaciones explícitas: SATISFIED / CONFLICTING / NO_INFORMATION_GAIN /
#      BUDGET_EXHAUSTED.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import pytest

from src.core.domain.rule_semantics import VerificationState
from src.knowledge.rule_compiler.model import CanonicalRule, RuleProperty
from src.runtime.premise_closure import (
    LANE_EXACT,
    PREMISE_LENGTH_POLICY,
    PREMISE_MATCHING_LITERAL,
    PREMISE_MATCHING_POSITIONAL,
    PREMISE_SYMBOL_PREFIX,
    TERMINATION_BUDGET_EXHAUSTED,
    TERMINATION_NO_INFORMATION_GAIN,
    TERMINATION_SATISFIED,
    EvidenceHit,
    PremiseClosureRequest,
    PremiseEvaluation,
    PremiseQueryPlanner,
    PremiseSearchOutcome,
    SourceScope,
    expected_semantic_dimension,
    normalize_premises,
    premise_ontology,
    run_premise_closure,
)

MISSING = (
    f"{PREMISE_SYMBOL_PREFIX}&",
    PREMISE_MATCHING_POSITIONAL,
    PREMISE_MATCHING_LITERAL,
    PREMISE_LENGTH_POLICY,
)

_FORBIDDEN_DOMAIN_TERMS = ("atpco", "fclas", "record 2", "fare basis", "fare class")


def _rule(rule_id: str, **properties: Any) -> CanonicalRule:
    props = {
        name: RuleProperty(
            name=name,
            value=value,
            state=VerificationState.SUPPORTED.value,
            evidence=["ev:1"],
            matched_text=f"{name} marker",
        )
        for name, value in properties.items()
    }
    return CanonicalRule(
        rule_id=rule_id,
        statement="fixture",
        subject="fixture",
        properties=props,
        verification_state=VerificationState.SUPPORTED.value,
        executable=True,
    )


def _missing_from_rules(rules: Sequence[Any], premises: Sequence[str]) -> tuple[str, ...]:
    missing: list[str] = []
    for premise in premises:
        dimension = expected_semantic_dimension(premise)
        covered = any(
            dimension in (getattr(rule, "properties", {}) or {})
            and getattr((getattr(rule, "properties", {}) or {})[dimension], "known", False)
            for rule in rules
        )
        if not covered:
            missing.append(premise)
    return tuple(missing)


def _hit(evidence_id: str, content: str, **overrides: Any) -> EvidenceHit:
    return EvidenceHit(evidence_id=evidence_id, content=content, **overrides)


@dataclass
class _FakeSearch:
    rounds: list[PremiseSearchOutcome]
    calls: list[dict] = field(default_factory=list)

    async def search(
        self,
        request: PremiseClosureRequest,
        queries: Sequence[Any],
        *,
        round_index: int,
        focus: SourceScope | None = None,
    ) -> PremiseSearchOutcome:
        self.calls.append(
            {
                "round": round_index,
                "queries": list(queries),
                "focus": focus,
                "missing": request.normalized_missing(),
            }
        )
        index = min(round_index - 1, len(self.rounds) - 1)
        return self.rounds[index]


class TestPremisePlanner:
    def _request(self, missing: Sequence[str] = MISSING) -> PremiseClosureRequest:
        return PremiseClosureRequest(
            original_query="¿el valor ABCFGEGE cumple el patrón &&&F?",
            missing_premises=tuple(missing),
            runtime_pattern="&&&F",
            field_context=("fare basis",),
        )

    def test_symbol_queries_are_exact_first(self) -> None:
        plan = PremiseQueryPlanner().plan(self._request())
        symbol_queries = [
            query for query in plan if query.premise == f"{PREMISE_SYMBOL_PREFIX}&"
        ]
        assert symbol_queries
        assert symbol_queries[0].lane == LANE_EXACT
        assert symbol_queries[0].symbol == "&"
        # El símbolo puntual es la primera consulta de todas.
        assert plan[0].symbol == "&"
        assert plan[0].lane == LANE_EXACT

    def test_every_premise_gets_small_queries(self) -> None:
        plan = PremiseQueryPlanner().plan(self._request())
        premises = {query.premise for query in plan}
        assert f"{PREMISE_SYMBOL_PREFIX}&" in premises
        assert PREMISE_MATCHING_POSITIONAL in premises
        assert PREMISE_LENGTH_POLICY in premises
        # Ninguna consulta es gigante.
        assert all(len(query.query) <= 240 for query in plan)
        assert len(plan) <= 6

    def test_ontology_is_domain_agnostic(self) -> None:
        terms = " ".join(
            [
                *premise_ontology(PREMISE_MATCHING_POSITIONAL),
                *premise_ontology(PREMISE_MATCHING_LITERAL),
                *premise_ontology(PREMISE_LENGTH_POLICY),
            ]
        ).lower()
        for forbidden in _FORBIDDEN_DOMAIN_TERMS:
            assert forbidden not in terms, forbidden

    def test_normalization_of_variant_vocabulary(self) -> None:
        normalized = normalize_premises(
            (
                "matching_policy",
                "positional_semantics",
                "literal_semantics",
                "length_semantics",
                "definition:symbol:&",
                "symbol:&",
                "length.policy",
                "rule:no_candidate",
            )
        )
        assert f"{PREMISE_SYMBOL_PREFIX}&" in normalized
        assert PREMISE_MATCHING_POSITIONAL in normalized
        assert PREMISE_MATCHING_LITERAL in normalized
        assert PREMISE_LENGTH_POLICY in normalized
        # Los diagnósticos de regla ausente no son premisas buscables.
        assert all("rule:" not in item for item in normalized)


class TestPremiseClosureLoop:
    @pytest.mark.asyncio
    async def test_distributed_premises_close_across_rounds(self) -> None:
        symbol_rule = _rule("rule:sym", **{"matching.symbol.&": "alphanumeric position"})
        matching_rule = _rule("rule:match", **{"matching.operator": "POSITIONAL"})
        literal_rule = _rule("rule:literal", **{"matching.literal": True})
        length_rule = _rule("rule:length", **{"length.policy": "MIN_LENGTH"})
        search = _FakeSearch(
            rounds=[
                PremiseSearchOutcome(
                    rules=(symbol_rule,),
                    evidence=(_hit("ev:1", "The & can be used to indicate a position."),),
                ),
                PremiseSearchOutcome(
                    rules=(matching_rule, literal_rule),
                    evidence=(_hit("ev:2", "matching is positional; literal characters match exactly"),),
                ),
                PremiseSearchOutcome(rules=(length_rule,)),
            ]
        )

        async def evaluate(rules: Sequence[Any], _evidence: Sequence[Any]) -> PremiseEvaluation:
            return PremiseEvaluation(missing_premises=_missing_from_rules(rules, MISSING))

        request = PremiseClosureRequest(
            original_query="q",
            missing_premises=MISSING,
            rounds_left=3,
        )
        result = await run_premise_closure(request, search=search, evaluate=evaluate)
        assert result.termination == TERMINATION_SATISFIED
        assert result.missing_after == ()
        assert result.total_information_gain == 4
        assert len(result.rounds) == 3
        # La segunda ronda ya no repite la consulta exacta del símbolo.
        second_queries = [query.premise for query in search.calls[1]["queries"]]
        assert f"{PREMISE_SYMBOL_PREFIX}&" not in second_queries

    @pytest.mark.asyncio
    async def test_no_information_gain_stops_immediately(self) -> None:
        search = _FakeSearch(rounds=[PremiseSearchOutcome()])

        async def evaluate(rules: Sequence[Any], _evidence: Sequence[Any]) -> PremiseEvaluation:
            return PremiseEvaluation(missing_premises=_missing_from_rules(rules, MISSING))

        request = PremiseClosureRequest(
            original_query="q", missing_premises=MISSING, rounds_left=3
        )
        result = await run_premise_closure(request, search=search, evaluate=evaluate)
        assert result.termination == TERMINATION_NO_INFORMATION_GAIN
        assert len(result.rounds) == 1
        assert result.total_information_gain == 0
        assert len(search.calls) == 1

    @pytest.mark.asyncio
    async def test_budget_exhausted_is_explicit(self) -> None:
        search = _FakeSearch(
            rounds=[
                PremiseSearchOutcome(rules=(_rule("rule:sym", **{"matching.symbol.&": "x"}),)),
                PremiseSearchOutcome(rules=(_rule("rule:match", **{"matching.operator": "POSITIONAL"}),)),
            ]
        )

        async def evaluate(rules: Sequence[Any], _evidence: Sequence[Any]) -> PremiseEvaluation:
            return PremiseEvaluation(missing_premises=_missing_from_rules(rules, MISSING))

        request = PremiseClosureRequest(
            original_query="q", missing_premises=MISSING, rounds_left=1
        )
        result = await run_premise_closure(request, search=search, evaluate=evaluate)
        assert result.termination == TERMINATION_BUDGET_EXHAUSTED
        assert result.total_information_gain == 1
        assert result.missing_after

    @pytest.mark.asyncio
    async def test_compilation_gap_reported_when_evidence_covers_premise(self) -> None:
        # La evidencia define el símbolo, pero ninguna regla lo representa:
        # COMPILATION_GAP, jamás una respuesta inventada.
        search = _FakeSearch(
            rounds=[
                PremiseSearchOutcome(
                    evidence=(
                        _hit(
                            "ev:symbol",
                            'An "&" can be used to indicate a number or alpha in a specific position.',
                            document_id="doc-1",
                            page=4,
                        ),
                    )
                ),
            ]
        )

        async def evaluate(_rules: Sequence[Any], _evidence: Sequence[Any]) -> PremiseEvaluation:
            return PremiseEvaluation(missing_premises=(f"{PREMISE_SYMBOL_PREFIX}&",))

        request = PremiseClosureRequest(
            original_query="q",
            missing_premises=(f"{PREMISE_SYMBOL_PREFIX}&",),
            rounds_left=2,
        )
        result = await run_premise_closure(request, search=search, evaluate=evaluate)
        assert result.termination == TERMINATION_NO_INFORMATION_GAIN
        assert result.compilation_gaps
        gap = result.compilation_gaps[0]
        assert gap.premise == f"{PREMISE_SYMBOL_PREFIX}&"
        assert gap.expected_semantic_dimension == "matching.symbol.&"
        assert gap.document_id == "doc-1"
        assert result.feedback and result.feedback[0].frequency >= 1

    @pytest.mark.asyncio
    async def test_graph_expansion_closes_premise_without_global_search(self) -> None:
        search = _FakeSearch(
            rounds=[
                PremiseSearchOutcome(
                    rules=(_rule("rule:seed", **{"matching.symbol.&": "alphanumeric"}),)
                )
            ]
        )
        neighbor = _rule("rule:neighbor", **{"matching.operator": "POSITIONAL"})
        premises = (f"{PREMISE_SYMBOL_PREFIX}&", PREMISE_MATCHING_POSITIONAL)

        async def expand(_rules: Sequence[Any], _request: PremiseClosureRequest) -> list[Any]:
            return [neighbor]

        async def evaluate(rules: Sequence[Any], _evidence: Sequence[Any]) -> PremiseEvaluation:
            return PremiseEvaluation(missing_premises=_missing_from_rules(rules, premises))

        request = PremiseClosureRequest(
            original_query="q",
            missing_premises=premises,
            rounds_left=1,
        )
        result = await run_premise_closure(
            request, search=search, evaluate=evaluate, expand=expand
        )
        assert result.termination == TERMINATION_SATISFIED
        assert any("rule:neighbor" in round_.new_rule_ids for round_ in result.rounds)

    @pytest.mark.asyncio
    async def test_source_local_focus_after_exact_symbol_hit(self) -> None:
        search = _FakeSearch(
            rounds=[
                PremiseSearchOutcome(
                    rules=(_rule("rule:sym", **{"matching.symbol.&": "alphanumeric"}),),
                    evidence=(
                        _hit(
                            "ev:symbol",
                            'The "&" indicates a match to any alphanumeric character in that position.',
                            document_id="doc-7",
                            section_path=("Matching",),
                        ),
                    ),
                    exact_symbol_hits=("&",),
                ),
                PremiseSearchOutcome(),
            ]
        )

        async def evaluate(rules: Sequence[Any], _evidence: Sequence[Any]) -> PremiseEvaluation:
            return PremiseEvaluation(missing_premises=_missing_from_rules(rules, MISSING))

        request = PremiseClosureRequest(
            original_query="q", missing_premises=MISSING, rounds_left=2
        )
        await run_premise_closure(request, search=search, evaluate=evaluate)
        assert len(search.calls) >= 2
        focus = search.calls[1]["focus"]
        assert focus is not None
        assert focus.document_id == "doc-7"
        assert "doc-7" in focus.document_ids
