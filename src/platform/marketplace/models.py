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
    "operations", "data", "productivity", "demo", "other",
)
RISK_LEVELS = ("info", "normal", "elevated", "critical")
PROVIDER_KINDS = ("rest", "demo_echo", "public_rest")
EVENT_DELIVERY_MODES = ("webhook", "polling", "internal")


class ManifestValidationError(ValueError):
    """Manifest inválido (seguridad/estructura)."""


def _require_type(value: Any, typ: type, field: str) -> None:
    if not isinstance(value, typ):
        raise ManifestValidationError(f"{field}: debe ser {typ.__name__}")


def _is_json_schema(schema: Any) -> bool:
    return isinstance(schema, dict) and schema.get("type") == "object"


def validate_action_manifest(
    action: dict, integration_slug: str, capability_slug: str | None = None
) -> list[str]:
    """Valida una action de manifest. Devuelve lista de errores (vacía = ok)."""
    errors: list[str] = []
    action_id = str(action.get("action_id") or "")
    label = action_id or "action"
    if not action_id:
        errors.append("action_id requerido")
    prefixes = {f"{integration_slug}.", "demo."}
    if capability_slug:
        prefixes.add(f"{capability_slug}.")
    if not action_id.startswith(tuple(prefixes)):
        errors.append(
            f"{label}: action_id debe empezar por '{integration_slug}.' o '{capability_slug}.'"
        )
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
        timeout = int(action.get("timeout_ms") or 5000)
        if not 100 <= timeout <= 120_000:
            errors.append(f"{label}: timeout_ms fuera de rango")
    except (TypeError, ValueError):
        errors.append(f"{label}: timeout_ms inválido")
    model = (action.get("cost_model") or {}).get("model")
    if model and model not in COST_MODELS:
        errors.append(f"{label}: cost_model.model inválido")
    if isinstance(action.get("provider_config"), dict):
        kind = action["provider_config"].get("kind")
        if kind not in PROVIDER_KINDS:
            errors.append(f"{label}: provider_config.kind debe ser {'|'.join(PROVIDER_KINDS)}")
        if kind == "rest" and not str(action["provider_config"].get("path_template") or ""):
            errors.append(f"{label}: provider_config.path_template requerido para rest")
        if kind == "public_rest":
            base_url = str(action["provider_config"].get("base_url") or "")
            if not base_url.startswith("https://"):
                errors.append(f"{label}: public_rest requiere base_url https")
            if not str(action["provider_config"].get("path_template") or ""):
                errors.append(f"{label}: provider_config.path_template requerido para public_rest")
    return errors


def validate_event_manifest(event: dict, integration_slug: str) -> list[str]:
    """Valida un connector event del manifest v2 (misión §8 y §19)."""
    errors: list[str] = []
    event_id = str(event.get("id") or "")
    label = event_id or "event"
    if not event_id:
        errors.append("event id requerido")
    elif not event_id.startswith(f"{integration_slug}.") and not event_id.startswith("demo."):
        errors.append(f"{label}: event id debe empezar por '{integration_slug}.'")
    if not str(event.get("business_name") or "").strip():
        errors.append(f"{label}: business_name requerido")
    if not _is_json_schema(event.get("event_schema")):
        errors.append(f"{label}: event_schema debe ser JSON Schema object")
    mode = str(event.get("delivery_mode") or "webhook")
    if mode not in EVENT_DELIVERY_MODES:
        errors.append(f"{label}: delivery_mode debe ser {'|'.join(EVENT_DELIVERY_MODES)}")
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
            continue
        errors.extend(
            f"[{cap.get('slug')}] {e}" for e in _validate_capability_contract(cap, str(cap.get("slug")))
        )
        for action in cap.get("actions") or []:
            errors.extend(
                f"[{cap.get('slug')}] {e}"
                for e in validate_action_manifest(action, slug, cap.get("slug"))
            )
    for event in manifest.get("events") or []:
        if not isinstance(event, dict):
            errors.append("event inválido")
            continue
        errors.extend(f"[event:{event.get('id')}] {e}" for e in validate_event_manifest(event, slug))
    pricing = manifest.get("pricing") or {}
    if pricing.get("model") and pricing["model"] not in COST_MODELS:
        errors.append(f"pricing.model inválido: {pricing['model']}")
    # Addon Contract v2 (bloque completo). v1 sin estos campos sigue válido.
    errors.extend(_validate_contract_block(manifest))
    return errors


# =============================================================================
# Addon Contract v2 — un addon declara QUÉ ofrece y CÓMO se gobierna
# =============================================================================
# El contrato v1 sigue válido (compatibilidad total). v2 añade el bloque
# `contract` con la superficie completa del addon: identidad, superficies,
# capacidades con esquemas, eventos y su webhook, credenciales (solo NOMBRES),
# riesgo, permisos, aprobación, idempotencia, rate limits, coste, health check,
# sandbox, compatibilidad y documentación.
#
# Regla dura: NUNCA un valor secreto en el manifest. Las credenciales se
# declaran por nombre y los valores viven en el SecretStore.
# =============================================================================
CONTRACT_VERSIONS = (1, 2)

