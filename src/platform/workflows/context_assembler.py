# =============================================================================
# Workflow Context Assembler — el subset de contexto que un nodo (o agente)
# realmente necesita (Workflow Semantic Core, Fase 1).
#
# Aplica scope (`context_reads`), seguridad (nunca `security` ni runtime-only),
# y budget de tamaño (brief §13). Sin I/O, sin LLM.
# =============================================================================
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from src.platform.workflows.context import (
    LLM_VISIBLE_SECTIONS,
    RUNTIME_ONLY_SECTIONS,
    WorkflowContext,
    normalize_section,
)
from src.platform.workflows.values import jsonable

DEFAULT_SECTION_ORDER: tuple[str, ...] = (
    "trigger",
    "data",
    "knowledge",
    "evidence_refs",
    "claim_refs",
    "entity_refs",
    "findings",
    "decisions",
    "artifacts",
)


@dataclass(frozen=True, kw_only=True)
class ContextBudget:
    """Topes de contexto ensamblado (por sección y total)."""

    max_values_per_section: int = 20
    max_chars_per_section: int = 4_000
    max_chars_total: int = 12_000


DEFAULT_CONTEXT_BUDGET = ContextBudget()


@dataclass(frozen=True)
class AssembledContext:
    """Contexto filtrado y acotado para un nodo/agente."""

    payload: dict[str, Any] = field(default_factory=dict)
    rendered: str = ""
    sections_used: tuple[str, ...] = ()
    truncated: tuple[str, ...] = ()
    budget: ContextBudget = DEFAULT_CONTEXT_BUDGET


def _compact(value: Any, *, max_chars: int = 400) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    elif value is None:
        text = "null"
    else:
        text = str(value)
    return text if len(text) <= max_chars else text[:max_chars] + "…"


def _size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))


class WorkflowContextAssembler:
    """Ensambla el contexto declarado por un nodo, con caps duros."""

    def __init__(self, *, budget: ContextBudget | None = None) -> None:
        self._budget = budget or DEFAULT_CONTEXT_BUDGET

    @property
    def budget(self) -> ContextBudget:
        return self._budget

    def for_agent(
        self,
        context: WorkflowContext,
        *,
        reads: tuple[str, ...] | list[str],
    ) -> AssembledContext:
        """Contexto permitido para un prompt de agente."""
        return self.for_node(context, reads=reads)

    def for_node(
        self,
        context: WorkflowContext,
        *,
        reads: tuple[str, ...] | list[str] = (),
        include_sections: tuple[str, ...] | list[str] | None = None,
    ) -> AssembledContext:
        wanted = self._resolve_sections(reads if include_sections is None else include_sections)
        payload: dict[str, Any] = {}
        used: list[str] = []
        truncated: list[str] = []
        for section in wanted:
            data = self._section_value(context, section)
            if data is None or data == {} or data == []:
                continue
            data, was_truncated = self._fit_section(data)
            if was_truncated:
                truncated.append(section)
            if data is None or data == {} or data == []:
                continue
            payload[section] = data
            used.append(section)
        payload, dropped = self._fit_total(payload)
        truncated.extend(dropped)
        return AssembledContext(
            payload=payload,
            rendered=self._render(payload),
            sections_used=tuple(used),
            truncated=tuple(dict.fromkeys(truncated)),
            budget=self._budget,
        )

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------
    def _resolve_sections(self, reads: tuple[str, ...] | list[str]) -> list[str]:
        resolved: list[str] = []
        for name in reads:
            section = normalize_section(str(name))
            if section is None:
                continue
            if section in RUNTIME_ONLY_SECTIONS or section not in LLM_VISIBLE_SECTIONS:
                continue
            if section not in resolved:
                resolved.append(section)
        return resolved

    def _section_value(self, context: WorkflowContext, section: str) -> Any:
        if section == "trigger":
            snapshot = context.trigger.to_dict()
            snapshot.pop("occurred_at", None)
            return snapshot
        if section in ("data", "knowledge"):
            slots = getattr(context, section, {}) or {}
            return {
                str(key): self._entry_value(entry)
                for key, entry in slots.items()
            }
        entries = getattr(context, section, None)
        if isinstance(entries, list):
            return [self._entry_value(entry) for entry in entries]
        return None

    @staticmethod
    def _entry_value(entry: Any) -> Any:
        """Compacta una entrada de contexto: solo el valor tipado."""
        if isinstance(entry, dict) and "value" in entry:
            if entry.get("redacted"):
                return "[redactado]"
            return jsonable(entry.get("value"))
        return jsonable(entry)

    def _fit_section(self, data: Any) -> tuple[Any, bool]:
        truncated = False
        if isinstance(data, list) and len(data) > self._budget.max_values_per_section:
            data = data[: self._budget.max_values_per_section]
            truncated = True
        elif isinstance(data, dict) and len(data) > self._budget.max_values_per_section:
            keys = list(data)[: self._budget.max_values_per_section]
            data = {key: data[key] for key in keys}
            truncated = True
        while data and _size(data) > self._budget.max_chars_per_section:
            truncated = True
            if isinstance(data, list):
                data = data[:-1]
            elif isinstance(data, dict):
                if not data:
                    break
                data.pop(list(data)[-1], None)
            else:
                data = str(data)[: self._budget.max_chars_per_section]
                break
        return data, truncated

    def _fit_total(self, payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        dropped: list[str] = []
        while payload:
            total = sum(_size(value) for value in payload.values())
            if total <= self._budget.max_chars_total:
                break
            key = list(payload)[-1]
            payload.pop(key)
            dropped.append(key)
        return payload, dropped

    def _render(self, payload: dict[str, Any]) -> str:
        lines: list[str] = []
        for section, data in payload.items():
            lines.append(f"[{section}]")
            if isinstance(data, dict):
                for key, value in data.items():
                    lines.append(f"- {key}: {_compact(value)}")
            elif isinstance(data, list):
                for index, value in enumerate(data):
                    lines.append(f"- {index}: {_compact(value)}")
            else:
                lines.append(f"- {_compact(data)}")
        return "\n".join(lines)


__all__ = [
    "AssembledContext",
    "ContextBudget",
    "DEFAULT_CONTEXT_BUDGET",
    "DEFAULT_SECTION_ORDER",
    "WorkflowContextAssembler",
]
