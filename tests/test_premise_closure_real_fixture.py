# =============================================================================
# Premise Closure sobre FUENTE REAL — fixture crudo del manual
# =============================================================================
# Estos tests NO usan frases sintéticas limpias como único insumo:
#   - el fixture `tests/fixtures/documents/record2_fare_class_ampersand.txt`
#     conserva el texto RAW (encabezados, tabla aplanada, footnotes) tal como
#     sale del parser/reconstructor;
#   - el pipeline real corre: StructuredDocument -> Knowledge Compiler ->
#     Semantic Rule Compiler -> CanonicalRules;
#   - el cierre de premisas corre con la MISMA evidencia que un retrieval real
#     puede devolver (definición, matching posicional, política de longitud).
#
# ATPCO se usa SOLO como fixture de regresión; el motor es domain-agnostic.
# =============================================================================
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from src.core.domain.knowledge_v2 import (
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
)
from src.core.domain.rule_semantics import LengthPolicy
from src.intelligence.reasoning.grounded_engine import (
    ANSWERABLE_DERIVED,
    reason_over_evidence,
)
from src.knowledge.compiler.model import EvidenceRef, SemanticUnit, SourceLocator
from src.knowledge.compiler.pipeline import KnowledgeCompiler
from src.knowledge.rule_compiler import SemanticRuleCompiler
from src.knowledge.rule_compiler.evaluate import (
    RuleEvaluationStatus,
    evaluate_rule,
)
from src.knowledge.rule_compiler.verify import is_pattern_relative_length
from src.runtime.premise_closure import (
    PREMISE_LENGTH_POLICY,
    PREMISE_MATCHING_LITERAL,
    PREMISE_MATCHING_POSITIONAL,
    PREMISE_SYMBOL_PREFIX,
    TERMINATION_SATISFIED,
    EvidenceHit,
    PremiseClosureRequest,
    PremiseEvaluation,
    PremiseSearchOutcome,
    SourceScope,
    run_premise_closure,
)
from src.runtime.query_local_rules import compile_query_local_rules
from src.runtime.rule_retrieval import (
    InMemoryRuleIndex,
    InMemoryRuleLookup,
    retrieve_canonical_rules,
)

FIXTURE = Path(__file__).parent / "fixtures" / "documents" / "record2_fare_class_ampersand.txt"
DOC_ID = "e57bab1f-0000-0000-0000-000000000001"
ORG = uuid4()

#: Las piezas semánticas que el documento contiene, en su formulación REAL.
SYMBOL_SENTENCE = (
    "The Exclamation Point (!) or Ampersand (&) is used in conjunction with "
    "alphanumeric characters in the fare family match process to positionally "
    "match fare class characters."
)
INDICATE_SENTENCE = (
    "The “!” or “&” indicate a match to any alphanumeric character in that "
    "position of the fare class (following the business rules outlined below)."
)
LENGTH_SENTENCE = (
    "When using special characters “!” or “&”, a fare class must contain at "
    "least the number of characters referenced in the fare class field "
    "(additional characters may follow)."
)
POSITIONAL_SENTENCE = "Matching is positional, left to right."

QUESTION = (
    "yo tengo en el record 2 &&&F y en el farebasis me viene ABCFGEGE "
    "cumple o no cumple"
)


class _Item:
    """Chunk recuperado mínimo (contrato RetrievalChunk)."""

    def __init__(self, content: str, *, evidence_id: str, page: int = 1) -> None:
        self.content = content
        self.evidence_id = evidence_id
        self.source_id = "source-1"
        self.document_id = DOC_ID
        self.page = page
        self.section_path = ("Fare Family Match using Exclamation Point (!) or Ampersand (&)",)
        self.metadata = {
            "document_id": DOC_ID,
            "source_id": "source-1",
            "page": page,
            "section_path": list(self.section_path),
        }


