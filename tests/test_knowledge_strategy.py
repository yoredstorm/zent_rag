# =============================================================================
# Knowledge Strategy — representaciones declaradas + scope, trazables.
# =============================================================================
from __future__ import annotations

import json

from src.rag.retrieval.planner import build_retrieval_plan
from src.runtime.knowledge_strategy import build_knowledge_strategy


def test_estrategia_declara_representaciones_con_razones() -> None:
    strategy = build_knowledge_strategy(
        build_retrieval_plan("¿Qué significa el Byte 105 de Category 31?"),
        organization_id="org-1",
        workspace_id="ws-1",
        role="admin",
    )
    assert strategy.primary == "exact"
    assert strategy.includes("vector")
    assert strategy.includes("exact")
    assert strategy.includes("graph")
    payload = strategy.to_public_dict()
    assert payload["scope"] == {
        "organization_id": "org-1",
        "workspace_id": "ws-1",
        "role": "admin",
    }
    assert all(item["reason"] for item in payload["representations"])
    assert json.loads(json.dumps(payload)) == payload


def test_sin_plan_construye_desde_query() -> None:
    strategy = build_knowledge_strategy(query="")
    assert strategy.representations[0].representation == "vector"
    assert strategy.primary == "vector"


def test_scope_por_defecto_vacio() -> None:
    strategy = build_knowledge_strategy(query="estado de la regla 4")
    assert strategy.to_public_dict()["scope"] == {
        "organization_id": None,
        "workspace_id": None,
        "role": "",
    }
