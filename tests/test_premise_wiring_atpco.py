# =============================================================================
# Premise wiring ATPCO — regresión del cableado RequirementGraph -> Decision
# =============================================================================
# Criterio de éxito (§22): PDF contiene evidencia -> retrieval la recupera ->
# RequirementGraph cierra premisas -> Rule Compiler ensambla CanonicalRule ->
# executable=true -> RuleEvaluation -> DerivedClaim deterministic=true ->
# DecisionEnvelope authoritative=true -> respuesta = DerivedClaim.
#
# ATPCO se usa SOLO como fixture de regresión; el motor es domain-agnostic.
# =============================================================================
from __future__ import annotations

import ast
import html
import random
from pathlib import Path
from uuid import uuid4

import pytest

from src.intelligence.query_semantics import classify_query_semantics
from src.intelligence.reasoning.grounded_engine import reason_over_evidence
from src.knowledge.rule_compiler.evaluate import (
    RuleEvaluationStatus,
    evaluate_rule,
)
from src.runtime.deterministic_authority import prepare_derived_authority
from src.runtime.premise_closure import (
    PREMISE_LENGTH_POLICY,
    PREMISE_MATCHING_POSITIONAL,
    PREMISE_SYMBOL_PREFIX,
    EvidenceHit,
    PremiseClosureRequest,
    PremiseEvaluation,
    PremiseSearchOutcome,
    SourceScope,
    run_premise_closure,
)
from src.runtime.premise_retriever import (
    PremiseEvidenceRetriever,
    build_premise_evidence_search,
    exact_needles,
)
from src.runtime.query_local_rules import compile_query_local_rules

REPO = Path(__file__).resolve().parents[1]
DOC_ID = "e57bab1f-0000-0000-0000-000000000001"
ORG = uuid4()

QUESTION_HTML = (
    "yo tengo en el record 2 &amp;&amp;&amp;F y en el farebasis me viene "
    "ABCFGEGE cumple o no cumple"
)
QUESTION = html.unescape(QUESTION_HTML)

#: Párrafo único real de OpenDataLoader: símbolo + matching + length policy
#: en UN solo bloque. NO se divide manualmente para el compiler.
ODL_PARAGRAPH = (
    "The ! or & indicate a match to any alphanumeric character in that position of "
    "the fare class. When using special characters ! or &, a fare class must contain "
    "at least the number of characters referenced in the fare class field (additional "
    "characters may follow). An & can be used to indicate a number or alpha in a "
    "specific position of the fare class."
)
SYMBOL_ONLY = (
    "The ! or & indicate a match to any alphanumeric character in that position of "
    "the fare class."
)
LENGTH_ONLY = (
    "When using special characters ! or &, a fare class must contain at least the "
    "number of characters referenced in the fare class field (additional characters "
    "may follow)."
)
POSITIONAL_ONLY = "An & can be used to indicate a number or alpha in a specific position of the fare class."
CONFLICTING_LENGTH = (
    "A fare class must contain exactly four characters, no additional characters may follow."
)
LENGTH_NO_SYMBOL = (
    "A fare class must contain at least the number of characters referenced in the "
    "field (additional characters may follow)."
)
NOISE = (
    "Este párrafo habla de facturación, inventario y logística sin relación con "
    "patrones de fare class ni símbolos."
)


class _Item:
    """Chunk recuperado mínimo (contrato RetrievalChunk)."""

    def __init__(
        self,
        content: str,
        *,
        evidence_id: str,
        page: int = 1,
        document_id: str = DOC_ID,
    ) -> None:
        self.content = content
        self.evidence_id = evidence_id
        self.source_id = "source-1"
        self.document_id = document_id
        self.page = page
        self.section_path = ("Fare Family Match",)
        self.metadata = {
            "document_id": document_id,
            "source_id": "source-1",
            "page": page,
            "section_path": list(self.section_path),
            "chunk_id": evidence_id,
        }