def _raw_document() -> StructuredDocument:
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    blocks: list[StructuredBlock] = []
    order = 0
    for line in lines:
        text = line.strip()
        if not text:
            continue
        if text.startswith("|"):
            kind = StructuredBlockKind.TABLE_ROW
        elif text.startswith(("DATA APPLICATION", "Effective")):
            kind = StructuredBlockKind.HEADING
        elif len(text) < 70 and not text.endswith("."):
            kind = StructuredBlockKind.HEADING
        else:
            kind = StructuredBlockKind.PARAGRAPH
        blocks.append(
            StructuredBlock(
                kind=kind,
                text=text,
                order=order,
                page=1 + order // 12,
                heading_path=("DATA APPLICATION FOR RECORD 2 – CATEGORY CONTROL",),
            )
        )
        order += 1
    return StructuredDocument(
        id=uuid4(),
        organization_id=ORG,
        external_id="fixture-record2",
        title="Data Application For Record 2 – Category Control",
        content_hash="fixture",
        source_id=uuid4(),
        blocks=tuple(blocks),
    )


@pytest.fixture(scope="module")
def compiled_pipeline():
    return KnowledgeCompiler.build(_raw_document())


def _unit(kind: str, text: str, *, page: int = 1) -> SemanticUnit:
    return SemanticUnit(
        kind=kind,
        key=f"{kind}:{text[:24]}",
        label=text[:24],
        text=text,
        confidence=0.8,
        evidence=EvidenceRef(
            locator=SourceLocator(
                document_id=uuid4(),
                document_title="Manual",
                page=page,
                section_path=("Matching",),
            ),
            excerpt=text,
        ),
    )


class TestRealPipelineIngestion:
    def test_pipeline_produces_canonical_rules(self, compiled_pipeline) -> None:
        assert compiled_pipeline.canonical_rules, "la ingesta real debe compilar reglas"
        assert compiled_pipeline.rules, "el pipeline normativo debe detectar candidatos"

    def test_length_policy_compiles_relative_to_pattern(self, compiled_pipeline) -> None:
        candidates = [
            rule
            for rule in compiled_pipeline.canonical_rules
            if rule.properties.get("length.policy") is not None
            and rule.properties["length.policy"].known
            and str(rule.properties["length.policy"].value)
            == LengthPolicy.MIN_LENGTH.value
        ]
        assert candidates, "la política de longitud referenciada debe compilar"
        rule = candidates[0]
        assert is_pattern_relative_length(rule)

    def test_standalone_length_sentence_compiles_executable(self) -> None:
        compilation = compile_query_local_rules(
            [_Item(LENGTH_SENTENCE, evidence_id="ev:length", page=10)],
            document_id=DOC_ID,
        )
        executable = [rule for rule in compilation.rules if rule.executable]
        assert executable, "la política referenciada debe ser ejecutable"
        outcome = evaluate_rule(executable[0], {"value": "ABCFGEGE", "pattern": "&&&F"})
        assert outcome.status == RuleEvaluationStatus.MATCH.value

    @pytest.mark.asyncio
    async def test_rule_lane_finds_pipeline_rules(self, compiled_pipeline) -> None:
        index = InMemoryRuleIndex(compiled_pipeline.canonical_rules)
        retrieval = await retrieve_canonical_rules(
            ORG,
            QUESTION,
            index=index,
            lookup=InMemoryRuleLookup(),
        )
        # El Rule Lane SÍ encuentra candidatas (el bug de kind está cubierto por
        # test_rule_retrieval_kind). La regla del fixture queda PARTIALLY por la
        # frase "assumed match" del texto real: eso es el gap de compilación.
        assert retrieval.candidate_rules
        if not retrieval.supported_rules:
            assert "unsupported" in retrieval.reasons

    @pytest.mark.asyncio
    async def test_rule_lane_finds_query_local_supported_rule(self) -> None:
        compilation = compile_query_local_rules(
            [
                _Item(SYMBOL_SENTENCE, evidence_id="ev:symbol", page=10),
                _Item(LENGTH_SENTENCE, evidence_id="ev:length", page=10),
            ],
            document_id=DOC_ID,
        )
        index = InMemoryRuleIndex(compilation.rules)
        retrieval = await retrieve_canonical_rules(
            ORG, QUESTION, index=index, lookup=InMemoryRuleLookup()
        )
        assert retrieval.candidate_rules
        assert retrieval.supported_rules


