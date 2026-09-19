# =============================================================================
# Workflow AI Decision — business labels; JEV Choice/Noul/Score stay internal.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.decision.questions import noul_certainty, noul_is_yes
from src.runtime.questions import (
    workflow_route_questions,
    workflow_score_questions,
    workflow_yes_no_questions,
)

KIND_ROUTE = "route"
KIND_YES_NO = "yes_no"
KIND_SCORE = "score"
KINDS = frozenset({KIND_ROUTE, KIND_YES_NO, KIND_SCORE})

LOW_FALLBACK = "fallback"
LOW_HUMAN = "human_review"
LOW_STOP = "stop"
LOW_LLM = "llm"
LOW_ACTIONS = frozenset({LOW_FALLBACK, LOW_HUMAN, LOW_STOP, LOW_LLM})

_DEFAULT_OPTIONS = (
    ("approve", "Aprobar"),
    ("reject", "Rechazar"),
    ("review", "Revisar"),
)


@dataclass(frozen=True)
class AiDecisionConfig:
    kind: str
    question: str
    options: tuple[tuple[str, str], ...]
    confidence_min: float
    on_low_confidence: str
    score_threshold: float


@dataclass(frozen=True)
class AiDecisionOutcome:
    result: bool
    choice: str
    route: str
    score: float | None
    confidence: float
    provider: str
    low_confidence: bool
    on_low_confidence: str
    question: str
    alternatives: tuple[str, ...] = ()


def parse_config(cfg: dict[str, Any] | None) -> AiDecisionConfig:
    raw = cfg or {}
    kind = str(raw.get("decision_kind") or raw.get("kind") or KIND_ROUTE).strip().lower()
    if kind in {"elegir_ruta", "choice", "select"}:
        kind = KIND_ROUTE
    elif kind in {"yes_no", "boolean", "noul", "si_no"}:
        kind = KIND_YES_NO
    elif kind in {"score", "scoring"}:
        kind = KIND_SCORE
    if kind not in KINDS:
        kind = KIND_ROUTE
    question = str(raw.get("question") or raw.get("prompt") or "").strip()[:500]
    options = _parse_options(raw.get("options"))
    try:
        confidence_min = float(raw.get("confidence_min") or 0.65)
    except (TypeError, ValueError):
        confidence_min = 0.65
    confidence_min = min(1.0, max(0.0, confidence_min))
    on_low = str(raw.get("on_low_confidence") or LOW_FALLBACK).strip().lower()
    if on_low not in LOW_ACTIONS:
        on_low = LOW_FALLBACK
    try:
        score_threshold = float(raw.get("score_threshold") or 0.5)
    except (TypeError, ValueError):
        score_threshold = 0.5
    return AiDecisionConfig(
        kind=kind,
        question=question or "Determinar la siguiente acción.",
        options=options,
        confidence_min=confidence_min,
        on_low_confidence=on_low,
        score_threshold=min(1.0, max(0.0, score_threshold)),
    )


def _parse_options(raw: Any) -> tuple[tuple[str, str], ...]:
    if isinstance(raw, str) and raw.strip():
        items = [part.strip() for part in raw.replace("\n", ",").split(",") if part.strip()]
        raw = items
    if not isinstance(raw, list) or not raw:
        return _DEFAULT_OPTIONS
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in raw[:8]:
        if isinstance(item, dict):
            key = str(item.get("id") or item.get("value") or item.get("label") or "").strip()
            label = str(item.get("label") or key).strip()
        else:
            key = str(item).strip()
            label = key
        slug = _slug(key)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        out.append((slug, label[:80] or slug))
    return tuple(out) or _DEFAULT_OPTIONS


def _slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in (value or ""))
    return cleaned.strip("_")[:40]


def questions_for(config: AiDecisionConfig) -> dict[str, dict]:
    if config.kind == KIND_YES_NO:
        return workflow_yes_no_questions(config.question)
    if config.kind == KIND_SCORE:
        levels = [label for _, label in config.options] if len(config.options) >= 2 else []
        return workflow_score_questions(config.question, levels)
    criteria = {key: label for key, label in config.options}
    return workflow_route_questions(criteria)