ADDON_APPLIES_TO = (
    "AGENTS", "WORKFLOWS", "KNOWLEDGE", "DATA", "INTEGRATIONS",
    "CHANNELS", "PAYMENTS", "AUTOMATIONS", "ANALYTICS", "ADMIN",
)

IDEMPOTENCY_SCOPES = ("action", "operation", "tenant", "none")
HEALTH_CHECK_KINDS = ("http", "none")
WEBHOOK_SIGNATURE_KINDS = ("hmac-sha256", "stripe-signature", "kr-hash", "shared-secret", "none")
SANDBOX_MODES = ("test", "live", "both")

#: Claves prohibidas dentro de `contract.credentials` (serían valores, no nombres).
_SECRET_VALUE_KEYS = (
    "value", "secret", "secrets", "token", "password", "api_key", "apikey",
    "private_key", "hash_key", "client_secret", "secret_key", "webhook_secret",
)


#: Campos que solo existen en el contrato v2.
_V2_ONLY_FIELDS = (
    "contract", "identity", "credentials", "risk", "permissions", "approval",
    "idempotency", "health_check", "sandbox", "compatibility", "documentation",
    "applies_to",
)


def contract_version(manifest: dict) -> int:
    """Versión del contrato declarada (o inferida por los campos v2 presentes).

    Un manifest sin `contract_version` pero con identidad/credenciales/sandbox/
    compatibilidad es v2: la versión describe lo que el addon declara, no una
    etiqueta que se pueda omitir.
    """
    raw = manifest.get("contract_version")
    if raw is None:
        raw = (manifest.get("identity") or {}).get("contract_version")
    if raw is None:
        raw = (manifest.get("compatibility") or {}).get("contract_version")
    if raw is not None:
        try:
            version = int(raw)
        except (TypeError, ValueError):
            return 1
        return version if version in CONTRACT_VERSIONS else 1
    if any(field in manifest for field in _V2_ONLY_FIELDS):
        return 2
    return 1


def _validate_credentials(credentials: Any) -> list[str]:
    errors: list[str] = []
    if credentials is None:
        return errors
    if not isinstance(credentials, list):
        return ["credentials: debe ser una lista de declaraciones {key, label, required}"]
    for entry in credentials:
        if not isinstance(entry, dict):
            errors.append("credentials: entrada inválida")
            continue
        key = str(entry.get("key") or "").strip()
        if not key:
            errors.append("credentials: cada entrada requiere key")
        for forbidden in _SECRET_VALUE_KEYS:
            if forbidden in entry and forbidden != "key":
                errors.append(
                    f"credentials[{key or '?'}]: '{forbidden}' prohibido — "
                    "el manifest declara NOMBRES, los valores van al SecretStore"
                )
    return errors


def _validate_capability_contract(cap: dict, label: str) -> list[str]:
    errors: list[str] = []
    if "input_schema" in cap and not _is_json_schema(cap.get("input_schema")):
        errors.append(f"{label}: input_schema debe ser JSON Schema object")
    if "output_schema" in cap and not _is_json_schema(cap.get("output_schema")):
        errors.append(f"{label}: output_schema debe ser JSON Schema object")
    risk = str(cap.get("risk_level") or "")
    if risk and risk not in RISK_LEVELS:
        errors.append(f"{label}: risk_level inválido")
    scope = str(cap.get("idempotency_scope") or "")
    if scope and scope not in IDEMPOTENCY_SCOPES:
        errors.append(f"{label}: idempotency_scope inválido")
    if cap.get("requires_approval") is not None and not isinstance(cap.get("requires_approval"), bool):
        errors.append(f"{label}: requires_approval debe ser booleano")
    if cap.get("idempotency_support") is not None and not isinstance(
        cap.get("idempotency_support"), bool
    ):
        errors.append(f"{label}: idempotency_support debe ser booleano")
    return errors


