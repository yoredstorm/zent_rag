# =============================================================================
# Authorized knowledge scope — el fast path jamás amplía el scope del agente
# =============================================================================
# Escenario obligatorio:
#   Source A: permitida para el agente, sin regla relevante.
#   Source B: misma organización, NO asignada, contiene la regla relevante.
#   Fast Path NO puede decidir usando B.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.knowledge.rule_compiler.model import CanonicalRule, RuleEvidence
from src.runtime.authorized_scope import (
    MIXED_SOURCE_RULE,
    OUT_OF_SCOPE_RULE,
    RULE_PROVENANCE_UNVERIFIED,
    AuthorizedKnowledgeScope,
    classify_rule_scope,
    filter_rules_for_scope,
    rule_provenance,
    scope_from_agent_config,
)
from src.runtime.decision_envelope import build_decision_envelope
from src.runtime.fast_path import (
    OUT_OF_SCOPE_RULE as FAST_PATH_OUT_OF_SCOPE,
)
from src.runtime.fast_path import (
    SOURCE_SCOPE_UNRESOLVED,
    evaluate_deterministic_fast_path,
)

SOURCE_A = str(uuid4())
SOURCE_B = str(uuid4())
KB_A = str(uuid4())


def _rule(
    *,
    rule_id: str,
    source_id: str,
    document_id: str | None = None,
    extra_document_id: str | None = None,
) -> CanonicalRule:
    document = document_id or str(uuid4())
    provenance = [
        RuleEvidence(
            evidence_id=f"ev:{rule_id}",
            locator={
                "source_id": source_id,
                "document_id": document,
                "document_title": "manual.pdf",
                "page_start": 7,
            },
            excerpt="Matching is positional, left to right.",
        )
    ]
    if extra_document_id:
        provenance.append(
            RuleEvidence(
                evidence_id=f"ev:{rule_id}:2",
                locator={
                    "source_id": source_id,
                    "document_id": extra_document_id,
                    "document_title": "manual.pdf",
                    "page_start": 8,
                },
                excerpt="Same rule fragment from another ingestion.",
            )
        )
    return CanonicalRule(
        rule_id=rule_id,
        statement="Positional match rule",
        verification_state="SUPPORTED",
        executable=True,
        provenance=provenance,
    )


def _scope(**overrides) -> AuthorizedKnowledgeScope:
    payload = {
        "organization_id": str(uuid4()),
        "source_ids": (SOURCE_A,),
        "knowledge_base_ids": (KB_A,),
    }
    payload.update(overrides)
    return AuthorizedKnowledgeScope(**payload)


def _grounded_with_rule(rule: CanonicalRule) -> dict:
    return {
        "answerability": "ANSWERABLE_DERIVED",
        "canonical_rules_used": [rule.to_public_dict()],
        "canonical_rule_flow": [
            {
                "rule_id": rule.rule_id,
                "status": "MATCH",
                "operation": "POSITIONAL_MATCH",
                "result": True,
                "checks": [{"name": "matching", "status": "MATCH", "result": "MATCH"}],
                "missing_premises": [],
            }
        ],
        "derived_claim": {
            "deterministic": True,
            "verification_status": "SUPPORTED",
            "operation": "POSITIONAL_MATCH",
            "result": True,
            "canonical_rule_ids": [rule.rule_id],
        },
        "derivations": {
            "claims": [
                {
                    "deterministic": True,
                    "verification_status": "SUPPORTED",
                    "operation": "POSITIONAL_MATCH",
                    "result": True,
                    "canonical_rule_ids": [rule.rule_id],
                }
            ]
        },
        "semantics": {"intent": "APPLY_RULE", "runtime_inputs": [{"value": "X"}]},
        "runtime_inputs": ["pattern=&&&F", "value=ABCFGEGE"],
        "missing_premises": [],
        "conflicts": [],
    }


# ---------------------------------------------------------------------------
# Scope explícito
# ---------------------------------------------------------------------------


