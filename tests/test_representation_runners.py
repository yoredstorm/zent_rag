# =============================================================================
# Runner framework — ejecución fail-soft y acotada de representaciones (C2).
# =============================================================================
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from src.runtime.representation_runners import (
    RunnerContext,
    RunnerItem,
    RunnerResult,
    run_representations,
)


class FakeRunner:
    def __init__(self, representation: str, *, result=None, error=None, delay=0.0):
        self.representation = representation
        self.result = result
        self.error = error
        self.delay = delay
        self.calls = 0

    async def run(self, ctx):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.result or RunnerResult(
            representation=self.representation,
            status="ok",
            items=(RunnerItem(title="t", summary="s"),),
        )


def _ctx() -> RunnerContext:
    return RunnerContext(
        query="q",
        organization_id=uuid4(),
        user_id=None,
        role="admin",
        strategy=None,
        entities=None,
    )


@pytest.mark.asyncio
async def test_solo_corre_representaciones_declaradas() -> None:
    graph = FakeRunner("graph")
    temporal = FakeRunner("temporal")
    results = await run_representations(
        _ctx(), (graph, temporal), representations=("graph",)
    )
    assert [result.representation for result in results] == ["graph"]
    assert graph.calls == 1 and temporal.calls == 0


@pytest.mark.asyncio
async def test_error_no_propaga() -> None:
    boom = FakeRunner("graph", error=RuntimeError("caída"))
    (result,) = await run_representations(_ctx(), (boom,))
    assert result.status == "error"
    assert "caída" in (result.error or "")


@pytest.mark.asyncio
async def test_timeout_acotado() -> None:
    slow = FakeRunner("graph", delay=0.2)
    (result,) = await run_representations(
        _ctx(), (slow,), timeout_seconds=0.01
    )
    assert result.status == "timeout"


@pytest.mark.asyncio
async def test_payload_recorta_items() -> None:
    many = RunnerResult(
        representation="graph",
        status="ok",
        items=tuple(
            RunnerItem(title=f"t{i}", summary="s") for i in range(9)
        ),
    )
    payload = many.to_public_dict(max_items=5)
    assert len(payload["items"]) == 5
    assert payload["count"] == 9
