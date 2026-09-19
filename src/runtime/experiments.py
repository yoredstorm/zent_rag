# =============================================================================
# Experiment Lab — compare Rules / JEV / small LLM / reasoning on a dataset.
# Does not call production traffic. Dataset is caller-supplied.
# =============================================================================
from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from src.core.domain.decision import DecisionContext
from src.decision.settings import DecisionEngineSettings


async def run_comparison(
    cases: list[dict[str, Any]],
    *,
    rules,
    jev=None,
    small_llm=None,
    reasoning=None,
    settings: DecisionEngineSettings | None = None,
) -> dict[str, Any]:
    cfg = settings or DecisionEngineSettings(routing_mode="jev", jev_api_key="x")
    providers = {
        "rules": rules,
        "jev": jev,
        "small_llm": small_llm,
        "reasoning": reasoning,
    }
    rows: list[dict[str, Any]] = []
    for case in cases[:200]:
        expected = str(case.get("expected_capability") or "")
        context = DecisionContext(
            user_request=str(case.get("request") or case.get("query") or ""),
            organization_id=case.get("organization_id") or uuid4(),
            request_id=uuid4(),
            sql_enabled=bool(case.get("sql_enabled", True)),
            knowledge_enabled=bool(case.get("knowledge_enabled", True)),
            available_capabilities=tuple(
                case.get("available_capabilities")
                or (
                    "knowledge.answer",
                    "database.query",
                    "respond_directly",
                    "agent.execute",
                    "workflow.execute",
                    "llm.reason",
                )
            ),
            permissions=frozenset({"*"}),
        )
        row: dict[str, Any] = {"request": context.user_request[:200], "expected": expected}
        for name, provider in providers.items():
            if provider is None:
                row[name] = None
                continue
            started = time.perf_counter()
            try:
                decision = await provider.decide(context)
                latency = (time.perf_counter() - started) * 1000
                row[name] = {
                    "capability": decision.capability,
                    "resolved": decision.resolved,
                    "confidence": round(decision.confidence, 4),
                    "latency_ms": round(latency, 2),
                    "tokens": int(decision.prompt_tokens or 0) + int(decision.completion_tokens or 0),
                    "cost": round(float(decision.estimated_cost or 0.0), 6),
                    "fallback": bool(decision.fallback_used),
                    "match": (decision.capability == expected) if expected else None,
                }
            except Exception as exc:  # noqa: BLE001
                row[name] = {"error": str(exc)[:160], "match": False}
        rows.append(row)
    return {"cases": len(rows), "results": rows, "mode": cfg.effective_mode}


def summarize(report: dict[str, Any]) -> dict[str, Any]:
    providers = ("rules", "jev", "small_llm", "reasoning")
    summary: dict[str, Any] = {}
    results = report.get("results") or []
    for name in providers:
        samples = [r.get(name) for r in results if isinstance(r.get(name), dict) and "error" not in (r.get(name) or {})]
        if not samples:
            summary[name] = None
            continue
        matches = [s for s in samples if s.get("match") is True]
        labeled = [s for s in samples if s.get("match") is not None]
        summary[name] = {
            "n": len(samples),
            "routing_accuracy": round(len(matches) / len(labeled), 4) if labeled else None,
            "average_confidence": round(sum(float(s.get("confidence") or 0) for s in samples) / len(samples), 4),
            "average_latency_ms": round(sum(float(s.get("latency_ms") or 0) for s in samples) / len(samples), 2),
            "tokens": int(sum(int(s.get("tokens") or 0) for s in samples)),
            "cost": round(sum(float(s.get("cost") or 0) for s in samples), 6),
            "fallback_rate": round(
                sum(1 for s in samples if s.get("fallback")) / len(samples), 4
            ),
        }
    return summary
