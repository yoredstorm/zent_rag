# =============================================================================
# Payment providers — adapters concretos detrás del contrato de capacidades
# =============================================================================
# Ningún workflow conoce estos nombres: el binding del tenant resuelve
# `payments.checkout.create` contra IZIPAY, Stripe o el sandbox determinista.
#
# Reglas comunes:
#   - la firma del webhook se verifica SIEMPRE antes de normalizar;
#   - el monto enviado al proveedor viene de la orden persistida;
#   - la creación de checkout viaja con Idempotency-Key estable, de modo que un
#     retry por timeout no crea un segundo cobro;
#   - las credenciales viven en el SecretStore, jamás en el código ni en un
#     manifest.
# =============================================================================
from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import httpx

from src.infrastructure.observability.logging_config import get_logger
from src.platform.commerce.payments.base import (
    CheckoutRequest,
    CheckoutResult,
    NormalizedPaymentEvent,
    PaymentProviderAdapter,
    PaymentProviderError,
    PaymentTimeoutError,
    SignatureVerificationError,
    to_cents,
)

logger = get_logger(__name__)

_HTTP_TIMEOUT = 20.0
_SIGNATURE_TOLERANCE_SECONDS = 300


def _cents_to_decimal(cents: Any) -> Decimal | None:
    try:
        return (Decimal(str(cents)) / 100).quantize(Decimal("0.01"))
    except Exception:  # noqa: BLE001
        return None


def _event_type_for_status(status: str) -> str:
    value = str(status or "").upper()
    if value in ("PAID", "CAPTURED", "AUTHORISED", "AUTHORIZED", "SUCCEEDED"):
        return "payment.succeeded"
    if value in ("REFUSED", "FAILED", "UNPAID", "REJECTED"):
        return "payment.failed"
    if value in ("EXPIRED",):
        return "payment.expired"
    if value in ("CANCELLED", "CANCELED"):
        return "payment.cancelled"
    if value in ("REFUNDED", "PARTIALLY_REFUNDED"):
        return "payment.refunded"
    if value in ("PENDING", "RUNNING", "INITIAL", "CREATED"):
        return "payment.pending"
    return "payment.pending"


