# =============================================================================
# Representation runners — framework de observación multi-representación (S5).
# =============================================================================
# Cada runner declara su representación y devuelve items con refs. El
# dispatcher los corre en orden, con timeout y fail-soft: un runner roto jamás
# cambia la respuesta.
# =============================================================================
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Collection, Protocol, Sequence
from uuid import UUID

if TYPE_CHECKING:  # anotaciones: no importa strategy ni resolution en runtime
    from src.runtime.entity_resolution import EntityResolution
    from src.runtime.knowledge_strategy import KnowledgeStrategy

RUNNER_TIMEOUT_SECONDS = 3.0
MAX_ITEMS_PER_RUNNER = 5


@dataclass(frozen=True)
class RunnerItem:
    title: str
    summary: str
    refs: dict = field(default_factory=dict)
    score: float | None = None

    def to_public_dict(self) -> dict:
        payload = {"title": self.title, "summary": self.summary, "refs": dict(self.refs)}
        if self.score is not None:
            payload["score"] = round(float(self.score), 4)
        return payload


@dataclass(frozen=True)
class RunnerResult:
    representation: str
    status: str  # ok | empty | skipped | error | timeout
    items: tuple[RunnerItem, ...] = ()
    latency_ms: float = 0.0
    error: str | None = None

    def to_public_dict(self, *, max_items: int = MAX_ITEMS_PER_RUNNER) -> dict:
        payload: dict = {
            "representation": self.representation,
            "status": self.status,
            "count": len(self.items),
            "items": [item.to_public_dict() for item in self.items[: max(0, max_items)]],
            "latency_ms": round(float(self.latency_ms), 1),
        }
        if self.error:
            payload["error"] = self.error[:200]
        return payload


@dataclass(frozen=True)
class RunnerContext:
    query: str
    organization_id: UUID
    user_id: UUID | None
    role: str
    strategy: "KnowledgeStrategy | None" = None
    entities: "EntityResolution | None" = None
    source_ids: tuple[UUID, ...] = ()


class RepresentationRunner(Protocol):
    representation: str

    async def run(self, ctx: RunnerContext) -> RunnerResult: ...


async def run_representations(
    ctx: RunnerContext,
    runners: Sequence[RepresentationRunner],
    *,
    representations: Collection[str] | None = None,
    timeout_seconds: float = RUNNER_TIMEOUT_SECONDS,
) -> tuple[RunnerResult, ...]:
    """Corre los runners declarados. Nunca lanza; cada resultado se traza."""
    wanted = None if representations is None else {str(rep) for rep in representations}
    results: list[RunnerResult] = []
    for runner in runners:
        representation = str(getattr(runner, "representation", "") or "")
        if not representation:
            continue
        if wanted is not None and representation not in wanted:
            continue
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                runner.run(ctx), timeout=max(0.01, float(timeout_seconds))
            )
            if not isinstance(result, RunnerResult):
                result = RunnerResult(
                    representation=representation,
                    status="error",
                    error="runner devolvió un tipo inválido",
                )
        except asyncio.TimeoutError:
            result = RunnerResult(
                representation=representation,
                status="timeout",
                error=f"timeout tras {timeout_seconds}s",
            )
        except Exception as exc:  # noqa: BLE001 — observación nunca rompe el run
            result = RunnerResult(
                representation=representation,
                status="error",
                error=str(exc)[:200],
            )
        latency_ms = (time.perf_counter() - started) * 1000
        results.append(replace(result, latency_ms=latency_ms))
    return tuple(results)
