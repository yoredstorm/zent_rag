# =============================================================================
# Developer API key scopes — allowlist, aliases, mapping to RBAC permissions
# =============================================================================
from __future__ import annotations

from collections.abc import Iterable

from src.core.domain.entities import display_api_key_prefix

PUBLIC_API_KEY_SCOPES: frozenset[str] = frozenset(
    {
        "rag:read",
        "rag:write",
        "agents:execute",
        "agents:read",
        "connectors:read",
        "connectors:write",
        "usage:read",
        "knowledge:read",
        "analytics:read",
    }
)

DEFAULT_API_KEY_SCOPES: list[str] = ["rag:read", "rag:write", "usage:read"]

LEGACY_SCOPE_ALIASES: dict[str, str] = {
    "rag:query": "rag:read",
    "rag:ingest": "rag:write",
    "billing:read": "usage:read",
}

_SCOPE_EQUIVALENTS: dict[str, frozenset[str]] = {
    "rag:read": frozenset({"rag:read", "rag:query", "knowledge:read"}),
    "rag:query": frozenset({"rag:read", "rag:query", "knowledge:read"}),
    "knowledge:read": frozenset({"rag:read", "rag:query", "knowledge:read"}),
    "rag:write": frozenset({"rag:write", "rag:ingest"}),
    "rag:ingest": frozenset({"rag:write", "rag:ingest"}),
    "usage:read": frozenset({"usage:read", "billing:read", "analytics:read"}),
    "billing:read": frozenset({"usage:read", "billing:read", "analytics:read"}),
    "analytics:read": frozenset({"usage:read", "billing:read", "analytics:read"}),
}

_SCOPE_TO_PERMISSIONS: dict[str, frozenset[str]] = {
    "rag:read": frozenset({"rag:read", "rag:query"}),
    "rag:query": frozenset({"rag:read", "rag:query"}),
    "rag:write": frozenset({"rag:write", "rag:ingest", "kbs:write", "sources:write"}),
    "rag:ingest": frozenset({"rag:write", "rag:ingest", "kbs:write", "sources:write"}),
    "agents:execute": frozenset({"agents:execute"}),
    "agents:read": frozenset({"agents:read"}),
    "knowledge:read": frozenset(
        {"rag:read", "rag:query", "sources:read", "kbs:read", "knowledge:read"}
    ),
    "connectors:read": frozenset({"connectors:read"}),
    "connectors:write": frozenset({"connectors:read", "connectors:write"}),
    "usage:read": frozenset({"usage:read", "billing:read", "analytics:read"}),
    "billing:read": frozenset({"usage:read", "billing:read", "analytics:read"}),
    "analytics:read": frozenset({"usage:read", "billing:read", "analytics:read"}),
}

DEFAULT_API_TOKEN_PREFIX = "zent_sk_live"  # noqa: S105 — prefix, not a secret


class InvalidApiKeyScope(ValueError):
    """Scope fuera del allowlist público de API keys."""


def canonicalize_scopes(scopes: Iterable[str]) -> list[str]:
    """Normaliza aliases legacy y rechaza scopes que no sean de developer."""
    canonical: list[str] = []
    seen: set[str] = set()
    for raw in scopes:
        mapped = LEGACY_SCOPE_ALIASES.get(raw, raw)
        if mapped not in PUBLIC_API_KEY_SCOPES:
            raise InvalidApiKeyScope(f"Invalid API key scope: {raw}")
        if mapped not in seen:
            seen.add(mapped)
            canonical.append(mapped)
    return canonical


def expand_scopes(scopes: Iterable[str]) -> frozenset[str]:
    """Expande aliases en ambos sentidos (rag:query ≡ rag:read)."""
    out: set[str] = set()
    for scope in scopes:
        out.add(scope)
        out.update(_SCOPE_EQUIVALENTS.get(scope, {scope}))
    return frozenset(out)


def scope_to_permissions(scopes: Iterable[str]) -> frozenset[str]:
    """Permisos RBAC que otorga una API key a partir de sus scopes."""
    perms: set[str] = set()
    for scope in scopes:
        if scope == "admin:*":
            perms.add("*")
            continue
        perms.update(_SCOPE_TO_PERMISSIONS.get(scope, ()))
        perms.update(expand_scopes([scope]))
    return frozenset(perms)


def permission_satisfied(held: frozenset[str], needed: str) -> bool:
    if "*" in held or needed in held:
        return True
    return bool(held & expand_scopes([needed]))


def has_scope(scopes: Iterable[str], needed: str) -> bool:
    """True si el token cubre `needed`, incluyendo aliases y bypass portal/admin."""
    held = set(scopes)
    if "admin:*" in held or "portal" in held:
        return True
    return bool(expand_scopes(held) & expand_scopes([needed]))


def display_key_prefix(token: str) -> str:
    return display_api_key_prefix(token)


def api_key_environment(prefix_or_token: str) -> str:
    """live | test from token/prefix. Same org data; test is watermark + cuota."""
    value = prefix_or_token or ""
    if value.startswith("zent_sk_test_") or value.startswith("rag_test_"):
        return "test"
    return "live"
