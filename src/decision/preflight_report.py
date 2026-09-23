# =============================================================================
# JEV Preflight — observaciones y reporte de efectividad (Control Center).
# =============================================================================
# Cada request que llega al gate de pre-generación deja UNA observación acotada:
# qué juicios se hicieron, qué decidió el código y qué efecto tuvo. El reporte
# agrega esas observaciones: KPIs, embudo de escalado, utilidad por pregunta.
#
# Reglas:
# - Sin datos no se inventan KPIs: un cálculo que no existe se omite.
# - Nunca se guarda razonamiento privado: sólo decisiones, efectos y números.
# - El buffer es en memoria y acotado (observabilidad operativa, no auditoría).
# =============================================================================
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any

from src.decision.preflight import (
    ACTION_DETERMINISTIC,
    ACTION_RECONSTRUCT,
    ACTION_RETRIEVE,
    DECIDED_BY_JEV,
    EXPENSIVE_TIERS,
    TIER_DETERMINISTIC,
    TIER_SMALL,
    TIER_STANDARD,
    normalize_preflight_mode,
)
from src.decision.registry import public_registry

MAX_OBSERVATIONS = 500


@dataclass
class PreflightObservation:
    """Lo que un request dejó en el gate. Sin CoT, sin texto libre."""

    mode: str = "off"
    tier: str = ""
    action: str = ""
    allow_generation: bool = True
    applied: bool = False
    legacy_tier: str = TIER_STANDARD
    judgments: int = 0
    calls: int = 0
    questions_per_call: float = 0.0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    uncertain: list[str] = field(default_factory=list)
    effects: list[str] = field(default_factory=list)
    unsatisfied: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    questions: list[dict[str, Any]] = field(default_factory=list)
    readiness: dict[str, int] = field(default_factory=dict)
    decided_by: str = DECIDED_BY_JEV

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "mode": self.mode,
            "tier": self.tier,
            "action": self.action,
            "allow_generation": bool(self.allow_generation),
            "applied": bool(self.applied),
            "judgments": int(self.judgments),
            "calls": int(self.calls),
        }
        if self.uncertain:
            payload["uncertain"] = list(self.uncertain)[:8]
        if self.effects:
            payload["effects"] = list(self.effects)[:8]
        return payload


_OBSERVATIONS: deque[PreflightObservation] = deque(maxlen=MAX_OBSERVATIONS)


def record_observation(observation: PreflightObservation | None) -> None:
    if observation is None:
        return
    # El detalle por pregunta se agrega en el reporte, no en memoria por request.
    observation.questions = list(observation.questions)[:64]
    _OBSERVATIONS.append(observation)


def observations() -> list[PreflightObservation]:
    return list(_OBSERVATIONS)


def clear_observations() -> None:
    _OBSERVATIONS.clear()


def observation_from_trace(
    *,
    trace: Any,
    decision: Any,
    mode: str = "",
    readiness: Any = None,
    legacy_tier: str = TIER_STANDARD,
) -> PreflightObservation:
    """Construye la observación del request desde la traza y la decisión."""
    summary = trace.summary() if trace is not None and hasattr(trace, "summary") else {}
    uncertain: list[str] = []
    effects: list[str] = []
    questions: list[dict[str, Any]] = []
    for pack in list(getattr(trace, "packs", ()) or ()):
        if not getattr(pack, "ok", False):
            continue
        for question in getattr(pack, "questions", ()) or ():
            if getattr(question, "effect", None):
                effects.append(str(question.effect))
            questions.append(
                {
                    "id": str(getattr(question, "id", "")),
                    "phase": str(getattr(pack, "phase", "")),
                    "type": str(getattr(question, "type", "")),
                    "version": int(getattr(question, "version", 0) or 0),
                    "uncertain": str(getattr(question, "decision", "")) == "uncertain"
                    or bool(getattr(question, "ambiguous", False)),
                    "effect": str(getattr(question, "effect", "") or ""),
                }
            )
        if hasattr(pack, "uncertain_ids"):
            uncertain.extend(str(item) for item in pack.uncertain_ids())
    for item in list(getattr(decision, "uncertain_critical", ()) or ()):
        uncertain.append(str(item))
    rows: dict[str, int] = {}
    if readiness is not None and hasattr(readiness, "rows"):
        for row in readiness.rows:
            rows[str(getattr(row, "state", "unknown"))] = (
                rows.get(str(getattr(row, "state", "unknown")), 0) + 1
            )
    return PreflightObservation(
        mode=normalize_preflight_mode(mode or getattr(decision, "mode", "")),
        tier=str(getattr(decision, "tier", "") or ""),
        action=str(getattr(decision, "action", "") or ""),
        allow_generation=bool(getattr(decision, "allow_generation", True)),
        applied=bool(getattr(decision, "applied", False)),
        legacy_tier=str(legacy_tier or TIER_STANDARD),
        judgments=int(summary.get("judgments") or 0),
        calls=int(summary.get("calls") or 0),
        questions_per_call=float(summary.get("questions_per_call") or 0.0),
        latency_ms=float(summary.get("latency_ms") or 0.0),
        cost_usd=float(summary.get("cost_usd") or 0.0),
        uncertain=sorted(set(uncertain)),
        effects=sorted(set(effects)),
        unsatisfied=[str(item) for item in list(getattr(decision, "unsatisfied", ()) or ())],
        conflicts=[str(item) for item in list(getattr(decision, "conflicts", ()) or ())],
        questions=questions,
        readiness=rows,
        decided_by=str(getattr(decision, "decided_by", DECIDED_BY_JEV) or DECIDED_BY_JEV),
    )


