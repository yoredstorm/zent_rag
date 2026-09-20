# =============================================================================
# Answer gate — JEV verifica el borrador del agente contra la evidencia.
# =============================================================================
# JEV no redacta ni ejecuta: puntua (respaldada, completa, calidad) y el
# runtime decide aprobar, pedir UNA revision o abstenerse. Fallback silencioso.
# =============================================================================
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from src.decision.questions import noul_certainty, noul_is_yes
from src.runtime.jev_state import StateSection, build_jev_state
from src.runtime.questions import answer_gate_questions

ANSWER_WEIGHTS = {"grounded": 0.45, "complete": 0.35, "quality": 0.20}

INSUFFICIENT_ANSWER = (
    "No hay evidencia suficiente en las fuentes consultadas para responder "
    "con confianza. Probá reformular la pregunta o cargar más información."
)


def answer_gate_mode(settings, config: dict | None = None) -> str:
    """off | shadow | on. `config.runtime.answer_gate` manda si esta definido."""
    runtime = (config or {}).get("runtime") if isinstance(config, dict) else None
    if isinstance(runtime, dict):
        override = runtime.get("answer_gate")
        if isinstance(override, bool):
            return "on" if override else "off"
    mode = str(getattr(settings, "RUNTIME_ANSWER_GATE", "off") or "off").lower()
    return mode if mode in {"off", "shadow", "on"} else "off"


@dataclass
class AnswerGateResult:
    verdict: str = "skipped"  # approve | revise | abstain | skipped
    score: float = 0.0
    grounded: bool = False
    complete: bool = False
    quality: float = 0.0  # 0-3
    feedback: str = ""
    provider: str = "skip"
    mode: str = "off"
    state_chars: int = 0
    latency_ms: float = 0.0
    answers: dict[str, Any] = field(default_factory=dict)

    def to_step(self) -> dict[str, Any]:
        return {
            "type": "answer_gate",
            "verdict": self.verdict,
            "score": round(self.score, 4),
            "grounded": self.grounded,
            "complete": self.complete,
            "quality": round(self.quality, 2),
            "provider": self.provider,
            "mode": self.mode,
            "state_chars": self.state_chars,
            "latency_ms": round(self.latency_ms, 2),
            "detail": self.feedback[:300],
        }


def _noul(answers: dict, key: str) -> float:
    raw = answers.get(key)
    if not isinstance(raw, dict):
        return 0.0
    try:
        return float(raw.get("noul") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _quality(answers: dict, max_level: int = 3) -> float:
    raw = answers.get("answer_quality")
    if not isinstance(raw, dict):
        return 0.0
    try:
        score = float(raw.get("score") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return min(float(max_level), max(0.0, score))


def _feedback(*, grounded: bool, complete: bool, quality: float, reason: str = "") -> str:
    parts: list[str] = []
    if not grounded:
        parts.append("las afirmaciones no estan respaldadas por la evidencia")
    if not complete:
        parts.append("la respuesta no cubre todo lo pedido")
    if quality <= 1.0:
        parts.append("subi la precision y cita las fuentes")
    if reason:
        parts.append(reason)
    if not parts:
        return ""
    return "Verificador JEV: " + "; ".join(parts) + "."


async def judge_answer(
    *,
    engine,
    mode: str,
    user_request: str,
    draft: str,
    observations: list[str],
    agent_instructions: str = "",
    settings,
    max_state_chars: int = 30000,
    noul_yes: float = 0.65,
    approve_at: float = 0.66,
    revise_at: float = 0.40,
) -> AnswerGateResult:
    """Evalua el borrador. Nunca lanza: ante error devuelve skipped."""
    result = AnswerGateResult(mode=mode, provider="skip")
    if mode == "off" or engine is None:
        return result
    evidence = "\n".join(line[:1500] for line in (observations or [])[-8:])
    built = build_jev_state(
        [
            StateSection("draft_answer", 1, (draft or "")[:6000]),
            StateSection("evidence", 2, evidence),
            StateSection("user_request", 3, (user_request or "")[:4000]),
            StateSection("agent_instructions", 4, agent_instructions),
        ],
        max_chars=max_state_chars,
    )
    try:
        started = time.perf_counter()
        payload = await engine.judge(state=built.state, questions=answer_gate_questions())
        result.latency_ms = (time.perf_counter() - started) * 1000
    except Exception:  # noqa: BLE001 — el gate nunca rompe el run
        return result
    if not isinstance(payload, dict):
        return result
    answers = payload.get("answers") if isinstance(payload.get("answers"), dict) else {}
    if not answers:
        return result

    grounded_noul = _noul(answers, "answer_grounded")
    complete_noul = _noul(answers, "answer_complete")
    grounded = noul_is_yes(grounded_noul, noul_yes)
    complete = noul_is_yes(complete_noul, noul_yes)
    quality = _quality(answers)
    score = (
        ANSWER_WEIGHTS["grounded"] * (1.0 if grounded else 0.0)
        + ANSWER_WEIGHTS["complete"] * (1.0 if complete else 0.0)
        + ANSWER_WEIGHTS["quality"] * (quality / 3.0)
    )
    # La certeza de los Noul ajusta el score: respuestas tibias valen menos.
    certainty = min(
        noul_certainty(grounded_noul),
        noul_certainty(complete_noul),
    )
    score = round(min(1.0, score * (0.7 + 0.3 * certainty)), 4)
    if score >= approve_at:
        verdict = "approve"
    elif score >= revise_at:
        verdict = "revise"
    else:
        verdict = "abstain"
    return AnswerGateResult(
        verdict=verdict,
        score=score,
        grounded=grounded,
        complete=complete,
        quality=quality,
        feedback=_feedback(grounded=grounded, complete=complete, quality=quality),
        provider=str(payload.get("model") or "jev"),
        mode=mode,
        state_chars=built.chars,
        latency_ms=result.latency_ms,
        answers=answers,
    )
