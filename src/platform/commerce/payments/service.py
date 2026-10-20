# =============================================================================
# Payment service — checkout, QR, estado, cancelación y ingestión de webhooks
# =============================================================================
# Flujo completo (nunca un payload externo se vuelve señal sin validación):
#
#   provider webhook → verificación de firma → normalización → dedupe
#     → BusinessEvent (payment.succeeded) → workflow signal → resume instance
#
# Idempotencia financiera extremo a extremo:
#   idempotency_key = sha256(organization_id | workflow_instance_id | node_id |
#                            business_operation_id)
#   Un retry por timeout repite la MISMA operación lógica y devuelve el mismo
#   checkout: jamás se crean dos cobros.
# =============================================================================
from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid5

from src.infrastructure.observability.logging_config import get_logger
from src.platform.commerce import contracts as C
from src.platform.commerce import store
from src.platform.commerce.payments.base import (
    CheckoutRequest,
    NormalizedPaymentEvent,
    PaymentProviderAdapter,
    PaymentProviderError,
)
from src.platform.commerce.payments.providers import build_adapter

logger = get_logger(__name__)

#: Namespace estable para el connector_id del SecretStore por (org, provider).
_CRED_NAMESPACE = UUID("6f5d1f6b-3a0f-4d1b-9d1a-2b3c4d5e6f70")

#: Estados locales del checkout que cierran la operación.
_TERMINAL_CHECKOUT = ("succeeded", "failed", "expired", "cancelled", "refunded")

#: Circuit breaker del proveedor de pagos (por tenant): tras N fallos
#: consecutivos se falla rápido durante un enfriamiento, para no martillar a
#: una pasarela caída (y no encadenar timeouts dentro de un workflow).
_CIRCUIT_FAILURE_THRESHOLD = 5
_CIRCUIT_COOLDOWN_SECONDS = 60


def credential_connector_id(organization_id: Any, provider: str) -> UUID:
    """UUID determinista del secreto en el SecretStore (nunca en el manifest)."""
    return uuid5(_CRED_NAMESPACE, f"{organization_id}:{provider}")


# ---------------------------------------------------------------------------
# Configuración del proveedor (BYOC con SecretStore)
# ---------------------------------------------------------------------------
async def configure_provider(
    organization_id: UUID,
    *,
    provider: str,
    secrets: dict[str, Any],
    mode: str = "test",
    config: dict[str, Any] | None = None,
    display_name: str | None = None,
    bind_capabilities: bool = True,
) -> dict[str, Any]:
    """Guarda credenciales + registra el provider y deja las capacidades listas.

    Es el paso "Instalar/configurar IZIPAY": después de esto
    `payments.checkout.create` y `payment.succeeded` quedan en verde.
    """
    key = str(provider or "").strip().lower()
    if key not in C.PAYMENT_PROVIDERS:
        raise PaymentProviderError("PROVIDER_UNKNOWN", f"proveedor no soportado: {provider}")
    connector_id = credential_connector_id(organization_id, key)
    if secrets:
        from src.infrastructure.secrets.secret_store_resolver import get_secret_store

        store_impl = get_secret_store()
        if store_impl is not None:
            await store_impl.put(organization_id, connector_id, dict(secrets))
    record = await store.upsert_payment_provider(
        organization_id,
        provider=key,
        display_name=display_name or key.upper(),
        mode=mode,
        sandbox=(key == "sandbox" or mode == "test"),
        credential_ref=str(connector_id),
        config=config or {},
        capabilities=list(C.PAYMENT_CAPABILITIES),
        events=list(C.PAYMENT_EVENTS),
        health={"ready": True, "missing_credentials": []},
    )
    if bind_capabilities:
        await _bind_payment_capabilities(organization_id, key, record)
    return record


async def _bind_payment_capabilities(
    organization_id: UUID, provider: str, record: dict[str, Any]
) -> None:
    """El tenant elige provider: el binding deja de nombrar al proveedor."""
    from src.platform.workflows.bindings import upsert_binding

    for capability in C.PAYMENT_CAPABILITIES:
        contract = C.contract_for(capability)
        try:
            await upsert_binding(
                organization_id,
                capability,
                C.PAYMENT_PROVIDER_KIND,
                config={"provider": provider, "mode": record.get("mode") or "test"},
                credential_ref=record.get("credential_ref"),
                contract_input_schema=contract.get("input") or {},
                contract_output_schema=contract.get("output") or {},
            )
        except Exception as exc:  # noqa: BLE001 — el binding es best-effort aquí
            logger.warning(
                "payment capability binding failed",
                capability=capability,
                provider=provider,
                error=str(exc)[:200],
            )


