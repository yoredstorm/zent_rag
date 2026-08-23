# =============================================================================
# Knowledge queue — Redis wakeup must not break /sync when Redis is down
# =============================================================================
from __future__ import annotations

import pytest

from src.core.config import get_settings
from src.infrastructure.redis import cache as redis_cache
from src.knowledge.queue import enqueue_knowledge_job


@pytest.fixture(autouse=True)
def _reset_redis_singleton() -> None:
    redis_cache._redis = None
    redis_cache._redis_loop = None
    yield
    redis_cache._redis = None
    redis_cache._redis_loop = None


@pytest.mark.asyncio
async def test_enqueue_does_not_raise_when_redis_unavailable(monkeypatch) -> None:
    """CI/local sin Redis: el job ya está en Postgres; el wakeup es best-effort."""

    async def _boom() -> None:
        raise ConnectionError("Error connecting to localhost:6379")

    monkeypatch.setattr("src.knowledge.queue._get_redis", _boom)
    await enqueue_knowledge_job("job-id")


@pytest.mark.asyncio
async def test_enqueue_raises_in_production_when_redis_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(get_settings(), "ENVIRONMENT", "production")

    async def _boom() -> None:
        raise ConnectionError("Error connecting to localhost:6379")

    monkeypatch.setattr("src.knowledge.queue._get_redis", _boom)
    with pytest.raises(ConnectionError):
        await enqueue_knowledge_job("job-id")


@pytest.mark.asyncio
async def test_get_redis_does_not_retain_client_after_ping_failure(
    monkeypatch,
) -> None:
    class BoomRedis:
        async def ping(self) -> None:
            raise ConnectionError("down")

        async def aclose(self) -> None:
            pass

        async def close(self) -> None:
            pass

    monkeypatch.setattr(redis_cache.aioredis, "from_url", lambda *a, **k: BoomRedis())
    with pytest.raises(ConnectionError):
        await redis_cache._get_redis()
    assert redis_cache._redis is None


@pytest.mark.asyncio
async def test_get_redis_survives_close_on_closed_event_loop(monkeypatch) -> None:
    class DeadRedis:
        async def close(self) -> None:
            raise RuntimeError("Event loop is closed")

        async def aclose(self) -> None:
            raise RuntimeError("Event loop is closed")

    class GoodRedis:
        async def ping(self) -> bool:
            return True

        async def aclose(self) -> None:
            pass

        async def close(self) -> None:
            pass

    class _ClosedLoop:
        def is_closed(self) -> bool:
            return True

    redis_cache._redis = DeadRedis()
    redis_cache._redis_loop = _ClosedLoop()  # type: ignore[assignment]

    monkeypatch.setattr(redis_cache.aioredis, "from_url", lambda *a, **k: GoodRedis())
    client = await redis_cache._get_redis()
    assert isinstance(client, GoodRedis)
