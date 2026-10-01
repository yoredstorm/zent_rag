# =============================================================================
# Runner estructurado — consulta tabular exacta en observación (C2).
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.ports.sql_expert import SqlQueryResult
from src.runtime.representation_runners import RunnerContext
from src.runtime.tabular_runner import TabularRunner


class FakeTabular:
    def __init__(self, answer=None, *, boom=False):
        self.answer = answer
        self.boom = boom
        self.calls: list[dict] = []

    async def try_answer(self, organization_id, question, **kwargs):
        self.calls.append({"organization_id": organization_id, "question": question, **kwargs})
        if self.boom:
            raise RuntimeError("lazy caído")
        return self.answer


def _ctx() -> RunnerContext:
    return RunnerContext(
        query="¿Cuál es el total de la columna 7?",
        organization_id=uuid4(),
        user_id=None,
        role="admin",
        strategy=None,
        entities=None,
    )


@pytest.mark.asyncio
async def test_tabular_runner_item_con_columnas_y_filas() -> None:
    answer = SqlQueryResult(
        sql="SELECT sum(col7) FROM t",
        columns=["total"],
        rows=[["1284"]],
        row_count=1,
        metadata={"table": "sheet_1", "strategy": "aggregation"},
    )
    fake = FakeTabular(answer)
    result = await TabularRunner(fake).run(_ctx())
    assert result.status == "ok"
    item = result.items[0]
    assert "total" in item.summary
    assert item.refs["table"] == "sheet_1"
    assert "SELECT" not in item.summary  # nunca SQL crudo en la traza
    assert fake.calls[0]["role"] == "admin"


@pytest.mark.asyncio
async def test_tabular_runner_sin_match_skip() -> None:
    result = await TabularRunner(FakeTabular(None)).run(_ctx())
    assert result.status == "skipped"
    assert result.error == "sin_match_tabular"


@pytest.mark.asyncio
async def test_tabular_runner_error_capturado_por_dispatcher() -> None:
    from src.runtime.representation_runners import run_representations

    (result,) = await run_representations(_ctx(), (TabularRunner(FakeTabular(boom=True)),))
    assert result.status == "error"
    assert "lazy" in (result.error or "")