async def ensure_provider(
    organization_id: UUID,
    *,
    provider: str | None = None,
    credential_ref: str | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[str, PaymentProviderAdapter]:
    """Resuelve el adapter del tenant: input → config del binding → sandbox."""
    chosen = str(provider or "").strip().lower()
    if not chosen:
        binding = await _payment_binding(organization_id)
        chosen = str((binding or {}).get("config", {}).get("provider") or "")
        config = {**(binding or {}).get("config", {}), **(config or {})}
        credential_ref = credential_ref or (binding or {}).get("credential_ref")
    if not chosen:
        chosen = C.DEFAULT_PAYMENT_PROVIDER
    record = await store.get_payment_provider(organization_id, chosen)
    if record is None and chosen != C.DEFAULT_PAYMENT_PROVIDER:
        raise PaymentProviderError(
            "NEEDS_CREDENTIALS",
            f"el proveedor de pago {chosen} no está configurado para la organización",
        )
    secrets: dict[str, Any] = {}
    ref = credential_ref or (record or {}).get("credential_ref")
    if ref:
        try:
            from src.infrastructure.secrets.secret_store_resolver import get_secret_store

            store_impl = get_secret_store()
            if store_impl is not None:
                secrets = await store_impl.get(organization_id, UUID(str(ref)))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "payment credentials unavailable", provider=chosen, error=str(exc)[:160]
            )
    merged_config = {**(record or {}).get("config", {}), **(config or {})}
    adapter = build_adapter(chosen, secrets or {}, merged_config)
    missing = [key for key in adapter.required_secrets if not (secrets or {}).get(key)]
    if missing and chosen != C.DEFAULT_PAYMENT_PROVIDER:
        raise PaymentProviderError(
            "NEEDS_CREDENTIALS",
            f"{chosen} no tiene configuradas las credenciales: {', '.join(missing)}",
        )
    return chosen, adapter


async def _circuit_guard(organization_id: UUID, provider: str) -> None:
    """Falla rápido si el proveedor está en enfriamiento tras fallos seguidos."""
    record = await store.get_payment_provider(organization_id, provider)
    if record is None:
        return
    circuit = dict((record.get("health") or {}).get("circuit") or {})
    opened_at = circuit.get("opened_at")
    if not opened_at:
        return
    try:
        from datetime import datetime, timezone

        opened = datetime.fromisoformat(str(opened_at))
    except ValueError:
        return
    elapsed = (datetime.now(timezone.utc) - opened).total_seconds()
    if elapsed < _CIRCUIT_COOLDOWN_SECONDS:
        raise PaymentProviderError(
            "PROVIDER_CIRCUIT_OPEN",
            f"{provider} está temporalmente no disponible; reintenta en "
            f"{int(_CIRCUIT_COOLDOWN_SECONDS - elapsed)}s",
        )


async def _circuit_report(organization_id: UUID, provider: str, *, ok: bool) -> None:
    """Cuenta fallos consecutivos del proveedor y abre/cierra el circuito."""

    record = await store.get_payment_provider(organization_id, provider)
    if record is None:
        return
    health = dict(record.get("health") or {})
    circuit = dict(health.get("circuit") or {})
    if ok:
        circuit = {"failures": 0, "opened_at": None, "last_ok_at": _now_iso()}
    else:
        failures = int(circuit.get("failures") or 0) + 1
        circuit = {
            "failures": failures,
            "last_failure_at": _now_iso(),
            "opened_at": (
                _now_iso() if failures >= _CIRCUIT_FAILURE_THRESHOLD else circuit.get("opened_at")
            ),
        }
    health["circuit"] = circuit
    try:
        await store.upsert_payment_provider(
            organization_id,
            provider=provider,
            display_name=record.get("display_name") or provider.upper(),
            mode=str(record.get("mode") or "test"),
            sandbox=bool(record.get("sandbox")),
            credential_ref=record.get("credential_ref"),
            config=dict(record.get("config") or {}),
            capabilities=list(record.get("capabilities") or C.PAYMENT_CAPABILITIES),
            events=list(record.get("events") or C.PAYMENT_EVENTS),
            health=health,
            status=str(record.get("status") or "connected"),
        )
    except Exception as exc:  # noqa: BLE001 — el breaker no puede romper el cobro
        logger.warning("circuit report failed", provider=provider, error=str(exc)[:160])


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


async def _payment_binding(organization_id: UUID) -> dict[str, Any] | None:
    from src.platform.workflows.bindings import resolve_binding

    try:
        return await resolve_binding(organization_id, C.CAP_PAYMENT_CHECKOUT_CREATE)
    except Exception as exc:  # noqa: BLE001
        logger.warning("payment binding lookup failed", error=str(exc)[:160])
        return None


