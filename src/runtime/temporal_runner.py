# =============================================================================
# Temporal runner — vigencia de assertions canónicas (S5, C2).
# =============================================================================
# Determinista: valid_from/valid_to -> current | historical | future | unknown.
# No resuelve vigencias ni elige "la correcta": las declara.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Protocol
from uuid import UUID

from src.runtime.representation_runners import (
    MAX_ITEMS_PER_RUNNER,
    RunnerContext,
    RunnerItem,
    RunnerResult,
)


class TemporalLookup(Protocol):
    async def object_assertions(
        self, organization_id: UUID, object_id: UUID, *, limit: int = 100
    ) -> list[dict]: ...


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def validity_state(
    valid_from: str | None, valid_to: str | None, now: datetime
) -> str:
    """Estado de vigencia medido, nunca inferido."""
    start = _parse(valid_from)
    end = _parse(valid_to)
    if start is None and end is None:
        return "unknown"
    if start is not None and start > now:
        return "future"
    if end is not None and end < now:
        return "historical"
    return "current"


class TemporalRunner:
    representation = "temporal"

    def __init__(
        self,
        lookup: TemporalLookup,
        *,
        max_assertions: int = 20,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._lookup = lookup
        self._max_assertions = max(1, int(max_assertions))
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def run(self, ctx: RunnerContext) -> RunnerResult:
        if ctx.entities is None or not ctx.entities.mentions:
            return RunnerResult(
                representation=self.representation,
                status="skipped",
                error="sin_entidades_resueltas",
            )
        resolved = [
            item
            for item in ctx.entities.mentions
            if item.status == "resolved" and item.matches
        ]
        if not resolved:
            return RunnerResult(
                representation=self.representation,
                status="skipped",
                error="menciones_sin_resolver",
            )
        now = self._now()
        items: list[RunnerItem] = []
        for mention in resolved:
            match = mention.matches[0]
            rows = await self._lookup.object_assertions(
                ctx.organization_id,
                UUID(match.canonical_id),
                limit=self._max_assertions,
            )
            for row in list(rows or ()):
                valid_from = row.get("valid_from")
                valid_to = row.get("valid_to")
                state = validity_state(valid_from, valid_to, now)
                if state == "unknown":
                    continue
                label = (
                    f"{row.get('subject_label') or mention.mention} "
                    f"{row.get('predicate') or ''} "
                    f"{row.get('object_value') or ''}"
                ).strip()
                items.append(
                    RunnerItem(
                        title=label,
                        summary=f"vigencia {state}",
                        refs={
                            "assertion_id": str(row.get("id") or ""),
                            "canonical_id": match.canonical_id,
                            "subject_label": str(
                                row.get("subject_label") or mention.mention
                            ),
                            "predicate": str(row.get("predicate") or ""),
                            "object_value": str(row.get("object_value") or ""),
                            "validity": state,
                            "valid_from": valid_from,
                            "valid_to": valid_to,
                        },
                        score=row.get("confidence"),
                    )
                )
                if len(items) >= MAX_ITEMS_PER_RUNNER:
                    break
            if len(items) >= MAX_ITEMS_PER_RUNNER:
                break
        status = "ok" if items else "empty"
        return RunnerResult(
            representation=self.representation, status=status, items=tuple(items)
        )
