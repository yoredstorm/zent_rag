# =============================================================================
# Answer gate — JEV verifica el borrador del agente contra la evidencia.
# =============================================================================
# JEV no redacta ni ejecuta: juzga respaldo, completitud y presentación, y el
# código compone la acción de forma determinista.
#
# Separación de preguntas (no un único score que mezcla todo):
#
#   CONTENT / GROUNDING  ¿la respuesta está respaldada por las fuentes?
#   PRESENTATION         ¿está bien explicada?
#
# Una respuesta imperfecta se REVISA; una respuesta sin evidencia se ABSTIENE.
# «La respuesta podría mejorar» NUNCA se convierte en «no existe evidencia».
#
# Política (mismo orden que el preflight del RAG):
#
#   sin evidencia            -> retrieve_more (si queda presupuesto) | abstain
#   evidencia irrelevante    -> retrieve_more (si queda) | abstain
#   evidencia relevante y
#   borrador sin respaldo    -> retrieve_more (si el gate pide más) | revise
#   respaldo ok y falta
#   completitud/presentación -> revise
#   respaldo parcial         -> answer_with_limits
#   todo ok                  -> approve
#
# La evidencia que recibe el gate es la MISMA (`evidence_id`) que vio el
# generador: no hay segunda versión recortada de la evidencia.
# =============================================================================
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from src.core.domain.adaptive import EvidenceItem
from src.decision.judgment import PHASE_ANSWER_GATE, JudgmentContext, call_judge
from src.decision.questions import noul_certainty, noul_from_answer, noul_is_yes
from src.runtime.evidence import (
    ACTION_ABSTAIN,
    ACTION_ANSWER_WITH_LIMITS,
    ACTION_APPROVE,
    ACTION_RETRIEVE_MORE,
    ACTION_REVISE,
    DEFAULT_BUDGET_CHARS,
    EvidenceSelection,
    assess_sufficiency,
    evidence_index_block,
    render_evidence,
    select_evidence,
)
from src.runtime.jev_state import StateSection, build_jev_state
from src.runtime.questions import answer_gate_questions

ANSWER_WEIGHTS = {"grounded": 0.45, "complete": 0.35, "quality": 0.20}

#: Veredicto de contenido (la pregunta del grounding).
GROUNDING_SUPPORTED = "SUPPORTED"
GROUNDING_PARTIAL = "PARTIAL"
GROUNDING_UNSUPPORTED = "UNSUPPORTED"
GROUNDING_UNKNOWN = "unknown"

#: Veredicto de presentación (la pregunta de la forma).
PRESENTATION_OK = "ok"
PRESENTATION_NEEDS_REVISION = "needs_revision"
PRESENTATION_UNKNOWN = "unknown"

INSUFFICIENT_ANSWER = (
    "No hay evidencia suficiente en las fuentes consultadas para responder "
    "con confianza. Probá reformular la pregunta o cargar más información."
)