def _order_reference(order: dict[str, Any]) -> str:
    return str(order.get("order_number") or order.get("order_id"))


# ---------------------------------------------------------------------------
# checkout.create
# ---------------------------------------------------------------------------
async def create_checkout(
    organization_id: UUID,
    inputs: dict[str, Any],
    *,
    workflow_instance_id: str | None = None,
    node_id: str | None = None,
    workspace_id: UUID | None = None,
    notification_url: str | None = None,
) -> dict[str, Any]:
    """Crea (o recupera) el checkout de una orden. El monto es SIEMPRE server-side."""
    order = await _resolve_order(organization_id, inputs)
    if order is None:
        raise PaymentProviderError("ORDER_NOT_FOUND", "orden no encontrada para el checkout")
    if order["status"] in (C.ORDER_CANCELLED, C.ORDER_EXPIRED):
        raise PaymentProviderError("ORDER_CLOSED", f"la orden está {order['status']}")
    if order["status"] == C.ORDER_PAID:
        existing = await store.find_checkout(organization_id, reference=_order_reference(order))
        if existing:
            return _checkout_output(existing)
    amount = Decimal(str(order["total"]))
    if amount <= 0:
        raise PaymentProviderError("INVALID_AMOUNT", "la orden no tiene total cobrable")
    currency = str(order["currency"] or "PEN").upper()
    provider, adapter = await ensure_provider(
        organization_id, provider=inputs.get("provider"), config=None
    )
    reference = _order_reference(order)
    idempotency_key = store.stable_operation_key(
        organization_id=organization_id,
        workflow_instance_id=workflow_instance_id or order.get("workflow_instance_id"),
        node_id=node_id,
        business_operation_id=f"checkout:{reference}",
    )
    existing = await store.find_checkout(organization_id, idempotency_key=idempotency_key)
    if existing and existing["status"] in _TERMINAL_CHECKOUT:
        return _checkout_output(existing)
    if existing:
        # La operación lógica ya existe: se devuelve el MISMO checkout.
        return _checkout_output(existing)
    await _circuit_guard(organization_id, provider)
    ttl = int(inputs.get("ttl_seconds") or 1800)
    request = CheckoutRequest(
        organization_id=str(organization_id),
        order_id=order["order_id"],
        order_number=order["order_number"],
        amount=amount,
        currency=currency,
        idempotency_key=idempotency_key,
        reference=reference,
        customer=dict(order.get("customer") or {}),
        expires_in_seconds=ttl,
        notification_url=notification_url,
    )
    try:
        result = await adapter.create_checkout(request)
        await _circuit_report(organization_id, provider, ok=True)
    except PaymentProviderError as exc:
        await _circuit_report(organization_id, provider, ok=False)
        raise
    except Exception as exc:  # noqa: BLE001
        await _circuit_report(organization_id, provider, ok=False)
        raise PaymentProviderError("PROVIDER_ERROR", f"checkout falló: {str(exc)[:200]}") from exc
    checkout = await store.upsert_checkout_session(
        organization_id,
        order_id=order["order_id"],
        provider=provider,
        reference=reference,
        idempotency_key=idempotency_key,
        amount=amount,
        currency=currency,
        status="pending",
        provider_reference=result.provider_reference,
        checkout_url=result.checkout_url,
        qr_payload=result.qr_payload,
        qr_image_url=result.qr_image_url,
        workflow_instance_id=workflow_instance_id or order.get("workflow_instance_id"),
        node_id=node_id,
        raw=dict(result.raw or {}),
    )
    order_after = order
    if order["status"] != C.ORDER_AWAITING_PAYMENT:
        order_after = await store.transition_order(
            organization_id,
            order_id=order["order_id"],
            target_status=C.ORDER_AWAITING_PAYMENT,
            payment_reference=reference,
            payment_provider=provider,
            payment_status="pending",
        )
    reservation = await _maybe_reserve(organization_id, order_after, checkout, inputs)
    if reservation:
        await store.transition_order(
            organization_id,
            order_id=order["order_id"],
            target_status=C.ORDER_AWAITING_PAYMENT,
            reservation_id=reservation.get("reservation_id"),
        )
    return _checkout_output(checkout)


def _checkout_output(checkout: dict[str, Any]) -> dict[str, Any]:
    return {
        "checkout_id": checkout["checkout_id"],
        "provider": checkout["provider"],
        "status": checkout["status"],
        "amount": checkout["amount"],
        "currency": checkout["currency"],
        "reference": checkout["reference"],
        "checkout_url": checkout.get("checkout_url"),
        "qr_payload": checkout.get("qr_payload"),
        "qr_image_url": checkout.get("qr_image_url"),
        "expires_at": checkout.get("expires_at"),
        "order_id": checkout.get("order_id"),
        "payment_instructions": store.format_payment_instructions(checkout),
    }


