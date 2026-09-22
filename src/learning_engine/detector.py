# =============================================================================
# Pattern detector — tasas, umbrales, ventanas. Sin modelo entrenado.
# =============================================================================
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from src.core.domain.learning_cycle import Finding, FindingSeverity, RunSignal, WindowName
from src.learning_engine.outcome import OutcomeEvaluator
from src.learning_engine.windows import confidence_for

_EVALUATOR = OutcomeEvaluator()
_STRATEGY_GAP = 0.15
_RETRY_RATE = 0.20
_TIMEOUT_RATE = 0.15
_GROUNDING_FAIL = 0.20
_FAILURE_RATE = 0.25
_COST_RATIO = 1.20
_QUALITY_TIE = 0.02
_JEV_SHARE = 0.25
_SUCCESS_SHARE = 0.70
_LOOP_RATE = 0.30


@dataclass(kw_only=True)
class PatternHit:
    category: str
    severity: str
    pattern_key: str
    observed: str
    alternative: str
    baseline_strategy: str
    candidate_strategy: str
    sample_size: int
    window: str
    confidence: str
    evidence: list[str]
    affected: list[str]
    impact: dict[str, Any] = field(default_factory=dict)
    baseline_rate: float | None = None
    candidate_rate: float | None = None

    def dedupe_key(self) -> str:
        return f"{self.category}:{self.pattern_key}:{self.baseline_strategy}:{self.candidate_strategy}"

    def to_finding(self, organization_id: UUID, now: datetime | None = None) -> Finding:
        current = now or datetime.now(timezone.utc)
        return Finding(
            organization_id=organization_id,
            category=self.category,
            severity=FindingSeverity(self.severity),
            pattern_key=self.pattern_key,
            observed=self.observed,
            alternative=self.alternative,
            baseline_strategy=self.baseline_strategy,
            candidate_strategy=self.candidate_strategy,
            sample_size=self.sample_size,
            window=self.window,
            confidence=self.confidence,
            dedupe_key=self.dedupe_key(),
            first_seen=current,
            last_seen=current,
            evidence=list(self.evidence)[:10],
            affected=list(self.affected)[:20],
            impact=dict(self.impact),
            baseline_rate=self.baseline_rate,
            candidate_rate=self.candidate_rate,
        )


def detect(
    signals: list[RunSignal],
    *,
    window: WindowName | str,
    min_sample: int = 20,
) -> list[PatternHit]:
    hits: list[PatternHit] = []
    hits.extend(_retrieval_gaps(signals, window=window, min_sample=min_sample))
    hits.extend(_retry_rates(signals, window=window, min_sample=min_sample))
    hits.extend(_timeouts(signals, window=window, min_sample=min_sample))
    hits.extend(_grounding_by_source(signals, window=window, min_sample=min_sample))
    hits.extend(_agent_loops(signals, window=window, min_sample=min_sample))
    hits.extend(_cost_gaps(signals, window=window, min_sample=min_sample))
    hits.extend(_jev_disagreements(signals, window=window, min_sample=min_sample))
    covered = {hit.pattern_key for hit in hits if hit.category == "retrieval" and hit.candidate_strategy}
    for hit in _failure_rates(signals, window=window, min_sample=min_sample):
        if hit.pattern_key in covered:
            continue
        hits.append(hit)
    return _dedupe(hits)


def _dedupe(hits: list[PatternHit]) -> list[PatternHit]:
    seen: set[str] = set()
    unique: list[PatternHit] = []
    for hit in hits:
        key = hit.dedupe_key()
        if key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    return unique


def _groups(signals: list[RunSignal]) -> dict[str, list[RunSignal]]:
    grouped: dict[str, list[RunSignal]] = defaultdict(list)
    for signal in signals:
        grouped[signal.pattern_key].append(signal)
    return grouped


def _rate(flags: list[bool]) -> float:
    if not flags:
        return 0.0
    return sum(1 for flag in flags if flag) / len(flags)


def _sources(signals: list[RunSignal]) -> list[str]:
    names: list[str] = []
    for signal in signals:
        if signal.source_name and signal.source_name not in names:
            names.append(signal.source_name)
    return names[:20]


def _severity_from_failure(rate: float) -> str:
    if rate >= 0.50:
        return FindingSeverity.HIGH.value
    if rate >= 0.25:
        return FindingSeverity.MEDIUM.value
    return FindingSeverity.LOW.value


def _success_flag(signal: RunSignal) -> bool:
    if signal.success is not None:
        return bool(signal.success)
    outcome = _EVALUATOR.evaluate(signal)
    return bool(outcome.task_success is not None and outcome.task_success >= 0.5)