def _validate_contract_block(manifest: dict) -> list[str]:
    errors: list[str] = []
    contract = manifest.get("contract")
    if contract is not None and not isinstance(contract, dict):
        return ["contract: debe ser un objeto"]

    applies_to = manifest.get("applies_to") or (contract or {}).get("applies_to") or []
    if not isinstance(applies_to, list):
        errors.append("applies_to: debe ser una lista")
    else:
        for surface in applies_to:
            if str(surface).upper() not in ADDON_APPLIES_TO:
                errors.append(f"applies_to inválido: {surface}")

    errors.extend(_validate_credentials(manifest.get("credentials")))

    risk = str(manifest.get("risk") or "")
    if risk and risk not in RISK_LEVELS:
        errors.append(f"risk inválido: {risk}")

    idempotency = manifest.get("idempotency")
    if idempotency is not None:
        if not isinstance(idempotency, dict):
            errors.append("idempotency: debe ser un objeto")
        else:
            scope = str(idempotency.get("scope") or "")
            if scope and scope not in IDEMPOTENCY_SCOPES:
                errors.append(f"idempotency.scope inválido: {scope}")

    health = manifest.get("health_check")
    if health is not None:
        if not isinstance(health, dict):
            errors.append("health_check: debe ser un objeto")
        else:
            kind = str(health.get("kind") or "none")
            if kind not in HEALTH_CHECK_KINDS:
                errors.append(f"health_check.kind inválido: {kind}")
            if kind == "http" and not str(health.get("url") or "").startswith("https://"):
                errors.append("health_check: kind http requiere url https")

    sandbox = manifest.get("sandbox")
    if sandbox is not None:
        if not isinstance(sandbox, dict):
            errors.append("sandbox: debe ser un objeto")
        else:
            mode = str(sandbox.get("mode") or "")
            if mode and mode not in SANDBOX_MODES:
                errors.append(f"sandbox.mode inválido: {mode}")

    for event in manifest.get("events") or []:
        if not isinstance(event, dict):
            continue
        webhook = event.get("webhook")
        if webhook is None:
            continue
        if not isinstance(webhook, dict):
            errors.append(f"[event:{event.get('id')}] webhook: debe ser un objeto")
            continue
        signature = str(webhook.get("signature") or "")
        if signature and signature not in WEBHOOK_SIGNATURE_KINDS:
            errors.append(f"[event:{event.get('id')}] webhook.signature inválido: {signature}")
        window = webhook.get("replay_window_seconds")
        if window is not None:
            try:
                if not 0 < int(window) <= 86_400:
                    errors.append(f"[event:{event.get('id')}] replay_window_seconds fuera de rango")
            except (TypeError, ValueError):
                errors.append(f"[event:{event.get('id')}] replay_window_seconds inválido")
        if str(webhook.get("path") or "") and not str(webhook["path"]).startswith("/"):
            errors.append(f"[event:{event.get('id')}] webhook.path debe empezar por '/'")

    compatibility = manifest.get("compatibility")
    if compatibility is not None and not isinstance(compatibility, dict):
        errors.append("compatibility: debe ser un objeto")
    documentation = manifest.get("documentation")
    if documentation is not None and not isinstance(documentation, dict):
        errors.append("documentation: debe ser un objeto")
    permissions = manifest.get("permissions")
    if permissions is not None and not isinstance(permissions, list):
        errors.append("permissions: debe ser una lista")
    approval = manifest.get("approval")
    if approval is not None and not isinstance(approval, dict):
        errors.append("approval: debe ser un objeto")
    return errors


def normalize_contract(manifest: dict) -> dict:
    """Bloque `contract` normalizado (lo que se persiste y proyecta)."""
    contract = dict(manifest.get("contract") or {})
    identity = dict(manifest.get("identity") or {})
    normalized: dict[str, Any] = {
        "contract_version": contract_version(manifest),
        "identity": {
            "slug": identity.get("slug") or manifest.get("slug"),
            "name": identity.get("name") or manifest.get("name"),
            "publisher": identity.get("publisher") or manifest.get("provider"),
            "version": identity.get("version") or manifest.get("version") or 1,
        },
        "applies_to": [
            str(s).upper() for s in (manifest.get("applies_to") or contract.get("applies_to") or [])
        ],
        "capabilities": [
            {
                "ref": str(cap.get("slug") or ""),
                "risk_level": cap.get("risk_level"),
                "requires_approval": bool(cap.get("requires_approval") or False),
                "idempotency_support": bool(cap.get("idempotency_support") or False),
                "idempotency_scope": cap.get("idempotency_scope"),
                "rate_limits": dict(cap.get("rate_limits") or {}),
                "cost_model": dict(cap.get("cost_model") or {}),
                "has_input_schema": bool(cap.get("input_schema")),
                "has_output_schema": bool(cap.get("output_schema")),
            }
            for cap in (manifest.get("capabilities") or [])
            if isinstance(cap, dict)
        ],
        "events": [
            {
                "ref": str(event.get("id") or ""),
                "delivery_mode": event.get("delivery_mode") or "webhook",
                "webhook": dict(event.get("webhook") or {}),
            }
            for event in (manifest.get("events") or [])
            if isinstance(event, dict)
        ],
        "credentials": [
            {
                "key": str(entry.get("key") or ""),
                "label": entry.get("label"),
                "required": bool(entry.get("required", True)),
            }
            for entry in (manifest.get("credentials") or [])
            if isinstance(entry, dict)
        ],
        "risk": manifest.get("risk"),
        "permissions": list(manifest.get("permissions") or []),
        "approval": dict(manifest.get("approval") or {}),
        "idempotency": dict(manifest.get("idempotency") or {}),
        "rate_limits": dict(manifest.get("rate_limits") or {}),
        "cost_model": dict(manifest.get("cost_model") or manifest.get("pricing") or {}),
        "health_check": dict(manifest.get("health_check") or {}),
        "sandbox": dict(manifest.get("sandbox") or {}),
        "compatibility": dict(manifest.get("compatibility") or {}),
        "documentation": dict(manifest.get("documentation") or {}),
    }
    return normalized


ALLOWED_PUBLISH_TRANSITIONS: dict[str, set[str]] = {    "DRAFT": {"SUBMITTED"},
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
