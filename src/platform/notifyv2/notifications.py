# =============================================================================
# Multi-Tenant Notifications & Webhooks v2 — centro in-app, preferencias por
# canal y entregas de webhook con firma HMAC y reintentos con backoff.
# =============================================================================
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

DEFAULT_CHANNELS = {"in_app": True, "email": True, "webhook": True}
BACKOFF_SECONDS = (60, 300, 1800, 7200, 21600)  # 1m, 5m, 30m, 2h, 6h


# ---------------------------------------------------------------------------
# Preferencias
# ---------------------------------------------------------------------------
async def get_preferences(organization_id: UUID) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT channels, events FROM notification_preferences "
                    "WHERE organization_id = :oid"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    channels = dict(DEFAULT_CHANNELS)
    events: dict = {}
    if row is not None:
        channels.update(row.channels or {})
        events = row.events or {}
    return {"channels": channels, "events": events}


async def update_preferences(organization_id: UUID, channels: dict | None = None, events: dict | None = None) -> dict:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO notification_preferences (id, organization_id, channels, events) "
                "VALUES (gen_random_uuid(), :oid, :channels, :events) "
                "ON CONFLICT (organization_id) DO UPDATE SET "
                "channels = :channels, events = :events, updated_at = NOW()"
            ),
            {
                "oid": organization_id,
                "channels": json.dumps(channels or DEFAULT_CHANNELS),
                "events": json.dumps(events or {}),
            },
        )
        await session.commit()
    finally:
        await session.close()
    return await get_preferences(organization_id)


def _channel_enabled(preferences: dict, event_type: str, channel: str) -> bool:
    events = preferences.get("events") or {}
    event_override = events.get(event_type) or {}
    if channel in event_override:
        return bool(event_override[channel])
    return bool((preferences.get("channels") or {}).get(channel, True))


# ---------------------------------------------------------------------------
# Notificación multicanal
# ---------------------------------------------------------------------------
async def _owner_email(organization_id: UUID) -> str | None:
    session = await get_async_session()
    try:
        return (
            await session.execute(
                text(
                    "SELECT email FROM users WHERE organization_id = :oid AND email IS NOT NULL "
                    "ORDER BY created_at LIMIT 1"
                ),
                {"oid": organization_id},
            )
        ).scalar()
    finally:
        await session.close()


async def notify(
    organization_id: UUID,
    event_type: str,
    title: str,
    body: str | None = None,
    data: dict | None = None,
) -> dict:
    """Envía por canal según preferencias: in_app (siempre), email y webhook."""
    preferences = await get_preferences(organization_id)
    data = data or {}
    result: dict = {"in_app": False, "email": False, "webhook_deliveries": 0}

    if _channel_enabled(preferences, event_type, "in_app"):
        try:
            session = await get_async_session()
            try:
                await session.execute(
                    text(
                        "INSERT INTO tenant_notifications (id, organization_id, channel, "
                        "event_type, title, body, data) "
                        "VALUES (gen_random_uuid(), :oid, 'in_app', :etype, :title, :body, :data)"
                    ),
                    {
                        "oid": organization_id,
                        "etype": event_type[:60],
                        "title": title[:200],
                        "body": body,
                        "data": json.dumps(data),
                    },
                )
                await session.commit()
                result["in_app"] = True
            finally:
                await session.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("In-app notification failed", error=str(exc)[:150])

    if _channel_enabled(preferences, event_type, "email"):
        try:
            from src.platform.customer_success.customer_success import send_email

            email = await _owner_email(organization_id)
            if email:
                await send_email(
                    email,
                    f"[Zent] {title}",
                    f"<p><b>{title}</b></p><p>{body or ''}</p>",
                )
                result["email"] = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Email notification failed", error=str(exc)[:150])

    if _channel_enabled(preferences, event_type, "webhook"):
        try:
            result["webhook_deliveries"] = await enqueue_deliveries(
                organization_id, event_type, {"event": event_type, "title": title, **data}
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Webhook enqueue failed", error=str(exc)[:150])
    return result


# ---------------------------------------------------------------------------
# Centro de notificaciones in-app
# ---------------------------------------------------------------------------
async def list_notifications(
    organization_id: UUID,
    *,
    unread_only: bool = False,
    event_type: str | None = None,
    hours: int = 168,
    limit: int = 100,
) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    session = await get_async_session()
    try:
        where = ["organization_id = :oid", "created_at >= :since"]
        params: dict = {"oid": organization_id, "since": since, "limit": limit}
        if unread_only:
            where.append("read_at IS NULL AND archived_at IS NULL")
        if event_type:
            where.append("event_type = :etype")
            params["etype"] = event_type
        rows = (
            await session.execute(
                text(
                    "SELECT id, channel, event_type, title, body, data, read_at, "
                    "archived_at, created_at FROM tenant_notifications WHERE "
                    + " AND ".join(where)
                    + " ORDER BY created_at DESC LIMIT :limit"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "notifications": [
            {
                "id": str(r.id),
                "channel": r.channel,
                "event_type": r.event_type,
                "title": r.title,
                "body": r.body,
                "data": r.data,
                "read": r.read_at is not None,
                "archived": r.archived_at is not None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "count": len(rows),
    }


async def unread_count(organization_id: UUID) -> int:
    session = await get_async_session()
    try:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM tenant_notifications "
                        "WHERE organization_id = :oid AND read_at IS NULL AND archived_at IS NULL"
                    ),
                    {"oid": organization_id},
                )
            ).scalar()
            or 0
        )
    finally:
        await session.close()


async def mark_read(organization_id: UUID, notification_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "UPDATE tenant_notifications SET read_at = NOW() "
                "WHERE id = :nid AND organization_id = :oid AND read_at IS NULL"
            ),
            {"nid": notification_id, "oid": organization_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def mark_all_read(organization_id: UUID) -> int:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "UPDATE tenant_notifications SET read_at = NOW() "
                "WHERE organization_id = :oid AND read_at IS NULL"
            ),
            {"oid": organization_id},
        )
        await session.commit()
        return result.rowcount
    finally:
        await session.close()


