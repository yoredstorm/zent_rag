from __future__ import annotations

import httpx
import pytest
import respx
from zent import AuthenticationError, RateLimitError, Zent
from zent.client import AsyncZent


@respx.mock
def test_chat_returns_answer() -> None:
    respx.post("http://localhost:8000/api/v1/rag/query").mock(
        return_value=httpx.Response(
            200,
            json={
                "answer": "hello",
                "query_id": "11111111-1111-1111-1111-111111111111",
                "sources": [],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                "model": "mock",
            },
        )
    )
    client = Zent(api_key="zent_sk_live_test")
    result = client.chat("What is our refund policy?")
    assert result.answer == "hello"
    assert result.usage["total_tokens"] == 2


@respx.mock
def test_authentication_error() -> None:
    respx.post("http://localhost:8000/api/v1/rag/query").mock(
        return_value=httpx.Response(
            401, json={"error_code": "invalid_token", "message": "Invalid or expired API key"}
        )
    )
    client = Zent(api_key="bad")
    with pytest.raises(AuthenticationError) as exc:
        client.chat("hi")
    assert exc.value.status_code == 401


@respx.mock
def test_retries_on_429_then_succeeds() -> None:
    route = respx.post("http://localhost:8000/api/v1/rag/query")
    route.side_effect = [
        httpx.Response(429, json={"error_code": "rate_limited", "message": "slow down"}),
        httpx.Response(200, json={"answer": "ok", "sources": [], "usage": {}}),
    ]
    client = Zent(api_key="zent_sk_live_test", max_retries=2)
    assert client.chat("hi").answer == "ok"
    assert route.call_count == 2


@respx.mock
def test_post_sends_idempotency_key() -> None:
    route = respx.post("http://localhost:8000/api/v1/rag/query").mock(
        return_value=httpx.Response(200, json={"answer": "ok", "sources": [], "usage": {}})
    )
    Zent(api_key="zent_sk_live_test").chat("hi")
    assert "Idempotency-Key" in route.calls.last.request.headers


@respx.mock
def test_rate_limit_exhausted_raises() -> None:
    respx.post("http://localhost:8000/api/v1/rag/query").mock(
        return_value=httpx.Response(429, json={"error_code": "rate_limited", "message": "nope"})
    )
    client = Zent(api_key="zent_sk_live_test", max_retries=0)
    with pytest.raises(RateLimitError):
        client.chat("hi")


@pytest.mark.asyncio
@respx.mock
async def test_async_chat() -> None:
    respx.post("http://localhost:8000/api/v1/rag/query").mock(
        return_value=httpx.Response(200, json={"answer": "async", "sources": [], "usage": {}})
    )
    async with AsyncZent(api_key="zent_sk_live_test") as client:
        result = await client.chat("hi")
    assert result.answer == "async"