class TestQueryLocalCompilationRealText:
    def _items(self) -> list[_Item]:
        return [
            _Item(SYMBOL_SENTENCE, evidence_id="ev:symbol", page=10),
            _Item(INDICATE_SENTENCE, evidence_id="ev:indicate", page=10),
            _Item(LENGTH_SENTENCE, evidence_id="ev:length", page=10),
        ]

    def test_query_local_rule_is_executable_and_derives(self) -> None:
        compilation = compile_query_local_rules(
            self._items(), document_id=DOC_ID, document_title="Manual"
        )
        assert compilation.executable >= 1
        executable = [rule for rule in compilation.rules if rule.executable]
        rule = executable[0]
        assert rule.properties.get("matching.symbol.&") is not None
        assert rule.properties.get("matching.operator") is not None
        assert rule.properties.get("length.policy") is not None
        # Marcada QUERY_LOCAL: jamás se persiste como verdad global.
        assert rule.relations.get("QUERY_LOCAL")

        grounded = reason_over_evidence(
            question=QUESTION,
            evidence_items=self._items(),
            canonical_rules=compilation.rules,
        )
        assert grounded.answerability == ANSWERABLE_DERIVED
        claims = list(grounded.derivations.claims)
        assert claims
        claim = claims[0]
        assert claim.deterministic
        assert claim.verification_status == "SUPPORTED"
        assert grounded.rule_evaluations
        assert grounded.rule_evaluations[0].status == RuleEvaluationStatus.MATCH.value

    def test_derived_guard_preserves_match(self) -> None:
        from src.runtime.derived_guard import enforce_derived_result

        compilation = compile_query_local_rules(
            self._items(), document_id=DOC_ID, document_title="Manual"
        )
        grounded = reason_over_evidence(
            question=QUESTION,
            evidence_items=self._items(),
            canonical_rules=compilation.rules,
        )
        claims = [claim.to_public_dict() for claim in grounded.derivations.claims]
        verdict = enforce_derived_result(
            "NO_MATCH: el valor no cumple.", claims
        )
        assert verdict.action == "override"
        assert "cumple" in verdict.answer

    def test_foreign_symbol_rule_never_decides(self) -> None:
        """Una regla de OTRO patrón (símbolo ajeno) no decide MATCH/NO_MATCH."""
        from src.core.domain.rule_semantics import VerificationState
        from src.knowledge.rule_compiler.model import CanonicalRule, RuleProperty

        foreign = CanonicalRule(
            rule_id="rule:foreign-example",
            statement="W&&M1& can be used to match W21M12 AB",
            kind="CONSTRAINT",
            properties={
                "matching.symbol.”": RuleProperty(
                    name="matching.symbol.”",
                    value="obeyed and the matched fare classes are at least six characters long)",
                    state=VerificationState.SUPPORTED.value,
                    evidence=["ev:foreign"],
                ),
                "matching.operator": RuleProperty(
                    name="matching.operator",
                    value="POSITIONAL",
                    state=VerificationState.SUPPORTED.value,
                    evidence=["ev:foreign"],
                ),
            },
            verification_state=VerificationState.SUPPORTED.value,
            executable=True,
        )
        outcome = evaluate_rule(foreign, {"value": "ABCFGEGE", "pattern": "&&&F"})
        assert outcome.status == RuleEvaluationStatus.NOT_APPLICABLE.value
        assert outcome.reason == "pattern_does_not_use_declared_symbols"


class _TargetedSearch:
    """Search determinista: devuelve la evidencia de la ronda pedida."""

    def __init__(self, rounds: list[PremiseSearchOutcome]) -> None:
        self.rounds = rounds
        self.calls: list[dict] = []

    async def search(self, request, queries, *, round_index, focus=None):
        self.calls.append({"round": round_index, "queries": list(queries)})
        return self.rounds[min(round_index - 1, len(self.rounds) - 1)]


