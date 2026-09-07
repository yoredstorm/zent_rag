"""Phase 27B — Hybrid Semantic Catalog Search."""
from __future__ import annotations

from src.catalog.hybrid_search import DEFAULT_WEIGHTS, HybridCatalogSearch


def test_score_returns_hybrid_and_ranking_signals() -> None:
    search = HybridCatalogSearch()
    candidates = [
        {
            "object_id": "a",
            "name": "A1672",
            "business_name": "Sales Transaction",
            "description": "ventas",
            "business_mapping": 0.9,
            "verified_query": 0.2,
            "graph_proximity": 0.1,
            "historical_success": 0.5,
            "authority": 0.8,
            "embedding_score": 0.7,
        },
        {
            "object_id": "b",
            "name": "A9999",
            "business_name": "Inventory",
            "description": "stock",
            "business_mapping": 0.1,
            "verified_query": 0.0,
            "graph_proximity": 0.0,
            "historical_success": 0.0,
            "authority": 0.1,
            "embedding_score": 0.1,
        },
    ]
    ranked = search.score("ventas sales", candidates, signals={})
    assert len(ranked) == 2
    assert ranked[0]["object_id"] == "a"
    assert "hybrid_score" in ranked[0]
    signals = ranked[0]["ranking_signals"]
    for key in DEFAULT_WEIGHTS:
        assert key in signals
    assert ranked[0]["hybrid_score"] >= ranked[1]["hybrid_score"]


def test_configurable_weights_change_ranking() -> None:
    lexical_heavy = HybridCatalogSearch(weights={**DEFAULT_WEIGHTS, "lexical": 5.0})
    authority_heavy = HybridCatalogSearch(weights={**DEFAULT_WEIGHTS, "authority": 5.0})
    candidates = [
        {
            "object_id": "lex",
            "name": "pedido",
            "business_name": "Order",
            "description": "pedido cliente",
            "authority": 0.0,
            "embedding_score": 0.0,
        },
        {
            "object_id": "auth",
            "name": "ZZZZ",
            "business_name": "Other",
            "description": "nada",
            "authority": 1.0,
            "embedding_score": 0.0,
        },
    ]
    by_lex = lexical_heavy.score("pedido", candidates)
    by_auth = authority_heavy.score("pedido", candidates)
    assert by_lex[0]["object_id"] == "lex"
    assert by_auth[0]["object_id"] == "auth"


def test_signals_by_id_override() -> None:
    search = HybridCatalogSearch()
    candidates = [{"object_id": "x", "name": "foo", "business_name": "bar"}]
    ranked = search.score(
        "zzz",
        candidates,
        signals={"by_id": {"x": {"verified_query": 1.0, "embedding": 1.0}}},
    )
    assert ranked[0]["ranking_signals"]["verified_query"] == 1.0
    assert ranked[0]["ranking_signals"]["embedding"] == 1.0
