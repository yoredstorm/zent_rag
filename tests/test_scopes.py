# =============================================================================
# Developer API key scopes — allowlist, aliases, permission mapping
# =============================================================================
from __future__ import annotations

import pytest


def test_canonicalize_maps_legacy_aliases() -> None:
    from src.platform.auth.scopes import canonicalize_scopes

    assert canonicalize_scopes(["rag:query", "rag:ingest"]) == ["rag:read", "rag:write"]


def test_canonicalize_dedupes_and_preserves_order() -> None:
    from src.platform.auth.scopes import canonicalize_scopes

    assert canonicalize_scopes(["rag:read", "rag:query", "usage:read"]) == [
        "rag:read",
        "usage:read",
    ]


def test_canonicalize_rejects_admin_star() -> None:
    from src.platform.auth.scopes import InvalidApiKeyScope, canonicalize_scopes

    with pytest.raises(InvalidApiKeyScope):
        canonicalize_scopes(["admin:*"])


def test_canonicalize_rejects_unknown_scope() -> None:
    from src.platform.auth.scopes import InvalidApiKeyScope, canonicalize_scopes

    with pytest.raises(InvalidApiKeyScope):
        canonicalize_scopes(["billing:write"])


def test_expand_scopes_makes_legacy_and_canonical_equivalent() -> None:
    from src.platform.auth.scopes import expand_scopes

    legacy = expand_scopes(["rag:query", "rag:ingest"])
    canonical = expand_scopes(["rag:read", "rag:write"])
    assert "rag:read" in legacy
    assert "rag:query" in canonical
    assert "rag:write" in legacy
    assert "rag:ingest" in canonical


def test_scope_to_permissions_maps_connectors_and_usage() -> None:
    from src.platform.auth.scopes import scope_to_permissions

    perms = scope_to_permissions(["connectors:read", "usage:read"])
    assert "connectors:read" in perms
    assert "usage:read" in perms
    assert "connectors:write" not in perms
    assert "*" not in perms


def test_scope_to_permissions_write_implies_read_for_connectors() -> None:
    from src.platform.auth.scopes import scope_to_permissions

    perms = scope_to_permissions(["connectors:write"])
    assert "connectors:write" in perms
    assert "connectors:read" in perms


def test_scope_to_permissions_rag_write_includes_ingest() -> None:
    from src.platform.auth.scopes import scope_to_permissions

    perms = scope_to_permissions(["rag:write"])
    assert "rag:ingest" in perms
    assert "rag:write" in perms
    assert "sources:write" in perms
    assert "kbs:write" in perms


def test_permission_satisfied_aliases_rag_query_to_read() -> None:
    from src.platform.auth.scopes import permission_satisfied

    assert permission_satisfied(frozenset({"rag:query"}), "rag:read")
    assert permission_satisfied(frozenset({"rag:read"}), "rag:query")
    assert not permission_satisfied(frozenset({"rag:read"}), "agents:execute")


def test_has_scope_accepts_aliases() -> None:
    from src.platform.auth.scopes import has_scope

    assert has_scope(["rag:write"], "rag:ingest")
    assert has_scope(["rag:query"], "rag:read")
    assert has_scope(["portal"], "rag:read")
    assert has_scope(["admin:*"], "agents:execute")
    assert not has_scope(["usage:read"], "rag:read")


def test_display_api_key_prefix_known_and_fallback() -> None:
    from src.core.domain.entities import display_api_key_prefix

    assert display_api_key_prefix("zent_sk_live_abc") == "zent_sk_live_"
    assert display_api_key_prefix("rag_test_xyz") == "rag_test_"
    assert display_api_key_prefix("customtoken") == "customtoken"[:12]
