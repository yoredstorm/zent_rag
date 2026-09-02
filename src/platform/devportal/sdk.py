# =============================================================================
# Developer Experience — SDK reference auto-generada, webhooks salientes
# (HMAC), changelog y status público del platform.
# =============================================================================
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.infrastructure.redis.cache import _get_redis

logger = get_logger(__name__)

EVENTS_CHANNEL = "rag:events"

# ---------------------------------------------------------------------------
# SDK reference
# ---------------------------------------------------------------------------
_ENDPOINTS: list[dict] = [
    {
        "path": "POST /api/v1/rag/federated",
        "auth": "Bearer <API_KEY>",
        "body": '{"query": "¿cuánto stock queda?", "top_k": 10}',
        "description": "Búsqueda federada cross-KB con ranking unificado.",
    },
    {
        "path": "POST /api/v1/deployments/{slug}/query",
        "auth": "Bearer <API_KEY> (scope agents:execute)",
        "body": '{"input": "consulta", "user": {"id": "erp-1"}}',
        "description": "Query pública a un deployment healthy (structured output).",
    },
    {
        "path": "POST /api/v1/agents",
        "auth": "Bearer <API_KEY> + Idempotency-Key",
        "body": '{"name": "mi-agente", "system_prompt": "...", "model": "gpt-4o-mini"}',
        "description": "Crear un agente.",
    },
    {
        "path": "GET /api/v1/knowledge-bases",
        "auth": "Bearer <API_KEY>",
        "body": None,
        "description": "Listar knowledge bases de la organización.",
    },
]


def _snippets(endpoint: dict) -> dict[str, str]:
    path = endpoint["path"].split(" ", 1)[1]
    method = endpoint["path"].split(" ", 1)[0].lower()
    url = f"https://api.zent.example{path}"
    body = endpoint["body"] or "{}"

    python = f'''import httpx

resp = httpx.{method}(
    "{url}",
    headers={{'Authorization': 'Bearer $ZENT_API_KEY'}},
    json={body},
)
print(resp.status_code, resp.json())'''
    javascript = f'''const resp = await fetch("{url}", {{
  method: "{method.upper()}",
  headers: {{
    "Authorization": `Bearer ${{process.env.ZENT_API_KEY}}`,
    "Content-Type": "application/json",
  }},
  body: JSON.stringify({body}),
}});
const data = await resp.json();
console.log(resp.status, data);'''
    csharp = f'''using var client = new HttpClient();
client.DefaultRequestHeaders.Authorization =
    new AuthenticationHeaderValue("Bearer", apiKey);
var body = new StringContent({json.dumps(body)}, Encoding.UTF8, "application/json");
var resp = await client.{method.title()}Async("{url}", body);
Console.WriteLine(await resp.Content.ReadAsStringAsync());'''
    java = f'''HttpClient client = HttpClient.newHttpClient();
HttpRequest request = HttpRequest.newBuilder()
    .uri(URI.create("{url}"))
    .header("Authorization", "Bearer " + apiKey)
    .header("Content-Type", "application/json")
    .{method}HttpRequest.BodyPublishers.ofString({json.dumps(body)})
    .build();
HttpResponse<String> resp = client.send(request, HttpResponse.BodyHandlers.ofString());
System.out.println(resp.body());'''
    php = f'''$ch = curl_init("{url}");
curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_HTTPHEADER => ['Authorization: Bearer ' . getenv('ZENT_API_KEY')],
    CURLOPT_{'POSTFIELDS' if method == 'post' else 'HTTPGET'} => true,
]);
$resp = curl_exec($ch);
echo $resp;'''
    return {
        "python": python,
        "javascript": javascript,
        "csharp": csharp,
        "java": java,
        "php": php,
    }


async def sdk_reference() -> dict:
    return {
        "base_url": "https://api.zent.example",
        "auth": "API keys con scopes (Bearer). Idempotency-Key obligatoria en POST.",
        "endpoints": [
            {**e, "snippets": _snippets(e)} for e in _ENDPOINTS
        ],
    }


# ---------------------------------------------------------------------------
# Changelog + status
# ---------------------------------------------------------------------------
async def list_changelog(public_only: bool = True) -> list[dict]:
    session = await get_async_session()
    try:
        sql = (
            "SELECT id, version, title, body, is_public, published_at "
            "FROM platform_changelog WHERE 1=1 "
        )
        if public_only:
            sql += " AND is_public = true "
        sql += " ORDER BY published_at DESC LIMIT 50"
        rows = (await session.execute(text(sql))).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "version": r.version,
            "title": r.title,
            "body": r.body,
            "is_public": bool(r.is_public),
            "published_at": r.published_at.isoformat(),
        }
        for r in rows
    ]


async def add_changelog(version: str, title: str, body: str, is_public: bool = True) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO platform_changelog (id, version, title, body, is_public) "
                    "VALUES (gen_random_uuid(), :version, :title, :body, :public) "
                    "RETURNING id, version, title"
                ),
                {"version": version, "title": title, "body": body, "public": is_public},
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {"id": str(row.id), "version": row.version, "title": row.title}


async def platform_status() -> dict:
    from src.platform.observability.health import system_health

    health = await system_health()
    changelog = await list_changelog(public_only=True)
    return {
        "api_version": "v2.6.0",
        "status": health["status"],
        "checks": health["checks"],
        "latest_releases": changelog[:3],
    }


# ---------------------------------------------------------------------------
# Webhooks salientes
# ---------------------------------------------------------------------------
WEBHOOK_EVENTS = (
    "agent_run",
    "api_query",
    "deployment_event",
    "incident",
    "workflow_run",
    "invoice.paid",
    "quota.exceeded",
    "usage.alert",
    "agent.deployed",
    "test.ping",
)