async def _resolve_order(organization_id: UUID, inputs: dict[str, Any]) -> dict[str, Any] | None:
    if inputs.get("order_id"):
        return await store.get_order(organization_id, order_id=str(inputs["order_id"]))
    if inputs.get("order_number"):
        return await store.get_order(organization_id, order_number=str(inputs["order_number"]))
    return None


async def _maybe_reserve(
    organization_id: UUID,
    order: dict[str, Any],
    checkout: dict[str, Any],
    inputs: dict[str, Any],
) -> dict[str, Any] | None:
    """Política de reserva configurable. Default: reservar al crear checkout."""
    policy = str(
        inputs.get("reservation_policy")
        or order.get("metadata", {}).get("reservation_policy")
        or C.RESERVATION_POLICY_CHECKOUT
    )
    if policy != C.RESERVATION_POLICY_CHECKOUT:
        return None
    if order.get("reservation_id"):
        return None
    items = [
        {"product_id": item.get("product_id"), "quantity": item.get("quantity")}
        for item in order.get("items") or []
        if item.get("product_id")
    ]
    if not items:
        return None
    try:
        return await store.stock_reserve(
            organization_id,
            items=items,
            order_id=order["order_id"],
            workflow_instance_id=order.get("workflow_instance_id"),
            ttl_seconds=int(inputs.get("ttl_seconds") or 1800),
        )
    except store.CommerceError as exc:
        # Sin stock: el checkout no debe existir sin reserva posible.
        if str(checkout.get("status")) == "pending":
            await store.update_checkout_status(
                organization_id=organization_id,
                checkout_id=checkout["checkout_id"],
                status="failed",
            )
        raise PaymentProviderError(f"STOCK_{exc.code}", exc.message) from exc


# ---------------------------------------------------------------------------
# qr.create / status.get / cancel / refund
# ---------------------------------------------------------------------------
async def create_qr(organization_id: UUID, inputs: dict[str, Any]) -> dict[str, Any]:
    checkout = await _resolve_checkout(organization_id, inputs)
    if checkout is None:
        raise PaymentProviderError("CHECKOUT_NOT_FOUND", "checkout no encontrado")
    payload = checkout.get("qr_payload") or checkout.get("checkout_url")
    if payload and not checkout.get("qr_payload"):
        updated = await store.update_checkout_status(
            organization_id=organization_id,
            checkout_id=checkout["checkout_id"],
            status=checkout["status"],
            qr_payload=payload,
        )
        checkout = updated or checkout
    return {
        "checkout_id": checkout["checkout_id"],
        "qr_payload": checkout.get("qr_payload") or payload,
        "qr_image_url": checkout.get("qr_image_url"),
        "amount": checkout["amount"],
        "currency": checkout["currency"],
        "status": checkout["status"],
        "provider": checkout["provider"],
        "reference": checkout["reference"],
    }


async def payment_status(organization_id: UUID, inputs: dict[str, Any]) -> dict[str, Any]:
    """Estado del pago. Autoridad = registro local; el proveedor es consultivo."""
    checkout = await _resolve_checkout(organization_id, inputs)
    if checkout is None:
        order = await store.get_order(
            organization_id,
            order_number=inputs.get("order_number") or inputs.get("reference"),
        )
        if order is None:
            raise PaymentProviderError("CHECKOUT_NOT_FOUND", "pago no encontrado")
        return {
            "reference": order["order_number"],
            "status": order.get("payment_status") or order["status"],
            "provider": order.get("payment_provider"),
            "amount": order["total"],
            "currency": order["currency"],
            "order_id": order["order_id"],
        }
    provider_status: str | None = None
    adapter: PaymentProviderAdapter | None = None
    try:
        _provider, adapter = await ensure_provider(
            organization_id, provider=checkout["provider"], config={"query_provider_status": True}
        )
        if adapter and checkout.get("reference"):
            remote = await adapter.get_status(checkout["reference"])
            provider_status = str(remote.get("status") or "")
    except PaymentProviderError as exc:
        provider_status = f"unavailable:{exc.code}"
    return {
        "reference": checkout["reference"],
        "checkout_id": checkout["checkout_id"],
        "order_id": checkout["order_id"],
        "status": checkout["status"],
        "provider": checkout["provider"],
        "provider_status": provider_status,
        "amount": checkout["amount"],
        "currency": checkout["currency"],
    }