def _item(content: str, evidence_id: str) -> _Item:
    return _Item(content, evidence_id=evidence_id)


@pytest.fixture
def offline_db(monkeypatch):
    """Sin Postgres: rule index vacío y expanders noop (igual que prod fail-soft)."""
    from src.runtime import premise_search as ps
    from src.runtime import rule_retrieval as rr

    async def _empty_search(self, request):
        return []

    async def _noop_expander(rules, request):
        return []

    monkeypatch.setattr(rr.PostgresRuleIndex, "search", _empty_search)
    monkeypatch.setattr(ps, "load_document_rules", lambda *a, **k: [])
    monkeypatch.setattr(
        ps, "make_source_local_expander", lambda *a, **k: _noop_expander
    )
    monkeypatch.setattr(ps, "make_fabric_expander", lambda *a, **k: _noop_expander)
    return True


# ---------------------------------------------------------------------------
# A. Production wiring guard
# ---------------------------------------------------------------------------


def _prepare_calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.id
            if isinstance(func, ast.Name)
            else func.attr
            if isinstance(func, ast.Attribute)
            else ""
        )
        if name == "prepare_derived_authority":
            calls.append(node)
    return calls


def test_production_callers_wire_premise_evidence_search() -> None:
    """Orchestrator y agent_runtime deben pasar evidence search real."""
    for relative in (
        "src/agents/runtime/orchestrator.py",
        "src/agents/runtime/agent_runtime.py",
    ):
        calls = _prepare_calls(REPO / relative)
        assert calls, f"{relative} debe llamar prepare_derived_authority"
        for call in calls:
            keywords = {kw.arg for kw in call.keywords}
            assert "enable_premise_closure" in keywords, relative
            assert "premise_evidence_search" in keywords, (
                f"{relative}: premise closure habilitada SIN evidence search real"
            )


# ---------------------------------------------------------------------------
# B. HTML escaped query
# ---------------------------------------------------------------------------


def test_html_escaped_question_normalizes_pattern_and_value() -> None:
    semantics = classify_query_semantics(QUESTION_HTML)
    patterns = [
        str(getattr(item, "value", "") or "")
        for item in (getattr(semantics, "runtime_patterns", ()) or ())
    ]
    inputs = [
        str(getattr(item, "value", "") or "")
        for item in (getattr(semantics, "runtime_inputs", ()) or ())
    ]
    assert "&&&F" in patterns, f"pattern no normalizado: {patterns}"
    assert "ABCFGEGE" in inputs, f"value no normalizado: {inputs}"


# ---------------------------------------------------------------------------
# C. Real ODL paragraph (un solo bloque, sin dividir)
# ---------------------------------------------------------------------------


def test_odl_single_paragraph_compiles_executable_rule() -> None:
    compilation = compile_query_local_rules(
        [_item(ODL_PARAGRAPH, "ev:odl")], document_id=DOC_ID
    )
    assert compilation.executable >= 1, "el párrafo ODL debe ensamblar regla ejecutable"
    executable = [rule for rule in compilation.rules if rule.executable]
    rule = executable[0]
    assert rule.properties.get("matching.symbol.&") is not None
    assert rule.properties.get("matching.operator") is not None
    assert rule.properties.get("length.policy") is not None
    outcome = evaluate_rule(rule, {"value": "ABCFGEGE", "pattern": "&&&F"})
    assert outcome.status == RuleEvaluationStatus.MATCH.value


# ---------------------------------------------------------------------------
# D. Productive path end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_productive_path_decides_match(offline_db) -> None:
    item = _item(ODL_PARAGRAPH, "ev:odl")

    async def evidence_search(query, scope, limit):
        return [item]

    prep = await prepare_derived_authority(
        organization_id=ORG,
        question=QUESTION_HTML,
        evidence_items=[item],
        enable_premise_closure=True,
        premise_evidence_search=evidence_search,
    )
    assert prep.has_authority, "el caso documentado debe decidir"
    envelope = prep.authoritative_envelope
    assert envelope is not None and envelope.authoritative
    assert envelope.normalized_result == "MATCH"
    claims = [
        claim
        for claim in (prep.derived_claims or ())
        if bool(getattr(claim, "deterministic", False))
    ]
    assert claims, "debe existir DerivedClaim deterministic"
    assert claims[0].operation == "POSITIONAL_MATCH"
    assert claims[0].verification_status == "SUPPORTED"
    state, _reason = prep.answer_state()
    assert state == "DERIVED_RESULT"


