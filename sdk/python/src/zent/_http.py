from __future__ import annotations

import os
import time
from typing import Any, Iterator
from uuid import uuid4

import httpx

from zent.errors import (
    APIError,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
)


def _error_from_response(response: httpx.Response) -> APIError:
    error_code = None
    message = response.text[:500] or response.reason_phrase
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error_code = payload.get("error_code")
            message = str(payload.get("message") or payload.get("detail") or message)
    except Exception:
        pass
    if response.status_code == 401:
        return AuthenticationError(message, status_code=401, error_code=error_code)
    if response.status_code == 403:
        return PermissionDeniedError(message, status_code=403, error_code=error_code)
    if response.status_code == 429:
        return RateLimitError(message, status_code=429, error_code=error_code)
    return APIError(message, status_code=response.status_code, error_code=error_code)


class HttpClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout: float,
        max_retries: int,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def close(self) -> None:
        self._client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        idempotency: bool = False,
    ) -> httpx.Response:
        headers: dict[str, str] = {}
        if idempotency or method.upper() in {"POST", "PUT", "PATCH"}:
            headers["Idempotency-Key"] = uuid4().hex
        attempt = 0
        while True:
            try:
                response = self._client.request(
                    method, path, json=json, headers=headers
                )
            except httpx.TimeoutException as exc:
                if attempt >= self.max_retries:
                    raise APIError("Request timed out") from exc
                attempt += 1
                time.sleep(_backoff(attempt))
                continue
            if response.status_code in {429, 500, 502, 503, 504}:
                if attempt >= self.max_retries:
                    raise _error_from_response(response)
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else _backoff(attempt + 1)
                attempt += 1
                time.sleep(delay)
                continue
            if response.is_error:
                raise _error_from_response(response)
            return response

    def stream_sse(
        self, path: str, *, json: dict[str, Any] | None = None
    ) -> Iterator[tuple[str, str]]:
        headers = {"Idempotency-Key": uuid4().hex, "Accept": "text/event-stream"}
        with self._client.stream("POST", path, json=json, headers=headers) as response:
            if response.is_error:
                response.read()
                raise _error_from_response(response)
            event = "message"
            data_lines: list[str] = []
            for line in response.iter_lines():
                if line is None:
                    continue
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
                elif line == "":
                    if data_lines:
                        yield event, "\n".join(data_lines)
                    event = "message"
                    data_lines = []


class AsyncHttpClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout: float,
        max_retries: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        idempotency: bool = False,
    ) -> httpx.Response:
        import asyncio

        headers: dict[str, str] = {}
        if idempotency or method.upper() in {"POST", "PUT", "PATCH"}:
            headers["Idempotency-Key"] = uuid4().hex
        attempt = 0
        while True:
            try:
                response = await self._client.request(
                    method, path, json=json, headers=headers
                )
            except httpx.TimeoutException as exc:
                if attempt >= self.max_retries:
                    raise APIError("Request timed out") from exc
                attempt += 1
                await asyncio.sleep(_backoff(attempt))
                continue
            if response.status_code in {429, 500, 502, 503, 504}:
                if attempt >= self.max_retries:
                    raise _error_from_response(response)
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else _backoff(attempt + 1)
                attempt += 1
                await asyncio.sleep(delay)
                continue
            if response.is_error:
                raise _error_from_response(response)
            return response


def default_base_url() -> str:
    return os.environ.get("ZENT_BASE_URL", "http://localhost:8000/api/v1")


def _backoff(attempt: int) -> float:
    return min(2 ** attempt * 0.25, 8.0)
