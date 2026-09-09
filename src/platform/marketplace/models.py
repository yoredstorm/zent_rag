# =============================================================================
# Phase 32B — Marketplace models & manifest validation
#
# Marketplace NO modela URL+headers: modela Integration → Capability → Action
# con action_id estables (peru.taxpayer.lookup) y manifests validables.
# =============================================================================
from __future__ import annotations

from typing import Any

AUTH_MODES = ("BYOC", "OAUTH", "ZENT_MANAGED", "PARTNER_MANAGED", "API_KEY", "CERT", "MTLS", "NONE")
PUBLISHING_STATES = ("DRAFT", "SUBMITTED", "SECURITY_REVIEW", "APPROVED", "PUBLISHED", "SUSPENDED", "DEPRECATED")
ACTION_STATUS = ("ACTIVE", "DEPRECATED", "END_OF_LIFE")
AUTO_USE_POLICY = ("NEVER_AUTO", "AUTO_READ_ONLY", "REQUIRE_APPROVAL", "WORKFLOW_ONLY")
COST_MODELS = ("FREE", "PER_CALL", "MONTHLY", "TIERED", "USAGE_PLUS_BASE", "BYOC_NO_MARKUP", "ZENT_MANAGED_MARKUP")
CATEGORIES = (
    "government", "sales", "finance", "communication", "commerce",
    "operations", "data", "productivity", "other",
)
RISK_LEVELS = ("info", "normal", "elevated", "critical")


class ManifestValidationError(ValueError):
    """Manifest inválido (seguridad/estructura)."""


def _require_type(value: Any, typ: type, field: str) -> None:
    if not isinstance(value, typ):
        raise ManifestValidationError(f"{field}: debe ser {typ.__name__}")


def _is_json_schema(schema: Any) -> bool:
    return isinstance(schema, dict) and schema.get("type") == "object"


def validate_action_manifest(action: dict, integration_slug: str) -> list[str]:
    """Valida una action de manifest. Devuelve lista de errores (vacía = ok)."""
    errors: list[str] = []
    action_id = str(action.get("action_id") or "")
    label = action_id or "action"
    if not action_id:
        errors.append("action_id requerido")
    if not action_id.startswith((f"{integration_slug}.",)) and not action_id.startswith("demo."):
        errors.append(f"{label}: action_id debe empezar por '{integration_slug}.'")
    if len(action_id) > 120:
        errors.append(f"{label}: action_id demasiado largo")
    if not str(action.get("display_name") or "").strip():
        errors.append(f"{label}: display_name requerido")
    if not _is_json_schema(action.get("input_schema")):
        errors.append(f"{label}: input_schema debe ser JSON Schema object")
    if not _is_json_schema(action.get("output_schema")):
        errors.append(f"{label}: output_schema debe ser JSON Schema object")
    if str(action.get("risk_level") or "info") not in RISK_LEVELS:
        errors.append(f"{label}: risk_level inválido")
    try:
        timeout = int(action.get("timeout_ms") or 0)
        if not 100 <= timeout <= 120_000:
            errors.append(f"{label}: timeout_ms fuera de rango")
    except (TypeError, ValueError):
        errors.append(f"{label}: timeout_ms inválido")
    model = (action.get("cost_model") or {}).get("model")
    if model and model not in COST_MODELS:
        errors.append(f"{label}: cost_model.model inválido")
    if isinstance(action.get("provider_config"), dict):
        kind = action["provider_config"].get("kind")
        if kind not in ("rest", "demo_echo"):
            errors.append(f"{label}: provider_config.kind debe ser rest|demo_echo")
        if kind == "rest" and not str(action["provider_config"].get("path_template") or ""):
            errors.append(f"{label}: provider_config.path_template requerido para rest")
    return errors


def validate_integration_manifest(manifest: dict) -> list[str]:
    """Valida un IntegrationManifest completo (lista de errores; vacía = ok)."""
    errors: list[str] = []
    slug = str(manifest.get("slug") or "")
    if not slug or not slug.replace("-", "").replace("_", "").isalnum():
        errors.append("slug inválido (solo letras/números/-/_)")
    if len(slug) > 80:
        errors.append("slug demasiado largo")
    if not str(manifest.get("name") or "").strip():
        errors.append("name requerido")
    status = str(manifest.get("status") or "DRAFT")
    if status not in PUBLISHING_STATES:
        errors.append(f"status inválido: {status}")
    for mode in manifest.get("auth_modes") or []:
        if mode not in AUTH_MODES:
            errors.append(f"auth_modes inválido: {mode}")
    if str(manifest.get("category") or "data") not in CATEGORIES:
        errors.append("category inválida")
    caps = manifest.get("capabilities") or []
    pricing = manifest.get("pricing") or {}
    is_pack = str(pricing.get("_pack_kind") or "") in ("workflow_template", "agent_pack")
    if not isinstance(caps, list) or (not caps and not is_pack):
        errors.append("capabilities: se requiere al menos una capacidad (o _pack_kind en pricing)")
    for cap in caps:
        if not isinstance(cap, dict) or not str(cap.get("slug") or ""):
            errors.append("capability sin slug")
        for action in cap.get("actions") or []:
            errors.extend(f"[{cap.get('slug')}] {e}" for e in validate_action_manifest(action, slug))
    pricing = manifest.get("pricing") or {}
    if pricing.get("model") and pricing["model"] not in COST_MODELS:
        errors.append(f"pricing.model inválido: {pricing['model']}")
    return errors


ALLOWED_PUBLISH_TRANSITIONS: dict[str, set[str]] = {
    "DRAFT": {"SUBMITTED"},
    "SUBMITTED": {"SECURITY_REVIEW", "DRAFT"},
    "SECURITY_REVIEW": {"APPROVED", "SUBMITTED", "SUSPENDED"},
    "APPROVED": {"PUBLISHED", "SUSPENDED"},
    "PUBLISHED": {"DEPRECATED", "SUSPENDED"},
    "SUSPENDED": {"APPROVED", "DRAFT"},
    "DEPRECATED": {"END_OF_LIFE" if "END_OF_LIFE" in PUBLISHING_STATES else "SUSPENDED"},
}


def can_transition(current: str, target: str) -> bool:
    allowed = ALLOWED_PUBLISH_TRANSITIONS.get(current, set())
    return target in (allowed | {current})