# ---------------------------------------------------------------------------
# E. Accumulative evidence between rounds (§8)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compile_evidence_receives_accumulated_hits() -> None:
    seen: list[list[str]] = []
    hits_round_1 = [
        EvidenceHit(
            evidence_id="ev:symbol",
            content=SYMBOL_ONLY,
            document_id=DOC_ID,
            page=10,
            lane="exact",
        )
    ]
    hits_round_2 = [
        EvidenceHit(
            evidence_id="ev:length",
            content=LENGTH_ONLY,
            document_id=DOC_ID,
            page=11,
            lane="canonical",
        )
    ]

    class _Search:
        async def search(self, request, queries, *, round_index, focus=None):
            return PremiseSearchOutcome(
                evidence=tuple(hits_round_1 if round_index == 1 else hits_round_2),
                queries=tuple(queries),
            )

    def evaluate(rules, hits):
        return PremiseEvaluation(
            missing_premises=(PREMISE_LENGTH_POLICY,) if len(hits) < 2 else ()
        )

    def compile_evidence(hits, _request):
        seen.append([hit.evidence_id for hit in hits])
        return compile_query_local_rules(
            [_item(SYMBOL_ONLY, "ev:symbol"), _item(LENGTH_ONLY, "ev:length")],
            document_id=DOC_ID,
        ).rules

    request = PremiseClosureRequest(
        original_query=QUESTION,
        missing_premises=(
            f"{PREMISE_SYMBOL_PREFIX}&",
            PREMISE_MATCHING_POSITIONAL,
            PREMISE_LENGTH_POLICY,
        ),
        runtime_pattern="&&&F",
        source_scope=SourceScope(organization_id=str(ORG), document_ids=(DOC_ID,)),
        rounds_left=2,
    )
    result = await run_premise_closure(
        request, search=_Search(), evaluate=evaluate, compile_evidence=compile_evidence
    )
    assert seen, "compile_evidence debe correr"
    last = seen[-1]
    assert "ev:symbol" in last and "ev:length" in last, (
        f"la compilación de la última ronda debe ver TODA la evidencia: {seen}"
    )
    assert len(result.evidence) >= 2


# ---------------------------------------------------------------------------
# F. Missing source stays UNDETERMINED (fail-closed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_symbol_source_stays_undetermined(offline_db) -> None:
    # Evidencia sin definición de símbolo NI menciones de símbolos: el motor no
    # puede inventar semántica posicional (fail-closed real).
    length_item = _item(LENGTH_NO_SYMBOL, "ev:length")

    async def evidence_search(query, scope, limit):
        return [length_item]

    prep = await prepare_derived_authority(
        organization_id=ORG,
        question=QUESTION_HTML,
        evidence_items=[length_item],
        enable_premise_closure=True,
        premise_evidence_search=evidence_search,
    )
    assert not prep.has_authority, "sin definición de símbolo NO puede decidir"
    state, _reason = prep.answer_state()
    assert state in {"UNDETERMINED_RULE", "UNANSWERABLE_MISSING_PREMISE"}


# ---------------------------------------------------------------------------
# G. Conflicting length policies
# ---------------------------------------------------------------------------


