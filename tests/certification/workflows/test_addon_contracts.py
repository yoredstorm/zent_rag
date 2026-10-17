# =============================================================================
# Certification — Addon Contract v2
# =============================================================================
# Un addon declara su superficie completa (identidad, applies_to, capacidades
# con esquemas, eventos con webhook, credenciales por NOMBRE, riesgo, permisos,
# aprobación, idempotencia, rate limits, coste, health check, sandbox,
# compatibilidad y documentación). Los valores secretos NUNCA viajan en el
# manifest: viven en el SecretStore.
# =============================================================================
from __future__ import annotations

import pytest
from httpx import AsyncClient

from src.platform.marketplace.catalog import get_manifest, register_manifest
from src.platform.marketplace.models import (
    ManifestValidationError,
    contract_version,
    normalize_contract,
    validate_integration_manifest,
)
from tests.test_workflows import _create_org, _headers, _owner_session


def _izipay_manifest(**overrides) -> dict:
    manifest = {
        "slug": "izipay-payments",
        "name": "IZIPAY Payments",
        "provider": "IZIPAY",
        "version": 2,
        "status": "PUBLISHED",
        "category": "finance",
        "auth_modes": ["BYOC", "API_KEY"],
        "applies_to": ["WORKFLOWS", "AGENTS", "PAYMENTS"],
        "identity": {
            "slug": "izipay-payments",
            "name": "IZIPAY Payments",
            "publisher": "IZIPAY",
            "version": 2,
        },
        "capabilities": [
            {
                "slug": "payments.checkout.create",
                "name": "Crear checkout",
                "description": "Sesión de pago con QR o link.",
                "input_schema": {"type": "object", "properties": {"order_id": {"type": "string"}}},
                "output_schema": {"type": "object", "properties": {"checkout_url": {"type": "string"}}},
                "risk_level": "elevated",
                "requires_approval": False,
                "idempotency_support": True,
                "idempotency_scope": "operation",
                "rate_limits": {"per_minute": 60},
                "cost_model": {"model": "PER_CALL", "amount": 0.0},
            },
            {
                "slug": "payments.qr.create",
                "name": "Crear QR",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "risk_level": "normal",
            },
            {
                "slug": "payments.status.get",
                "name": "Consultar pago",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "risk_level": "info",
                "idempotency_support": True,
                "idempotency_scope": "operation",
            },
        ],
        "events": [
            {
                "id": "izipay-payments.payment.succeeded",
                "business_name": "Pago confirmado",
                "event_schema": {"type": "object"},
                "delivery_mode": "webhook",
                "webhook": {
                    "path": "/api/v1/public/payments/izipay/webhook",
                    "signature": "kr-hash",
                    "replay_window_seconds": 300,
                },
            }
        ],
        "credentials": [
            {"key": "merchant_code", "label": "Código de comercio", "required": True},
            {"key": "api_key", "label": "Llave de API", "required": True},
            {"key": "hash_key", "label": "Llave HMAC del webhook", "required": False},
        ],
        "risk": "elevated",
        "permissions": ["marketplace:install", "integration_credentials:manage"],
        "approval": {"required": False, "roles": []},
        "idempotency": {"support": True, "scope": "operation"},
        "rate_limits": {"per_minute": 120},
        "cost_model": {"model": "BYOC_NO_MARKUP"},
        "health_check": {"kind": "http", "url": "https://api.micuentaweb.pe/health", "interval_seconds": 300},
        "sandbox": {"supported": True, "mode": "both"},
        "compatibility": {"min_zent_version": "0.1.0", "contract_version": 2},
        "documentation": {
            "url": "https://docs.zent.local/addons/izipay",
            "setup_url": "https://docs.zent.local/addons/izipay/setup",
        },
        "pricing": {"model": "FREE"},
    }
    manifest.update(overrides)
    return manifest


def test_addon_contract_v2_is_valid_and_normalized() -> None:
    manifest = _izipay_manifest()
    assert validate_integration_manifest(manifest) == []
    assert contract_version(manifest) == 2
    contract = normalize_contract(manifest)
    assert contract["identity"]["publisher"] == "IZIPAY"
    assert contract["applies_to"] == ["WORKFLOWS", "AGENTS", "PAYMENTS"]
    refs = {cap["ref"] for cap in contract["capabilities"]}
    assert {"payments.checkout.create", "payments.qr.create", "payments.status.get"} == refs
    checkout = next(c for c in contract["capabilities"] if c["ref"] == "payments.checkout.create")
    assert checkout["idempotency_support"] is True
    assert checkout["idempotency_scope"] == "operation"
    assert checkout["has_input_schema"] and checkout["has_output_schema"]
    assert contract["events"][0]["webhook"]["signature"] == "kr-hash"
    assert contract["credentials"] == [
        {"key": "merchant_code", "label": "Código de comercio", "required": True},
        {"key": "api_key", "label": "Llave de API", "required": True},
        {"key": "hash_key", "label": "Llave HMAC del webhook", "required": False},
    ]
    assert contract["risk"] == "elevated"
    assert contract["sandbox"]["mode"] == "both"
    assert contract["health_check"]["kind"] == "http"
    assert contract["documentation"]["setup_url"].startswith("https://")


