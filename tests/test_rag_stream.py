# =============================================================================
# Tests del endpoint de streaming SSE — POST /api/v1/rag/query/stream
# =============================================================================
from __future__ import annotations

import json
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.domain.entities import QueryStatus, RAGQueryResult
from tests.conftest import MockRAGOrchestrator


class StreamingMockOrchestrator(MockRAGOrchestrator):
    """Orquestador que además invoca on_delta para simular tokens en vivo."""

    async def execute(self, **kwargs):
        on_delta = kwargs.get("on_delta")
        if callable(on_delta):
            await on_delta("Hola ")
            await on_delta("mundo")
        return await super().execute(**kwargs)


def _parse_sse(raw: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for frame in raw.split("\n\n"):
        if not frame.strip():
            continue
        event = "message"
        data = ""
        for line in frame.split("\n"):
            if line.startswith("event: "):
                event = line[len("event: "):].strip()
            elif line.startswith("data: "):
                data += line[len("data: "):]
        events.append((event, json.loads(data) if data else {}))
    return events


@pytest.fixture
def streaming_orchestrator() -> StreamingMockOrchestrator:
    return StreamingMockOrchestrator()


@pytest.fixture
async def stream_client(streaming_orchestrator: StreamingMockOrchestrator):
    from src.api.deps import get_rag_orchestrator
    from src.api.main import app

    app.dependency_overrides[get_rag_orchestrator] = lambda: streaming_orchestrator
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


async def _create_trial_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={"company_name": f"Test Co {uuid4().hex[:8]}"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    return {
        "Authorization": f"Bearer {data['api_token']}",
        "X-Tenant-Id": data["tenant_id"],
        "X-User-Role": "admin",
    }


@pytest.mark.asyncio
async def test_stream_returns_status_delta_done(stream_client: AsyncClient):
    """El flujo SSE emite status, deltas, sources y done en orden."""
    headers = await _create_trial_headers(stream_client)
    async with stream_client.stream(
        "POST",
        "/api/v1/rag/query/stream",
        json={"query": "cuantos productos hay", "role": "admin"},
        headers=headers,
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        raw = ""
        async for chunk in response.aiter_text():
            raw += chunk

    events = _parse_sse(raw)
    kinds = [e for e, _ in events]

    assert kinds[0] == "status"
    deltas = [d["text"] for e, d in events if e == "delta"]
    assert deltas == ["Hola ", "mundo"]
    assert "sources" in kinds
    assert kinds[-1] == "done"

    done = next(d for e, d in events if e == "done")
    assert done["conversation_id"]
    assert done["query_id"]
    assert done["latency_ms"] is not None


@pytest.mark.asyncio
async def test_stream_error_event_on_failed_result(
    stream_client: AsyncClient
):
    """Si el orquestador falla, el stream emite un evento error con el mensaje."""
    from src.api.deps import get_rag_orchestrator
    from src.api.main import app

    failing = MockRAGOrchestrator(
        response=RAGQueryResult(
            query_id=uuid4(),
            tenant_id=uuid4(),
            user_id=uuid4(),
            query="x",
            status=QueryStatus.FAILED,
            error_message="Rate limit exceeded for this tenant",
        )
    )
    app.dependency_overrides[get_rag_orchestrator] = lambda: failing
    try:
        headers = await _create_trial_headers(stream_client)
        async with stream_client.stream(
            "POST",
            "/api/v1/rag/query/stream",
            json={"query": "x", "role": "admin"},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            raw = ""
            async for chunk in response.aiter_text():
                raw += chunk
    finally:
        app.dependency_overrides.clear()

    events = _parse_sse(raw)
    kinds = [e for e, _ in events]
    assert kinds[-1] == "error"
    error = next(d for e, d in events if e == "error")
    assert "Rate limit" in error["message"]


@pytest.mark.asyncio
async def test_stream_missing_auth_returns_401(stream_client: AsyncClient):
    """Sin tenant/token, el endpoint responde 401 antes de emitir SSE."""
    response = await stream_client.post(
        "/api/v1/rag/query/stream",
        json={"query": "x", "role": "admin"},
    )
    assert response.status_code == 401
