# =============================================================================
# Rollout de ingesta/fabric por organización o workspace.
# El default global no cambia de golpe a todos los tenants.
# =============================================================================
from __future__ import annotations

import json

OFF = "off"
SHADOW = "shadow"
CANARY = "canary"
ACTIVE = "active"
MODES = frozenset({OFF, SHADOW, CANARY, ACTIVE})


def _settings():
    try:
        from src.core.config import get_settings

        return get_settings()
    except Exception:  # noqa: BLE001
        return None


def _clean(value: object) -> str:
    text = str(value or "").strip().lower()
    return text if text in MODES else OFF


def rollout_policy() -> dict:
    raw = "{}"
    settings = _settings()
    if settings is not None:
        raw = str(getattr(settings, "KNOWLEDGE_SEMANTIC_ROLLOUT", "") or "{}")
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {"workspaces": {}, "organizations": {}}
    if not isinstance(parsed, dict):
        return {"workspaces": {}, "organizations": {}}
    return {
        "workspaces": dict(parsed.get("workspaces") or {}),
        "organizations": dict(parsed.get("organizations") or {}),
    }


def resolve_semantic_mode(
    *,
    organization_id=None,
    workspace_id=None,
    global_mode: str = OFF,
) -> str:
    """Workspace pisa organización. Organización pisa el modo global."""
    policy = rollout_policy()
    workspace = str(workspace_id or "")
    organization = str(organization_id or "")
    if workspace and workspace in policy["workspaces"]:
        return _clean(policy["workspaces"][workspace])
    if organization and organization in policy["organizations"]:
        return _clean(policy["organizations"][organization])
    return _clean(global_mode)


def resolve_fabric_mode(
    *,
    organization_id=None,
    workspace_id=None,
    global_semantic_mode: str = OFF,
    global_fabric_mode: str = SHADOW,
) -> str:
    """ACTIVE semántico usa el fabric en retrieval. OFF no lo toca."""
    semantic = resolve_semantic_mode(
        organization_id=organization_id,
        workspace_id=workspace_id,
        global_mode=global_semantic_mode,
    )
    if semantic == ACTIVE:
        return ACTIVE
    if semantic == OFF:
        return OFF
    fabric = str(global_fabric_mode or SHADOW).strip().lower()
    return fabric if fabric in {OFF, SHADOW, ACTIVE} else SHADOW
