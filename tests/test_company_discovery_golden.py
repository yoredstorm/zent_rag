# =============================================================================
# Company Discovery — Golden Set (§26)
# =============================================================================
# Preguntas empresariales reales contra el grafo demo (fixtures). Verifican
# que el compilador entregue el contexto correcto y ACOTADO: si alguien envía
# el grafo completo al runtime, estos tests fallan por presupuesto.
# =============================================================================
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from src.company.context import CompanyContextCompiler, ContextBudget
from tests.company_discovery_fixtures import (
    ORG,
    FakeAuthorityService,
    build_demo_graph,
    demo_authority_rules,
)

_GOLDEN_PATH = Path(__file__).parent / "golden" / "company_discovery.json"


def _cases() -> list[dict]:
    payload = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))
    return payload["cases"]


def _compile(case: dict):
    compiler = CompanyContextCompiler(
        build_demo_graph(),
        authority_service=FakeAuthorityService(demo_authority_rules()),
    )
    as_of = (
        datetime.fromisoformat(case["as_of"]) if case.get("as_of") else None
    )
    return compiler, as_of


@pytest.mark.parametrize("case", _cases(), ids=[c["id"] for c in _cases()])
@pytest.mark.asyncio
async def test_golden_business_question(case: dict) -> None:
    compiler, as_of = _compile(case)
    compiled = await compiler.compile(ORG, case["question"], as_of=as_of)
    expects = case["expects"]

    if "concepts_include" in expects:
        names = {item["name"] for item in compiled.concepts}
        for expected in expects["concepts_include"]:
            assert expected in names, f"{case['id']}: {expected} missing in concepts"

    if "mappings_include_field" in expects:
        fields = {item["field"] for item in compiled.mappings}
        assert expects["mappings_include_field"] in fields, (
            f"{case['id']}: mapping to {expects['mappings_include_field']} missing"
        )

    if "mapping_values_include" in expects:
        values = {value for item in compiled.mappings for value in item.get("values", [])}
        assert expects["mapping_values_include"] in values, (
            f"{case['id']}: value {expects['mapping_values_include']} missing"
        )

    if "systems_include" in expects:
        names = {item["name"] for item in compiled.systems}
        for expected in expects["systems_include"]:
            assert expected in names, f"{case['id']}: {expected} missing in systems"

    if "processes_include" in expects:
        names = {item["name"] for item in compiled.processes}
        for expected in expects["processes_include"]:
            assert expected in names, f"{case['id']}: {expected} missing in processes"

    if "rules_include" in expects:
        names = {item["name"] for item in compiled.rules}
        for expected in expects["rules_include"]:
            assert expected in names, f"{case['id']}: {expected} missing in rules"

    if "rules_exclude" in expects:
        names = {item["name"] for item in compiled.rules}
        for excluded in expects["rules_exclude"]:
            assert excluded not in names, f"{case['id']}: {excluded} should be excluded"

    if "authority_include_source" in expects:
        sources = {item["source_name"] for item in compiled.authority}
        assert expects["authority_include_source"] in sources, (
            f"{case['id']}: authority source missing"
        )
        if "authority_level" in expects:
            levels = {
                item["authority_level"]
                for item in compiled.authority
                if item["source_name"] == expects["authority_include_source"]
            }
            assert expects["authority_level"] in levels

    if "max_tokens_estimate" in expects:
        assert compiled.tokens_estimate <= expects["max_tokens_estimate"], (
            f"{case['id']}: context too large ({compiled.tokens_estimate} tokens)"
        )


@pytest.mark.asyncio
async def test_golden_set_stays_bounded() -> None:
    """Ninguna pregunta puede desbordar el presupuesto por defecto."""
    budget = ContextBudget()
    compiler = CompanyContextCompiler(
        build_demo_graph(),
        authority_service=FakeAuthorityService(demo_authority_rules()),
    )
    for case in _cases():
        as_of = datetime.fromisoformat(case["as_of"]) if case.get("as_of") else None
        compiled = await compiler.compile(ORG, case["question"], as_of=as_of)
        assert compiled.tokens_estimate <= budget.max_tokens_estimate
        assert len(compiled.concepts) <= budget.max_concepts
        assert len(compiled.mappings) <= budget.max_mappings
        assert len(compiled.processes) <= budget.max_processes
        assert len(compiled.systems) <= budget.max_systems
        assert len(compiled.rules) <= budget.max_rules
        assert len(compiled.dependencies) <= budget.max_relationships


@pytest.mark.asyncio
async def test_golden_questions_are_tenant_scoped() -> None:
    """Otra organización no recibe nada del grafo demo."""
    from uuid import uuid4

    compiler = CompanyContextCompiler(build_demo_graph())
    for case in _cases():
        compiled = await compiler.compile(uuid4(), case["question"])
        assert compiled.is_empty()
        assert compiled.tokens_estimate > 0  # presupuesto evaluado igual