#: Motivos de revisión que son de CONTENIDO (no de forma).
CONTENT_REVISION_REASONS = frozenset({"missing_evidence", "unsupported_claim"})


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
    verdict: str = "skipped"  # approve | revise | retrieve_more | answer_with_limits | abstain | skipped
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
    #: Veredictos separados (§14) y señales de evidencia observadas.
    grounding_verdict: str = GROUNDING_UNKNOWN
    presentation_verdict: str = PRESENTATION_UNKNOWN
    #: Motivo concreto de la revisión de forma (vacío si no hubo).
    presentation_revision_reason: str = ""
    evidence_ids: tuple[str, ...] = ()
    evidence_chars: int = 0
    evidence_used: bool = False
    missing_entities: tuple[str, ...] = ()
    unsupported_claims: tuple[str, ...] = ()
    claims_summary: dict[str, Any] = field(default_factory=dict)

    @property
    def action(self) -> str:
        return self.verdict

    def to_step(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
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
        if self.grounding_verdict != GROUNDING_UNKNOWN:
            payload["grounding_verdict"] = self.grounding_verdict
        if self.presentation_verdict != PRESENTATION_UNKNOWN:
            payload["presentation_verdict"] = self.presentation_verdict
        if self.presentation_revision_reason:
            payload["presentation_revision_reason"] = self.presentation_revision_reason
        if self.evidence_used:
            payload["evidence_ids"] = list(self.evidence_ids)[:24]
            payload["evidence_chars"] = self.evidence_chars
        if self.missing_entities:
            payload["missing_entities"] = list(self.missing_entities)[:6]
        if self.claims_summary:
            payload["claims"] = dict(self.claims_summary)
        return payload


def _noul(answers: dict, key: str) -> float:
    raw = answers.get(key)
    if not isinstance(raw, dict):
        return 0.0
    return noul_from_answer(raw, 0.0)


def _quality(answers: dict, max_level: int = 3) -> float:
    raw = answers.get("answer_quality")
    if not isinstance(raw, dict):
        return 0.0
    try:
        score = float(raw.get("score") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return min(float(max_level), max(0.0, score))


def _score_value(answers: dict, key: str) -> float | None:
    raw = answers.get(key)
    if not isinstance(raw, dict):
        return None
    try:
        return float(raw.get("score"))
    except (TypeError, ValueError):
        return None


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


#: §25: motivos de revision del gate de presentacion, en lenguaje de instruccion.
REVISION_REASON_FEEDBACK: dict[str, str] = {
    "unclear": "hace falta que se entienda sin contexto previo",
    "too_verbose": "quita lo que no agregue valor",
    "too_short": "la explicacion quedo corta para lo que se pregunto",
    "missing_explanation": "explica el motivo, no solo la conclusion",
    "missing_example": "agrega un ejemplo breve que aclare la regla",
    "missing_evidence": "cita la evidencia que sostiene cada afirmacion",
    "unsupported_claim": "quita lo que la evidencia no sostiene",
    "poor_structure": "ordena la respuesta para que se pueda leer de arriba abajo",
    "does_not_answer_question": "responde la pregunta que se hizo",
    # Legibilidad: qué hace difícil leer una respuesta correcta. Nunca abstención.
    "wall_of_text": "parti el texto en bloques: una idea por párrafo, con la respuesta primero",
    "poor_chunking": "separa las ideas: cada párrafo desarrolla una sola",
    "buried_answer": "pone la respuesta en la primera frase; el detalle va después",
    "irrelevant_detail": "quita el detalle secundario que la pregunta no pide",
    "bad_enumeration_format": "enumerá los valores uno por uno, con viñetas o tabla",
    "unnecessary_limitations": "quita los límites o advertencias que el caso no necesita",
}

#: Motivos de PRESENTACIÓN: una mala forma se revisa, nunca se abstiene (§8, §18).
PRESENTATION_REVISION_REASONS = frozenset(
    reason for reason in REVISION_REASON_FEEDBACK if reason not in CONTENT_REVISION_REASONS
)


def revision_feedback(answers: dict | None) -> str:
    """§25: traduce el motivo de revision elegido por JEV. Nunca inventa."""
    reason = revision_reason(answers)
    return REVISION_REASON_FEEDBACK.get(reason, "")


def revision_reason(answers: dict | None) -> str:
    """Motivo elegido por JEV ('' si no eligió ninguno)."""
    if not isinstance(answers, dict):
        return ""
    value = answers.get("revision_reason")
    if isinstance(value, dict):
        choice = str(value.get("choice") or value.get("decision") or "").strip()
    else:
        choice = str(value or "").strip()
    return choice if choice in REVISION_REASON_FEEDBACK else ""


def presentation_gate_enabled() -> bool:
    """El gate de presentación es una política del sistema, no del request."""
    try:
        from src.core.config import get_settings

        return bool(getattr(get_settings(), "RAG_RESPONSE_PRESENTATION_GATE", True))
    except Exception:  # noqa: BLE001
        return True


#: Preguntas de forma cuya respuesta explícita manda sobre el motivo elegido.
_PRESENTATION_SIGNAL_KEYS = (
    "structure",
    "usefulness",
    "answer_explains_key_reason",
    "answer_is_needlessly_verbose",
    "important_context_missing",
)


def presentation_needs_revision(answers: dict, *, noul_yes: float = 0.65) -> bool:
    """Señales de FORMA. Nunca decide abstención: sólo revisión.

    El motivo elegido (`revision_reason`) sólo pide revisión si JEV no respondió
    explícitamente que TODAS las señales de forma están bien: un motivo suelto no
    puede contradecir cinco respuestas claras.
    """
    if not isinstance(answers, dict):
        return False
    fine = 0
    structure = _score_value(answers, "structure")
    if structure is not None:
        if structure < 2.0:
            return True
        fine += 1
    usefulness = _score_value(answers, "usefulness")
    if usefulness is not None:
        if usefulness < 2.0:
            return True
        fine += 1
    explains = answers.get("answer_explains_key_reason")
    if isinstance(explains, dict):
        if not noul_is_yes(_noul(answers, "answer_explains_key_reason"), noul_yes):
            return True
        fine += 1
    verbose = answers.get("answer_is_needlessly_verbose")
    if isinstance(verbose, dict):
        if noul_is_yes(_noul(answers, "answer_is_needlessly_verbose"), noul_yes):
            return True
        fine += 1
    missing_context = answers.get("important_context_missing")
    if isinstance(missing_context, dict):
        if noul_is_yes(_noul(answers, "important_context_missing"), noul_yes):
            return True
        fine += 1
    reason = revision_reason(answers)
    if reason in CONTENT_REVISION_REASONS:
        return False
    if reason and fine < len(_PRESENTATION_SIGNAL_KEYS):
        return True
    return False


#: Máximo de claims que se le preguntan a JEV en la misma llamada del gate.
MAX_CLAIM_QUESTIONS = 3


def claim_checks(
    draft: str,
    items: Sequence[EvidenceItem],
    *,
    max_claims: int = 6,
) -> dict[str, Any]:
    """Grounding por claim con la evidencia del run (determinista primero).

    Reutiliza el extractor y el juicio determinístico del Adaptive RAG: los
    extremos (overlap fuerte, sin evidencia) se deciden en código y los claims
    de la banda incierta los juzga JEV en la misma llamada del gate. Cada claim
    apunta a su `evidence_id` cuando existe.
    """
    if not draft:
        return {}
    try:
        from src.rag.adaptive.claims import deterministic_judgment
        from src.rag.grounding.service import extract_claims

        claims = extract_claims(draft, max_claims=max(1, int(max_claims)))
        verdicts = [deterministic_judgment(claim, list(items)) for claim in claims]
    except Exception:  # noqa: BLE001 — la verificación por claim nunca rompe el gate
        return {}
    return {
        "claims": [verdict.to_public_dict() for verdict in verdicts],
        "supported": sum(1 for v in verdicts if v.verdict == "supported"),
        "unsupported": sum(1 for v in verdicts if v.verdict == "unsupported"),
        "not_verifiable": sum(1 for v in verdicts if v.verdict == "not_verifiable"),
        "uncertain": [
            v.text
            for v in verdicts
            if v.verdict == "not_verifiable" and v.factual
        ][:MAX_CLAIM_QUESTIONS],
        "unsupported_texts": [
            verdict.text for verdict in verdicts if verdict.verdict == "unsupported"
        ][:4],
    }


def claim_questions(uncertain: Sequence[str]) -> dict[str, dict]:
    """Preguntas atómicas por claim (mismo vocabulario que el POST_GENERATION)."""
    questions: dict[str, dict] = {}
    for index, claim in enumerate(uncertain[:MAX_CLAIM_QUESTIONS]):
        questions[f"claim_{index}_supported"] = {
            "type": "noul",
            "instructions": (
                f"Is this claim supported by `evidence`? Claim: {claim[:300]}"
            ),
        }
        questions[f"claim_{index}_contradicted"] = {
            "type": "noul",
            "instructions": (
                f"Does `evidence` contradict this claim? Claim: {claim[:300]}"
            ),
        }
    return questions


def apply_claim_answers(
    claims: dict[str, Any],
    answers: dict[str, Any],
    *,
    noul_yes: float = 0.65,
    noul_no: float = 0.35,
) -> dict[str, Any]:
    """Compone el veredicto por claim con las respuestas de JEV (código decide)."""
    uncertain = list(claims.get("uncertain") or ())
    if not uncertain or not isinstance(answers, dict):
        return claims
    por_texto = {
        str(claim.get("text")): claim
        for claim in claims.get("claims") or []
        if isinstance(claim, dict)
    }
    for index, text in enumerate(uncertain):
        claim = por_texto.get(text)
        if claim is None:
            continue
        support = _noul(answers, f"claim_{index}_supported")
        contradiction = _noul(answers, f"claim_{index}_contradicted")
        raw_support = answers.get(f"claim_{index}_supported")
        raw_contradiction = answers.get(f"claim_{index}_contradicted")
        if raw_contradiction is not None and noul_is_yes(contradiction, 0.5):
            claim["verdict"] = "contradicted"
            claim["reason"] = "jev_contradicted"
        elif raw_support is not None and noul_is_yes(support, noul_yes):
            claim["verdict"] = "supported"
            claim["reason"] = "jev_supported"
        elif raw_support is not None and support <= noul_no:
            claim["verdict"] = "unsupported"
            claim["reason"] = "jev_unsupported"
        claim["jev_used"] = True
    claims["supported"] = sum(
        1 for c in claims.get("claims") or [] if c.get("verdict") == "supported"
    )
    claims["unsupported"] = sum(
        1 for c in claims.get("claims") or [] if c.get("verdict") == "unsupported"
    )
    claims["not_verifiable"] = sum(
        1 for c in claims.get("claims") or [] if c.get("verdict") == "not_verifiable"
    )
    claims["unsupported_texts"] = [
        str(c.get("text"))
        for c in claims.get("claims") or []
        if c.get("verdict") in {"unsupported", "contradicted"}
    ][:4]
    return claims


def _legacy_verdict(score: float, *, approve_at: float, revise_at: float) -> str:
    if score >= approve_at:
        return ACTION_APPROVE
    if score >= revise_at:
        return ACTION_REVISE
    return ACTION_ABSTAIN


def _evidence_action(
    *,
    grounded: bool,
    complete: bool,
    presentation_revision: bool,
    unsupported_claims: bool,
    relevant: bool,
    partial_entity_coverage: bool,
    uncovered_entities: bool,
    retrieval_rounds_left: int,
    retrieve_recommended: bool,
) -> str:
    """Compone la acción. El código aplica la política; JEV aporta las señales."""
    if not relevant:
        # Sin evidencia usable: primero buscar; abstenerse sólo al agotar rondas.
        return ACTION_RETRIEVE_MORE if retrieval_rounds_left > 0 else ACTION_ABSTAIN
    if not grounded:
        # La evidencia existe y es relevante: el problema es el borrador, no la
        # ausencia de evidencia. Nunca «no hay evidencia suficiente» acá.
        if retrieve_recommended and retrieval_rounds_left > 0 and partial_entity_coverage:
            return ACTION_RETRIEVE_MORE
        return ACTION_REVISE
    if unsupported_claims or presentation_revision or not complete:
        return ACTION_REVISE
    if uncovered_entities:
        # Hay respaldo para lo explicado, pero la evidencia no cubre todo lo
        # pedido: se responde y se declara exactamente qué falta.
        return ACTION_ANSWER_WITH_LIMITS
    return ACTION_APPROVE


async def judge_answer(
    *,
    engine,
    mode: str,
    user_request: str,
    draft: str,
    observations: list[str] | None = None,
    evidence: Iterable[EvidenceItem] | None = None,
    agent_instructions: str = "",
    settings,
    max_state_chars: int = 30000,
    noul_yes: float = 0.65,
    approve_at: float = 0.66,
    revise_at: float = 0.40,
    context: JudgmentContext | None = None,
    retrieval_rounds_left: int = 0,
    evidence_budget_chars: int = DEFAULT_BUDGET_CHARS,
    presentation_enabled: bool | None = None,
) -> AnswerGateResult:
    """Evalua el borrador. Nunca lanza: ante error devuelve skipped.

    Con `evidence` (la evidencia registrada del run) el gate juzga la MISMA
    evidencia que vio el generador y aplica la política por acción. Sin
    `evidence` conserva el comportamiento previo sobre `observations`.
    """
    result = AnswerGateResult(mode=mode, provider="skip")
    if mode == "off" or engine is None:
        return result
    include_presentation = (
        presentation_gate_enabled() if presentation_enabled is None else bool(presentation_enabled)
    )

    items = list(evidence or ())
    evidence_provided = evidence is not None
    selection: EvidenceSelection | None = None
    evidence_text = ""
    if items:
        selection = select_evidence(
            items, user_request, budget_chars=max(500, int(evidence_budget_chars or 0) or DEFAULT_BUDGET_CHARS)
        )
        evidence_text = render_evidence(selection)
    else:
        evidence_text = "\n".join(line[:1500] for line in (observations or [])[-8:])

    sufficiency = assess_sufficiency(
        items, user_request, retrieval_rounds_left=retrieval_rounds_left
    )
    claims = claim_checks(draft, selection.items if selection is not None else items)

    sections = [
        StateSection("draft_answer", 1, (draft or "")[:6000]),
        StateSection("evidence", 2, evidence_text),
        StateSection("user_request", 3, (user_request or "")[:4000]),
        StateSection("agent_instructions", 4, agent_instructions),
    ]
    if selection is not None and selection.items:
        sections.insert(2, StateSection("evidence_index", 2, evidence_index_block(selection)))
    if items:
        # Señales objetivas (§9): reglas que preparan el juicio, no que lo reemplazan.
        sections.insert(
            3,
            StateSection(
                "evidence_signals",
                3,
                "; ".join(
                    part
                    for part in (
                        f"fragmentos={sufficiency.supporting_chunks}",
                        f"accion_recomendada={sufficiency.recommended_action}",
                        f"motivo={sufficiency.reason}",
                        (
                            f"cobertura_entidades={sufficiency.entity_coverage:.2f}"
                            if sufficiency.entity_coverage is not None
                            else ""
                        ),
                        (
                            "entidades_faltantes=" + ", ".join(sufficiency.missing_entities)
                            if sufficiency.missing_entities
                            else ""
                        ),
                    )
                    if part
                ),
            ),
        )
    built = build_jev_state(sections, max_chars=max_state_chars)
    questions = answer_gate_questions(include_presentation=include_presentation)
    if items and claims.get("uncertain"):
        # Los claims de la banda incierta se juzgan en la MISMA llamada: JEV es
        # el árbitro, el código compone el veredicto.
        questions.update(claim_questions(claims["uncertain"]))
    try:
        started = time.perf_counter()
        payload = await call_judge(
            engine,
            state=built.state,
            questions=questions,
            context=context or JudgmentContext(phase=PHASE_ANSWER_GATE),
        )
        result.latency_ms = (time.perf_counter() - started) * 1000
    except Exception:  # noqa: BLE001 — el gate nunca rompe el run
        return result
    if not isinstance(payload, dict):
        return result
    answers = payload.get("answers") if isinstance(payload.get("answers"), dict) else {}
    if not answers:
        return result
    if items and claims.get("uncertain"):
        claims = apply_claim_answers(
            claims, answers, noul_yes=noul_yes, noul_no=0.35
        )

    grounded_noul = _noul(answers, "answer_grounded")
    complete_noul = _noul(answers, "answer_complete")
    grounded = noul_is_yes(grounded_noul, noul_yes)
    complete = noul_is_yes(complete_noul, noul_yes)
    quality = _quality(answers)

    # --- score de compatibilidad (observabilidad del camino previo) ----------
    score = (
        ANSWER_WEIGHTS["grounded"] * (1.0 if grounded else 0.0)
        + ANSWER_WEIGHTS["complete"] * (1.0 if complete else 0.0)
        + ANSWER_WEIGHTS["quality"] * (quality / 3.0)
    )
    certainty = min(
        noul_certainty(grounded_noul),
        noul_certainty(complete_noul),
    )
    score = round(min(1.0, score * (0.7 + 0.3 * certainty)), 4)

    needs_presentation = include_presentation and presentation_needs_revision(answers, noul_yes=noul_yes)
    unsupported = tuple(claims.get("unsupported_texts") or ()) if claims else ()
    missing_entities = tuple(sufficiency.missing_entities)

    if evidence_provided:
        relevant = sufficiency.exact_entity_match is True or (
            (sufficiency.entity_coverage or 0.0) > 0.0
            or (not sufficiency.entities_asked and sufficiency.supporting_chunks > 0)
        )
        # La acción se reutiliza como veredicto: compatibilidad con el runtime y
        # el flujo, que ya hablan en términos de approve/revise/abstain.
        action = _evidence_action(
            grounded=grounded,
            complete=complete,
            presentation_revision=needs_presentation,
            unsupported_claims=bool(unsupported),
            relevant=relevant,
            partial_entity_coverage=0.0 < (sufficiency.entity_coverage or 0.0) < 1.0,
            uncovered_entities=bool(missing_entities),
            retrieval_rounds_left=max(0, int(retrieval_rounds_left or 0)),
            retrieve_recommended=sufficiency.recommended_action
            in {ACTION_RETRIEVE_MORE, ACTION_ABSTAIN},
        )
        grounding_verdict = (
            GROUNDING_SUPPORTED
            if grounded
            else (GROUNDING_PARTIAL if relevant else GROUNDING_UNSUPPORTED)
        )
    else:
        action = _legacy_verdict(score, approve_at=approve_at, revise_at=revise_at)
        if grounded and action == ACTION_ABSTAIN:
            # Presentación/completitud no pueden anular una respuesta respaldada.
            action = ACTION_REVISE
        if needs_presentation and action == ACTION_APPROVE:
            action = ACTION_REVISE
        grounding_verdict = GROUNDING_SUPPORTED if grounded else GROUNDING_UNSUPPORTED
    presentation_verdict = (
        PRESENTATION_NEEDS_REVISION if needs_presentation else PRESENTATION_OK
    )

    feedback = _feedback(
        grounded=grounded,
        complete=complete,
        quality=quality,
        reason=revision_feedback(answers) if action == ACTION_REVISE else "",
    )
    if action == ACTION_REVISE and unsupported and not feedback:
        feedback = "Verificador JEV: quita lo que la evidencia no sostiene."

    return AnswerGateResult(
        verdict=action,
        score=score,
        grounded=grounded,
        complete=complete,
        quality=quality,
        feedback=feedback,
        provider=str(payload.get("model") or "jev"),
        mode=mode,
        state_chars=built.chars,
        latency_ms=result.latency_ms,
        answers=answers,
        grounding_verdict=grounding_verdict,
        presentation_verdict=presentation_verdict,
        presentation_revision_reason=(revision_reason(answers) if needs_presentation else ""),
        evidence_ids=selection.ids if selection is not None else (),
        evidence_chars=selection.chars if selection is not None else 0,
        evidence_used=bool(items),
        missing_entities=missing_entities,
        unsupported_claims=unsupported,
        claims_summary={
            key: claims[key]
            for key in ("supported", "unsupported", "not_verifiable")
            if key in claims
        }
        if claims
        else {},
    )


__all__ = [
    "ANSWER_WEIGHTS",
    "CONTENT_REVISION_REASONS",
    "GROUNDING_PARTIAL",
    "GROUNDING_SUPPORTED",
    "GROUNDING_UNKNOWN",
    "GROUNDING_UNSUPPORTED",
    "INSUFFICIENT_ANSWER",
    "MAX_CLAIM_QUESTIONS",
    "PRESENTATION_NEEDS_REVISION",
    "PRESENTATION_OK",
    "PRESENTATION_REVISION_REASONS",
    "PRESENTATION_UNKNOWN",
    "REVISION_REASON_FEEDBACK",
    "AnswerGateResult",
    "answer_gate_mode",
    "apply_claim_answers",
    "claim_checks",
    "claim_questions",
    "presentation_gate_enabled",
    "presentation_needs_revision",
    "revision_feedback",
    "revision_reason",
]