def _encrypt_secret(secret: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = hashlib.sha256(
        get_settings().CONNECTOR_SECRETS_KEY.get_secret_value().encode()
    ).digest()
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, secret.encode(), None)
    return base64.urlsafe_b64encode(nonce + ct).decode()


def _decrypt_secret(blob: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = hashlib.sha256(
        get_settings().CONNECTOR_SECRETS_KEY.get_secret_value().encode()
    ).digest()
    raw = base64.urlsafe_b64decode(blob.encode())
    return AESGCM(key).decrypt(raw[:12], raw[12:], None).decode()


def _sign_payload(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


async def subscribe_webhook(organization_id: UUID, event_type: str, url: str, secret: str | None) -> dict:
    if event_type not in WEBHOOK_EVENTS:
        raise ValueError(f"event_type inválido: {event_type}")
    secret = secret or secrets.token_urlsafe(24)
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO webhook_subscriptions (id, organization_id, event_type, "
                    "url, secret_enc) VALUES (gen_random_uuid(), :oid, :etype, :url, :sec) "
                    "ON CONFLICT (organization_id, event_type, url) DO UPDATE SET "
                    "secret_enc = EXCLUDED.secret_enc, enabled = true "
                    "RETURNING id, event_type, url"
                ),
                {"oid": organization_id, "etype": event_type, "url": url, "sec": _encrypt_secret(secret)},
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {"id": str(row.id), "event_type": row.event_type, "url": row.url, "secret": secret}


async def list_webhooks(organization_id: UUID) -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, event_type, url, enabled, delivery_count, fail_count, "
                    "last_delivered_at, created_at FROM webhook_subscriptions "
                    "WHERE organization_id = :oid ORDER BY created_at DESC"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "event_type": r.event_type,
            "url": r.url,
            "enabled": bool(r.enabled),
            "delivery_count": int(r.delivery_count or 0),
            "fail_count": int(r.fail_count or 0),
            "last_delivered_at": r.last_delivered_at.isoformat() if r.last_delivered_at else None,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


async def delete_webhook(organization_id: UUID, webhook_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "DELETE FROM webhook_subscriptions "
                "WHERE id = :wid AND organization_id = :oid"
            ),
            {"wid": webhook_id, "oid": organization_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def test_webhook(organization_id: UUID, webhook_id: UUID) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT url, secret_enc FROM webhook_subscriptions "
                    "WHERE id = :wid AND organization_id = :oid"
                ),
                {"wid": webhook_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return {"status": "not_found"}
    ok = await _post_webhook(
        row.url, _decrypt_secret(row.secret_enc),
        {"event": "ping", "ts": datetime.now(timezone.utc).isoformat()},
    )
    return {"status": "delivered" if ok else "failed"}


async def _post_webhook(url: str, secret: str, payload: dict) -> bool:
    import httpx

    body = json.dumps(payload, default=str)
    signature = _sign_payload(secret, body)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Zent-Signature": f"sha256={signature}",
                },
            )
        return 200 <= resp.status_code < 300
    except Exception as exc:  # noqa: BLE001
        logger.warning("Webhook dispatch failed", url=url, error=str(exc)[:150])
        return False


async def _update_counts(webhook_id: UUID, ok: bool) -> None:
    session = await get_async_session()
    try:
        if ok:
            await session.execute(
                text(
                    "UPDATE webhook_subscriptions SET delivery_count = delivery_count + 1, "
                    "last_delivered_at = NOW() WHERE id = :wid"
                ),
                {"wid": webhook_id},
            )
        else:
            await session.execute(
                text(
                    "UPDATE webhook_subscriptions SET fail_count = fail_count + 1 "
                    "WHERE id = :wid"
                ),
                {"wid": webhook_id},
            )
        await session.commit()
    finally:
        await session.close()


async def dispatch_event(event_type: str, organization_id: UUID, payload: dict) -> int:
    """Entrega el evento a las suscripciones activas de la org. Devuelve nº de entregas."""
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
    finally:
        await session.close()
    delivered = 0
    for sub in subs:
        ok = await _post_webhook(
            sub.url, _decrypt_secret(sub.secret_enc), {"event": event_type, **payload}
        )
        await _update_counts(sub.id, ok)
        if ok:
            delivered += 1
    return delivered


async def webhook_dispatcher_loop() -> None:
    """Consume rag:events y reenvía a webhooks por org/evento."""
    while True:
        try:
            client = await _get_redis()
            pubsub = client.pubsub()
            await pubsub.subscribe(EVENTS_CHANNEL)
            it = pubsub.listen().__aiter__()
            try:
                while True:
                    try:
                        message = await asyncio.wait_for(it.__anext__(), timeout=5.0)
                    except asyncio.TimeoutError:
                        continue
                    if message.get("type") != "message":
                        continue
                    try:
                        payload = json.loads(message["data"])
                    except (TypeError, json.JSONDecodeError):
                        continue
                    event_type = payload.pop("event", None)
                    org_id = payload.pop("organization_id", None)
                    if not event_type or not org_id:
                        continue
                    try:
                        await dispatch_event(event_type, UUID(org_id), payload)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Webhook dispatch iteration failed", error=str(exc)[:150])
            finally:
                try:
                    await pubsub.unsubscribe(EVENTS_CHANNEL)
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("Webhook dispatcher iteration failed", error=str(exc)[:200])
            await asyncio.sleep(5)
