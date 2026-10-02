# =============================================================================
# Cognitive story — proyección de flow["cognitive"] a 3 niveles (C6, W3).
# =============================================================================
# normal   = pasos humanos (claves + números; el portal traduce a texto)
# expanded = detalle estructurado acotado (strategy, evidencia, budget, loop)
# raw      = refs y métricas crudas del run profundo
# Aditivo y fail-soft: sin cognitive devuelve shape vacío; nunca lanza.
# =============================================================================
from __future__ import annotations

from typing import Any, Mapping

COGNITIVE_STORY_SCHEMA_VERSION = 1
_MAX_EXPANDED_ITEMS = 8


def _mapping(value: Any) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list:
    return list(value) if isinstance(value, (list, tuple)) else []


def _counts_by_status(mentions: list) -> dict:
    counts: dict[str, int] = {}
    for mention in mentions:
        status = str(_mapping(mention).get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def build_cognitive_story(flow: Mapping | None) -> dict:
    """Deriva los 3 niveles del bloque cognitivo del flow."""
    cognitive = _mapping(_mapping(flow).get("cognitive"))
    if not cognitive:
        return {
            "schema_version": COGNITIVE_STORY_SCHEMA_VERSION,
            "normal": [],
            "expanded": {},
            "raw": {},
        }

    normal: list[dict] = []

    plan = _mapping(cognitive.get("plan"))
    if plan:
        normal.append(
            {
                "kind": "cognitive_plan",
                "phase": "planning",
                "status": "ok",
                "metrics": {
                    "complexity": plan.get("complexity"),
                    "needs": len(_sequence(plan.get("needs"))),
                },
            }
        )

    strategy = _mapping(cognitive.get("strategy"))
    if strategy:
        representations = _sequence(strategy.get("representations"))
        normal.append(
            {
                "kind": "cognitive_strategy",
                "phase": "planning",
                "status": "ok",
                "metrics": {
                    "primary": strategy.get("primary"),
                    "representations": len(representations),
                },
            }
        )

    entities = _mapping(cognitive.get("entities"))
    if entities:
        mentions = _sequence(entities.get("mentions"))
        normal.append(
            {
                "kind": "cognitive_entities",
                "phase": "understanding",
                "status": "ok" if entities.get("resolved") else "warn",
                "metrics": {
                    "resolved": bool(entities.get("resolved")),
                    "mentions": len(mentions),
                    "by_status": _counts_by_status(mentions),
                },
            }
        )

    for runner in _sequence(cognitive.get("runners")):
        item = _mapping(runner)
        normal.append(
            {
                "kind": "cognitive_runner",
                "phase": "evidence",
                "status": str(item.get("status") or "ok"),
                "metrics": {
                    "representation": item.get("representation"),
                    "count": item.get("count"),
                    "latency_ms": item.get("latency_ms"),
                },
            }
        )

    evidence = _mapping(cognitive.get("evidence"))
    if evidence:
        normal.append(
            {
                "kind": "cognitive_evidence",
                "phase": "evidence",
                "status": "ok" if not _sequence(evidence.get("conflicts")) else "warn",
                "metrics": {
                    "count": evidence.get("count"),
                    "chars": evidence.get("chars"),
                    "budget_chars": evidence.get("budget_chars"),
                    "conflicts": len(_sequence(evidence.get("conflicts"))),
                    "dropped": evidence.get("dropped_count"),
                },
            }
        )

    brief = _mapping(cognitive.get("brief"))
    if brief:
        normal.append(
            {
                "kind": "cognitive_brief",
                "phase": "planning",
                "status": "ok",
                "metrics": {
                    "chars": brief.get("chars"),
                    "budget_chars": brief.get("budget_chars"),
                    "sections": len(_sequence(brief.get("sections"))),
                },
            }
        )

    verification = _mapping(cognitive.get("verification"))
    if verification:
        normal.append(
            {
                "kind": "cognitive_verification",
                "phase": "verification",
                "status": (
                    "ok" if verification.get("action") == "approve" else "warn"
                ),
                "metrics": {
                    "action": verification.get("action"),
                    "count": verification.get("count"),
                    "unsupported": verification.get("unsupported"),
                    "conflicted": verification.get("conflicted"),
                },
            }
        )

    budget = _mapping(cognitive.get("budget"))
    if budget:
        normal.append(
            {
                "kind": "cognitive_budget",
                "phase": "decision",
                "status": "ok" if budget.get("within_budget") else "warn",
                "metrics": {
                    "complexity": budget.get("complexity"),
                    "tokens": budget.get("tokens"),
                    "max_tokens": budget.get("max_tokens"),
                    "llm_calls": budget.get("llm_calls"),
                },
            }
        )

    loop = _mapping(cognitive.get("loop"))
    if loop:
        normal.append(
            {
                "kind": "cognitive_loop",
                "phase": "evidence",
                "status": "warn" if loop.get("exhausted") else "ok",
                "metrics": {
                    "count": loop.get("count"),
                    "extra_round": bool(loop.get("extra_round")),
                    "exhausted": bool(loop.get("exhausted")),
                },
            }
        )

    learning = _sequence(cognitive.get("learning"))
    if learning:
        normal.append(
            {
                "kind": "cognitive_learning",
                "phase": "learning",
                "status": "ok",
                "metrics": {
                    "count": len(learning),
                    "kinds": sorted(
                        {str(_mapping(item).get("kind") or "") for item in learning}
                    ),
                },
            }
        )

    run_id = str(cognitive.get("run_id") or "")
    deep = _mapping(cognitive.get("deep"))
    if run_id or deep:
        normal.append(
            {
                "kind": "cognitive_deep_run",
                "phase": "generation",
                "status": (
                    "ok"
                    if str(deep.get("status") or "") == "completed"
                    else ("warn" if deep else "ok")
                ),
                "metrics": {
                    "run_id": run_id or None,
                    "status": deep.get("status"),
                    "failure_mode": deep.get("failure_mode") or None,
                    "tokens": _mapping(deep.get("metrics")).get("tokens"),
                },
            }
        )

    expanded = {
        "signals": dict(_mapping(cognitive.get("signals"))),
        "strategy": dict(strategy),
        "entities": dict(entities),
        "runners": _sequence(cognitive.get("runners"))[:_MAX_EXPANDED_ITEMS],
        "evidence": {
            "counts": dict(_mapping(evidence.get("counts"))),
            "chars": evidence.get("chars"),
            "budget_chars": evidence.get("budget_chars"),
            "conflicts": len(_sequence(evidence.get("conflicts"))),
            "dropped_count": evidence.get("dropped_count"),
        },
        "brief": {
            "chars": brief.get("chars"),
            "budget_chars": brief.get("budget_chars"),
            "sections": [
                {
                    "kind": _mapping(section).get("kind"),
                    "count": _mapping(section).get("count"),
                    "chars": _mapping(section).get("chars"),
                    "truncated": _mapping(section).get("truncated"),
                }
                for section in _sequence(brief.get("sections"))[:_MAX_EXPANDED_ITEMS]
            ],
        },
        "verification": dict(verification),
        "budget": dict(budget),
        "loop": dict(loop),
        "learning": learning[:_MAX_EXPANDED_ITEMS],
        "deep": dict(deep),
    }
    raw = {
        "mode": cognitive.get("mode"),
        "run_id": run_id or None,
        "deep_metrics": dict(_mapping(deep.get("metrics"))),
        "budget": dict(budget),
        "loop": dict(loop),
    }
    return {
        "schema_version": COGNITIVE_STORY_SCHEMA_VERSION,
        "normal": normal,
        "expanded": expanded,
        "raw": raw,
    }
