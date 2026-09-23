# =============================================================================
# Hypothesis Engine (§25-§28) + Inference Verification (§29/§30) +
# Analysis Completion Gate (§31)
# =============================================================================
# La hipótesis del usuario se representa explícitamente y NO se asume cierta.
# Se generan pocas alternativas (máximo configurable) y se prueban primero de
# forma determinística; el JEV sólo entra en zonas inciertas con preguntas
# atómicas.
#
# La verificación de inferencias es distinta de la de claims: las premisas
# pueden ser correctas y la conclusión NO seguirse de ellas.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Awaitable, Callable
from uuid import UUID

from src.core.domain.reasoning import (
    AnalysisCompletion,
    CompletionCheck,
    Fact,
    FactStatus,
    Hypothesis,
    HypothesisOrigin,
    HypothesisSet,
    HypothesisVerdict,
    InferenceRecord,
    InferenceVerdict,
    MissingRequirement,
    ReasoningPlan,
    ReasoningWorkspace,
    StateTransitionSet,
    StructuredScenario,
)

#: Hipótesis implícita en la pregunta del usuario.
_USER_HYPOTHESIS_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bfalta\b.*\bregistro", "Falta un registro (de cierre) en la secuencia"),
    (r"\bfalta\s+un\s+cierre", "Falta un cierre para completar la secuencia"),
    (r"\bmissing\b.*\brecord", "Falta un registro (de cierre) en la secuencia"),
    (r"\bse\s+perdi[oó]\b", "Se perdió un evento de la secuencia"),
    (r"\bdeber[ií]a\s+haber\b", "Debería existir un evento adicional"),
    (r"\bes\s+correcto\s+que\b", "La secuencia observada es correcta"),
)


#: Señales de regla, en español e inglés. "renumer" (ES) y "renumber" (EN) no
#: comparten raíz escribible, así que ambas se buscan explícitamente.
_RENUMBER_MARKERS = ("renumer", "renumber", "reasigna", "reassign")
_COEXIST_MARKERS = (
    "coexist",
    "pueden convivir",
    "varias secuencias activas",
    "multiple active sequences",
    "no requiere cierre",
    "no closing record is required",
    "no close",
    "sin cierre",
)
_CLOSE_MARKERS = (
    "requiere cierre",
    "must close",
    "closing record is required",
    "debe cerrar",
    "obligatorio cerrar",
    "incomplete without",
    "must be closed",
)


_NEGATION_MARKERS = ("no ", "not ", "never ", "sin ", "nunca ", "ningún ", "ningun ")


def _has_unnegated(text: str, markers: tuple[str, ...]) -> bool:
    """Busca el marcador SIN negación delante.

    "no closing record is required" contiene "closing record is required"; sin
    este chequeo la regla se leería al revés.
    """
    for marker in markers:
        start = 0
        while True:
            index = text.find(marker, start)
            if index == -1:
                break
            prefix = text[max(0, index - 18) : index]
            if not any(negation in prefix for negation in _NEGATION_MARKERS):
                return True
            start = index + len(marker)
    return False


def _has_negated(text: str, markers: tuple[str, ...]) -> bool:
    for marker in markers:
        start = 0
        while True:
            index = text.find(marker, start)
            if index == -1:
                break
            prefix = text[max(0, index - 18) : index]
            if any(negation in prefix for negation in _NEGATION_MARKERS):
                return True
            start = index + len(marker)
    return False


def rule_signals(statement: str) -> dict[str, bool]:
    """Señales normalizadas de una regla. Evita duplicar el matching léxico."""
    text = (statement or "").lower()
    negated_close = _has_negated(text, _CLOSE_MARKERS)
    return {
        "renumbers": any(marker in text for marker in _RENUMBER_MARKERS),
        "allows_coexistence": any(marker in text for marker in _COEXIST_MARKERS)
        or negated_close,
        "requires_close": _has_unnegated(text, _CLOSE_MARKERS),
    }


