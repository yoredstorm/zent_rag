# =============================================================================
# JEV state builder — presupuesto de contexto con prioridad por seccion.
# =============================================================================
# JEV acepta contextos grandes, pero el valor esta en mandar lo relevante
# completo y no en volcar la KB entera. Cada seccion declara una prioridad
# (menor = mas importante); el builder asigna presupuesto en ese orden y
# reporta que se recorto.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_MAX_SECTION_CHARS = 8000


@dataclass(frozen=True)
class StateSection:
    name: str
    priority: int
    text: str


@dataclass
class BuiltState:
    state: dict[str, Any]
    chars: int
    truncated: list[str] = field(default_factory=list)


def _clean(text: str) -> str:
    return " ".join(str(text or "").split())


def build_jev_state(
    sections: list[StateSection],
    *,
    max_chars: int,
    extra: dict[str, Any] | None = None,
) -> BuiltState:
    """Arma el state JSON respetando el presupuesto, por prioridad."""
    budget = max(500, int(max_chars))
    ordered = sorted(sections, key=lambda section: section.priority)
    state: dict[str, Any] = {}
    truncated: list[str] = []
    for section in ordered:
        text = _clean(section.text)
        if not text:
            continue
        allowance = min(len(text), _MAX_SECTION_CHARS, budget)
        if allowance <= 0:
            truncated.append(section.name)
            continue
        if allowance < len(text):
            truncated.append(section.name)
            text = text[:allowance]
        state[section.name] = text
        budget -= len(text)
    if extra:
        state.update(extra)
    return BuiltState(state=state, chars=sum(len(v) for v in state.values() if isinstance(v, str)), truncated=truncated)