def test_conflicting_length_policies_do_not_decide() -> None:
    items = [
        _item(SYMBOL_ONLY, "ev:symbol"),
        _item(POSITIONAL_ONLY, "ev:pos"),
        _item(LENGTH_ONLY, "ev:length-a"),
        _item(CONFLICTING_LENGTH, "ev:length-b"),
    ]
    compilation = compile_query_local_rules(items, document_id=DOC_ID)
    assert compilation.executable == 0, (
        "políticas de longitud incompatibles no pueden quedar ejecutables"
    )
    assert compilation.conflicts >= 1 or not compilation.rules


# ---------------------------------------------------------------------------
# H. 100-run consistency
# ---------------------------------------------------------------------------


def test_decision_is_stable_over_100_runs() -> None:
    items = [_item(ODL_PARAGRAPH, "ev:odl")]
    compilation = compile_query_local_rules(items, document_id=DOC_ID)
    rules = [rule for rule in compilation.rules if rule.executable]
    assert rules
    signatures: set[tuple] = set()
    for run in range(100):
        shuffled = list(items)
        # Reproducibilidad determinista, no criptografía.
        random.Random(run).shuffle(shuffled)  # noqa: S311
        grounded = reason_over_evidence(
            question=QUESTION, evidence_items=shuffled, canonical_rules=rules
        )
        claims = tuple(
            sorted(
                f"{getattr(claim, 'operation', '')}:{getattr(claim, 'result', '')}"
                for claim in grounded.derivations.claims
                if getattr(claim, "deterministic", False)
            )
        )
        signatures.add((grounded.answerability, claims))
    assert len(signatures) == 1, f"decisión inestable: {signatures}"


# ---------------------------------------------------------------------------
# Adapter: scope + lanes (§4, §6)
# ---------------------------------------------------------------------------


class _Chunk:
    def __init__(self, content: str, document_id: str, chunk_id: str) -> None:
        self.content = content
        self.score = 0.9
        self.metadata = {
            "document_id": document_id,
            "source_id": "source-1",
            "chunk_id": chunk_id,
            "page": 3,
            "section_path": ["Matching"],
        }


class _FakeRetriever:
    def __init__(self, chunks):
        self.chunks = chunks
        self.queries = []

    async def retrieve(self, query, options=None):
        self.queries.append(query)
        from types import SimpleNamespace

        return SimpleNamespace(context=list(self.chunks))


class _FakeStore:
    def __init__(self, chunks):
        self.chunks = chunks

    async def scan_text_literal(self, organization_id, needles, **kwargs):
        from types import SimpleNamespace

        return SimpleNamespace(chunks=list(self.chunks))


class _FakeEmbedder:
    async def embed(self, text, model=None):
        return [0.1, 0.2]


@pytest.mark.asyncio
async def test_adapter_respects_scope_and_records_lanes() -> None:
    own = _Chunk(SYMBOL_ONLY, DOC_ID, "chunk-own")
    foreign = _Chunk(NOISE, "other-document", "chunk-foreign")
    adapter = PremiseEvidenceRetriever(
        organization_id=ORG,
        retriever=_FakeRetriever([foreign, own]),
        vector_store=_FakeStore([own]),
        embedding_provider=_FakeEmbedder(),
    )
    scope = SourceScope(organization_id=str(ORG), document_ids=(DOC_ID,))
    hits = await adapter.search("definition:symbol:& ampersand indicate", scope, 5)
    assert hits, "el adapter debe devolver evidencia del scope"
    assert all(hit.document_id == DOC_ID for hit in hits), "no debe ampliar scope"
    lanes = {hit.lane for hit in hits}
    assert "exact" in lanes
    assert adapter.last_lanes.get("exact", 0) >= 1


def test_exact_needles_keep_symbols() -> None:
    needles = exact_needles("definition:symbol:& y patrón &&&F “additional characters may follow”")
    assert "&&&F" in needles
    assert any("additional characters" in needle for needle in needles)


def test_factory_returns_none_without_deps(monkeypatch) -> None:
    import src.api.deps as deps

    monkeypatch.setattr(deps, "get_knowledge_retriever", lambda: (_ for _ in ()).throw(RuntimeError("no deps")))
    assert build_premise_evidence_search(ORG) is None