async def cancel_payment(organization_id: UUID, inputs: dict[str, Any]) -> dict[str, Any]:
    checkout = await _resolve_checkout(organization_id, inputs)
    if checkout is None:
        raise PaymentProviderError("CHECKOUT_NOT_FOUND", "checkout no encontrado")
    if checkout["status"] in ("succeeded", "refunded"):
        raise PaymentProviderError("ALREADY_PAID", "el pago ya se completó")
    if checkout["status"] != "cancelled":
        _provider, adapter = await ensure_provider(organization_id, provider=checkout["provider"])
        try:
            await adapter.cancel(checkout.get("provider_reference") or checkout["reference"])
        except PaymentProviderError as exc:
            logger.warning("provider cancel failed", provider=checkout["provider"], error=exc.code)
        await store.update_checkout_status(
            organization_id=organization_id,
            checkout_id=checkout["checkout_id"],
            status="cancelled",
        )
    order = await store.get_order(organization_id, order_id=checkout["order_id"])
    if order and order["status"] == C.ORDER_AWAITING_PAYMENT:
        await store.transition_order(
            organization_id, order_id=order["order_id"], target_status=C.ORDER_CANCELLED
        )
    await store.stock_release(organization_id, order_id=checkout["order_id"])
    return {"cancelled": True, "checkout_id": checkout["checkout_id"], "reference": checkout["reference"]}


async def refund_payment(organization_id: UUID, inputs: dict[str, Any]) -> dict[str, Any]:
    checkout = await _resolve_checkout(organization_id, inputs)
    if checkout is None:
        raise PaymentProviderError("CHECKOUT_NOT_FOUND", "checkout no encontrado")
    if checkout["status"] != "succeeded":
        raise PaymentProviderError("NOT_PAID", "solo se reembolsa un pago confirmado")
    amount = inputs.get("amount")
    _provider, adapter = await ensure_provider(organization_id, provider=checkout["provider"])
    result = await adapter.refund(
        checkout.get("provider_reference") or checkout["reference"],
        Decimal(str(amount)) if amount is not None else None,
    )
    await store.update_checkout_status(
        organization_id=organization_id,
        checkout_id=checkout["checkout_id"],
        status="refunded",
    )
    return {"refunded": True, "checkout_id": checkout["checkout_id"], **result}


async def _resolve_checkout(
    organization_id: UUID, inputs: dict[str, Any]
) -> dict[str, Any] | None:
    if inputs.get("checkout_id"):
        return await store.find_checkout(organization_id, checkout_id=str(inputs["checkout_id"]))
    if inputs.get("reference"):
        return await store.find_checkout(organization_id, reference=str(inputs["reference"]))
    if inputs.get("order_id"):
        order = await store.get_order(organization_id, order_id=str(inputs["order_id"]))
        if order:
            return await store.find_checkout(
                organization_id, reference=str(order["order_number"])
            )
    if inputs.get("order_number"):
        order = await store.get_order(organization_id, order_number=str(inputs["order_number"]))
        if order:
            return await store.find_checkout(
                organization_id, reference=str(order["order_number"])
            )
    return None