def test_scope_sin_config_no_es_explicito() -> None:
    scope = scope_from_agent_config(
        organization_id=uuid4(), agent_config={}, org_config={}
    )
    assert scope.is_explicit is False
    decision = evaluate_deterministic_fast_path(
        requires_deterministic=True,
        envelope={"authoritative": True, "operation": "POSITIONAL_MATCH", "result": "MATCH"},
        grounded=_grounded_with_rule(_rule(rule_id="rule:a", source_id=SOURCE_A)),
        claims=[{"deterministic": True, "verification_status": "SUPPORTED"}],
        scope_explicit=scope.is_explicit,
    )
    assert decision.eligible is False
    assert decision.reason == SOURCE_SCOPE_UNRESOLVED


def test_scope_explicito_desde_config() -> None:
    scope = scope_from_agent_config(
        organization_id=uuid4(),
        agent_config={"source_ids": [SOURCE_A], "knowledge_base_ids": [KB_A]},
        org_config={},
    )
    assert scope.is_explicit is True
    assert scope.source_ids == (SOURCE_A,)
    assert scope.knowledge_base_ids == (KB_A,)


# ---------------------------------------------------------------------------
# Source A permitida / Source B no asignada
# ---------------------------------------------------------------------------


def test_regla_de_source_b_queda_fuera_de_scope() -> None:
    scope = _scope()
    rule_b = _rule(rule_id="rule:b", source_id=SOURCE_B)
    assert classify_rule_scope(rule_b, scope) == "OUT_OF_SCOPE"
    kept, excluded = filter_rules_for_scope([rule_b], scope)
    assert kept == []
    assert excluded[0]["reason"] == OUT_OF_SCOPE_RULE


def test_regla_de_source_a_entra() -> None:
    scope = _scope()
    rule_a = _rule(rule_id="rule:a", source_id=SOURCE_A)
    kept, excluded = filter_rules_for_scope([rule_a], scope)
    assert [rule.rule_id for rule in kept] == ["rule:a"]
    assert excluded == []


def test_fast_path_no_decide_con_regla_de_b() -> None:
    scope = _scope()
    rule_b = _rule(rule_id="rule:b", source_id=SOURCE_B)
    envelope = build_decision_envelope(_grounded_with_rule(rule_b))
    decision = evaluate_deterministic_fast_path(
        requires_deterministic=True,
        envelope=envelope,
        grounded=_grounded_with_rule(rule_b),
        claims=[{"deterministic": True, "verification_status": "SUPPORTED",
                 "canonical_rule_ids": ["rule:b"]}],
        scope_explicit=True,
        out_of_scope_rule_ids=["rule:b"],
    )
    assert decision.eligible is False
    assert decision.reason == FAST_PATH_OUT_OF_SCOPE


def test_fast_path_elegible_solo_con_regla_de_a() -> None:
    scope = _scope()
    rule_a = _rule(rule_id="rule:a", source_id=SOURCE_A)
    grounded = _grounded_with_rule(rule_a)
    envelope = build_decision_envelope(grounded)
    decision = evaluate_deterministic_fast_path(
        requires_deterministic=True,
        envelope=envelope,
        grounded=grounded,
        claims=list((grounded.get("derivations") or {}).get("claims") or ()),
        scope_explicit=scope.is_explicit,
        out_of_scope_rule_ids=[],
    )
    assert decision.eligible is True


# ---------------------------------------------------------------------------
# Provenance y reingestas
# ---------------------------------------------------------------------------


def test_provenance_expone_fuente_documento_paginas() -> None:
    rule = _rule(rule_id="rule:a", source_id=SOURCE_A, document_id="doc-1")
    provenance = rule_provenance(rule)
    assert provenance["source_ids"] == (SOURCE_A,)
    assert provenance["document_ids"] == ("doc-1",)
    assert provenance["pages"] == (7,)


def test_reingestas_mezcladas_se_excluyen() -> None:
    rule = _rule(
        rule_id="rule:mixed",
        source_id=SOURCE_A,
        document_id="doc-legacy",
        extra_document_id="doc-odl",
    )
    kept, excluded = filter_rules_for_scope([rule], _scope())
    assert kept == []
    assert excluded[0]["reason"] == MIXED_SOURCE_RULE