_AUTHORITY_RANK = {
    "authoritative": 4,
    "primary": 3,
    "secondary": 2,
    "informational": 1,
    "untrusted": 0,
}


def authority_rank(level: str | None) -> int:
    """Rango del nivel de autoridad. Sin nivel configurado = 0."""
    return _AUTHORITY_RANK.get(str(level or "").strip().lower(), 0)


@dataclass
class HypothesisEngine:
    """Construye y prueba hipótesis. Determinista primero."""

    max_hypotheses: int = 4
    judge: Callable[..., Awaitable[dict | None]] | None = None

    async def evaluate(
        self,
        *,
        question: str,
        workspace: ReasoningWorkspace,
        rules: list[Fact] | None = None,
        memory_hints: tuple[str, ...] = (),
    ) -> HypothesisSet:
        hypotheses: list[Hypothesis] = []
        user_statement = self._user_hypothesis(question)
        user_id: UUID | None = None
        scenario = workspace.scenario
        transitions = workspace.transitions
        rule_list = list(rules or workspace.rules)
        missing = list(scenario.missing_requirements) if scenario else []

        if user_statement:
            hypothesis = Hypothesis(
                statement=user_statement, origin=HypothesisOrigin.USER
            )
            hypotheses.append(hypothesis)
            user_id = hypothesis.id

        # Las alternativas derivadas de una regla quedan atadas a esa regla: el
        # veredicto no depende de la morfología del enunciado generado.
        generated_support: dict[UUID, tuple[UUID, ...]] = {}
        for statement, origin, support_refs in self._alternatives(
            question=question,
            scenario=scenario,
            transitions=transitions,
            rules=rule_list,
            memory_hints=memory_hints,
        ):
            if len(hypotheses) >= self.max_hypotheses:
                break
            if any(item.statement == statement for item in hypotheses):
                continue
            hypothesis = Hypothesis(statement=statement, origin=origin)
            if support_refs:
                generated_support[hypothesis.id] = support_refs
            hypotheses.append(hypothesis)

        tested: list[Hypothesis] = []
        for hypothesis in hypotheses:
            verdict = await self._verdict(
                hypothesis=hypothesis,
                workspace=workspace,
                rules=rule_list,
                missing=missing,
                user_hypothesis=hypothesis.id == user_id,
                rule_support=generated_support.get(hypothesis.id, ()),
            )
            tested.append(verdict)
        return HypothesisSet(
            hypotheses=tuple(tested),
            user_hypothesis_id=user_id,
            max_hypotheses=self.max_hypotheses,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _user_hypothesis(question: str) -> str:
        text = " ".join((question or "").lower().split())
        for pattern, statement in _USER_HYPOTHESIS_PATTERNS:
            if re.search(pattern, text):
                return statement
        return ""

    def _alternatives(
        self,
        *,
        question: str,
        scenario: StructuredScenario | None,
        transitions: StateTransitionSet | None,
        rules: list[Fact],
        memory_hints: tuple[str, ...],
    ) -> list[tuple[str, HypothesisOrigin, tuple[UUID, ...]]]:
        alternatives: list[tuple[str, HypothesisOrigin, tuple[UUID, ...]]] = []
        renumber_rules = tuple(
            rule.id
            for rule in rules
            if rule.usable_as_premise and rule_signals(rule.statement)["renumbers"]
        )
        coexist_rules = tuple(
            rule.id
            for rule in rules
            if rule.usable_as_premise
            and rule_signals(rule.statement)["allows_coexistence"]
        )
        if renumber_rules:
            alternatives.append(
                (
                    "La renumeración abrió espacio de ordenamiento; el salto es esperado",
                    HypothesisOrigin.RULE,
                    renumber_rules,
                )
            )
        if coexist_rules:
            alternatives.append(
                (
                    "Pueden coexistir varias secuencias activas: no falta un cierre",
                    HypothesisOrigin.RULE,
                    coexist_rules,
                )
            )
        if transitions and transitions.gaps:
            alternatives.append(
                (
                    "El salto de numeración se debe a un evento no incluido en el input",
                    HypothesisOrigin.COMPANY_GRAPH,
                    (),
                )
            )
        for hint in memory_hints[:1]:
            alternatives.append((hint, HypothesisOrigin.MEMORY, ()))
        if not alternatives and scenario and scenario.unparsed_items:
            alternatives.append(
                (
                    "El input está incompleto y no permite decidir",
                    HypothesisOrigin.USER,
                    (),
                )
            )
        return alternatives

    async def _verdict(
        self,
        *,
        hypothesis: Hypothesis,
        workspace: ReasoningWorkspace,
        rules: list[Fact],
        missing: list[MissingRequirement],
        user_hypothesis: bool,
        rule_support: tuple[UUID, ...] = (),
    ) -> Hypothesis:
        supporting: list[UUID] = []
        contradicting: list[UUID] = []
        supporting_rules: list[Fact] = []
        contradicting_rules: list[Fact] = []
        unresolved_requirements: list[str] = []
        transitions = workspace.transitions
        applicable = [rule for rule in rules if rule.usable_as_premise]

        text = hypothesis.statement.lower()
        wants_close = "falta" in text or "missing" in text or "cierre" in text
        expects_space = (
            "renumer" in text or "espacio" in text or "coexisten" in text
        )

        for rule in applicable:
            signals = rule_signals(rule.statement)
            if wants_close:
                if signals["requires_close"]:
                    supporting.append(rule.id)
                    supporting_rules.append(rule)
                if signals["allows_coexistence"] or signals["renumbers"]:
                    contradicting.append(rule.id)
                    contradicting_rules.append(rule)
            if expects_space and (signals["renumbers"] or signals["allows_coexistence"]):
                supporting.append(rule.id)
                supporting_rules.append(rule)

        # La alternativa nació de una regla: esa regla la respalda aunque el
        # enunciado generado no repita sus palabras.
        for rule in applicable:
            if rule.id in rule_support and rule.id not in supporting:
                supporting.append(rule.id)
                supporting_rules.append(rule)
                contradicting = [item for item in contradicting if item != rule.id]
                contradicting_rules = [
                    item for item in contradicting_rules if item.id != rule.id
                ]

        for requirement in missing:
            if not requirement.resolved:
                unresolved_requirements.append(requirement.kind.value)

        verdict = HypothesisVerdict.UNRESOLVED
        rationale = ""
        if unresolved_requirements:
            rationale = (
                "Falta evidencia crítica: " + ", ".join(unresolved_requirements[:3])
            )
        elif supporting and not contradicting:
            verdict = HypothesisVerdict.SUPPORTED
            rationale = f"{len(supporting)} regla(s) con autoridad respaldan la hipótesis"
        elif contradicting and not supporting:
            verdict = HypothesisVerdict.REJECTED
            rationale = (
                f"{len(contradicting)} regla(s) con autoridad contradicen la hipótesis"
            )
        elif supporting and contradicting:
            # §7/§57: la autoridad del tenant tiene precedencia; si no hay
            # autoridad configurada, el conflicto se declara y no se resuelve.
            best_support = max(
                authority_rank(rule.authority) for rule in supporting_rules
            )
            best_contra = max(
                authority_rank(rule.authority) for rule in contradicting_rules
            )
            if best_contra > best_support:
                verdict = HypothesisVerdict.REJECTED
                rationale = (
                    "La fuente autoritativa contradice la hipótesis "
                    f"(autoridad {best_contra} contra {best_support})"
                )
            elif best_support > best_contra:
                verdict = HypothesisVerdict.SUPPORTED
                rationale = (
                    "La fuente autoritativa respalda la hipótesis "
                    f"(autoridad {best_support} contra {best_contra})"
                )
            else:
                verdict = HypothesisVerdict.UNRESOLVED
                rationale = (
                    "Evidencia en conflicto sin autoridad configurada que desempate"
                )

        # Sin reglas aplicables pero con transiciones confirmadas: no se afirma.
        if verdict is HypothesisVerdict.UNRESOLVED and not rationale:
            if not applicable:
                rationale = (
                    "No hay regla aplicable para resolver la hipótesis con la "
                    "evidencia disponible"
                )
            elif transitions is not None and not transitions.transitions:
                rationale = "No se pudo reconstruir la secuencia de estados"
            else:
                rationale = "La evidencia disponible no alcanza para decidir"

        # El juez sólo entra si sigue incierto y hay algo que preguntar.
        if verdict is HypothesisVerdict.UNRESOLVED and self.judge is not None and applicable:
            verdict, rationale = await self._judge_verdict(
                hypothesis=hypothesis,
                workspace=workspace,
                rules=applicable,
                rationale=rationale,
            )

        return Hypothesis(
            id=hypothesis.id,
            statement=hypothesis.statement,
            origin=hypothesis.origin,
            supporting_fact_ids=tuple(supporting),
            contradicting_fact_ids=tuple(contradicting),
            missing_requirement_ids=tuple(unresolved_requirements),
            verdict=verdict,
            rationale=rationale,
        )

    async def _judge_verdict(
        self,
        *,
        hypothesis: Hypothesis,
        workspace: ReasoningWorkspace,
        rules: list[Fact],
        rationale: str,
    ) -> tuple[HypothesisVerdict, str]:
        """Preguntas atómicas al juez: nunca "¿cuál explicación es correcta?"."""
        assert self.judge is not None
        fact_text = " | ".join(
            f"[{fact.status.value}] {fact.statement[:180]}"
            for fact in workspace.confirmed_facts[:6]
        )
        state = {
            "hypothesis": hypothesis.statement[:400],
            "facts": fact_text[:2000],
            "rules": " | ".join(rule.statement[:180] for rule in rules[:6]),
        }
        questions = {
            "supported_by_facts": {
                "type": "noul",
                "instructions": "Does the available evidence support this hypothesis?",
            },
            "contradicted_by_facts": {
                "type": "noul",
                "instructions": "Does the available evidence contradict this hypothesis?",
            },
            "critical_evidence_missing": {
                "type": "noul",
                "instructions": "Is critical evidence missing to decide this hypothesis?",
            },
        }
        try:
            payload = await self.judge(state=state, questions=questions)
        except Exception:  # noqa: BLE001
            return HypothesisVerdict.UNRESOLVED, rationale
        if not isinstance(payload, dict):
            return HypothesisVerdict.UNRESOLVED, rationale
        from src.decision.batch import noul_for

        answers = payload.get("answers") or {}

        def _noul(key: str) -> float:
            value = noul_for(answers, key, default=0.0)
            return float(value) if value is not None else 0.0

        missing_signal = _noul("critical_evidence_missing")
        supports = _noul("supported_by_facts")
        contradicts = _noul("contradicted_by_facts")
        if missing_signal > 0.65:
            return HypothesisVerdict.UNRESOLVED, "El juez reporta evidencia crítica faltante"
        if supports > 0.65 and supports > contradicts:
            return HypothesisVerdict.SUPPORTED, "El juez confirma respaldo en la evidencia"
        if contradicts > 0.65:
            return HypothesisVerdict.REJECTED, "El juez detecta contradicción en la evidencia"
        return HypothesisVerdict.UNRESOLVED, rationale


# ---------------------------------------------------------------------------
# Inference verification (premisas -> conclusión)
# ---------------------------------------------------------------------------


@dataclass
class InferenceVerifier:
    """Verifica que la conclusión se SIGA de las premisas y las reglas."""

    def verify(
        self,
        *,
        conclusion: str,
        premises: list[Fact],
        rule_refs: tuple[str, ...] = (),
        evidence_refs: tuple[str, ...] = (),
    ) -> InferenceRecord:
        premise_refs = tuple(fact.id for fact in premises)
        if not premises:
            return InferenceRecord(
                conclusion=conclusion,
                verdict=InferenceVerdict.UNRESOLVED,
                rationale="No hay premisas con evidencia",
                evidence_refs=evidence_refs,
                rule_refs=rule_refs,
            )
        unusable = [fact for fact in premises if not fact.usable_as_premise]
        if unusable:
            return InferenceRecord(
                conclusion=conclusion,
                premise_refs=premise_refs,
                rule_refs=rule_refs,
                evidence_refs=evidence_refs,
                verdict=InferenceVerdict.UNRESOLVED,
                rationale=(
                    "Hay premisas sin respaldo suficiente: "
                    + "; ".join(fact.statement[:80] for fact in unusable[:3])
                ),
            )
        contradicting = [fact for fact in premises if fact.status is FactStatus.CONTRADICTED]
        if contradicting:
            return InferenceRecord(
                conclusion=conclusion,
                premise_refs=premise_refs,
                rule_refs=rule_refs,
                evidence_refs=evidence_refs,
                verdict=InferenceVerdict.CONTRADICTED,
                rationale="Una premisa está contradicha por la evidencia",
            )
        if not rule_refs:
            # Premisas correctas, pero sin regla que conecte con la conclusión.
            return InferenceRecord(
                conclusion=conclusion,
                premise_refs=premise_refs,
                rule_refs=(),
                evidence_refs=evidence_refs,
                verdict=InferenceVerdict.UNSUPPORTED,
                rationale=(
                    "Las premisas están respaldadas pero ninguna regla disponible "
                    "conecta con la conclusión propuesta"
                ),
            )
        return InferenceRecord(
            conclusion=conclusion,
            premise_refs=premise_refs,
            rule_refs=rule_refs,
            evidence_refs=evidence_refs,
            verdict=InferenceVerdict.SUPPORTED,
            rationale="Premisas respaldadas y regla aplicable identificada",
        )


# ---------------------------------------------------------------------------
# Analysis completion gate (§31)
# ---------------------------------------------------------------------------


@dataclass
class AnalysisCompletionGate:
    """Determinístico: decide si se puede concluir o hay que abstenerse."""

    min_parse_confidence: float = 0.4

    def evaluate(
        self,
        *,
        plan: ReasoningPlan,
        workspace: ReasoningWorkspace,
    ) -> AnalysisCompletion:
        checks: list[CompletionCheck] = []
        blockers: list[str] = []
        reason_codes: list[str] = []
        scenario = workspace.scenario
        timeline = workspace.timeline
        transitions = workspace.transitions
        hypotheses = workspace.hypotheses

        if plan.required_facts:
            resolved = [
                fact
                for fact in workspace.facts
                if fact.usable_as_premise
            ]
            satisfied = len(resolved) >= len(plan.required_facts)
            checks.append(
                CompletionCheck(
                    name="required_facts_resolved",
                    satisfied=satisfied,
                    detail=f"{len(resolved)}/{len(plan.required_facts)}",
                )
            )
            if not satisfied:
                blockers.append("required_facts_unresolved")
                reason_codes.append("ANALYSIS_INCOMPLETE")

        if plan.requires_scenario_parse:
            unresolved = [
                item
                for item in (scenario.missing_requirements if scenario else ())
                if not item.resolved
            ]
            satisfied = bool(scenario and scenario.events) and not unresolved
            checks.append(
                CompletionCheck(
                    name="scenario_parsed",
                    satisfied=satisfied,
                    detail=(
                        f"{len(scenario.events) if scenario else 0} eventos, "
                        f"{len(unresolved)} requisitos sin resolver"
                    ),
                )
            )
            if unresolved:
                kinds = {item.kind.value for item in unresolved}
                blockers.append("scenario_incomplete")
                reason_codes.extend(sorted(kinds))
                if "RECORD_LAYOUT_REQUIRED" in kinds or "SCHEMA_REQUIRED" in kinds:
                    reason_codes.append("SCHEMA_REQUIRED")

        if plan.requires_timeline:
            satisfied = bool(timeline and timeline.events)
            chronology = bool(
                timeline and timeline.criteria.get("chronology_proven")
            )
            checks.append(
                CompletionCheck(
                    name="timeline_complete",
                    satisfied=satisfied,
                    detail=(
                        f"{len(timeline.events) if timeline else 0} eventos, "
                        f"cronología {'probada' if chronology else 'no probada por fechas'}"
                    ),
                )
            )
            if not satisfied:
                blockers.append("timeline_incomplete")
                reason_codes.append("TIMELINE_INCOMPLETE")

        if plan.requires_state_reconstruction:
            satisfied = bool(transitions and transitions.transitions)
            checks.append(
                CompletionCheck(
                    name="state_reconstructed",
                    satisfied=satisfied,
                    detail=(
                        f"{transitions.confirmed if transitions else 0} confirmadas, "
                        f"{transitions.unresolved if transitions else 0} sin resolver"
                    ),
                )
            )
            if not satisfied:
                blockers.append("state_unresolved")
                reason_codes.append("STATE_UNRESOLVED")

        if plan.requires_hypothesis_testing:
            has_user = bool(hypotheses and hypotheses.user_hypothesis_id)
            user_resolved = False
            if has_user and hypotheses is not None:
                user = hypotheses.by_id(hypotheses.user_hypothesis_id)
                user_resolved = bool(
                    user and user.verdict is not HypothesisVerdict.UNRESOLVED
                )
            satisfied = has_user and user_resolved
            checks.append(
                CompletionCheck(
                    name="user_hypothesis_evaluated",
                    satisfied=satisfied,
                    detail=(
                        "sin hipótesis del usuario"
                        if not has_user
                        else ("resuelta" if user_resolved else "sin resolver")
                    ),
                )
            )
            if has_user and not user_resolved:
                blockers.append("hypothesis_unresolved")
                reason_codes.append("HYPOTHESIS_UNRESOLVED")

        if plan.requires_graph_traversal:
            satisfied = bool(workspace.graph_facts)
            checks.append(
                CompletionCheck(
                    name="graph_evidence_present",
                    satisfied=satisfied,
                    detail=f"{len(workspace.graph_facts)} hechos de grafo",
                )
            )
            if not satisfied:
                blockers.append("graph_evidence_missing")
                reason_codes.append("GRAPH_RELATION_UNCONFIRMED")

        unresolved_inference = [
            item
            for item in workspace.inferences
            if item.verdict in (InferenceVerdict.UNSUPPORTED, InferenceVerdict.CONTRADICTED)
        ]
        if workspace.inferences:
            checks.append(
                CompletionCheck(
                    name="inference_path_supported",
                    satisfied=not unresolved_inference,
                    detail=(
                        "todas las inferencias soportadas"
                        if not unresolved_inference
                        else f"{len(unresolved_inference)} inferencia(s) sin soporte"
                    ),
                )
            )
            if unresolved_inference:
                blockers.append("inference_unsupported")
                reason_codes.append("INFERENCE_UNSUPPORTED")

        if workspace.contradictions:
            checks.append(
                CompletionCheck(
                    name="contradictions_resolved",
                    satisfied=False,
                    detail=f"{len(workspace.contradictions)} contradicción(es) abiertas",
                )
            )
            blockers.append("contradictions_open")
            reason_codes.append("SOURCE_CONFLICT")

        complete = not blockers
        if not complete and "ANALYSIS_INCOMPLETE" not in reason_codes:
            reason_codes.append("ANALYSIS_INCOMPLETE")
        return AnalysisCompletion(
            complete=complete,
            checks=tuple(checks),
            blockers=tuple(dict.fromkeys(blockers)),
            reason_codes=tuple(dict.fromkeys(reason_codes)),
        )


__all__ = [
    "AnalysisCompletionGate",
    "HypothesisEngine",
    "InferenceVerifier",
    "rule_signals",
]
