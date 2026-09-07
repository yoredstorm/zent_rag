# =============================================================================
# Answerability Gate — decide si la pregunta es contestable
# =============================================================================
# Decisión por prioridad DETERMINISTA sobre señales del sistema. El LLM puede
# actuar como crítico adicional (post-generación), pero nunca es la única
# señal. NO usa falsa precisión: confianza discreta HIGH/MEDIUM/LOW/INSUFFICIENT.
#
# Orden de prioridad (bloqueantes estructurales primero):
#   ACCESS_BLOCKED > EXECUTION_FAILED > SOURCE_CONFLICT > CLARIFICATION_REQUIRED
#   > AMBIGUOUS > CONTEXT_MISSING > DATA_MISSING > DATA_QUALITY_LOW
#   > HUMAN_REVIEW_REQUIRED > ANSWERABLE
# =============================================================================
from __future__ import annotations

from typing import Any

from src.core.domain.intelligence import (
    AnswerabilityDecision,
    AnswerabilityStatus,
    ConfidenceLevel,
    EvidenceObject,
    PlanStrategy,
    QueryPlan,
    QueryUnderstanding,
)
from src.intelligence.signals import SignalSet, weights_for_plan

_BLOCKED_ERROR_HINTS = ("blocked for role", "is blocked")

_CRITIC_PROMPT = """Evalúa si la siguiente respuesta está completamente soportada
por la evidencia provista. Responde SOLO con JSON: {{"supported": true, "reason": "..."}}

Evidencia:
{evidence}

Pregunta: {question}

Respuesta:
{answer}
"""


def detect_source_conflicts(
    evidences: list[EvidenceObject],
    tolerance_pct: float = 5.0,
    *,
    authoritative_source: str | None = None,
) -> list[dict]:
    """Detecta contradicciones entre fuentes para el mismo dato.

    Si existe una fuente autoritativa configurada entre las involucradas,
    la contradicción se considera resuelta (no se retorna conflicto).
    """
    conflicts: list[dict] = []
    by_metric: dict[str, list[EvidenceObject]] = {}
    for e in evidences:
        if e.value is None or not isinstance(e.value, (int, float)):
            continue
        metric = (e.metadata or {}).get("metric") or "__generic__"
        by_metric.setdefault(metric, []).append(e)

    for metric, group in by_metric.items():
        numeric = [(e, float(e.value)) for e in group if e.value is not None]
        if len(numeric) < 2:
            continue
        sources = {e.source_name for e, _ in numeric}
        if len(sources) < 2:
            continue
        base = max(numeric, key=lambda item: abs(item[1]))
        for e, value in numeric:
            if e is base[0]:
                continue
            if abs(value - base[1]) / max(abs(base[1]), 1e-9) * 100 > tolerance_pct:
                if authoritative_source and e.source_name == authoritative_source:
                    continue
                if authoritative_source and base[0].source_name == authoritative_source:
                    continue
                conflicts.append(
                    {
                        "metric": metric,
                        "source_a": base[0].source_name,
                        "value_a": base[1],
                        "source_b": e.source_name,
                        "value_b": value,
                        "evidence_a": base[0].evidence_id,
                        "evidence_b": e.evidence_id,
                    }
                )
    return conflicts