# ---------------------------------------------------------------------------
# Ingestión de webhooks de proveedor
# ---------------------------------------------------------------------------
async def ingest_provider_webhook(
    provider: str,
    *,
    raw_body: bytes,
    headers: dict[str, str],
) -> dict[str, Any]:
    """webhook → firma → normalización → dedupe → BusinessEvent → signal.

    El tenant se resuelve desde NUESTRO registro (checkout), nunca desde el
    payload: un payload externo no puede elegir organización ni instancia.
    """
    key = str(provider or "").strip().lower()
    if key not in C.PAYMENT_PROVIDERS:
        raise PaymentProviderError("PROVIDER_UNKNOWN", f"proveedor desconocido: {provider}")
    # El adapter necesita las credenciales del tenant para verificar la firma.
    # Se prueban los tenants que tienen ese proveedor configurado; la firma
    # falla cerrada si ninguno valida.
    candidates = await _tenants_with_provider(key)
    verified: list[tuple[UUID, NormalizedPaymentEvent]] = []
    last_error: Exception | None = None
    for organization_id in candidates:
        _provider, adapter = await ensure_provider(
            organization_id, provider=key, config={"query_provider_status": False}
        )
        try:
            verified.append((organization_id, adapter.verify_webhook(raw_body, headers)))
        except Exception as exc:  # noqa: BLE001 — se prueba el siguiente tenant
            last_error = exc
            continue
    if not verified:
        await store.record_provider_event(
            provider=key,
            provider_event_id=_fallback_event_id(raw_body),
            event_type="unverified",
            organization_id=None,
            verified=False,
            normalized_event={},
            correlation={},
            processing_status="rejected",
            processing_error=str(last_error)[:200] if last_error else "firma no verificable",
            signature_mode="none",
        )
        raise PaymentProviderError(
            "SIGNATURE_INVALID",
            "no se pudo verificar la firma del webhook con ningún proveedor configurado",
        )

    # La firma identifica al tenant firmante. El checkout DEBE pertenecer a ese
    # mismo tenant; validar la firma y luego buscar una referencia global sería
    # cross-tenant. Se prueban solo los tenants cuya firma verificó.
    checkout: dict[str, Any] | None = None
    normalized: NormalizedPaymentEvent | None = None
    signer_organization_id: UUID | None = None
    for organization_id, event in verified:
        candidate = None
        if event.provider_reference:
            candidate = await store.find_checkout(
                organization_id,
                provider_reference=str(event.provider_reference),
                provider=key,
            )
        if candidate is None and event.reference:
            candidate = await store.find_checkout(
                organization_id, reference=str(event.reference), provider=key
            )
        if candidate is None:
            continue
        if str(candidate.get("provider") or "") != key:
            continue
        if checkout is not None and checkout["checkout_id"] != candidate["checkout_id"]:
            raise PaymentProviderError(
                "TENANT_MISMATCH",
                "el evento resuelve más de un checkout para firmantes distintos",
            )
        checkout = candidate
        normalized = event
        signer_organization_id = organization_id

    if checkout is None or normalized is None or signer_organization_id is None:
        first = verified[0][1]
        foreign = None
        if first.provider_reference:
            foreign = await store.find_checkout_any_tenant(
                provider=key, provider_reference=str(first.provider_reference)
            )
        if foreign is None and first.reference:
            foreign = await store.find_checkout_by_reference_any_tenant(first.reference)
        if foreign is not None:
            await store.record_provider_event(
                provider=key,
                provider_event_id=first.provider_event_id,
                event_type=first.event_type,
                organization_id=str(foreign["organization_id"]),
                verified=True,
                normalized_event=first.payload(),
                correlation=first.correlation(),
                processing_status="tenant_mismatch",
                processing_error="la firma y el checkout pertenecen a tenants distintos",
                signature_mode=first.signature_mode,
            )
            raise PaymentProviderError(
                "TENANT_MISMATCH",
                "el checkout no pertenece al tenant cuya credencial firmó el webhook",
            )
        outcome, _ = await store.record_provider_event(
            provider=key,
            provider_event_id=first.provider_event_id,
            event_type=first.event_type,
            organization_id=None,
            verified=True,
            normalized_event=first.payload(),
            correlation=first.correlation(),
            processing_status="unmatched",
            processing_error="checkout no encontrado para el tenant que firmó el evento",
            signature_mode=first.signature_mode,
        )
        return {"status": outcome, "event_type": first.event_type, "matched": False}

    organization_id = str(checkout["organization_id"])
    if str(signer_organization_id) != organization_id:
        await store.record_provider_event(
            provider=key,
            provider_event_id=normalized.provider_event_id,
            event_type=normalized.event_type,
            organization_id=organization_id,
            verified=True,
            normalized_event=normalized.payload(),
            correlation=normalized.correlation(),
            processing_status="tenant_mismatch",
            processing_error="la firma y el checkout pertenecen a tenants distintos",
            signature_mode=normalized.signature_mode,
        )
        raise PaymentProviderError(
            "TENANT_MISMATCH",
            "el checkout no pertenece al tenant cuya credencial firmó el webhook",
        )

    # Monto y moneda deben coincidir con NUESTRO checkout. Un payload firmado
    # con otro importe o moneda no puede avanzar el proceso ni marcar venta.
    from decimal import Decimal as _Decimal

    if normalized.amount is not None and _Decimal(str(normalized.amount)) != _Decimal(
        str(checkout["amount"])
    ):
        await store.record_provider_event(
            provider=key,
            provider_event_id=normalized.provider_event_id,
            event_type=normalized.event_type,
            organization_id=organization_id,
            verified=True,
            normalized_event=normalized.payload(),
            correlation=normalized.correlation(),
            processing_status="amount_mismatch",
            processing_error=(
                f"monto del evento {normalized.amount} != checkout {checkout['amount']}"
            ),
            signature_mode=normalized.signature_mode,
        )
        raise PaymentProviderError(
            "AMOUNT_MISMATCH",
            "el monto del evento no coincide con el checkout registrado",
        )
    if (
        normalized.currency
        and str(normalized.currency).strip().upper()
        != str(checkout["currency"]).strip().upper()
    ):
        await store.record_provider_event(
            provider=key,
            provider_event_id=normalized.provider_event_id,
            event_type=normalized.event_type,
            organization_id=organization_id,
            verified=True,
            normalized_event=normalized.payload(),
            correlation=normalized.correlation(),
            processing_status="currency_mismatch",
            processing_error=(
                f"moneda del evento {normalized.currency} != checkout {checkout['currency']}"
            ),
            signature_mode=normalized.signature_mode,
        )
        raise PaymentProviderError(
            "CURRENCY_MISMATCH",
            "la moneda del evento no coincide con el checkout registrado",
        )
    correlation = normalized.correlation()
    outcome, existing = await store.record_provider_event(
        provider=key,
        provider_event_id=normalized.provider_event_id,
        event_type=normalized.event_type,
        organization_id=organization_id,
        verified=True,
        normalized_event=normalized.payload(),
        correlation=correlation,
        processing_status="received",
        signature_mode=normalized.signature_mode,
    )
    if outcome == "duplicate":
        existing_status = str((existing or {}).get("processing_status") or "")
        existing_org = (existing or {}).get("organization_id")
        if existing_org and str(existing_org) != str(organization_id):
            raise PaymentProviderError(
                "TENANT_MISMATCH",
                "el evento ya existe asociado a otro tenant",
            )
        # Un evento que quedó `received`/`processing`/`failed` por una caída
        # debe poder recuperarse. Los efectos son idempotentes; solo
        # `processed` se considera terminalmente aplicado.
        if existing_status not in ("received", "processing", "failed"):
            return {
                "status": "duplicate",
                "event_type": normalized.event_type,
                "matched": True,
                "organization_id": organization_id,
            }
        logger.warning(
            "recovering incomplete provider event",
            provider=key,
            provider_event_id=normalized.provider_event_id,
            previous_status=existing_status,
        )
    try:
        await _apply_event_state(organization_id, checkout, normalized)
        signal_result = await _signal_from_event(
            organization_id, checkout, normalized, provider=key
        )
        await store.mark_provider_event(
            normalized.provider_event_id, status="processed"
        )
    except Exception as exc:  # noqa: BLE001 — deja el evento recuperable
        try:
            await store.mark_provider_event(
                normalized.provider_event_id,
                status="failed",
                error=str(exc)[:400],
            )
        except Exception:  # noqa: BLE001
            logger.warning("provider event failure mark failed", provider=key)
        raise
    return {
        "status": "processed",
        "event_type": normalized.event_type,
        "matched": True,
        "organization_id": organization_id,
        "checkout_id": checkout["checkout_id"],
        "signal": signal_result,
        "recovered": bool(outcome == "duplicate"),
    }