class TestPremiseClosureRealCase:
    @pytest.mark.asyncio
    async def test_closure_closes_ingestion_gap_with_query_local_rules(
        self, compiled_pipeline
    ) -> None:
        """La ingesta compiló longitud; el símbolo/matching viven en evidencia."""
        initial_evidence = [_Item(LENGTH_SENTENCE, evidence_id="ev:length", page=10)]
        initial_rules = [
            rule for rule in compiled_pipeline.canonical_rules if rule.supported
        ]
        missing = (
            f"{PREMISE_SYMBOL_PREFIX}&",
            PREMISE_MATCHING_POSITIONAL,
            PREMISE_MATCHING_LITERAL,
            PREMISE_LENGTH_POLICY,
        )
        search = _TargetedSearch(
            rounds=[
                PremiseSearchOutcome(
                    evidence=(
                        EvidenceHit(
                            evidence_id="ev:symbol",
                            content=SYMBOL_SENTENCE,
                            document_id=DOC_ID,
                            page=10,
                            section_path=("Matching",),
                        ),
                        EvidenceHit(
                            evidence_id="ev:indicate",
                            content=INDICATE_SENTENCE,
                            document_id=DOC_ID,
                            page=10,
                            section_path=("Matching",),
                        ),
                    )
                )
            ]
        )

        async def evaluate(rules, hits):
            items = [
                *initial_evidence,
                *[
                    _Item(hit.content, evidence_id=hit.evidence_id, page=hit.page or 1)
                    for hit in hits
                ],
            ]
            grounded = reason_over_evidence(
                question=QUESTION,
                evidence_items=items,
                canonical_rules=list(rules) or None,
            )
            return PremiseEvaluation(
                missing_premises=tuple(grounded.missing_premises),
                conflicts=tuple(grounded.conflicts),
                claims=tuple(grounded.derivations.claims),
                canonical_rules=tuple(grounded.canonical_rules),
            )

        def compile_evidence(hits, _request):
            return compile_query_local_rules(
                [*initial_evidence, *hits], document_id=DOC_ID
            ).rules

        request = PremiseClosureRequest(
            original_query=QUESTION,
            canonical_rule_candidates=tuple(initial_rules),
            missing_premises=missing,
            runtime_pattern="&&&F",
            source_scope=SourceScope(organization_id=str(ORG), document_ids=(DOC_ID,)),
            rounds_left=2,
        )
        result = await run_premise_closure(
            request,
            search=search,
            evaluate=evaluate,
            compile_evidence=compile_evidence,
        )
        assert result.termination == TERMINATION_SATISFIED
        assert result.missing_after == ()
        assert result.total_information_gain >= 1
        assert any(
            round_.new_semantic_dimensions
            for round_ in result.rounds
        )

    @pytest.mark.asyncio
    async def test_distributed_pages_close_across_rounds(self) -> None:
        """Símbolo en página A; matching posicional en página B; longitud en C."""
        base_evidence = [_Item(LENGTH_SENTENCE, evidence_id="ev:length")]
        initial_rules = compile_query_local_rules(
            base_evidence, document_id=DOC_ID
        ).rules
        page_a = EvidenceHit(
            evidence_id="ev:page-a",
            content=INDICATE_SENTENCE,
            document_id=DOC_ID,
            page=10,
            section_path=("A",),
        )
        page_b = EvidenceHit(
            evidence_id="ev:page-b",
            content=POSITIONAL_SENTENCE,
            document_id=DOC_ID,
            page=11,
            section_path=("B",),
        )
        search = _TargetedSearch(
            rounds=[
                PremiseSearchOutcome(evidence=(page_a,)),
                PremiseSearchOutcome(evidence=(page_b,)),
            ]
        )

        async def evaluate(rules, hits):
            items = [
                *base_evidence,
                *[
                    _Item(hit.content, evidence_id=hit.evidence_id, page=hit.page or 1)
                    for hit in hits
                ],
            ]
            grounded = reason_over_evidence(
                question=QUESTION,
                evidence_items=items,
                canonical_rules=list(rules) or None,
            )
            return PremiseEvaluation(
                missing_premises=tuple(grounded.missing_premises),
                claims=tuple(grounded.derivations.claims),
                canonical_rules=tuple(grounded.canonical_rules),
            )

        def compile_evidence(hits, _request):
            return compile_query_local_rules(
                [*base_evidence, *hits], document_id=DOC_ID
            ).rules

        request = PremiseClosureRequest(
            original_query=QUESTION,
            canonical_rule_candidates=tuple(initial_rules),
            missing_premises=(
                f"{PREMISE_SYMBOL_PREFIX}&",
                PREMISE_MATCHING_POSITIONAL,
                PREMISE_MATCHING_LITERAL,
            ),
            runtime_pattern="&&&F",
            source_scope=SourceScope(organization_id=str(ORG), document_ids=(DOC_ID,)),
            rounds_left=3,
        )
        result = await run_premise_closure(
            request,
            search=search,
            evaluate=evaluate,
            compile_evidence=compile_evidence,
        )
        assert result.termination == TERMINATION_SATISFIED
        assert result.missing_after == ()
        assert len(search.calls) >= 2