async def archive(organization_id: UUID, notification_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "UPDATE tenant_notifications SET archived_at = NOW() "
                "WHERE id = :nid AND organization_id = :oid"
            ),
            {"nid": notification_id, "oid": organization_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Webhook deliveries con reintentos
# ---------------------------------------------------------------------------
def _sign_payload(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _decrypt_secret(blob: str) -> str:
    import base64

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from src.core.config import get_settings

    key = hashlib.sha256(
        get_settings().CONNECTOR_SECRETS_KEY.get_secret_value().encode()
    ).digest()
    raw = base64.urlsafe_b64decode(blob.encode())
    return AESGCM(key).decrypt(raw[:12], raw[12:], None).decode()


async def enqueue_deliveries(organization_id: UUID, event_type: str, payload: dict) -> int:
    """Crea entregas pendientes para las suscripciones activas que coinciden."""
    session = await get_async_session()
    try:
        subs = (
            await session.execute(
                text(
                    "SELECT id, url, secret_enc FROM webhook_subscriptions "
                    "WHERE organization_id = :oid AND event_type = :etype AND enabled = true"
                ),
                {"oid": organization_id, "etype": event_type},
            )
        ).fetchall()
        body = json.dumps(payload, default=str)
        count = 0
        for sub in subs:
            try:
                signature = _sign_payload(_decrypt_secret(sub.secret_enc), body)
            except Exception:  # noqa: BLE001
                signature = None
            await session.execute(
                text(
                    "INSERT INTO webhook_deliveries (id, subscription_id, organization_id, "
                    "event_type, payload, signature, status, attempts, next_attempt_at) "
                    "VALUES (gen_random_uuid(), :sid, :oid, :etype, "
                    "CAST(:payload AS jsonb), CAST(:sig AS varchar), "
                    "'pending', 0, NOW())"
                ),
                {
                    "sid": sub.id,
                    "oid": organization_id,
                    "etype": event_type[:60],
                    "payload": body,
                    "sig": signature,
                },
            )
            count += 1
        await session.commit()
        return count
    finally:
        await session.close()


async def process_deliveries(batch: int = 20) -> dict:
    """Procesa pendientes/reintentos; backoff exponencial en fallos."""
    import httpx

    processed: list[dict] = []
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT d.id, d.subscription_id, d.organization_id, d.event_type, "
                    "d.payload, d.signature, d.attempts, s.url, s.secret_enc "
                    "FROM webhook_deliveries d "
                    "JOIN webhook_subscriptions s ON s.id = d.subscription_id "
                    "WHERE d.status IN ('pending', 'retrying') "
                    "AND (d.next_attempt_at IS NULL OR d.next_attempt_at <= NOW()) "
                    "ORDER BY d.created_at LIMIT :batch"
                ),
                {"batch": batch},
            )
        ).fetchall()
        for row in rows:
            start = datetime.now(timezone.utc)
            status_code = None
            error = None
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        row.url,
                        content=json.dumps(row.payload, default=str),
                        headers={
                            "Content-Type": "application/json",
                            "X-Zent-Signature": f"sha256={row.signature or ''}",
                        },
                    )
                status_code = resp.status_code
                ok = 200 <= resp.status_code < 300
            except Exception as exc:  # noqa: BLE001
                ok = False
                error = str(exc)[:300]
            latency_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000
            attempts = int(row.attempts) + 1

            if ok:
                status = "delivered"
                next_attempt = None
            elif attempts >= 5:
                status = "failed"
                next_attempt = None
            else:
                status = "retrying"
                delay = BACKOFF_SECONDS[min(attempts - 1, len(BACKOFF_SECONDS) - 1)]
                next_attempt = datetime.now(timezone.utc) + timedelta(seconds=delay)
            await session.execute(
                text(
                    "UPDATE webhook_deliveries SET status = CAST(:status AS varchar), attempts = :attempts, "
                    "next_attempt_at = :next, last_status_code = :code, "
                    "latency_ms = :lat, error = :error, "
                    "delivered_at = CASE WHEN CAST(:status AS text) = 'delivered' THEN NOW() ELSE delivered_at END "
                    "WHERE id = :did"
                ),
                {
                    "status": status,
                    "attempts": attempts,
                    "next": next_attempt,
                    "code": status_code,
                    "lat": round(latency_ms, 1),
                    "error": error,
                    "did": row.id,
                },
            )
            await session.execute(
                text(
                    "UPDATE webhook_subscriptions SET "
                    "delivery_count = delivery_count + CASE WHEN :ok THEN 1 ELSE 0 END, "
                    "fail_count = fail_count + CASE WHEN :ok THEN 0 ELSE 1 END, "
                    "last_delivered_at = CASE WHEN :ok THEN NOW() ELSE last_delivered_at END "
                    "WHERE id = :sid"
                ),
                {"ok": ok, "sid": row.subscription_id},
            )
            processed.append(
                {
                    "delivery_id": str(row.id),
                    "event_type": row.event_type,
                    "status": status,
                    "attempts": attempts,
                    "status_code": status_code,
                    "latency_ms": round(latency_ms, 1),
                }
            )
        await session.commit()
    finally:
        await session.close()
    return {"processed": processed, "count": len(processed)}


