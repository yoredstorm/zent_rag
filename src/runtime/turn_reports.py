# =============================================================================
# Reportes del turno — budget por profundidad y loop controlado (C4).
# =============================================================================
# Determinista y sin I/O: mide lo que el run ya hizo. C4 reporta; el
# enforcement duro (bloquear/reencaminar) es C5.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass

_PROFILE_LLM_CALLS = {"L0": 0, "L1": 1, "L2": 1, "L3": 4, "L4": 8, "L5": 12}
_PROFILE_TOKENS = {
    "L0": 0,
    "L1": 1_500,
    "L2": 4_000,
    "L3": 12_000,
    "L4": 16_000,
    "L5": 24_000,
}
_PROFILE_SECONDS = {"L0": 5.0, "L1": 20.0, "L2": 45.0, "L3": 90.0, "L4": 120.0, "L5": 180.0}


@dataclass(frozen=True)
class BudgetReport:
    complexity: str
    max_llm_calls: int
    max_tokens: int
    max_seconds: float
    llm_calls: int
    tokens: int
    elapsed_ms: float
    within_budget: bool

    def to_public_dict(self) -> dict:
        return {
            "complexity": self.complexity,
            "max_llm_calls": self.max_llm_calls,
            "max_tokens": self.max_tokens,
            "max_seconds": self.max_seconds,
            "llm_calls": self.llm_calls,
            "tokens": self.tokens,
            "elapsed_ms": round(float(self.elapsed_ms), 1),
            "within_budget": self.within_budget,
        }


def build_budget_report(
    *,
    complexity: str | None,
    llm_calls: int,
    tokens: int,
    elapsed_ms: float,
) -> BudgetReport:
    """Perfil por profundidad; complejidad desconocida cae a L1 (least sufficient)."""
    level = str(complexity or "L1").upper()
    if level not in _PROFILE_TOKENS:
        level = "L1"
    max_calls = _PROFILE_LLM_CALLS[level]
    max_tokens = _PROFILE_TOKENS[level]
    max_seconds = _PROFILE_SECONDS[level]
    calls = max(0, int(llm_calls))
    used = max(0, int(tokens))
    elapsed = max(0.0, float(elapsed_ms))
    return BudgetReport(
        complexity=level,
        max_llm_calls=max_calls,
        max_tokens=max_tokens,
        max_seconds=max_seconds,
        llm_calls=calls,
        tokens=used,
        elapsed_ms=elapsed,
        within_budget=(
            calls <= max_calls and used <= max_tokens and elapsed <= max_seconds * 1000
        ),
    )


def _attempt_field(attempt: object, name: str, default=None):
    if isinstance(attempt, dict):
        return attempt.get(name, default)
    return getattr(attempt, name, default)


@dataclass(frozen=True)
class LoopRound:
    attempt: int
    strategy: str
    sufficient: bool | None
    quality_score: float | None
    reason: str

    def to_public_dict(self) -> dict:
        payload = {
            "attempt": self.attempt,
            "strategy": self.strategy,
            "sufficient": self.sufficient,
            "reason": self.reason,
        }
        if self.quality_score is not None:
            payload["quality_score"] = round(float(self.quality_score), 4)
        return payload


@dataclass(frozen=True)
class LoopReport:
    rounds: tuple[LoopRound, ...] = ()
    extra_round: bool = False
    max_rounds: int = 3
    exhausted: bool = False

    def to_public_dict(self) -> dict:
        return {
            "rounds": [round_.to_public_dict() for round_ in self.rounds],
            "count": len(self.rounds),
            "extra_round": self.extra_round,
            "max_rounds": self.max_rounds,
            "exhausted": self.exhausted,
        }


def build_loop_report(adaptive: dict, *, max_rounds: int = 3) -> LoopReport:
    """Rondas reales del run, con su razón medida (nunca inferida)."""
    rounds: list[LoopRound] = []
    for raw in list((adaptive or {}).get("attempts") or []):
        if raw is None:
            continue
        sufficient = _attempt_field(raw, "sufficient")
        quality = _attempt_field(raw, "quality_score")
        if sufficient is False:
            reason = "insuficiente"
        elif sufficient is True:
            reason = "suficiente"
        else:
            reason = "sin_medicion"
        attempt_value = _attempt_field(raw, "attempt", None)
        try:
            attempt = (
                int(attempt_value)
                if attempt_value is not None
                else len(rounds) + 1
            )
        except (TypeError, ValueError):
            attempt = len(rounds) + 1
        rounds.append(
            LoopRound(
                attempt=attempt,
                strategy=str(_attempt_field(raw, "strategy") or ""),
                sufficient=bool(sufficient) if sufficient is not None else None,
                quality_score=(
                    float(quality) if quality is not None else None
                ),
                reason=reason,
            )
        )
    extra = bool((adaptive or {}).get("preflight_extra_round"))
    cap = max(1, int(max_rounds))
    return LoopReport(
        rounds=tuple(rounds),
        extra_round=extra,
        max_rounds=cap,
        exhausted=len(rounds) >= cap,
    )