class AnswerabilityGate:
    """Compuerta central de answerability (independiente del LLM)."""

    def __init__(
        self,
        *,
        min_score: float = 0.6,
        coverage_min: float = 0.2,
        conflict_tolerance_pct: float = 5.0,
        llm_critic_enabled: bool = False,
        llm_provider: Any | None = None,
    ) -> None:
        self._min_score = min_score
        self._coverage_min = coverage_min
        self._conflict_tolerance_pct = conflict_tolerance_pct
        self._critic_enabled = llm_critic_enabled
        self._llm = llm_provider

    @property
    def critic_enabled(self) -> bool:
        return self._critic_enabled

    @staticmethod
    def confidence_level(score: float) -> ConfidenceLevel:
        """Mapeo discreto del score a confianza (sin falsa precisión)."""
        if score >= 0.8:
            return ConfidenceLevel.HIGH
        if score >= 0.6:
            return ConfidenceLevel.MEDIUM
        if score >= 0.4:
            return ConfidenceLevel.LOW
        return ConfidenceLevel.INSUFFICIENT

    def evaluate(
        self,
        signals: SignalSet,
        understanding: QueryUnderstanding,
        plan: QueryPlan,
        evidences: list[EvidenceObject],
        *,
        execution_error: str | None = None,
        missing_data_hints: list[str] | None = None,
        authoritative_source: str | None = None,
    ) -> AnswerabilityDecision:
        score = signals.score(weights_for_plan(plan))

        # 1) ACCESS_BLOCKED — permisos denegados (señal determinista)
        if signals.permission_check <= 0 or (
            execution_error and any(h in execution_error.lower() for h in _BLOCKED_ERROR_HINTS)
        ):
            return AnswerabilityDecision(
                status=AnswerabilityStatus.ACCESS_BLOCKED,
                answerable=False,
                confidence_level=ConfidenceLevel.INSUFFICIENT,
                score=score,
                reason_codes=["PERMISSION_DENIED"],
                evidence_ids=[e.evidence_id for e in evidences],
                recommended_actions=[
                    "Revisar permisos/blocklists de la organización para esta consulta"
                ],
                message=(
                    "No tengo permisos para acceder a la información solicitada. "
                    "La consulta fue bloqueada por la política de acceso."
                ),
            )

        # 2) EXECUTION_FAILED — ejecución falló sin evidencia alternativa
        if execution_error and not evidences:
            return AnswerabilityDecision(
                status=AnswerabilityStatus.EXECUTION_FAILED,
                answerable=False,
                confidence_level=ConfidenceLevel.INSUFFICIENT,
                score=score,
                reason_codes=["EXECUTION_ERROR"],
                missing_context=[],
                evidence_ids=[],
                recommended_actions=[
                    "Reintentar la consulta o verificar la salud de las fuentes"
                ],
                message=(
                    "La consulta falló durante su ejecución y no pude obtener "
                    "evidencia alternativa."
                ),
            )

        # 3) SOURCE_CONFLICT — fuentes se contradicen sin fuente autoritativa
        conflicts = detect_source_conflicts(
            evidences,
            tolerance_pct=self._conflict_tolerance_pct,
            authoritative_source=authoritative_source,
        )
        if conflicts:
            return AnswerabilityDecision(
                status=AnswerabilityStatus.SOURCE_CONFLICT,
                answerable=False,
                confidence_level=ConfidenceLevel.LOW,
                score=score,
                reason_codes=["SOURCE_DISAGREEMENT"],
                conflicting_sources=conflicts,
                evidence_ids=[e.evidence_id for e in evidences],
                recommended_actions=[
                    "Configurar una fuente autoritativa para la métrica en conflicto"
                ],
                message=(
                    "Las fuentes disponibles se contradicen y no existe una "
                    "fuente autoritativa configurada. No elijo una arbitrariamente."
                ),
            )

        # 4) CLARIFICATION_REQUIRED — ambigüedad resoluble con UNA pregunta
        if understanding.ambiguity and understanding.clarifying_question:
            return AnswerabilityDecision(
                status=AnswerabilityStatus.CLARIFICATION_REQUIRED,
                answerable=False,
                confidence_level=ConfidenceLevel.MEDIUM,
                score=score,
                reason_codes=["AMBIGUOUS_QUERY"],
                clarifying_question=understanding.clarifying_question,
                evidence_ids=[e.evidence_id for e in evidences],
                recommended_actions=["Preguntar la aclaración al usuario"],
                message=understanding.clarifying_question,
            )

        # 5) AMBIGUOUS — ambigüedad sin pregunta única que la resuelva
        if understanding.ambiguity:
            return AnswerabilityDecision(
                status=AnswerabilityStatus.AMBIGUOUS,
                answerable=False,
                confidence_level=ConfidenceLevel.LOW,
                score=score,
                reason_codes=["AMBIGUOUS_QUERY"],
                evidence_ids=[e.evidence_id for e in evidences],
                recommended_actions=["Pedir contexto adicional al usuario"],
                message=(
                    "La información existe pero la consulta es ambigua: admite "
                    "varias interpretaciones que no puedo resolver sin más contexto."
                ),
            )

        # 6) CONTEXT_MISSING — la data existe pero falta su definición/regla
        #    Solo los conceptos que REQUIEREN definición disparan este estado
        #    (evita abstenerse por sustantivos genéricos sin regla empresarial).
        resolved = understanding.resolved_concepts or {}
        definitional = (
            understanding.requires_definition
            or (understanding.concepts if understanding.extraction_source == "llm" else [])
        )
        undefined = [c for c in definitional if not resolved.get(c, False)]
        if undefined and (
            plan.needs_semantic_resolution
            or plan.strategy in (PlanStrategy.SQL, PlanStrategy.SQL_RAG)
        ):
            return AnswerabilityDecision(
                status=AnswerabilityStatus.CONTEXT_MISSING,
                answerable=False,
                confidence_level=ConfidenceLevel.LOW,
                score=score,
                reason_codes=["UNDEFINED_BUSINESS_TERM"],
                missing_context=[
                    f"Definition of {concept}" for concept in undefined
                ],
                found=[c for c, d in resolved.items() if d],
                evidence_ids=[e.evidence_id for e in evidences],
                recommended_actions=[
                    f"Create or approve the {concept} business metric/definition"
                    for concept in undefined
                ],
                message=(
                    "Puedo identificar los datos subyacentes, pero no existe una "
                    "definición empresarial aprobada de: "
                    + ", ".join(undefined)
                    + "."
                ),
            )

        # 7) DATA_MISSING — la información física necesaria no existe o no está conectada
        if signals.result_presence <= 0:
            hints = missing_data_hints or [
                f"Datos para {'/'.join(understanding.concepts) or 'la consulta'}"
            ]
            return AnswerabilityDecision(
                status=AnswerabilityStatus.DATA_MISSING,
                answerable=False,
                confidence_level=ConfidenceLevel.INSUFFICIENT,
                score=score,
                reason_codes=["NO_SQL_RESULT", "NO_RETRIEVAL"],
                missing_data=hints,
                evidence_ids=[e.evidence_id for e in evidences],
                recommended_actions=[
                    "Conectar la fuente de datos requerida o reindexar la knowledge base"
                ],
                message=(
                    "No puedo responder porque la información física necesaria "
                    "no existe o no está conectada: "
                    + ", ".join(hints)
                    + "."
                ),
            )

        # 8) DATA_QUALITY_LOW — data presente pero frescura/autoridad/cobertura débiles
        quality_issues: list[str] = []
        sql_path_authoritative = (
            plan.needs_sql and signals.sql_execution_success > 0
        )
        if not sql_path_authoritative:
            if (
                plan.needs_retrieval
                and signals.retrieval_coverage < self._coverage_min
            ):
                quality_issues.append("retrieval coverage baja")
            if signals.source_authority < 0.6:
                quality_issues.append("fuentes sin autoridad suficiente")
        if signals.source_freshness < 0.5 and not sql_path_authoritative:
            quality_issues.append("fuentes con frescura insuficiente")
        if quality_issues:
            return AnswerabilityDecision(
                status=AnswerabilityStatus.DATA_QUALITY_LOW,
                answerable=False,
                confidence_level=ConfidenceLevel.LOW,
                score=score,
                reason_codes=["LOW_DATA_QUALITY"],
                evidence_ids=[e.evidence_id for e in evidences],
                recommended_actions=quality_issues,
                message=(
                    "La información existe pero su calidad es insuficiente: "
                    + ", ".join(quality_issues)
                    + "."
                ),
            )

        # 9) HUMAN_REVIEW_REQUIRED — score insuficiente con algo de evidencia
        if score < self._min_score:
            return AnswerabilityDecision(
                status=AnswerabilityStatus.HUMAN_REVIEW_REQUIRED,
                answerable=False,
                confidence_level=self.confidence_level(score),
                score=score,
                reason_codes=["LOW_ANSWERABILITY_SCORE"],
                evidence_ids=[e.evidence_id for e in evidences],
                recommended_actions=["Revisión humana de la evidencia recopilada"],
                message=(
                    "La evidencia recopilada no alcanza el umbral de confianza "
                    "para responder automáticamente; requiere revisión humana."
                ),
            )

        # 10) ANSWERABLE
        return AnswerabilityDecision(
            status=AnswerabilityStatus.ANSWERABLE,
            answerable=True,
            confidence_level=self.confidence_level(score),
            score=score,
            reason_codes=[],
            evidence_ids=[e.evidence_id for e in evidences],
            message=None,
        )

    async def critic(
        self,
        *,
        question: str,
        answer: str,
        evidence_text: str,
    ) -> dict | None:
        """Crítico LLM post-generación (señal ADICIONAL, nunca única)."""
        if not self._critic_enabled or self._llm is None:
            return None
        try:
            resp = await self._llm.generate(
                prompt=_CRITIC_PROMPT.format(
                    evidence=evidence_text[:8000],
                    question=question[:2000],
                    answer=answer[:4000],
                ),
                max_tokens=128,
                temperature=0.0,
            )
            import json
            import re

            content = (resp.content or "").strip()
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if not match:
                return {"supported": True, "reason": "critic_parse_failed"}
            return json.loads(match.group(0))
        except Exception:  # noqa: BLE001 — el critic nunca rompe la respuesta
            return None

    def apply_critic(
        self,
        decision: AnswerabilityDecision,
        critic_result: dict | None,
    ) -> AnswerabilityDecision:
        """Degrada la decisión si el crítico marca la respuesta como no soportada."""
        if not critic_result or decision.status != AnswerabilityStatus.ANSWERABLE:
            return decision
        supported = critic_result.get("supported", True)
        if not supported:
            decision.status = AnswerabilityStatus.HUMAN_REVIEW_REQUIRED
            decision.answerable = False
            decision.confidence_level = ConfidenceLevel.LOW
            decision.reason_codes = ["CRITIC_UNSUPPORTED"]
            decision.llm_critic = critic_result
            decision.recommended_actions = [
                "Revisión humana: el crítico no encontró soporte completo en la evidencia"
            ]
            decision.message = (
                "La respuesta generada no está completamente soportada por la "
                "evidencia; requiere revisión humana."
            )
        return decision
