# =============================================================================
# User intent — qué pide realmente el usuario (no cómo debe sonar).
# =============================================================================
# Separado de AgentIdentity (quién habla) y de ResponseProfile (cómo se
# expresa). Las reglas son genéricas y multitemáticas: no conocen "El
# principito" ni ningún dominio concreto.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass

INTENT_INFORMATION = "information"
INTENT_VALUATION = "valuation"
INTENT_INTERPRETATION = "interpretation"
INTENT_RECOMMENDATION = "recommendation"
INTENT_COMPARISON = "comparison"
INTENT_CREATION = "creation"
INTENT_TEACHING = "teaching"
INTENT_EXECUTION = "execution"

USER_INTENTS: tuple[str, ...] = (
    INTENT_INFORMATION,
    INTENT_VALUATION,
    INTENT_INTERPRETATION,
    INTENT_RECOMMENDATION,
    INTENT_COMPARISON,
    INTENT_CREATION,
    INTENT_TEACHING,
    INTENT_EXECUTION,
)

EVALUATIVE_INTENTS: frozenset[str] = frozenset(
    {INTENT_VALUATION, INTENT_INTERPRETATION, INTENT_RECOMMENDATION}
)

_VALUATION_RE = re.compile(
    r"(?:\bqu[eé]\s+te\s+parece\b|\bqu[eé]\s+te\s+pareci[oó]\b|"
    r"\bqu[eé]\s+opinas\b|\bqu[eé]\s+opin[aá]s\b|\btu\s+opini[oó]n\b|"
    r"\bc[oó]mo\s+lo\s+valor[aá]s\b|\bc[oó]mo\s+valor[aá]s\b|"
    r"\bqu[eé]\s+valor\s+tiene\b|\bte\s+parece\s+(?:bueno|malo|justo|correcto)\b|"
    r"\bqu[eé]\s+te\s+sugiere\b|\bqu[eé]\s+te\s+dice\b|"
    r"\bwhat\s+do\s+you\s+think\b|\byour\s+opinion\b|"
    r"\bhow\s+would\s+you\s+rate\b|\bdo\s+you\s+like\b|\bis\s+it\s+good\b)",
    re.IGNORECASE,
)
_INTERPRETATION_RE = re.compile(
    r"(?:\binterpretaci[oó]n\b|\binterpret[aá]\b|\binterpret[aá]s\b|"
    r"\bqu[eé]\s+significa\s+para\s+vos\b|\bc[oó]mo\s+lo\s+le[eé]s\b|"
    r"\bc[oó]mo\s+lo\s+interpret[aá]s\b|\bsimbolog[ií]a\b|"
    r"\byour\s+interpretation\b|\bwhat\s+does\s+it\s+mean\s+to\s+you\b|"
    r"\bsymbolism\b|\bread(?:ing)?\s+of\b)",
    re.IGNORECASE,
)
_RECOMMENDATION_RE = re.compile(
    r"(?:\brecomendar[ií]as\b|\brecomend[aá]s\b|\brecomiendas\b|"
    r"\bqu[eé]\s+me\s+recomend[aá]s\b|\bqu[eé]\s+recomend[aá]s\b|"
    r"\bconviene\s+(?:usar|elegir|comprar|migrar|esperar)\b|"
    r"\bcu[aá]l\s+conviene\b|"
    r"\bwould\s+you\s+recommend\b|\bshould\s+i\b|\bwhich\s+should\s+i\s+choose\b)",
    re.IGNORECASE,
)
_COMPARISON_RE = re.compile(
    r"(?:\bvs\.?\b|\bversus\b|\bdiferencia(?:\s+hay)?\s+entre\b|\bcompar[aá]\b|"
    r"\bcomparaci[oó]n\b|\bcu[aá]l\s+conviene\b|\bwhich\s+is\s+better\b|"
    r"\bdifference\s+between\b)",
    re.IGNORECASE,
)
_CREATION_RE = re.compile(
    r"(?:\b(?:escr[ií]b\w*|escrib\w*|redact\w*|invent\w*|cre\w*)\b.{0,40}"
    r"\b(?:cuento|poema|historia|relato|canci[oó]n|f[aá]bula|texto)\b|"
    r"\b(?:write|compose|create)\b.{0,40}\b(?:story|poem|tale|song)\b)",
    re.IGNORECASE | re.DOTALL,
)
_TEACHING_RE = re.compile(
    r"(?:\bexpl[ií]came\b|\bense[nñ]ame\b|\bdesde\s+cero\b|\bpaso\s+a\s+paso\b|"
    r"\btutorial\b|\bcomo\s+si\s+(?:no\s+supiera|fuera\s+nuevo)\b|"
    r"\bexplain\s+like\b|\bteach\s+me\b)",
    re.IGNORECASE,
)
_EXECUTION_RE = re.compile(
    r"(?:\bejecuta\b|\bejecut[aá]\b|\bcrea\s+(?:un\s+)?(?:workflow|flujo|tarea)\b|"
    r"\benv[ií]a\b|\bactualiza\b|\belimina\b|\bprograma\b|\bagenda\b|"
    r"\brun\b|\bexecute\b|\bdeploy\b|\bcall\s+the\s+api\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class UserIntent:
    """Intención funcional del turno, separada de la forma de responder."""

    kind: str = INTENT_INFORMATION
    confidence: float = 0.0
    signals: tuple[str, ...] = ()
    evaluative: bool = False

    def to_public_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "confidence": round(float(self.confidence), 4),
            "evaluative": bool(self.evaluative),
            "signals": list(self.signals),
        }


def detect_user_intent(question: str) -> UserIntent:
    """Clasificación genérica y determinista de la petición.

    No decide la respuesta ni el nivel de evidencia. Sólo separa información,
    valoración, interpretación, recomendación, comparación, creación,
    enseñanza y ejecución.
    """
    text = str(question or "").strip()
    if not text:
        return UserIntent()
    checks: tuple[tuple[str, re.Pattern[str], float], ...] = (
        (INTENT_INTERPRETATION, _INTERPRETATION_RE, 0.9),
        (INTENT_RECOMMENDATION, _RECOMMENDATION_RE, 0.88),
        (INTENT_VALUATION, _VALUATION_RE, 0.9),
        (INTENT_COMPARISON, _COMPARISON_RE, 0.86),
        (INTENT_CREATION, _CREATION_RE, 0.84),
        (INTENT_TEACHING, _TEACHING_RE, 0.82),
        (INTENT_EXECUTION, _EXECUTION_RE, 0.82),
    )
    for kind, pattern, confidence in checks:
        if pattern.search(text):
            return UserIntent(
                kind=kind,
                confidence=confidence,
                signals=(kind,),
                evaluative=kind in EVALUATIVE_INTENTS,
            )
    return UserIntent(kind=INTENT_INFORMATION, confidence=0.6, signals=("default_information",))


def is_evaluative_question(question: str) -> bool:
    return detect_user_intent(question).evaluative


__all__ = [
    "EVALUATIVE_INTENTS",
    "INTENT_COMPARISON",
    "INTENT_CREATION",
    "INTENT_EXECUTION",
    "INTENT_INFORMATION",
    "INTENT_INTERPRETATION",
    "INTENT_RECOMMENDATION",
    "INTENT_TEACHING",
    "INTENT_VALUATION",
    "USER_INTENTS",
    "UserIntent",
    "detect_user_intent",
    "is_evaluative_question",
]
