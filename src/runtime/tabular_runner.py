# =============================================================================
# Tabular runner — representación estructurada en observación (S5, C2).
# =============================================================================
# Usa el servicio tabular ya productivo (lookup/agregación exactos). Solo
# observa y traza: el resultado no entra al contexto en C2.
# =============================================================================
from __future__ import annotations

from typing import Protocol

from src.runtime.representation_runners import (
    RunnerContext,
    RunnerItem,
    RunnerResult,
)


class TabularQuery(Protocol):
    async def try_answer(
        self,
        organization_id,
        question: str,
        *,
        source_ids=None,
        knowledge_base_id=None,
        role: str = "admin",
        user_id=None,
    ): ...


def _format_cell(value) -> str:
    text = "" if value is None else str(value)
    return text[:120]


class TabularRunner:
    representation = "structured"

    def __init__(self, tabular_query: TabularQuery, *, max_rows: int = 3) -> None:
        self._tabular = tabular_query
        self._max_rows = max(1, int(max_rows))

    async def run(self, ctx: RunnerContext) -> RunnerResult:
        answer = await self._tabular.try_answer(
            ctx.organization_id,
            ctx.query,
            role=ctx.role,
            user_id=ctx.user_id,
        )
        if answer is None:
            return RunnerResult(
                representation=self.representation,
                status="skipped",
                error="sin_match_tabular",
            )
        columns = [str(column) for column in (getattr(answer, "columns", None) or ())]
        rows = list(getattr(answer, "rows", None) or ())
        table = str((getattr(answer, "metadata", None) or {}).get("table") or "")
        header = " | ".join(columns[:8])
        preview = "\n".join(
            " | ".join(_format_cell(cell) for cell in row[:8])
            for row in rows[: self._max_rows]
        )
        summary = header if not preview else f"{header}\n{preview}"
        item = RunnerItem(
            title="Consulta tabular exacta",
            summary=summary[:800],
            refs={
                "table": table,
                "row_count": int(getattr(answer, "row_count", 0) or 0),
            },
            score=1.0,
        )
        return RunnerResult(
            representation=self.representation, status="ok", items=(item,)
        )