# ---------------------------------------------------------------------------
# Sandbox determinista (CI / desarrollo / demo verificable)
# ---------------------------------------------------------------------------
class SandboxPaymentAdapter(PaymentProviderAdapter):
    """Proveedor local determinista: mismo contrato, cero red.

    Existe para que el Gold Test y el CI prueben el camino financiero completo
    (checkout → QR → webhook firmado → dedupe → señal → venta) sin depender de
    una pasarela externa. La firma es HMAC real sobre el body crudo.
    """

    name = "sandbox"
    supports_qr = True
    required_secrets = ("webhook_secret",)

    def _secret(self) -> str:
        return str(self.secrets.get("webhook_secret") or "zent-sandbox-payment-secret")

    async def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        provider_reference = f"sbx_{uuid4().hex[:20]}"
        base = str(self.config.get("payment_page_url") or "https://sandbox.zent.local/pay")
        url = f"{base.rstrip('/')}/{request.reference}?ref={provider_reference}"
        return CheckoutResult(
            provider=self.name,
            provider_reference=provider_reference,
            status="pending",
            checkout_url=url,
            qr_payload=url,
            qr_image_url=None,
            expires_in_seconds=request.expires_in_seconds,
            raw={"sandbox": True, "amount_cents": to_cents(request.amount)},
        )

    async def get_status(self, reference: str) -> dict[str, Any]:
        raise PaymentProviderError(
            "PROVIDER_STATUS_LOCAL",
            "el sandbox no consulta estado remoto: el estado local es la autoridad",
        )

    async def cancel(self, reference: str) -> bool:
        return True

    async def refund(self, reference: str, amount: Decimal | None = None) -> dict[str, Any]:
        return {
            "refunded": True,
            "provider": self.name,
            "reference": reference,
            "amount": float(amount) if amount is not None else None,
        }

    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> NormalizedPaymentEvent:
        header = ""
        for key, value in headers.items():
            if key.lower() == "x-zent-signature":
                header = str(value)
                break
        if not header.startswith("sha256="):
            raise SignatureVerificationError("falta el header X-Zent-Signature")
        expected = hmac.new(self._secret().encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        provided = header.split("=", 1)[1].strip()
        if not hmac.compare_digest(expected, provided):
            raise SignatureVerificationError("firma sandbox inválida")
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise SignatureVerificationError(f"payload ilegible: {str(exc)[:80]}") from exc
        event_id = str(body.get("event_id") or body.get("id") or "")
        if not event_id:
            raise SignatureVerificationError("event_id requerido")
        status = str(body.get("status") or "paid")
        return NormalizedPaymentEvent(
            provider=self.name,
            provider_event_id=event_id,
            provider_event_type=str(body.get("type") or status),
            event_type=str(body.get("event_type") or _event_type_for_status(status)),
            reference=body.get("reference"),
            provider_reference=body.get("provider_reference"),
            amount=_cents_to_decimal(body.get("amount_cents"))
            if body.get("amount_cents") is not None
            else (Decimal(str(body["amount"])) if body.get("amount") is not None else None),
            currency=body.get("currency"),
            status=status,
            occurred_at=body.get("occurred_at"),
            signature_mode="hmac-sha256",
            raw=body,
        )


# ---------------------------------------------------------------------------
# Stripe
# ---------------------------------------------------------------------------
class StripePaymentAdapter(PaymentProviderAdapter):
    """Stripe Checkout Sessions + verificación de firma `Stripe-Signature`."""

    name = "stripe"
    supports_qr = False
    required_secrets = ("secret_key", "webhook_secret")
    api_base = "https://api.stripe.com/v1"

    def _secret_key(self) -> str:
        return str(self.secrets.get("secret_key") or "")

    def _webhook_secret(self) -> str:
        return str(self.secrets.get("webhook_secret") or "")

    async def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        if not self._secret_key():
            raise PaymentProviderError("NEEDS_CREDENTIALS", "falta secret_key de Stripe")
        base = str(self.config.get("api_base") or self.api_base)
        return_url = str(
            self.config.get("return_url")
            or request.return_url
            or "https://portal.zent.local/payments/return"
        )
        form = {
            "mode": "payment",
            "success_url": f"{return_url}?status=success&ref={request.reference}",
            "cancel_url": f"{return_url}?status=cancel&ref={request.reference}",
            "client_reference_id": request.reference,
            "metadata[order_id]": request.order_id,
            "metadata[order_number]": request.order_number,
            "payment_intent_data[metadata][order_number]": request.order_number,
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": request.currency.lower(),
            "line_items[0][price_data][unit_amount]": str(to_cents(request.amount)),
            "line_items[0][price_data][product_data][name]": f"Pedido {request.order_number}",
        }
        headers = {
            "Authorization": f"Bearer {self._secret_key()}",
            "Idempotency-Key": request.idempotency_key,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                response = await client.post(f"{base}/checkout/sessions", data=form, headers=headers)
        except httpx.TimeoutException as exc:
            raise PaymentTimeoutError(f"Stripe no respondió en {_HTTP_TIMEOUT}s") from exc
        except httpx.HTTPError as exc:
            raise PaymentProviderError("PROVIDER_UNREACHABLE", str(exc)[:200]) from exc
        if response.status_code >= 400:
            raise PaymentProviderError(
                "PROVIDER_HTTP_ERROR", f"Stripe HTTP {response.status_code}: {response.text[:200]}"
            )
        body = response.json()
        return CheckoutResult(
            provider=self.name,
            provider_reference=str(body.get("id") or ""),
            status="pending",
            checkout_url=body.get("url"),
            qr_payload=body.get("url"),
            expires_in_seconds=request.expires_in_seconds,
            raw={"stripe": {"id": body.get("id"), "amount_total": body.get("amount_total")}},
        )

    async def get_status(self, reference: str) -> dict[str, Any]:
        if not self._secret_key():
            raise PaymentProviderError("NEEDS_CREDENTIALS", "falta secret_key de Stripe")
        base = str(self.config.get("api_base") or self.api_base)
        headers = {"Authorization": f"Bearer {self._secret_key()}"}
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                response = await client.get(
                    f"{base}/checkout/sessions",
                    params={"limit": 1, "client_reference_id": reference},
                    headers=headers,
                )
        except httpx.TimeoutException as exc:
            raise PaymentTimeoutError("Stripe no respondió") from exc
        if response.status_code >= 400:
            raise PaymentProviderError("PROVIDER_HTTP_ERROR", f"Stripe HTTP {response.status_code}")
        data = (response.json() or {}).get("data") or []
        if not data:
            return {"status": "not_found", "provider": self.name}
        session = data[0]
        return {
            "provider": self.name,
            "status": session.get("payment_status") or session.get("status"),
            "checkout_url": session.get("url"),
            "provider_reference": session.get("id"),
        }

    async def cancel(self, reference: str) -> bool:
        if not self._secret_key():
            raise PaymentProviderError("NEEDS_CREDENTIALS", "falta secret_key de Stripe")
        base = str(self.config.get("api_base") or self.api_base)
        headers = {"Authorization": f"Bearer {self._secret_key()}"}
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                response = await client.post(f"{base}/checkout/sessions/{reference}/expire", headers=headers)
        except httpx.HTTPError as exc:
            raise PaymentProviderError("PROVIDER_UNREACHABLE", str(exc)[:200]) from exc
        return response.status_code < 400

    async def refund(self, reference: str, amount: Decimal | None = None) -> dict[str, Any]:
        if not self._secret_key():
            raise PaymentProviderError("NEEDS_CREDENTIALS", "falta secret_key de Stripe")
        base = str(self.config.get("api_base") or self.api_base)
        data: dict[str, str] = {"payment_intent": reference}
        if amount is not None:
            data["amount"] = str(to_cents(amount))
        headers = {"Authorization": f"Bearer {self._secret_key()}"}
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                response = await client.post(f"{base}/refunds", data=data, headers=headers)
        except httpx.HTTPError as exc:
            raise PaymentProviderError("PROVIDER_UNREACHABLE", str(exc)[:200]) from exc
        if response.status_code >= 400:
            raise PaymentProviderError("PROVIDER_HTTP_ERROR", f"Stripe HTTP {response.status_code}")
        body = response.json()
        return {"refunded": True, "refund_id": body.get("id"), "status": body.get("status")}

    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> NormalizedPaymentEvent:
        signature = ""
        for key, value in headers.items():
            if key.lower() == "stripe-signature":
                signature = str(value)
                break
        secret = self._webhook_secret()
        if not signature or not secret:
            raise SignatureVerificationError("falta Stripe-Signature o webhook_secret")
        parts = dict(
            item.split("=", 1) for item in signature.split(",") if "=" in item
        )
        timestamp = parts.get("t")
        provided = parts.get("v1")
        if not timestamp or not provided:
            raise SignatureVerificationError("header Stripe-Signature malformado")
        try:
            if abs(time.time() - int(timestamp)) > _SIGNATURE_TOLERANCE_SECONDS:
                raise SignatureVerificationError("webhook fuera de la ventana anti-replay")
        except ValueError as exc:
            raise SignatureVerificationError("timestamp inválido") from exc
        expected = hmac.new(
            secret.encode("utf-8"), f"{timestamp}.".encode("utf-8") + raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, provided):
            raise SignatureVerificationError("firma Stripe inválida")
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise SignatureVerificationError(f"payload ilegible: {str(exc)[:80]}") from exc
        event_id = str(body.get("id") or "")
        if not event_id:
            raise SignatureVerificationError("event id requerido")
        provider_type = str(body.get("type") or "")
        obj = ((body.get("data") or {}).get("object")) or {}
        reference = (
            obj.get("client_reference_id")
            or (obj.get("metadata") or {}).get("order_number")
            or None
        )
        if not reference and isinstance(obj.get("metadata"), dict):
            reference = obj["metadata"].get("order_number")
        amount = None
        if obj.get("amount_total") is not None:
            amount = _cents_to_decimal(obj["amount_total"])
        elif obj.get("amount") is not None:
            amount = _cents_to_decimal(obj["amount"])
        payment_status = str(
            obj.get("payment_status") or obj.get("status") or ""
        ).strip().lower()
        # Stripe: `checkout.session.completed` NO significa fondos confirmados.
        # En métodos asíncronos llega con payment_status=unpaid y la confirmación
        # real llega por checkout.session.async_payment_succeeded. Uncompleted
        # unpaid no puede despertar un WAIT de payment.succeeded.
        if provider_type == "checkout.session.completed":
            event_type = (
                "payment.succeeded"
                if payment_status in ("paid", "no_payment_required")
                else "payment.pending"
            )
        elif provider_type == "checkout.session.async_payment_succeeded":
            event_type = "payment.succeeded"
        elif provider_type == "checkout.session.async_payment_failed":
            event_type = "payment.failed"
        else:
            event_type = {
                "checkout.session.expired": "payment.expired",
                "payment_intent.succeeded": "payment.succeeded",
                "payment_intent.payment_failed": "payment.failed",
                "charge.refunded": "payment.refunded",
            }.get(provider_type, "")
        if not event_type:
            event_type = _event_type_for_status(payment_status)
        return NormalizedPaymentEvent(
            provider=self.name,
            provider_event_id=event_id,
            provider_event_type=provider_type,
            event_type=event_type,
            reference=reference,
            provider_reference=obj.get("id") or obj.get("payment_intent"),
            amount=amount,
            currency=str(obj.get("currency") or "").upper() or None,
            status=str(obj.get("payment_status") or obj.get("status") or ""),
            occurred_at=str(body.get("created") or ""),
            signature_mode="stripe-signature",
            raw=body,
        )


# ---------------------------------------------------------------------------
# IZIPAY (Lykke / monext — `micuentaweb` V4)
# ---------------------------------------------------------------------------
class IzipayPaymentAdapter(PaymentProviderAdapter):
    """IZIPAY `CreatePayment` + verificación KR-Hash de webhooks.

    Credenciales (SecretStore): `merchant_code` (shop id), `api_key` (password
    de API), `hash_key` (llave HMAC del webhook; si falta se usa `api_key`).

    `payment_page_url` es configurable porque la página de pago del comercio
    puede ser la hospedada por IZIPAY o un formulario embebido propio; el token
    de formulario viaja como `vads_form_token`.
    """

    name = "izipay"
    supports_qr = True
    required_secrets = ("merchant_code", "api_key")
    api_base = "https://api.micuentaweb.pe"
    payment_page = "https://secure.micuentaweb.pe/vads-payment/"

    def _merchant_code(self) -> str:
        return str(self.secrets.get("merchant_code") or "")

    def _api_key(self) -> str:
        return str(self.secrets.get("api_key") or "")

    def _hash_key(self) -> str:
        return str(self.secrets.get("hash_key") or self._api_key())

    def _mode(self) -> str:
        return str(self.config.get("mode") or ("test" if self.config.get("sandbox") else "live"))

    async def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        if not self._merchant_code() or not self._api_key():
            raise PaymentProviderError(
                "NEEDS_CREDENTIALS", "IZIPAY requiere merchant_code y api_key"
            )
        base = str(self.config.get("api_base") or self.api_base)
        payload = {
            "amount": to_cents(request.amount),
            "currency": request.currency.upper(),
            "orderId": request.reference,
            "channelOptions": {"channelType": "QR" if self.supports_qr else "URL"},
            "customer": {
                "email": (request.customer or {}).get("email") or "cliente@zent.local",
            },
        }
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                response = await client.post(
                    f"{base}/api-payment/V4/Charge/CreatePayment",
                    json=payload,
                    auth=(self._merchant_code(), self._api_key()),
                    headers={
                        "Content-Type": "application/json",
                        "Idempotency-Key": request.idempotency_key,
                    },
                )
        except httpx.TimeoutException as exc:
            raise PaymentTimeoutError(f"IZIPAY no respondió en {_HTTP_TIMEOUT}s") from exc
        except httpx.HTTPError as exc:
            raise PaymentProviderError("PROVIDER_UNREACHABLE", str(exc)[:200]) from exc
        if response.status_code >= 400:
            raise PaymentProviderError(
                "PROVIDER_HTTP_ERROR", f"IZIPAY HTTP {response.status_code}: {response.text[:200]}"
            )
        body = response.json()
        if str(body.get("status") or "").upper() != "SUCCESS":
            answer = body.get("answer") or {}
            raise PaymentProviderError(
                "PROVIDER_REJECTED",
                f"IZIPAY rechazó el checkout: {answer.get('errorCode')} {answer.get('errorMessage')}",
            )
        form_token = str((body.get("answer") or {}).get("formToken") or "")
        page = str(self.config.get("payment_page_url") or self.payment_page)
        query = urlencode({"vads_form_token": form_token, "vads_payment_ref": request.reference})
        url = f"{page}?{query}"
        return CheckoutResult(
            provider=self.name,
            provider_reference=form_token or request.reference,
            status="pending",
            checkout_url=url,
            qr_payload=url,
            qr_image_url=None,
            expires_in_seconds=request.expires_in_seconds,
            raw={"izipay": {"status": body.get("status"), "mode": self._mode()}},
        )

    async def get_status(self, reference: str) -> dict[str, Any]:
        if not self._merchant_code() or not self._api_key():
            raise PaymentProviderError("NEEDS_CREDENTIALS", "IZIPAY requiere merchant_code y api_key")
        base = str(self.config.get("api_base") or self.api_base)
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                response = await client.post(
                    f"{base}/api-payment/V4/Order/Get",
                    json={"orderId": reference},
                    auth=(self._merchant_code(), self._api_key()),
                    headers={"Content-Type": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise PaymentTimeoutError("IZIPAY no respondió") from exc
        if response.status_code >= 400:
            raise PaymentProviderError("PROVIDER_HTTP_ERROR", f"IZIPAY HTTP {response.status_code}")
        body = response.json()
        answer = body.get("answer") or {}
        return {
            "provider": self.name,
            "status": answer.get("orderStatus") or body.get("status"),
            "provider_reference": answer.get("orderId"),
            "found": bool(answer),
        }

    async def cancel(self, reference: str) -> bool:
        if not self._merchant_code() or not self._api_key():
            raise PaymentProviderError("NEEDS_CREDENTIALS", "IZIPAY requiere merchant_code y api_key")
        base = str(self.config.get("api_base") or self.api_base)
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                response = await client.post(
                    f"{base}/api-payment/V4/Order/Cancel",
                    json={"orderId": reference},
                    auth=(self._merchant_code(), self._api_key()),
                    headers={"Content-Type": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise PaymentProviderError("PROVIDER_UNREACHABLE", str(exc)[:200]) from exc
        return response.status_code < 400

    async def refund(self, reference: str, amount: Decimal | None = None) -> dict[str, Any]:
        if not self._merchant_code() or not self._api_key():
            raise PaymentProviderError("NEEDS_CREDENTIALS", "IZIPAY requiere merchant_code y api_key")
        base = str(self.config.get("api_base") or self.api_base)
        payload: dict[str, Any] = {"orderId": reference}
        if amount is not None:
            payload["amount"] = to_cents(amount)
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                response = await client.post(
                    f"{base}/api-payment/V4/Order/Refund",
                    json=payload,
                    auth=(self._merchant_code(), self._api_key()),
                    headers={"Content-Type": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise PaymentProviderError("PROVIDER_UNREACHABLE", str(exc)[:200]) from exc
        if response.status_code >= 400:
            raise PaymentProviderError("PROVIDER_HTTP_ERROR", f"IZIPAY HTTP {response.status_code}")
        body = response.json()
        return {"refunded": True, "provider": self.name, "status": body.get("status")}

    #: IZIPAY manda `kr-answer` (JSON como string) + `kr-hash` (HMAC-SHA256 hex).
    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> NormalizedPaymentEvent:
        content_type = ""
        for key, value in headers.items():
            if key.lower() == "content-type":
                content_type = str(value).lower()
        try:
            if "application/x-www-form-urlencoded" in content_type:
                from urllib.parse import parse_qs

                parsed = parse_qs(raw_body.decode("utf-8"))
                body = {k: (v[0] if v else "") for k, v in parsed.items()}
            else:
                body = json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise SignatureVerificationError(f"payload ilegible: {str(exc)[:80]}") from exc
        raw_answer = body.get("kr-answer")
        provided_hash = str(body.get("kr-hash") or "")
        hash_key_kind = str(body.get("kr-hash-key") or "")
        if not raw_answer or not provided_hash:
            raise SignatureVerificationError("falta kr-answer o kr-hash")
        # IPN oficial V4 firma `kr-answer` con el PASSWORD de la API y usa
        # HMAC-SHA256 hexadecimal. El front puede usar la clave HMAC separada
        # (`kr-hash-key=sha256_hmac`). Si el IPN no declara el tipo, se usa
        # password para no aceptar una firma calculada con otra clave.
        secret = (
            self._api_key()
            if hash_key_kind in ("", "password")
            else self._hash_key()
        )
        if not secret:
            raise SignatureVerificationError("sin llave para verificar la firma")
        expected = hmac.new(
            secret.encode("utf-8"), str(raw_answer).encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, provided_hash):
            raise SignatureVerificationError("KR-Hash inválido")
        answer = json.loads(raw_answer) if isinstance(raw_answer, str) else dict(raw_answer)
        provider_status = str(answer.get("orderStatus") or "")
        transactions = list(answer.get("transactions") or [])
        first = transactions[0] if transactions else {}
        event_id = str(
            first.get("uuid")
            or answer.get("orderDetails", {}).get("orderId")
            or f"{answer.get('orderDetails', {}).get('orderId')}:{provider_status}"
        )
        amount = _cents_to_decimal(first.get("amount") or answer.get("amount"))
        return NormalizedPaymentEvent(
            provider=self.name,
            provider_event_id=event_id,
            provider_event_type=f"izipay.order.{provider_status.lower() or 'unknown'}",
            event_type=_event_type_for_status(provider_status),
            reference=answer.get("orderDetails", {}).get("orderId"),
            provider_reference=str(first.get("uuid") or "") or None,
            amount=amount,
            currency=str(first.get("currency") or answer.get("currency") or "").upper() or None,
            status=provider_status,
            occurred_at=str(answer.get("orderDetails", {}).get("creationDate") or ""),
            signature_mode=f"kr-hash:{hash_key_kind or 'sha256_hmac'}",
            raw={"kr-answer": answer},
        )


def build_adapter(
    provider: str, secrets: dict[str, Any], config: dict[str, Any] | None = None
) -> PaymentProviderAdapter:
    """Factory de adapters. Un provider desconocido es un error accionable."""
    key = str(provider or "").strip().lower()
    if key == "izipay":
        return IzipayPaymentAdapter(secrets, config)
    if key == "stripe":
        return StripePaymentAdapter(secrets, config)
    if key == "sandbox":
        return SandboxPaymentAdapter(secrets, config)
    raise PaymentProviderError("PROVIDER_UNKNOWN", f"proveedor de pago desconocido: {provider}")
