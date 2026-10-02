# =============================================================================
# KnowledgeScope — scope declarativo, estrecha nunca amplía (C7).
# =============================================================================
from __future__ import annotations

from uuid import uuid4

from src.core.domain.knowledge_scope import KnowledgeScope, from_config, narrow


def test_from_config_lee_scope_y_legacy() -> None:
    org = uuid4()
    scope = from_config(
        {
            "knowledge_scope": {
                "source_ids": [str(org)],
                "knowledge_base_ids": [str(uuid4())],
                "workspace_ids": [str(uuid4())],
                "canonical_kinds": ["rule", "entity"],
                "domains": ["pricing"],
                "tags": ["atpco"],
            }
        }
    )
    assert scope.source_ids == (org,)
    assert scope.canonical_kinds == ("rule", "entity")
    assert scope.domains == ("pricing",)

    legacy = from_config({"source_ids": [str(org)], "knowledge_base_ids": [str(uuid4())]})
    assert legacy.source_ids == (org,)


def test_parse_fail_soft_descarta_invalidos() -> None:
    scope = from_config(
        {
            "knowledge_scope": {
                "source_ids": ["no-uuid", str(uuid4()), 7],
                "canonical_kinds": ["rule", "", 9, "rule"],
                "domains": "pricing",
            }
        }
    )
    assert len(scope.source_ids) == 1
    assert scope.canonical_kinds == ("rule",)
    assert scope.domains == ()


def test_narrow_intersecta_y_vacio_no_restringe() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    base = KnowledgeScope(source_ids=(a, b), canonical_kinds=("rule", "entity"))
    other = KnowledgeScope(source_ids=(b, c), canonical_kinds=("entity",))
    result = narrow(base, other)
    assert result.source_ids == (b,)
    assert result.canonical_kinds == ("entity",)

    assert narrow(KnowledgeScope(), base).source_ids == (a, b)
    assert narrow(base, KnowledgeScope()).source_ids == (a, b)
    assert narrow(KnowledgeScope(source_ids=(a,)), KnowledgeScope(source_ids=(b,))).source_ids == ()


def test_payload_publico() -> None:
    scope = KnowledgeScope(source_ids=(uuid4(),), tags=("atpco",))
    payload = scope.to_public_dict()
    assert payload["source_ids"]
    assert payload["tags"] == ["atpco"]
    assert payload["knowledge_base_ids"] == []