async def list_deliveries(
    organization_id: UUID | None = None,
    status: str | None = None,
    hours: int = 168,
    limit: int = 100,
) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    session = await get_async_session()
    try:
        where = ["created_at >= :since"]
        params: dict = {"since": since, "limit": limit}
        if organization_id:
            where.append("organization_id = :oid")
            params["oid"] = organization_id
        if status:
            where.append("status = :status")
            params["status"] = status
        rows = (
            await session.execute(
                text(
                    "SELECT id, subscription_id, organization_id, event_type, status, "
                    "attempts, last_status_code, latency_ms, error, delivered_at, created_at "
                    "FROM webhook_deliveries WHERE "
                    + " AND ".join(where)
                    + " ORDER BY created_at DESC LIMIT :limit"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "deliveries": [
            {
                "id": str(r.id),
                "subscription_id": str(r.subscription_id),
                "organization_id": str(r.organization_id),
                "event_type": r.event_type,
                "status": r.status,
                "attempts": int(r.attempts),
                "last_status_code": r.last_status_code,
                "latency_ms": round(float(r.latency_ms), 1) if r.latency_ms is not None else None,
                "error": r.error,
                "delivered_at": r.delivered_at.isoformat() if r.delivered_at else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "count": len(rows),
    }


async def deliveries_dashboard(hours: int = 24) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT d.subscription_id, s.url, "
                    "COUNT(*) AS total, "
                    "COUNT(*) FILTER (WHERE d.status = 'delivered') AS delivered, "
                    "COUNT(*) FILTER (WHERE d.status = 'failed') AS failed, "
                    "COUNT(*) FILTER (WHERE d.status = 'retrying') AS retrying, "
                    "AVG(d.latency_ms) AS avg_latency_ms, "
                    "MAX(d.last_status_code) AS last_status_code "
                    "FROM webhook_deliveries d "
                    "JOIN webhook_subscriptions s ON s.id = d.subscription_id "
                    "WHERE d.created_at >= :since "
                    "GROUP BY d.subscription_id, s.url ORDER BY total DESC"
                ),
                {"since": since},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "window_hours": hours,
        "subscriptions": [
            {
                "subscription_id": str(r.subscription_id),
                "url": r.url,
                "total": int(r.total),
                "delivered": int(r.delivered),
                "failed": int(r.failed),
                "retrying": int(r.retrying),
                "success_rate": round(int(r.delivered) / int(r.total), 3) if int(r.total) else 0.0,
                "avg_latency_ms": round(float(r.avg_latency_ms), 1) if r.avg_latency_ms is not None else None,
                "last_status_code": r.last_status_code,
            }
            for r in rows
        ],
    }
