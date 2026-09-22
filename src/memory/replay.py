"""Replay de una respuesta: run nuevo, original intacto, sin efectos reales."""
from __future__ import annotations

import copy
from typing import Any
from uuid import UUID, uuid4

from src.learning_engine.safety import SAFE_EXECUTIONS, SIDE_EFFECT_TOOLS


class ReplayBlocked(RuntimeError):
    def __init__(self, tool: str) -> None:
        self.tool = tool
        super().__init__(f"{tool} requires mock, dry_run, or simulation during replay")


class ReplayNotFound(KeyError):
    pass


def assert_replay_safe(tools: list[dict[str, Any]]) -> None:
    """Falla cerrado. Un tool con efecto y ejecución live no arranca el replay."""
    for tool in tools:
        name = str(tool.get("name") or "")
        execution = str(tool.get("execution") or "live")
        risky = bool(tool.get("side_effect")) or name in SIDE_EFFECT_TOOLS
        if risky and execution not in SAFE_EXECUTIONS:
            raise ReplayBlocked(name or "tool")


def snapshot(flow: dict[str, Any] | None) -> dict[str, Any]:
    """Campos comparables. Ausente queda None. No rellena con 0."""
    data = flow or {}
    retrieval = _record(data.get("retrieval"))
    grounding = _record(data.get("grounding"))
    generation = _record(data.get("generation"))
    timings = _record(data.get("timings"))
    verdict = _record(data.get("verdict"))
    evidence = _record(data.get("evidence"))
    sources = [
        str(item.get("title"))
        for item in data.get("sources") or []
        if isinstance(item, dict) and item.get("title")
    ]
    outcome = _outcome(data, grounding, evidence)
    return {
        "route": _text(verdict.get("route")),
        "retrieval_strategy": _text(retrieval.get("strategy")) or _text(retrieval.get("engine_strategy")),
        "sources": sources,
        "grounding": _number(grounding.get("score")) if grounding else None,
        "cost": _number(generation.get("cost")) if generation else None,
        "latency_ms": _number(timings.get("total_ms")),
        "outcome": outcome,
    }


def compare_flows(original: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    left = snapshot(original)
    right = snapshot(current)
    fields = {}
    for key in ("route", "retrieval_strategy", "sources", "grounding", "cost", "latency_ms", "outcome"):
        fields[key] = {"original": left[key], "current": right[key]}
    return {"fields": fields, "improvement": _improvement(left, right)}


def what_changed(
    original: dict[str, Any],
    current: dict[str, Any],
    *,
    original_memories: list[dict[str, Any]] | None = None,
    current_memories: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Solo diferencias presentes en los dos flujos o en las listas de memoria."""
    left = snapshot(original)
    right = snapshot(current)
    changes: list[dict[str, Any]] = []
    for key in ("route", "retrieval_strategy", "outcome"):
        if left[key] != right[key] and (left[key] is not None or right[key] is not None):
            changes.append({"kind": key, "original": left[key], "current": right[key]})
    original_sources = set(left["sources"])
    current_sources = set(right["sources"])
    if original_sources != current_sources:
        changes.append(
            {
                "kind": "sources",
                "added": sorted(current_sources - original_sources),
                "removed": sorted(original_sources - current_sources),
            }
        )
    for key in ("grounding", "cost", "latency_ms"):
        if left[key] is None or right[key] is None:
            continue
        if left[key] != right[key]:
            changes.append({"kind": key, "original": left[key], "current": right[key]})
    seen = {str(item.get("memory_id")) for item in original_memories or [] if item.get("memory_id")}
    for item in current_memories or []:
        memory_id = str(item.get("memory_id") or "")
        if not memory_id or memory_id in seen:
            continue
        changes.append(
            {
                "kind": "memory",
                "memory_id": memory_id,
                "display_id": str(item.get("display_id") or memory_id.replace("-", "")[:8]),
                "title": str(item.get("title") or ""),
            }
        )
    return changes


def project_current_flow(
    original: dict[str, Any],
    patterns: list[dict[str, Any]],
    *,
    replay_query_id: UUID | None = None,
) -> dict[str, Any]:
    """Flujo actual sin rellenar grounding, costo ni latencia que no se midieron."""
    current: dict[str, Any] = {
        "query_id": str(replay_query_id or uuid4()),
        "status": "replay",
        "verdict": {"route": snapshot(original)["route"]},
        "retrieval": {},
    }
    modality = _modality(patterns)
    strategy = modality or snapshot(original)["retrieval_strategy"]
    if strategy:
        current["retrieval"]["strategy"] = strategy
    sources = original.get("sources")
    if isinstance(sources, list):
        current["sources"] = copy.deepcopy(sources)
    return current


class ReplayBook:
    """Guarda el flujo original y el replay. Nunca muta el original."""

    def __init__(self) -> None:
        self.flows: dict[tuple[str, str], dict[str, Any]] = {}
        self.replays: list[dict[str, Any]] = []

    def remember(self, organization_id: UUID, flow: dict[str, Any]) -> None:
        query_id = str(flow.get("query_id") or "")
        self.flows[(str(organization_id), query_id)] = copy.deepcopy(flow)

    def start(
        self,
        organization_id: UUID,
        query_id: UUID,
        *,
        tools: list[dict[str, Any]],
        patterns: list[dict[str, Any]],
        original_memories: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        assert_replay_safe(tools)
        key = (str(organization_id), str(query_id))
        stored = self.flows.get(key)
        if stored is None:
            raise ReplayNotFound(str(query_id))
        original = copy.deepcopy(stored)
        replay_query_id = uuid4()
        current = project_current_flow(original, patterns, replay_query_id=replay_query_id)
        if self.flows[key] != stored:
            raise RuntimeError("original flow was mutated")
        body = {
            "replay_id": str(uuid4()),
            "source_query_id": str(query_id),
            "replay_query_id": str(replay_query_id),
            "organization_id": str(organization_id),
            "original_unchanged": True,
            "comparison": compare_flows(original, current),
            "what_changed": what_changed(
                original,
                current,
                original_memories=original_memories,
                current_memories=patterns,
            ),
        }
        self.replays.append(body)
        if self.flows[key] != stored:
            raise RuntimeError("original flow was mutated")
        return body


def _modality(patterns: list[dict[str, Any]]) -> str | None:
    for pattern in patterns:
        value = _text(pattern.get("retrieval_modality"))
        if value and value not in {"unknown_retrieval", "none", "unclassified"}:
            return value
    return None


def _improvement(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {
        "quality": _percent(left.get("grounding"), right.get("grounding")),
        "cost": _percent(left.get("cost"), right.get("cost")),
    }


def _percent(original: Any, current: Any) -> float | None:
    if not isinstance(original, (int, float)) or not isinstance(current, (int, float)):
        return None
    if isinstance(original, bool) or isinstance(current, bool):
        return None
    if original == 0:
        return None
    return round((float(current) - float(original)) / abs(float(original)), 4)


def _outcome(data: dict[str, Any], grounding: dict[str, Any], evidence: dict[str, Any]) -> str | None:
    if grounding:
        if "grounded" not in grounding:
            return None
        return "grounded" if grounding.get("grounded") else "insufficient"
    if evidence:
        if "sufficient" not in evidence:
            return None
        return "sufficient" if evidence.get("sufficient") else "insufficient"
    status = _text(data.get("status"))
    if status in {"completed", "failed", "replay"}:
        return None
    return status


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