def _question_stats(rows: list[PreflightObservation]) -> list[dict[str, Any]]:
    """Utilidad por pregunta: cuántas veces se hizo, dudó y cambió algo (§48)."""
    stats: dict[str, dict[str, Any]] = {}
    for observation in rows:
        for detail in observation.questions:
            question_id = str(detail.get("id") or "")
            if not question_id:
                continue
            entry = stats.setdefault(
                question_id,
                {
                    "id": question_id,
                    "phase": str(detail.get("phase") or ""),
                    "type": str(detail.get("type") or ""),
                    "version": int(detail.get("version") or 0),
                    "asked": 0,
                    "uncertain": 0,
                    "with_effect": 0,
                },
            )
            entry["asked"] += 1
            if detail.get("uncertain") or detail.get("ambiguous"):
                entry["uncertain"] += 1
            if detail.get("effect"):
                entry["with_effect"] += 1
    return sorted(stats.values(), key=lambda item: (-item["asked"], item["id"]))


def _funnel(rows: list[PreflightObservation]) -> list[dict[str, Any]]:
    """Embudo de escalado: qué pasó con cada request que llegó al gate (§55)."""
    requests = len(rows)
    if not requests:
        return []
    blocked = [row for row in rows if not row.allow_generation]
    generated = [row for row in rows if row.allow_generation]
    cheap = [row for row in generated if row.tier in (TIER_DETERMINISTIC, TIER_SMALL)]
    expensive = [row for row in generated if row.tier in EXPENSIVE_TIERS]
    retrieval = [
        row
        for row in rows
        if row.action in (ACTION_RETRIEVE, ACTION_RECONSTRUCT)
    ]
    deterministic = [
        row for row in rows if row.tier == TIER_DETERMINISTIC or row.action == ACTION_DETERMINISTIC
    ]
    return [
        {"stage": "requests", "count": requests},
        {"stage": "deterministic_answer", "count": len(deterministic)},
        {"stage": "more_analysis_requested", "count": len(retrieval)},
        {"stage": "generation_allowed", "count": len(generated)},
        {"stage": "cheap_tier", "count": len(cheap)},
        {"stage": "expensive_tier", "count": len(expensive)},
        {"stage": "generation_blocked", "count": len(blocked)},
    ]


def preflight_report(*, settings: Any = None, mode: str | None = None) -> dict[str, Any]:
    """KPIs de efectividad del juicio previo. Sólo con datos reales."""
    rows = observations()
    effective_mode = normalize_preflight_mode(
        mode or (getattr(settings, "mode", "") if settings is not None else "") or "off"
    )
    judgments = sum(row.judgments for row in rows)
    calls = sum(row.calls for row in rows)
    latency = sum(row.latency_ms for row in rows)
    cost = sum(row.cost_usd for row in rows)
    uncertain = sum(len(row.uncertain) for row in rows)
    influenced = len(
        [
            row
            for row in rows
            if row.applied
            and (
                not row.allow_generation
                or row.tier in (TIER_DETERMINISTIC, TIER_SMALL)
                or row.effects
            )
        ]
    )
    avoided = len(
        [
            row
            for row in rows
            if row.applied
            and (
                not row.allow_generation
                or (
                    row.tier in (TIER_DETERMINISTIC, TIER_SMALL)
                    and row.legacy_tier in EXPENSIVE_TIERS
                )
            )
        ]
    )
    tiers: Counter[str] = Counter(row.tier for row in rows if row.tier)
    actions: Counter[str] = Counter(row.action for row in rows if row.action)
    effects: Counter[str] = Counter(effect for row in rows for effect in row.effects)
    readiness_states: Counter[str] = Counter(
        state for row in rows for state in row.readiness
    )
    kpis: dict[str, Any] = {
        "requests_observed": len(rows),
        "judgments": judgments,
        "batched_calls": calls,
        "uncertain_critical_judgments": uncertain,
        "decisions_influencing": influenced,
        "llm_escalations_avoided": avoided,
        "latency_ms_total": round(latency, 2),
        "cost_usd_total": round(cost, 6),
    }
    if calls:
        kpis["questions_per_call"] = round(judgments / calls, 2)
        kpis["avg_latency_ms"] = round(latency / calls, 2)
    if rows:
        kpis["judgments_per_request"] = round(judgments / len(rows), 2)
    report: dict[str, Any] = {
        "mode": effective_mode,
        "kpis": kpis,
        "funnel": _funnel(rows),
        "questions": _question_stats(rows),
        "decisions": {
            "tiers": dict(tiers),
            "actions": dict(actions),
            "effects": dict(effects),
            "readiness_rows": dict(readiness_states),
        },
        "recent": [row.to_public_dict() for row in rows[-20:]][::-1],
        "note": (
            "Sólo requests que llegaron al gate cuentan. Costo y latencia son los "
            "medidos por JEV; el cruce con FinOps vive en /costs."
        ),
    }
    if settings is not None:
        report["config"] = {
            "mode": effective_mode,
            "canary_percentage": int(getattr(settings, "canary_percentage", 0) or 0),
            "enforce": bool(getattr(settings, "enforce", True)),
            "allow_deterministic_answer": bool(
                getattr(settings, "allow_deterministic_answer", False)
            ),
            "allow_small_tier": bool(getattr(settings, "allow_small_tier", True)),
            "extra_retrieval": bool(getattr(settings, "extra_retrieval", True)),
            "reasoning_first": bool(getattr(settings, "reasoning_first", True)),
        }
    return report


def preflight_questions(*, phase: str | None = None) -> list[dict]:
    """Registro de preguntas para el modo técnico del Control Center (§53)."""
    return public_registry(phase=phase)


__all__ = [
    "MAX_OBSERVATIONS",
    "PreflightObservation",
    "clear_observations",
    "observation_from_trace",
    "observations",
    "preflight_questions",
    "preflight_report",
    "record_observation",
]