def _quality(signal: RunSignal) -> float | None:
    outcome = _EVALUATOR.evaluate(signal)
    if outcome.quality is not None:
        return outcome.quality
    return outcome.task_success


def _grounding(signal: RunSignal) -> float | None:
    return _EVALUATOR.evaluate(signal).grounding


def _hit(
    *,
    category: str,
    severity: str,
    pattern_key: str,
    observed: str,
    alternative: str,
    baseline: str,
    candidate: str,
    sample: list[RunSignal],
    window: WindowName | str,
    evidence: list[str],
    impact: dict[str, Any] | None = None,
    baseline_rate: float | None = None,
    candidate_rate: float | None = None,
    affected: list[RunSignal] | None = None,
) -> PatternHit:
    return PatternHit(
        category=category,
        severity=severity,
        pattern_key=pattern_key,
        observed=observed,
        alternative=alternative,
        baseline_strategy=baseline,
        candidate_strategy=candidate,
        sample_size=len(sample),
        window=WindowName(window).value,
        confidence=confidence_for(len(sample)),
        evidence=evidence,
        affected=_sources(affected if affected is not None else sample),
        impact=impact or {},
        baseline_rate=baseline_rate,
        candidate_rate=candidate_rate,
    )


def _retrieval_gaps(signals: list[RunSignal], *, window: WindowName | str, min_sample: int) -> list[PatternHit]:
    hits: list[PatternHit] = []
    for pattern, rows in _groups(signals).items():
        by_strategy: dict[str, list[RunSignal]] = defaultdict(list)
        for row in rows:
            if row.retrieval_strategy:
                by_strategy[row.retrieval_strategy].append(row)
        scored = []
        for strategy, group in by_strategy.items():
            if len(group) < min_sample:
                continue
            scored.append((strategy, _rate([_success_flag(item) for item in group]), group))
        if len(scored) < 2:
            continue
        scored.sort(key=lambda item: item[1])
        worst_name, worst_rate, worst_rows = scored[0]
        best_name, best_rate, best_rows = scored[-1]
        if best_rate - worst_rate < _STRATEGY_GAP:
            continue
        hits.append(
            _hit(
                category="retrieval",
                severity=_severity_from_failure(1 - worst_rate),
                pattern_key=pattern,
                observed=f"{worst_name} success {worst_rate:.0%}",
                alternative=f"{best_name} historically {best_rate:.0%}",
                baseline=worst_name,
                candidate=best_name,
                sample=worst_rows,
                window=window,
                evidence=[
                    f"baseline_success={worst_rate:.4f}",
                    f"candidate_success={best_rate:.4f}",
                    f"baseline_n={len(worst_rows)}",
                    f"candidate_n={len(best_rows)}",
                    f"window={WindowName(window).value}",
                ],
                impact={
                    "baseline_success_rate": round(worst_rate, 4),
                    "candidate_success_rate": round(best_rate, 4),
                    "sample_size": len(worst_rows),
                },
                baseline_rate=round(worst_rate, 4),
                candidate_rate=round(best_rate, 4),
                affected=worst_rows + best_rows,
            )
        )
    return hits


def _retry_rates(signals: list[RunSignal], *, window: WindowName | str, min_sample: int) -> list[PatternHit]:
    hits: list[PatternHit] = []
    for pattern, rows in _groups(signals).items():
        if len(rows) < min_sample:
            continue
        rate = _rate([row.retried for row in rows])
        if rate < _RETRY_RATE:
            continue
        hits.append(
            _hit(
                category="agent",
                severity=_severity_from_failure(rate),
                pattern_key=pattern,
                observed=f"retry rate {rate:.0%}",
                alternative="single attempt after a typed recovery",
                baseline="retry_same_call",
                candidate="recover_then_retry_once",
                sample=rows,
                window=window,
                evidence=[f"retry_rate={rate:.4f}", f"window={WindowName(window).value}"],
                baseline_rate=round(rate, 4),
                candidate_rate=None,
            )
        )
    return hits


def _timeouts(signals: list[RunSignal], *, window: WindowName | str, min_sample: int) -> list[PatternHit]:
    hits: list[PatternHit] = []
    for pattern, rows in _groups(signals).items():
        timed = [row for row in rows if row.failure_code in {"tool.timeout", "retrieval.timeout"}]
        if len(rows) < min_sample:
            continue
        rate = len(timed) / len(rows)
        if rate < _TIMEOUT_RATE:
            continue
        hits.append(
            _hit(
                category="agent",
                severity=_severity_from_failure(rate),
                pattern_key=pattern,
                observed=f"timeout rate {rate:.0%}",
                alternative="tighter timeout budget or fewer serial calls",
                baseline="current_timeout",
                candidate="reduced_serial_calls",
                sample=rows,
                window=window,
                evidence=[f"timeout_rate={rate:.4f}", f"window={WindowName(window).value}"],
                baseline_rate=round(rate, 4),
            )
        )
    return hits


