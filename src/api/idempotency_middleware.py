# =============================================================================
# Idempotency Middleware — deduplica retries de mutaciones críticas
# =============================================================================
# Header Idempotency-Key:
#   - Obligatorio en un conjunto de POST/PUT/PATCH (create key, connectors,
#     KBs, agents, agent run, ingestion sync, sources).
#   - Opcional en el resto (p. ej. RAG query).
# Misma key + mismo body → replay 24h. Misma key + body distinto → 409.
# =============================================================================
from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.redis.cache import _get_redis

logger = get_logger(__name__)

_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9\-_]{8,128}$")
_TTL_SECONDS = 86400
_STOREABLE_STATUS = {200, 201, 202, 204, 400, 401, 402, 403, 404, 409, 422, 429}

_REQUIRED: tuple[tuple[re.Pattern[str], frozenset[str]], ...] = (
    (re.compile(r"^/api/v1/organizations/api-keys$"), frozenset({"POST"})),
    (re.compile(r"^/api/v1/connectors$"), frozenset({"POST"})),
    (re.compile(r"^/api/v1/knowledge-bases$"), frozenset({"POST"})),
    (re.compile(r"^/api/v1/agents$"), frozenset({"POST"})),
    (re.compile(r"^/api/v1/agents/[^/]+/run$"), frozenset({"POST"})),
    (re.compile(r"^/api/v1/ingestion/sync$"), frozenset({"POST"})),
    (re.compile(r"^/api/v1/ingestion/sync/[^/]+/[^/]+$"), frozenset({"POST"})),
    (re.compile(r"^/api/v1/sources$"), frozenset({"POST"})),
    (re.compile(r"^/api/v1/knowledge-bases/[^/]+/sources$"), frozenset({"POST"})),
    (re.compile(r"^/api/v1/sources/files/upload$"), frozenset({"POST"})),
)

_mem_lock = threading.Lock()
_mem_store: dict[str, tuple[float, str]] = {}


def is_idempotency_required(method: str, path: str) -> bool:
    method_u = method.upper()
    for pattern, methods in _REQUIRED:
        if method_u in methods and pattern.match(path):
            return True
    return False


def _mem_get(key: str) -> str | None:
    now = time.monotonic()
    with _mem_lock:
        entry = _mem_store.get(key)
        if entry is None:
            return None
        expires, value = entry
        if now >= expires:
            _mem_store.pop(key, None)
            return None
        return value


def _mem_set(key: str, value: str, ttl: int) -> None:
    with _mem_lock:
        _mem_store[key] = (time.monotonic() + ttl, value)


def reset_memory_idempotency() -> None:
    with _mem_lock:
        _mem_store.clear()


def _json_error(status: int, error_code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error_code": error_code, "message": message},
    )


def _replay_response(payload: dict) -> Response:
    headers = dict(payload.get("headers") or {})
    headers["Idempotency-Replayed"] = "true"
    return Response(
        content=base64.b64decode(payload["body"]),
        status_code=payload["status"],
        headers=headers,
        media_type=payload.get("media_type"),
    )


class IdempotencyMiddleware(BaseHTTPMiddleware):

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        method = request.method.upper()
        if method not in ("POST", "PUT", "PATCH"):
            return await call_next(request)

        path = request.url.path
        required = is_idempotency_required(method, path)
        idem_key = request.headers.get("Idempotency-Key", "").strip()

        if not idem_key:
            if required:
                return _json_error(
                    400,
                    "idempotency_key_required",
                    "Idempotency-Key header is required for this operation",
                )
            return await call_next(request)

        if not _IDEMPOTENCY_KEY_RE.match(idem_key):
            if required:
                return _json_error(
                    400,
                    "idempotency_key_invalid",
                    "Idempotency-Key must be 8-128 chars [A-Za-z0-9-_]",
                )
            return await call_next(request)

        body = await request.body()
        body_hash = hashlib.sha256(body).hexdigest()

        organization_id = getattr(request.state, "organization_id", "") or ""
        if not organization_id:
            ctx = getattr(request.state, "tenant_context", None)
            if ctx is not None:
                organization_id = str(ctx.organization_id)
        client_ip = request.client.host if request.client else "unknown"
        namespace = f"organization:{organization_id}" if organization_id else f"ip:{client_ip}"
        store_key = f"zent:idem:{namespace}:{method}:{path}:{idem_key}"

        stored, redis_ok = await self._load(store_key, required)
        if stored is False:
            return _json_error(
                503,
                "idempotency_unavailable",
                "Idempotency store unavailable; retry with the same Idempotency-Key",
            )
        if stored:
            try:
                payload = json.loads(stored)
            except Exception as exc:
                logger.warning("Corrupt idempotency record", key=idem_key, error=str(exc))
                payload = None
            if payload is not None:
                if payload.get("body_hash") != body_hash:
                    return _json_error(
                        409,
                        "idempotency_key_conflict",
                        "Idempotency-Key was reused with a different request body",
                    )
                return _replay_response(payload)

        response = await call_next(request)

        content_type = (response.headers.get("content-type") or "").lower()
        if content_type.startswith("text/event-stream"):
            return response

        chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode("utf-8"))
        raw = b"".join(chunks)

        if response.status_code in _STOREABLE_STATUS:
            record = json.dumps(
                {
                    "body_hash": body_hash,
                    "status": response.status_code,
                    "media_type": response.media_type,
                    "headers": {
                        k: v
                        for k, v in response.headers.items()
                        if k.lower() in ("content-type", "cache-control")
                    },
                    "body": base64.b64encode(raw).decode("ascii"),
                }
            )
            await self._save(store_key, record, required, redis_ok)

        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(
            content=raw,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )

    async def _load(self, key: str, required: bool) -> tuple[str | None | bool, bool]:
        """Retorna (valor|None, redis_ok). False como valor = 503 en producción."""
        try:
            client = await _get_redis()
            return await client.get(key), True
        except Exception:
            logger.warning("Idempotency Redis unavailable; using in-memory fallback")
            from src.core.config import get_settings

            if required and get_settings().ENVIRONMENT == "production":
                return False, False
            return _mem_get(key), False

    async def _save(
        self, key: str, record: str, required: bool, redis_ok: bool
    ) -> None:
        if redis_ok:
            try:
                client = await _get_redis()
                await client.set(key, record, ex=_TTL_SECONDS)
                return
            except Exception as exc:
                logger.debug("Could not store idempotency record", error=str(exc))
                from src.core.config import get_settings

                if required and get_settings().ENVIRONMENT == "production":
                    return
        _mem_set(key, record, _TTL_SECONDS)


def new_idempotency_key() -> str:
    return uuid4().hex