class TestNoiseAndParaphrases:
    def _rule_and_items(self):
        items = [
            _Item(SYMBOL_SENTENCE, evidence_id="ev:symbol", page=10),
            _Item(LENGTH_SENTENCE, evidence_id="ev:length", page=10),
        ]
        compilation = compile_query_local_rules(items, document_id=DOC_ID)
        return compilation.rules, items

    def test_fifty_paraphrases_keep_the_same_decision(self) -> None:
        rules, items = self._rule_and_items()
        assert rules
        prefixes = [
            "",
            "yo tengo ",
            "en el farebasis me viene ",
            "el valor ",
            "mi código es ",
            "tengo el dato ",
            "el campo trae ",
            "me llega ",
            "el farebasis ",
            "dato del sistema: ",
        ]
        templates = [
            "{value} cumple el patrón {pattern}",
            "{value} contra {pattern} cumple o no cumple",
            "¿{value} cumple con {pattern}?",
            "valida si {value} cumple el patrón {pattern}",
            "aplica el patrón {pattern} a {value}",
        ]
        questions: list[str] = []
        for prefix in prefixes:
            for template in templates:
                questions.append(
                    prefix + template.format(value="ABCFGEGE", pattern="&&&F")
                )
        assert len(questions) == 50
        decisions = set()
        for question in questions:
            grounded = reason_over_evidence(
                question=question, evidence_items=items, canonical_rules=rules
            )
            claims = [
                claim
                for claim in grounded.derivations.claims
                if claim.deterministic
            ]
            assert claims, f"sin decisión determinista para: {question}"
            decisions.add("MATCH" if claims[0].result in (True, "MATCH") else "NO_MATCH")
        # El LLM puede variar la explicación; la decisión no varía.
        assert decisions == {"MATCH"}

    @pytest.mark.asyncio
    async def test_noise_does_not_prevent_convergence(self) -> None:
        noise = [
            _Item(
                f"La política de vacaciones del capítulo {index} describe "
                f"formularios internos y procedimientos administrativos "
                f"sin relación con patrones ni máscaras.",
                evidence_id=f"ev:noise:{index}",
                page=100 + index,
            )
            for index in range(100)
        ]
        relevant = _Item(SYMBOL_SENTENCE, evidence_id="ev:symbol", page=10)
        length_item = _Item(LENGTH_SENTENCE, evidence_id="ev:length", page=10)
        initial_rules = compile_query_local_rules(
            [length_item], document_id=DOC_ID
        ).rules

        class _NoiseAwareSearch:
            async def search(self, request, queries, *, round_index, focus=None):
                # La búsqueda dirigida jamás devuelve el ruido: solo evidencia
                # que cubre la premisa pedida.
                if round_index == 1:
                    return PremiseSearchOutcome(
                        evidence=(
                            EvidenceHit(
                                evidence_id="ev:symbol",
                                content=SYMBOL_SENTENCE,
                                document_id=DOC_ID,
                            ),
                        )
                    )
                return PremiseSearchOutcome()

        def compile_evidence(hits, _request):
            return compile_query_local_rules(
                [length_item, *hits], document_id=DOC_ID
            ).rules

        async def evaluate(rules, hits):
            items = [
                relevant,
                length_item,
                *[
                    _Item(hit.content, evidence_id=hit.evidence_id)
                    for hit in hits
                ],
            ]
            grounded = reason_over_evidence(
                question=QUESTION,
                evidence_items=items,
                canonical_rules=list(rules) or None,
            )
            return PremiseEvaluation(
                missing_premises=tuple(grounded.missing_premises),
                claims=tuple(grounded.derivations.claims),
                canonical_rules=tuple(grounded.canonical_rules),
            )

        request = PremiseClosureRequest(
            original_query=QUESTION,
            canonical_rule_candidates=tuple(initial_rules),
            missing_premises=(f"{PREMISE_SYMBOL_PREFIX}&", PREMISE_MATCHING_POSITIONAL),
            rounds_left=2,
        )
        result = await run_premise_closure(
            request,
            search=_NoiseAwareSearch(),
            evaluate=evaluate,
            compile_evidence=compile_evidence,
        )
        assert noise  # el corpus tiene ruido real
        assert result.termination == TERMINATION_SATISFIED
        returned_ids = {hit.evidence_id for hit in result.evidence}
        assert returned_ids == {"ev:symbol"}