def _grounding_by_source(
    signals: list[RunSignal], *, window: WindowName | str, min_sample: int
) -> list[PatternHit]:
    hits: list[PatternHit] = []
    grouped: dict[tuple[str, str], list[RunSignal]] = defaultdict(list)
    for signal in signals:
        if signal.source_name:
            grouped[(signal.pattern_key, signal.source_name)].append(signal)
    for (pattern, source), rows in grouped.items():
        measured = [row for row in rows if _grounding(row) is not None]
        if len(measured) < min_sample:
            continue
        fail = _rate([(_grounding(row) or 0) < 0.5 for row in measured])
        if fail < _GROUNDING_FAIL:
            continue
        hits.append(
            _hit(
                category="grounding",
                severity=_severity_from_failure(fail),
                pattern_key=pattern,
                observed=f"{source} grounding failure {fail:.0%}",
                alternative="stricter evidence filter for this source",
                baseline="current_grounding",
                candidate="source_evidence_filter",
                sample=measured,
                window=window,
                evidence=[f"grounding_failure_rate={fail:.4f}", f"source={source}"],
                baseline_rate=round(1 - fail, 4),
                affected=measured,
            )
        )
    return hits


def _schema_loop(signal: RunSignal) -> bool:
    tools = signal.tool_sequence
    errors = signal.tool_errors
    if len(tools) < 2 or len(errors) < 2:
        return False
    same_tool = tools[0] == tools[1] and bool(tools[0])
    schema = "schema" in errors[0].lower() and "schema" in errors[1].lower()
    return same_tool and schema


def _agent_loops(signals: list[RunSignal], *, window: WindowName | str, min_sample: int) -> list[PatternHit]:
    hits: list[PatternHit] = []
    for pattern, rows in _groups(signals).items():
        loops = [row for row in rows if _schema_loop(row)]
        if len(rows) < min_sample or not loops:
            continue
        rate = len(loops) / len(rows)
        if rate < _LOOP_RATE:
            continue
        tool = loops[0].tool_sequence[0]
        hits.append(
            _hit(
                category="agent",
                severity=_severity_from_failure(rate),
                pattern_key=pattern,
                observed=f"{tool} repeated with schema error {rate:.0%}",
                alternative="schema error then inspect_schema then retry once",
                baseline=f"repeat_{tool}",
                candidate="inspect_schema_then_retry_once",
                sample=rows,
                window=window,
                evidence=[
                    f"loop_rate={rate:.4f}",
                    f"tool={tool}",
                    "candidate_policy=schema_error,inspect_schema,retry_once",
                ],
                baseline_rate=round(rate, 4),
            )
        )
    return hits


def _monthly_factor(window: WindowName | str, sample_size: int) -> float | None:
    name = WindowName(window)
    if name == WindowName.ALL_TIME:
        return None
    per_window = {
        WindowName.LAST_HOUR: 24 * 30,
        WindowName.LAST_24H: 30,
        WindowName.LAST_7D: 30 / 7,
        WindowName.LAST_30D: 1,
    }[name]
    return per_window