async def _apply_event_state(
    organization_id: str, checkout: dict[str, Any], event: NormalizedPaymentEvent
) -> None:
    """Efectos deterministas locales ANTES de la señal (fuente de verdad)."""
    org = UUID(str(organization_id))
    status_map = {
        C.EVENT_PAYMENT_SUCCEEDED: "succeeded",
        C.EVENT_PAYMENT_FAILED: "failed",
        C.EVENT_PAYMENT_EXPIRED: "expired",
        C.EVENT_PAYMENT_REFUNDED: "refunded",
        C.EVENT_PAYMENT_CANCELLED: "cancelled",
        C.EVENT_PAYMENT_PENDING: "pending",
    }
    local_status = status_map.get(event.event_type, "pending")
    current = str(checkout.get("status"))
    if current == "succeeded" and local_status != "refunded":
        # Recuperación tras caída: si el evento alcanzó a marcar el checkout
        # pero no la reserva, se restituye solo mientras la orden siga abierta.
        order = await store.get_order(org, order_id=checkout["order_id"])
        if (
            event.event_type == C.EVENT_PAYMENT_SUCCEEDED
            and order is not None
            and order["status"] not in (C.ORDER_PAID, C.ORDER_CANCELLED, C.ORDER_EXPIRED)
        ):
            await _ensure_reservation(org, order, checkout)
        return
    # Idempotencia: un checkout ya cerrado no vuelve atrás.
    if current in _TERMINAL_CHECKOUT and current == local_status:
        return
    await store.update_checkout_status(
        organization_id=org,
        checkout_id=checkout["checkout_id"],
        status=local_status,
    )
    order = await store.get_order(org, order_id=checkout["order_id"])
    if order is None:
        return
    if event.event_type == C.EVENT_PAYMENT_SUCCEEDED:
        # El pago confirmado restituye la reserva si un intento anterior la
        # liberó: el workflow confirma inventario con una reserva viva.
        await _ensure_reservation(org, order, checkout)
    if event.event_type == C.EVENT_PAYMENT_FAILED:
        await store.stock_release(org, order_id=order["order_id"])
        await _notify_customer(
            org,
            C.EVENT_PAYMENT_FAILED,
            "Pago no completado",
            (
                f"El pago de {store.format_money(order['total'], order['currency'])} "
                "no se pudo completar. Puedes intentarlo de nuevo con el mismo "
                "enlace o QR."
            ),
            checkout,
        )
    elif event.event_type in (C.EVENT_PAYMENT_EXPIRED, C.EVENT_PAYMENT_CANCELLED):
        await store.stock_release(org, order_id=order["order_id"])
        await _notify_customer(
            org,
            C.EVENT_PAYMENT_EXPIRED,
            "Pago expirado",
            (
                "El tiempo para completar el pago terminó. "
                "Escríbeme cuando quieras retomar tu pedido."
            ),
            checkout,
        )
    # `payment.succeeded` NO marca la orden PAID aquí: eso es un paso explícito
    # del workflow (sales.order.mark_paid), para que la venta la cree el
    # proceso de negocio y no un payload externo.


