# =============================================================================
# Tests — feedback lazy_ingested + ensure_eval_table idempotente
# =============================================================================
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import BaseModel, Field

from src.infrastructure.evaluation import ensure_eval_table, store_feedback

_EVAL_ROUTE = Path(__file__).resolve().parents[1] / "src" / "api" / "routes" / "evaluation.py"


class FeedbackRequest(BaseModel):
    """Espejo del contrato en routes/evaluation.py para no importar FastAPI aquí."""

    query: str = Field(..., min_length=1, max_length=4000)
    rating: str = Field(..., pattern=r"^(up|down)$")
    lazy_ingested: bool = Field(default=False)


def test_feedback_request_lazy_ingested_defaults_false() -> None:
    source = _EVAL_ROUTE.read_text(encoding="utf-8")
    assert "lazy_ingested: bool = Field(default=False)" in source
    body = FeedbackRequest(query="precio del paracetamol", rating="up")
    assert body.lazy_ingested is False


def test_feedback_request_accepts_lazy_ingested_true() -> None:
    body = FeedbackRequest(query="precio del paracetamol", rating="down", lazy_ingested=True)
    assert body.lazy_ingested is True


class _FakeSession:
    def __init__(self, log: list[str], params_log: list[dict]) -> None:
        self._log = log
        self._params_log = params_log

    async def execute(self, stmt, params=None):  # type: ignore[no-untyped-def]
        self._log.append(str(stmt))
        if params is not None:
            self._params_log.append(params)

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_ensure_eval_table_alter_lazy_ingested_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements: list[str] = []
    params_log: list[dict] = []

    async def fake_session() -> _FakeSession:
        return _FakeSession(statements, params_log)

    monkeypatch.setattr("src.infrastructure.evaluation.get_async_session", fake_session)
    await ensure_eval_table()
    await ensure_eval_table()
    alters = [
        s for s in statements
        if "lazy_ingested" in s.lower() and "add column" in s.lower()
    ]
    assert len(alters) >= 2


@pytest.mark.asyncio
async def test_store_feedback_persists_lazy_ingested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements: list[str] = []
    params_log: list[dict] = []

    async def fake_session() -> _FakeSession:
        return _FakeSession(statements, params_log)

    monkeypatch.setattr("src.infrastructure.evaluation.get_async_session", fake_session)
    await store_feedback(
        tenant_id=uuid4(),
        query="precio",
        rating="up",
        lazy_ingested=True,
    )
    assert statements
    assert "lazy_ingested" in statements[0].lower()
    assert params_log[0]["lazy_ingested"] is True