def test_addon_contract_v1_keeps_working() -> None:
    legacy = {
        "slug": "legacy-addon",
        "name": "Legacy",
        "status": "PUBLISHED",
        "capabilities": [
            {
                "slug": "legacy.echo",
                "name": "Echo",
                "actions": [
                    {
                        "action_id": "legacy.echo.run",
                        "display_name": "Echo",
                        "input_schema": {"type": "object"},
                        "output_schema": {"type": "object"},
                        "provider_config": {"kind": "demo_echo"},
                    }
                ],
            }
        ],
    }
    assert validate_integration_manifest(legacy) == []
    assert contract_version(legacy) == 1
    contract = normalize_contract(legacy)
    assert contract["contract_version"] == 1
    assert contract["credentials"] == []


def test_manifest_never_carries_secret_values() -> None:
    bad = _izipay_manifest(
        credentials=[
            {"key": "api_key", "label": "Llave", "required": True, "value": "sk_live_no_debe_viajar"}
        ]
    )
    errors = validate_integration_manifest(bad)
    assert any("prohibido" in error for error in errors), errors

    also_bad = _izipay_manifest(credentials={"api_key": "sk_live_1234"})
    errors = validate_integration_manifest(also_bad)
    assert any("lista de declaraciones" in error for error in errors), errors


def test_manifest_rejects_invalid_surfaces_risk_and_webhook() -> None:
    assert any(
        "applies_to inválido" in error
        for error in validate_integration_manifest(_izipay_manifest(applies_to=["VENTAS"]))
    )
    assert any(
        "risk inválido" in error
        for error in validate_integration_manifest(_izipay_manifest(risk="extremo"))
    )
    bad_webhook = _izipay_manifest()
    bad_webhook["events"][0]["webhook"]["signature"] = "firma-de-la-casa"
    assert any(
        "webhook.signature inválido" in error for error in validate_integration_manifest(bad_webhook)
    )
    bad_health = _izipay_manifest(health_check={"kind": "http", "url": "http://insecure.local/h"})
    assert any("url https" in error for error in validate_integration_manifest(bad_health))
    bad_idem = _izipay_manifest(idempotency={"support": True, "scope": "attempt"})
    assert any("idempotency.scope inválido" in error for error in validate_integration_manifest(bad_idem))


@pytest.mark.asyncio
async def test_register_manifest_persists_contract_and_projects_surfaces(
    async_client: AsyncClient,
) -> None:
    org = await _create_org(async_client, "Addon Contract")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    manifest = _izipay_manifest()
    try:
        registered = await register_manifest(manifest)
        assert registered["slug"] == "izipay-payments"
        stored = await get_manifest("izipay-payments")
        assert stored is not None
        assert stored["contract_version"] == 2
        assert stored["applies_to"] == ["WORKFLOWS", "AGENTS", "PAYMENTS"]
        assert stored["contract"]["credentials"][0]["key"] == "merchant_code"
        # Nunca hay valores secretos persistidos en el manifest.
        assert "sk_live" not in str(stored)
        assert "value" not in stored["contract"]["credentials"][0]

        # La proyección al catálogo global respeta las superficies declaradas.
        from src.platform.marketplace.factory import sync_catalog_from_assets

        await sync_catalog_from_assets()
        products = await async_client.get(
            "/api/v1/products",
            headers=_headers(org),
            params={"q": "izipay"},
        )
        assert products.status_code == 200, products.text
        found = [
            p
            for p in products.json().get("products") or []
            if p["slug"] == "product-izipay-payments"
        ]
        assert found, products.text[:400]
        assert set(found[0]["applies_to"]) >= {"WORKFLOWS", "AGENTS", "PAYMENTS"}
    finally:
        # El addon de prueba no debe quedar publicado para el resto de la suite.
        await _drop_addon("izipay-payments")


async def _drop_addon(slug: str) -> None:
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text("DELETE FROM marketplace_products WHERE slug = :slug"),
            {"slug": f"product-{slug}"},
        )
        await session.execute(
            text("DELETE FROM integration_capabilities WHERE integration_id IN "
                 "(SELECT id FROM integration_manifests WHERE slug = :slug)"),
            {"slug": slug},
        )
        await session.execute(
            text("DELETE FROM integration_manifests WHERE slug = :slug"), {"slug": slug}
        )
        await session.commit()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_register_manifest_rejects_plaintext_secrets() -> None:
    with pytest.raises(ManifestValidationError):
        await register_manifest(
            _izipay_manifest(
                credentials=[{"key": "api_key", "value": "sk_live_xyz", "required": True}]
            )
        )


@pytest.mark.asyncio
async def test_financial_capabilities_declare_idempotency_in_the_registry() -> None:
    """El contrato de las capacidades financieras exige idempotencia."""
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT capability_ref, financial, idempotency_required, provider_kinds "
                    "FROM workflow_capability_contracts WHERE capability_ref LIKE 'payments.%'"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    assert rows, "el contrato de pagos debe estar registrado"
    by_ref = {str(r.capability_ref): r for r in rows}
    assert "payments.checkout.create" in by_ref
    assert bool(by_ref["payments.checkout.create"].financial) is True
    assert bool(by_ref["payments.checkout.create"].idempotency_required) is True
    assert "payment_provider" in list(by_ref["payments.checkout.create"].provider_kinds)
