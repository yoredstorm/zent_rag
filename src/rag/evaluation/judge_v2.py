# =============================================================================
# LLM Judge V2 — Enterprise Evaluation (opcional, Phase H)
# =============================================================================
# El evaluador determinista sigue siendo la base. El judge LLM es una SEÑAL
# ADICIONAL: juzga claims (grounded/partially/unsupported/conflicted) contra
# los excerpts del contexto. Validación estricta: los verdicts se limitan al
# enum; cualquier fallo/JSON inválido → None (el caller cae al veredicto
# determinista). Nunca es la única fuente de verdad.
# =============================================================================
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Awaitable, Callable

from src.rag.grounding.models import ClaimStatus

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)
_ALLOWED = {status.value for status in ClaimStatus}


JudgeFn = Callable[[str, str, tuple[str, ...]], Awaitable[tuple[dict, ...] | None]]
"""async (question, answer, context_excerpts) -> veredictos o None."""


@dataclass(frozen=True, kw_only=True)
class JudgeVerdict:
    claim: str
    verdict: ClaimStatus
    justification: str = ""

    def to_dict(self) -> dict:
        return {
            "claim": self.claim,
            "verdict": self.verdict.value,
            "justification": self.justification[:200],
        }


def make_llm_judge(llm) -> JudgeFn:
    """Construye la función judge a partir de un LLMProvider (fallback None)."""

    async def judge(
        question: str,
        answer: str,
        context_excerpts: tuple[str, ...],
    ) -> tuple[dict, ...] | None:
        try:
            # Extrae claims del propio answer (heurística) para juzgarlos
            claims = _split_claims(answer)
            if not claims:
                return None
            prompt = _format_prompt(question, answer, claims, context_excerpts)
            response = await llm.generate(
                prompt,
                max_tokens=512,
                temperature=0.0,
                system_prompt=(
                    "Eres un juez de groundedness. Solo decides con la evidencia "
                    "entregada; si un claim no está soportado, es unsupported. "
                    "JSON estricto."
                ),
            )
            match = _JSON_BLOCK_RE.search(response.content or "")
            if not match:
                return None
            payload = json.loads(match.group(0))
            verdicts = payload.get("claims") or []
            result: list[dict] = []
            for item in verdicts[:20]:
                text = str(item.get("text") or "").strip()
                verdict_raw = str(item.get("verdict") or "").lower()
                normalized = verdict_raw.upper()  # enum ClaimStatus es UPPERCASE
                if not text or normalized not in _ALLOWED:
                    continue
                result.append(
                    {
                        "claim": text,
                        "verdict": normalized,
                        "justification": str(item.get("justification") or ""),
                    }
                )
            return tuple(result)
        except Exception:  # noqa: BLE001 - el judge nunca rompe la eval
            return None

    return judge


def judge_groundedness(verdicts: tuple[dict, ...] | None) -> float | None:
    """Fracción de claims que el judge marcó soportados (None si no hay judge)."""
    if not verdicts:
        return None
    supported = {
        ClaimStatus.SUPPORTED,
        ClaimStatus.PARTIALLY_SUPPORTED,
    }
    hits = sum(
        1 for v in verdicts if v.get("verdict") in {s.value for s in supported}
    )
    return hits / len(verdicts)


def _split_claims(answer: str, limit: int = 10) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", answer.strip())
    claims: list[str] = []
    for sentence in sentences:
        clean = sentence.strip().strip("[],;")
        if len(clean) < 8:
            continue
        claims.append(clean)
        if len(claims) >= limit:
            break
    return claims


def _format_prompt(
    question: str,
    answer: str,
    claims: list[str],
    context_excerpts: tuple[str, ...],
) -> str:
    context = "\n".join(f"- {excerpt[:400]}" for excerpt in context_excerpts[:12])
    claims_text = "\n".join(f"{i + 1}. {claim}" for i, claim in enumerate(claims))
    return (
        "Consulta: "
        + question
        + "\n\nContexto (evidencia):\n"
        + (context or "(sin contexto)")
        + "\n\nClaims a juzgar:\n"
        + claims_text
        + "\n\nResponde SOLO JSON: {\"claims\": [{\"text\": <claim exacto>, "
        '"verdict": "supported|partially_supported|unsupported|conflicted", '
        '"justification": str}]}. "supported" solo si el contexto lo soporta '
        "directamente; de lo contrario unsupported."
    )
