from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChatResponse:
    answer: str
    query_id: str | None = None
    conversation_id: str | None = None
    model: str | None = None
    sources: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatEvent:
    event: str
    data: Any