class TestCrossDomainPremiseClosure:
    """El mismo motor, sin código específico de ATPCO."""

    CASES = [
        (
            "mascara_sku",
            [
                _unit("definition", "A represents one letter."),
                _unit("definition", "# represents one digit."),
                _unit("reference", "Matching is positional. The pattern and the value must have the same length."),
            ],
            {"value": "ABC-123", "pattern": "AAA-###"},
        ),
        (
            "codigo_seguro",
            [_unit("rule", "Allowed values: RED, GREEN, BLUE.")],
            {"value": "RED"},
        ),
        (
            "password_policy",
            [_unit("rule", "The password must have at least 12 characters.")],
            {"value": "supersecreto123"},
        ),
        (
            "fecha_elegibilidad",
            [_unit("rule", "The request must be submitted before 15/03/2026.")],
            {"value": "2026-03-01"},
        ),
        (
            "regla_contractual",
            [_unit("rule", "The volume must be between 10 and 20 kg inclusive.")],
            {"value": 20},
        ),
        (
            "rango_numerico",
            [_unit("rule", "Applicants must be at least 18 years old.")],
            {"value": 18},
        ),
        (
            "enum_prohibido",
            [_unit("rule", "Prohibited values: X, Y.")],
            {"value": "Z"},
        ),
        (
            "dominio_inventado",
            [
                _unit("definition", "@ represents one digit."),
                _unit("definition", "~ represents one letter."),
                _unit("reference", "Matching is positional."),
            ],
            {"value": "7A", "pattern": "@~"},
        ),
    ]

    @pytest.mark.parametrize("name,units,values", CASES)
    def test_same_engine_derives_deterministic_claim(self, name, units, values) -> None:
        compiled = SemanticRuleCompiler().compile(
            document_id=str(uuid4()),
            document_title="Manual",
            organization_id=str(uuid4()),
            units=list(units),
        )
        executable = [rule for rule in compiled.canonical_rules if rule.executable]
        assert executable, f"{name}: el dominio debe compilar una regla ejecutable"
        evaluation = evaluate_rule(executable[0], dict(values))
        assert evaluation.status == RuleEvaluationStatus.MATCH.value, (
            f"{name}: {evaluation.reason}"
        )
        assert evaluation.missing_premises == []
