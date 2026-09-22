# =============================================================================
# Failure / success memory. Un grupo, un MemoryRecord.
# =============================================================================
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass

from src.core.domain.learning_cycle import RunSignal
from src.core.domain.memory import MemoryRecord, MemoryType
from src.memory.service import MemoryFoundationService, MemoryObservation
from src.memory.signature import PatternFeatures
from src.memory.taxonomy import SuccessSignal


@dataclass(kw_only=True)
class ClusterWrite:
    kind: str
    pattern_key: str
    strategy: str
    record: MemoryRecord


def _bucket_key(signal: RunSignal, *, failure: bool) -> tuple[str, ...]:
    return (
        signal.organization_id.hex,
        signal.pattern_key,
        signal.source_type or "unknown_source",
        signal.retrieval_strategy or "unknown_retrieval",
        signal.tool_family or "none",
        signal.failure_code if failure else "none",
    )


def _idempotency(signals: list[RunSignal]) -> str:
    raw = ",".join(sorted(str(signal.id) for signal in signals))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _alternative(signals: list[RunSignal], pattern_key: str, weak: str) -> str:
    grouped: dict[str, list[bool]] = defaultdict(list)
    for signal in signals:
        if signal.pattern_key != pattern_key or not signal.retrieval_strategy:
            continue
        if signal.retrieval_strategy == weak:
            continue
        grouped[signal.retrieval_strategy].append(bool(signal.success))
    best = ""
    best_rate = -1.0
    for strategy, flags in grouped.items():
        if not flags:
            continue
        rate = sum(1 for flag in flags if flag) / len(flags)
        if rate > best_rate:
            best_rate = rate
            best = strategy
    return best


async def sync_clusters(
    service: MemoryFoundationService,
    signals: list[RunSignal],
    *,
    context: list[RunSignal] | None = None,
) -> list[ClusterWrite]:
    """Persiste grupos nuevos. `context` aporta la alternativa conocida."""
    universe = context if context is not None else signals
    written: list[ClusterWrite] = []
    failures: dict[tuple[str, ...], list[RunSignal]] = defaultdict(list)
    scorecards: dict[tuple[str, ...], list[RunSignal]] = defaultdict(list)
    for signal in signals:
        if signal.failure_code:
            failures[_bucket_key(signal, failure=True)].append(signal)
        if signal.retrieval_strategy or signal.route_label:
            scorecards[_bucket_key(signal, failure=False)].append(signal)
    for group in failures.values():
        record = await _write_failure(service, group, universe)
        if record is not None:
            written.append(record)
    for group in scorecards.values():
        if not any(signal.success for signal in group):
            continue
        record = await _write_success(service, group)
        if record is not None:
            written.append(record)
    return written


async def _write_failure(
    service: MemoryFoundationService,
    group: list[RunSignal],
    universe: list[RunSignal],
) -> ClusterWrite | None:
    sample = group[0]
    alternative = _alternative(universe, sample.pattern_key, sample.retrieval_strategy)
    sources = []
    for signal in group:
        if signal.source_name and signal.source_name not in sources:
            sources.append(signal.source_name)
    observation = MemoryObservation(
        organization_id=sample.organization_id,
        memory_type=MemoryType.LEARNING,
        title=sample.pattern_key.replace("_", " "),
        description=(
            f"Pattern {sample.pattern_key}. Failure {sample.failure_code}. "
            f"Known alternative {alternative or 'none'}."
        ),
        features=PatternFeatures(
            intent_family=sample.pattern_key,
            source_type=sample.source_type or "unknown_source",
            retrieval_modality=sample.retrieval_strategy or "unknown_retrieval",
            tool_family=sample.tool_family or "none",
            failure_category=sample.failure_code,
        ),
        source_component="learning.engine",
        phase="cluster",
        outcome=sample.failure_code,
        confidence=0.7,
        success=False,
        idempotency_key=_idempotency(group),
        metadata={
            "pattern": sample.pattern_key,
            "failure": sample.failure_code,
            "observed_outcome": "low retrieval precision",
            "known_alternative": alternative,
            "affected_sources": sources[:20],
            "latency_total_ms": sum(item.latency_ms for item in group),
            "cost_total": sum(item.cost for item in group),
        },
    )
    record = await service.record_cluster(
        observation, support_delta=len(group), success_delta=0
    )
    if record is None:
        return None
    return ClusterWrite(
        kind="failure",
        pattern_key=sample.pattern_key,
        strategy=sample.retrieval_strategy,
        record=record,
    )


async def _write_success(service: MemoryFoundationService, group: list[RunSignal]) -> ClusterWrite | None:
    sample = group[0]
    successful = sum(1 for item in group if item.success)
    signal = SuccessSignal.RETRIEVAL_EXACT.value
    if sample.agent_completed:
        signal = SuccessSignal.AGENT_COMPLETED.value
    elif sample.tool_succeeded:
        signal = SuccessSignal.TOOL_SUCCESS.value
    observation = MemoryObservation(
        organization_id=sample.organization_id,
        memory_type=MemoryType.OPERATIONAL,
        title=sample.pattern_key.replace("_", " "),
        description=(
            f"Pattern {sample.pattern_key}. Strategy {sample.retrieval_strategy or sample.route_label}."
        ),
        features=PatternFeatures(
            intent_family=sample.pattern_key,
            source_type=sample.source_type or "unknown_source",
            retrieval_modality=sample.retrieval_strategy or sample.route_label or "unknown_retrieval",
            tool_family=sample.tool_family or "none",
            failure_category="none",
        ),
        source_component="learning.engine",
        phase="cluster",
        outcome=signal,
        confidence=successful / len(group),
        success=True,
        idempotency_key=_idempotency(group),
        metadata={
            "pattern": sample.pattern_key,
            "strategy": sample.retrieval_strategy or sample.route_label,
            "success_signal": signal,
            "latency_total_ms": sum(item.latency_ms for item in group),
            "cost_total": sum(item.cost for item in group),
            "affected_sources": [sample.source_name] if sample.source_name else [],
        },
    )
    record = await service.record_cluster(
        observation, support_delta=len(group), success_delta=successful
    )
    if record is None:
        return None
    return ClusterWrite(
        kind="success",
        pattern_key=sample.pattern_key,
        strategy=sample.retrieval_strategy or sample.route_label,
        record=record,
    )