def _cost_gaps(signals: list[RunSignal], *, window: WindowName | str, min_sample: int) -> list[PatternHit]:
    hits: list[PatternHit] = []
    for pattern, rows in _groups(signals).items():
        by_route: dict[str, list[RunSignal]] = defaultdict(list)
        for row in rows:
            label = row.route_label or row.retrieval_strategy
            if label:
                by_route[label].append(row)
        scored = []
        for route, group in by_route.items():
            if len(group) < min_sample:
                continue
            qualities = [value for value in (_quality(item) for item in group) if value is not None]
            groundings = [value for value in (_grounding(item) for item in group) if value is not None]
            if not qualities:
                continue
            scored.append(
                {
                    "route": route,
                    "quality": sum(qualities) / len(qualities),
                    "grounding": (sum(groundings) / len(groundings)) if groundings else None,
                    "cost": sum(item.cost for item in group) / len(group),
                    "rows": group,
                }
            )
        if len(scored) < 2:
            continue
        scored.sort(key=lambda item: item["cost"])
        cheap = scored[0]
        for costly in scored[1:]:
            if costly["cost"] <= 0 or costly["cost"] < cheap["cost"] * _COST_RATIO:
                continue
            if abs(costly["quality"] - cheap["quality"]) > _QUALITY_TIE:
                continue
            if cheap["grounding"] is not None and costly["grounding"] is not None:
                if cheap["grounding"] + 1e-9 < costly["grounding"]:
                    continue
            per_run = costly["cost"] - cheap["cost"]
            factor = _monthly_factor(window, len(costly["rows"]))
            monthly = None if factor is None else round(per_run * len(costly["rows"]) * factor, 6)
            hits.append(
                _hit(
                    category="cost",
                    severity=FindingSeverity.MEDIUM.value,
                    pattern_key=pattern,
                    observed=f"{costly['route']} cost {costly['cost']:.6f}",
                    alternative=f"{cheap['route']} cost {cheap['cost']:.6f} at similar quality",
                    baseline=costly["route"],
                    candidate=cheap["route"],
                    sample=costly["rows"],
                    window=window,
                    evidence=[
                        f"current_cost={costly['cost']:.6f}",
                        f"candidate_cost={cheap['cost']:.6f}",
                        f"quality_delta={cheap['quality'] - costly['quality']:.4f}",
                    ],
                    impact={
                        "current_cost": round(costly["cost"], 6),
                        "candidate_cost": round(cheap["cost"], 6),
                        "quality_impact": round(cheap["quality"] - costly["quality"], 4),
                        "monthly_potential_saving": monthly,
                        "grounding_protected": True,
                    },
                    baseline_rate=round(costly["quality"], 4),
                    candidate_rate=round(cheap["quality"], 4),
                )
            )
            break
    return hits


def _jev_disagreements(
    signals: list[RunSignal], *, window: WindowName | str, min_sample: int
) -> list[PatternHit]:
    hits: list[PatternHit] = []
    grouped: dict[str, list[RunSignal]] = defaultdict(list)
    for signal in signals:
        if signal.intent_family and (signal.jev_capability or signal.executed_capability):
            grouped[signal.intent_family].append(signal)
    for intent, rows in grouped.items():
        labeled = [row for row in rows if row.jev_capability and row.executed_capability]
        if len(labeled) < min_sample:
            continue
        successful = [row for row in labeled if _success_flag(row)]
        if len(successful) < min_sample:
            continue
        jev_counts: dict[str, int] = defaultdict(int)
        success_counts: dict[str, int] = defaultdict(int)
        for row in labeled:
            jev_counts[row.jev_capability] += 1
        for row in successful:
            success_counts[row.executed_capability] += 1
        jev_choice = max(jev_counts, key=jev_counts.get)
        success_choice = max(success_counts, key=success_counts.get)
        if jev_choice == success_choice:
            continue
        jev_share = jev_counts[jev_choice] / len(labeled)
        success_share = success_counts[success_choice] / len(successful)
        if jev_share < _JEV_SHARE or success_share < _SUCCESS_SHARE:
            continue
        hits.append(
            _hit(
                category="decision",
                severity=FindingSeverity.MEDIUM.value,
                pattern_key=intent,
                observed=f"JEV selects {jev_choice} {jev_share:.0%}",
                alternative=f"successful executions indicate {success_choice} {success_share:.0%}",
                baseline=jev_choice,
                candidate=success_choice,
                sample=labeled,
                window=window,
                evidence=[
                    f"jev_share={jev_share:.4f}",
                    f"success_share={success_share:.4f}",
                    f"intent_family={intent}",
                ],
                baseline_rate=round(jev_share, 4),
                candidate_rate=round(success_share, 4),
            )
        )
    return hits


def _failure_rates(signals: list[RunSignal], *, window: WindowName | str, min_sample: int) -> list[PatternHit]:
    hits: list[PatternHit] = []
    for pattern, rows in _groups(signals).items():
        failed = [row for row in rows if row.failure_code]
        if len(failed) < min_sample:
            continue
        rate = len(failed) / len(rows) if rows else 0.0
        if rate < _FAILURE_RATE:
            continue
        code = failed[0].failure_code
        hits.append(
            _hit(
                category="retrieval" if code.startswith("retrieval.") else "agent",
                severity=_severity_from_failure(rate),
                pattern_key=pattern,
                observed=f"{code} rate {rate:.0%}",
                alternative="",
                baseline=code,
                candidate="",
                sample=failed,
                window=window,
                evidence=[f"failure_rate={rate:.4f}", f"code={code}"],
                baseline_rate=round(rate, 4),
            )
        )
    return hits