async def _ensure_reservation(
    organization_id: UUID, order: dict[str, Any], checkout: dict[str, Any]
) -> None:
    """Restituye la reserva si un intento previo la liberó (pago confirmado)."""
    policy = str(
        (order.get("metadata") or {}).get("reservation_policy") or C.RESERVATION_POLICY_CHECKOUT
    )
    if policy != C.RESERVATION_POLICY_CHECKOUT:
        return
    items = [
        {"product_id": item.get("product_id"), "quantity": item.get("quantity")}
        for item in order.get("items") or []
        if item.get("product_id")
    ]
    if not items:
        return
    if await store.has_held_reservation(organization_id, order_id=order["order_id"]):
        return
    try:
        await store.stock_reserve(
            organization_id,
            items=items,
            order_id=order["order_id"],
            workflow_instance_id=order.get("workflow_instance_id"),
            ttl_seconds=1800,
        )
    except store.CommerceError as exc:
        logger.warning(
            "reservation restore failed",
            order_id=order.get("order_id"),
            code=exc.code,
            error=exc.message[:160],
        )


async def _notify_customer(    organization_id: UUID,
    event_type: str,
    title: str,
    body: str,
    checkout: dict[str, Any],
) -> None:
    """Aviso determinista al cliente del proceso (no depende del LLM ni del workflow)."""
    try:
        from src.platform.notifyv2.notifications import notify

        await notify(
            organization_id,
            event_type,
            title,
            body,
            {
                "checkout_id": checkout.get("checkout_id"),
                "reference": checkout.get("reference"),
                "workflow_instance_id": checkout.get("workflow_instance_id"),
            },
            channels={"in_app"},
        )
    except Exception as exc:  # noqa: BLE001 — el aviso nunca rompe la ingesta
        logger.warning("payment customer notice failed", event=event_type, error=str(exc)[:160])


async def _signal_from_event(
    organization_id: str,
    checkout: dict[str, Any],
    event: NormalizedPaymentEvent,
    *,
    provider: str,
) -> dict[str, Any]:
    from src.platform.workflows.instances import signal_workflow_instance

    correlation = event.correlation()
    correlation.setdefault("payment_reference", checkout["reference"])
    instance_id = checkout.get("workflow_instance_id")
    result = await signal_workflow_instance(
        organization_id=UUID(str(organization_id)),
        event_type=event.event_type,
        correlation=correlation,
        payload={**event.payload(), "checkout_id": checkout["checkout_id"]},
        external_event_id=f"{provider}:{event.provider_event_id}",
        idempotency_key=f"payevt:{provider}:{event.provider_event_id}",
        source="provider_webhook",
        instance_id=UUID(str(instance_id)) if instance_id else None,
    )
    return {
        "status": result.get("status"),
        "resumed": result.get("resumed"),
        "signal_id": result.get("signal_id"),
    }


async def _tenants_with_provider(provider: str) -> list[UUID]:
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    await store.ensure_commerce_tables()
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT organization_id FROM commerce_payment_providers "
                    "WHERE provider = :prov AND status = 'connected' ORDER BY created_at"
                ),
                {"prov": provider},
            )
        ).fetchall()
    finally:
        await session.close()
    return [UUID(str(r.organization_id)) for r in rows]


def _fallback_event_id(raw_body: bytes) -> str:
    import hashlib as _hashlib

    return "unverified:" + _hashlib.sha256(raw_body).hexdigest()[:40]


__all__ = [
    "configure_provider",
    "ensure_provider",
    "create_checkout",
    "create_qr",
    "payment_status",
    "cancel_payment",
    "refund_payment",
    "ingest_provider_webhook",
    "credential_connector_id",
]
