# =============================================================================
# P20-08 (mínimo) - historial de conversación para el agente.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.agents.runtime.trace_store import load_conversation_turns

ORG = uuid4()
AGENT = uuid4()
CONV = uuid4()
USER = uuid4()


class _FakeSession:
    def __init__(self) -> None:
        self.sql = ""
        self.params: dict = {}

    async def execute(self, statement, params=None):
        self.sql = str(statement)
        self.params = params or {}
        return SimpleNamespace(
            fetchall=lambda: [
                SimpleNamespace(
                    message="segundo mensaje",
                    answer="segunda respuesta",
                    created_at="2026-01-02",
                ),
                SimpleNamespace(
                    message="primer mensaje",
                    answer="primera respuesta",
                    created_at="2026-01-01",
                ),
            ]
        )

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_load_conversation_turns_returns_chronological(monkeypatch) -> None:
    session = _FakeSession()

    async def _session():
        return session

    monkeypatch.setattr(
        "src.agents.runtime.trace_store.get_async_session", _session
    )
    turns = await load_conversation_turns(
        ORG, AGENT, CONV, user_id=USER, limit=6
    )

    assert [turn["message"] for turn in turns] == [
        "primer mensaje",
        "segundo mensaje",
    ]
    assert "conversation_id = :cid" in session.sql
    assert session.params["cid"] == str(CONV)
    assert session.params["uid"] == str(USER)
    assert session.params["limit"] == 6


@pytest.mark.asyncio
async def test_load_conversation_turns_fails_soft(monkeypatch) -> None:
    class _BrokenSession:
        async def execute(self, *_args, **_kwargs):
            raise RuntimeError("db down")

        async def close(self) -> None:
            return None

    async def _session():
        return _BrokenSession()

    monkeypatch.setattr(
        "src.agents.runtime.trace_store.get_async_session", _session
    )
    turns = await load_conversation_turns(ORG, AGENT, CONV)

    assert turns == []