def test_regla_sin_provenance_no_entra_con_scope_explicito() -> None:
    rule = CanonicalRule(
        rule_id="rule:no-prov",
        statement="sin provenance",
        verification_state="SUPPORTED",
        executable=True,
    )
    kept, excluded = filter_rules_for_scope([rule], _scope())
    assert kept == []
    assert excluded[0]["reason"] == RULE_PROVENANCE_UNVERIFIED


# ---------------------------------------------------------------------------
# prepare_derived_authority recibe el scope y filtra
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prepare_derived_authority_usa_scope_en_retrieval() -> None:
    from src.runtime.deterministic_authority import prepare_derived_authority
    from src.runtime.rule_retrieval import RuleRetrievalResult

    captured: dict = {}
    rule_b = _rule(rule_id="rule:b", source_id=SOURCE_B)

    async def fake_retrieve(organization_id, question, evidence_items=(), **kwargs):
        captured.update(kwargs)
        return RuleRetrievalResult(
            strategy="canonical_first",
            supported_rules=[rule_b],
            candidate_rules=[rule_b],
        )

    prep = await prepare_derived_authority(
        organization_id=uuid4(),
        question="¿ABCFGEGE cumple &&&F?",
        retrieval_fn=fake_retrieve,
        authorized_scope=_scope(),
    )

    assert captured.get("source_ids")
    assert str(captured["source_ids"][0]) == SOURCE_A
    assert [item["rule_id"] for item in prep.scope_excluded_rules] == ["rule:b"]
    assert prep.scope_excluded_rules[0]["reason"] == OUT_OF_SCOPE_RULE
    scope_step = next(
        (step for step in prep.steps if step.get("type") == "scope_filter"), None
    )
    assert scope_step is not None
    assert scope_step["excluded"] == 1


# ---------------------------------------------------------------------------
# Premise retriever: strict scope no cae a la organización
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_premise_retriever_strict_no_busca_fuera_del_scope() -> None:
    from src.runtime.premise_closure import SourceScope
    from src.runtime.premise_retriever import PremiseEvidenceRetriever

    class _Context:
        chunks: list = []

    class _Store:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def scan_text_literal(self, organization_id, needles, **kwargs):
            self.calls.append({"scanner": "literal", **kwargs})
            return _Context()

        async def scan_text(self, organization_id, needles, **kwargs):
            self.calls.append({"scanner": "text", **kwargs})
            return _Context()

    store = _Store()
    adapter = PremiseEvidenceRetriever(
        organization_id=uuid4(),
        vector_store=store,
        source_ids=[SOURCE_A],
        knowledge_base_ids=[KB_A],
        strict_scope=True,
    )
    hits = await adapter.search(
        'the symbol & represents one alphanumeric position',
        SourceScope(organization_id="org"),
        limit=4,
    )
    assert hits == []
    # Todas las llamadas llevan el scope autorizado; ninguna sin filtro.
    assert store.calls
    for call in store.calls:
        assert call.get("source_ids") == [UUID(SOURCE_A)]
        assert call.get("knowledge_base_id") == UUID(KB_A)


@pytest.mark.asyncio
async def test_premise_retriever_no_strict_conserva_fallback() -> None:
    from src.runtime.premise_closure import SourceScope
    from src.runtime.premise_retriever import PremiseEvidenceRetriever

    class _Context:
        chunks: list = []

    class _Store:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def scan_text_literal(self, organization_id, needles, **kwargs):
            self.calls.append(kwargs)
            return _Context()

        async def scan_text(self, organization_id, needles, **kwargs):
            self.calls.append(kwargs)
            return _Context()

    store = _Store()
    adapter = PremiseEvidenceRetriever(
        organization_id=uuid4(), vector_store=store, strict_scope=False
    )
    await adapter.search("matching positional", SourceScope(organization_id="org"), limit=2)
    assert any(not call.get("source_ids") for call in store.calls)