def interpret(
    config: AiDecisionConfig,
    payload: dict[str, Any] | None,
    *,
    noul_yes: float = 0.65,
) -> AiDecisionOutcome:
    answers = (payload or {}).get("answers") if isinstance(payload, dict) else None
    if not isinstance(answers, dict):
        answers = {}
    first = config.options[0][0] if config.options else "approve"
    provider = "jev" if answers else "fallback"
    if config.kind == KIND_YES_NO:
        noul = float((answers.get("yes") or {}).get("noul") or 0.0)
        yes = noul_is_yes(noul, noul_yes)
        confidence = noul_certainty(noul) if answers else 0.0
        route = "then" if yes else "else"
        return AiDecisionOutcome(
            result=yes,
            choice="yes" if yes else "no",
            route=route,
            score=noul if answers else None,
            confidence=confidence,
            provider=provider,
            low_confidence=bool(answers) and confidence < config.confidence_min,
            on_low_confidence=config.on_low_confidence,
            question=config.question,
        )
    if config.kind == KIND_SCORE:
        raw_score = (answers.get("score") or {}).get("score")
        try:
            score = float(raw_score) if raw_score is not None else 0.0
        except (TypeError, ValueError):
            score = 0.0
        # TypeSafe Score is typically 0-3 for 4 criteria; normalize to 0-1.
        max_score = max(len(config.options) - 1, 1)
        normalized = score / max_score if score > 1.0 else score
        confidence = float((answers.get("score") or {}).get("confidence") or 0.0)
        passed = normalized >= config.score_threshold
        return AiDecisionOutcome(
            result=passed,
            choice="pass" if passed else "fail",
            route="then" if passed else "else",
            score=round(normalized, 4),
            confidence=confidence,
            provider=provider,
            low_confidence=bool(answers) and confidence < config.confidence_min,
            on_low_confidence=config.on_low_confidence,
            question=config.question,
        )
    route_ans = answers.get("route") or {}
    choice = str(route_ans.get("choice") or first)
    allowed = {key for key, _ in config.options}
    if choice not in allowed:
        choice = first
    confidence = float(route_ans.get("confidence") or 0.0)
    noul_ok = answers.get("confidence_ok") or {}
    if "noul" in noul_ok:
        confidence = max(confidence, noul_certainty(float(noul_ok.get("noul") or 0.0)))
    probs = route_ans.get("probabilities") or {}
    alternatives = tuple(
        k
        for k, _ in sorted(
            ((str(k), float(v)) for k, v in probs.items() if str(k) != choice),
            key=lambda item: item[1],
            reverse=True,
        )[:3]
    )
    return AiDecisionOutcome(
        result=choice == first,
        choice=choice,
        route=choice,
        score=None,
        confidence=confidence,
        provider=provider,
        low_confidence=bool(answers) and confidence < config.confidence_min,
        on_low_confidence=config.on_low_confidence,
        question=config.question,
        alternatives=alternatives,
    )


def apply_low_confidence(outcome: AiDecisionOutcome, config: AiDecisionConfig) -> AiDecisionOutcome:
    if not outcome.low_confidence:
        return outcome
    action = config.on_low_confidence
    first = config.options[0][0] if config.options else "approve"
    if action == LOW_FALLBACK:
        if config.kind == KIND_ROUTE:
            return AiDecisionOutcome(
                result=True,
                choice=first,
                route=first,
                score=outcome.score,
                confidence=outcome.confidence,
                provider=outcome.provider,
                low_confidence=True,
                on_low_confidence=action,
                question=config.question,
                alternatives=outcome.alternatives,
            )
        return AiDecisionOutcome(
            result=False,
            choice="no" if config.kind == KIND_YES_NO else "fail",
            route="else",
            score=outcome.score,
            confidence=outcome.confidence,
            provider=outcome.provider,
            low_confidence=True,
            on_low_confidence=action,
            question=config.question,
        )
    return outcome


def to_output(outcome: AiDecisionOutcome) -> dict[str, Any]:
    return {
        "result": outcome.result,
        "choice": outcome.choice,
        "route": outcome.route,
        "score": outcome.score,
        "confidence": round(outcome.confidence, 4),
        "provider": outcome.provider,
        "low_confidence": outcome.low_confidence,
        "on_low_confidence": outcome.on_low_confidence,
        "question": outcome.question,
        "alternatives": list(outcome.alternatives),
    }
