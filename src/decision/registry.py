# =============================================================================
# Question Registry — definición central de las preguntas JEV.
# =============================================================================
# Cada pregunta es un dato versionado, no un string suelto en un builder:
#
#   id / fase / tipo / instrucciones / criterios / ui_label / risk / thresholds
#
# Permite observabilidad (¿qué preguntó el run?), calibración por pregunta y
# versionado: el batch registra `question_version` junto con la respuesta, así
# una pregunta reformulada no se mezcla con su historia.
#
# Las preguntas se registran por (fase, id): el mismo id puede existir en fases
# distintas (estados distintos). Las repetibles (una por hipótesis/claim) se
# declaran como plantilla y se expanden con `expand_definition`.
#
# Nada de esto cambia ejecución: JEV juzga, el código compone.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Iterable

from src.decision.judgment import (
    PHASE_POST_GENERATION,
    PHASE_POST_RECONSTRUCTION,
    PHASE_PRE_GENERATION,
    PHASE_PRE_REASONING,
)

TYPE_CHOICE = "choice"
TYPE_SCORE = "score"
TYPE_NOUL = "noul"
QUESTION_TYPES = (TYPE_CHOICE, TYPE_SCORE, TYPE_NOUL)

_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


@dataclass(frozen=True, kw_only=True)
class QuestionDefinition:
    """Una pregunta atómica, versionada y observable."""

    id: str
    phase: str
    type: str
    instructions: str
    version: int = 1
    criteria: dict[str, str] | list[str] | None = None
    options: tuple[str, ...] = ()
    ui_label: str = ""
    description: str = ""
    risk: str = "low"
    threshold_key: str = ""
    applicable_when: str = ""
    source: str = "preflight"
    repeatable: bool = False
    id_template: str = ""

    def __post_init__(self) -> None:
        if not _ID_RE.match(self.id):
            raise ValueError(f"invalid question id: {self.id!r}")
        if self.id_template and not _ID_RE.match(self.id_template.format(index=0)):
            raise ValueError(f"invalid question id template: {self.id_template!r}")
        if self.type not in QUESTION_TYPES:
            raise ValueError(f"invalid question type: {self.type!r} for {self.id!r}")

    def expand(self, index: int) -> "QuestionDefinition":
        """Instancia repetible de la plantilla (`hypothesis_{index}_supported`)."""
        if not self.repeatable:
            return self
        return replace(self, id=self.id_template.format(index=int(index)))

    def to_public_dict(self) -> dict:
        payload: dict = {
            "id": self.id,
            "phase": self.phase,
            "type": self.type,
            "version": self.version,
            "risk": self.risk,
            "source": self.source,
        }
        if self.ui_label:
            payload["ui_label"] = self.ui_label
        if self.description:
            payload["description"] = self.description
        if self.threshold_key:
            payload["threshold_key"] = self.threshold_key
        if self.options:
            payload["options"] = list(self.options)
        if self.applicable_when:
            payload["applicable_when"] = self.applicable_when
        return payload


class QuestionRegistry:
    """Catálogo de definiciones. Los ids no se renombran: se versionan."""

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], QuestionDefinition] = {}
        self._phases: list[str] = []

    def register(self, definition: QuestionDefinition) -> QuestionDefinition:
        key = (definition.phase, definition.id)
        current = self._by_key.get(key)
        if current is None:
            self._by_key[key] = definition
            if definition.phase not in self._phases:
                self._phases.append(definition.phase)
            return definition
        # Regresión de versión: se conserva la más alta (nada se degrada solo).
        if definition.version >= current.version:
            self._by_key[key] = definition
            return definition
        return current

    def register_many(self, definitions: Iterable[QuestionDefinition]) -> None:
        for definition in definitions:
            self.register(definition)

    def get(self, question_id: str, *, phase: str | None = None) -> QuestionDefinition | None:
        if phase is not None:
            return self._by_key.get((phase, question_id))
        for (_, candidate), definition in self._by_key.items():
            if candidate == question_id:
                return definition
        return None

    def version_of(self, question_id: str, *, phase: str | None = None) -> int:
        definition = self.get(question_id, phase=phase)
        return definition.version if definition is not None else 0

    def phases(self) -> tuple[str, ...]:
        return tuple(self._phases)

    def for_phase(self, phase: str) -> tuple[QuestionDefinition, ...]:
        return tuple(
            definition
            for (candidate_phase, _), definition in self._by_key.items()
            if candidate_phase == phase and not definition.repeatable
        )

    def repeatable_for_phase(self, phase: str) -> tuple[QuestionDefinition, ...]:
        return tuple(
            definition
            for (candidate_phase, _), definition in self._by_key.items()
            if candidate_phase == phase and definition.repeatable
        )

    def public(self, *, phase: str | None = None) -> list[dict]:
        rows = [
            definition
            for (candidate_phase, _), definition in self._by_key.items()
            if phase is None or candidate_phase == phase
        ]
        return [definition.to_public_dict() for definition in sorted(rows, key=lambda d: (d.phase, d.id))]


_REGISTRY = QuestionRegistry()


def default_registry() -> QuestionRegistry:
    return _REGISTRY


def register_question(definition: QuestionDefinition) -> QuestionDefinition:
    return _REGISTRY.register(definition)


def get_definition(question_id: str, *, phase: str | None = None) -> QuestionDefinition | None:
    return _REGISTRY.get(question_id, phase=phase)


def question_version(question_id: str, *, phase: str | None = None) -> int:
    return _REGISTRY.version_of(question_id, phase=phase)


def public_registry(*, phase: str | None = None) -> list[dict]:
    return _REGISTRY.public(phase=phase)


# -----------------------------------------------------------------------------
# PRE_REASONING — antes de retrieval/LLM caro (§7)
# -----------------------------------------------------------------------------

REASONING_SHAPE_OPTIONS = (
    "simple_lookup",
    "multi_evidence",
    "state_transition",
    "temporal_sequence",
    "consistency_check",
    "causal_analysis",
    "diagnostic",
    "hypothesis_test",
    "graph_reasoning",
)

SHAPE_CRITERIA: dict[str, str] = {
    "simple_lookup": "A single fact, definition, code, or value can answer the request.",
    "multi_evidence": "Several independent sources must be combined and compared.",
    "state_transition": "The answer depends on reconstructing how a state changed over records.",
    "temporal_sequence": "The answer depends on the order of events and their chronology.",
    "consistency_check": "The answer depends on detecting contradictions between sources.",
    "causal_analysis": "The request asks why something happened or what produced an effect.",
    "diagnostic": "The request asks what is wrong, failing, or blocking something.",
    "hypothesis_test": "The request states a suspicion that must be proven or rejected.",
    "graph_reasoning": "The answer depends on relationships between entities or items.",
}

CAPABILITY_OPTIONS = (
    "documents",
    "structured",
    "graph",
    "tool",
    "workflow",
    "direct",
)

CAPABILITY_CRITERIA: dict[str, str] = {
    "documents": "Unstructured text: policies, manuals, contracts, tickets.",
    "structured": "Structured records: tables, master data, transactional rows.",
    "graph": "Declared relationships between company entities or items.",
    "tool": "An external tool or API must be called to obtain the facts.",
    "workflow": "A known company workflow must be started or resumed.",
    "direct": "No retrieval is needed: the request carries its own facts.",
}

COMPLEXITY_LEVELS = (
    "trivial",
    "bounded",
    "analytical",
    "multi_stage",
    "high_complexity",
)

COMPLEXITY_CRITERIA = [
    "trivial: one lookup, no reasoning",
    "bounded: one source, one step",
    "analytical: several signals must be combined",
    "multi_stage: reconstruction plus hypothesis testing over several sources",
    "high_complexity: long scenario, conflicting evidence, rules and transitions",
]

PRE_REASONING_QUESTIONS: tuple[QuestionDefinition, ...] = (
    QuestionDefinition(
        id="reasoning_shape",
        phase=PHASE_PRE_REASONING,
        type=TYPE_CHOICE,
        risk="medium",
        threshold_key="reasoning_shape",
        options=REASONING_SHAPE_OPTIONS,
        criteria=SHAPE_CRITERIA,
        ui_label="¿Qué tipo de análisis necesita?",
        description="Forma del razonamiento requerido; eje ortogonal al intent.",
        instructions=(
            "Which reasoning shape does `user_request` require, given "
            "`company_context_summary`, `memory_patterns` and `available_sources`?"
        ),
    ),
    QuestionDefinition(
        id="preferred_capability",
        phase=PHASE_PRE_REASONING,
        type=TYPE_CHOICE,
        risk="low",
        threshold_key="preferred_capability",
        options=CAPABILITY_OPTIONS,
        criteria=CAPABILITY_CRITERIA,
        ui_label="¿De dónde deben venir los hechos?",
        description="Familia de fuente preferida para reunir los hechos.",
        instructions=(
            "Which source family in `available_sources` should provide the facts "
            "for `user_request`?"
        ),
    ),
    QuestionDefinition(
        id="analysis_complexity",
        phase=PHASE_PRE_REASONING,
        type=TYPE_SCORE,
        risk="low",
        threshold_key="analysis_complexity",
        criteria=COMPLEXITY_CRITERIA,
        ui_label="¿Qué complejidad tiene el análisis?",
        description="Score ordinal de complejidad del análisis.",
        instructions="How complex is `user_request` as an analysis task?",
    ),
    QuestionDefinition(
        id="needs_private_knowledge",
        phase=PHASE_PRE_REASONING,
        type=TYPE_NOUL,
        ui_label="¿Necesita conocimiento privado?",
        description="Los hechos no están en la pregunta.",
        instructions=(
            "Does answering `user_request` require private tenant knowledge that "
            "is not present in the request itself?"
        ),
    ),
    QuestionDefinition(
        id="needs_multiple_evidence",
        phase=PHASE_PRE_REASONING,
        type=TYPE_NOUL,
        ui_label="¿Necesita múltiples evidencias?",
        description="Más de una fuente o registro deben combinarse.",
        instructions=(
            "Does `user_request` require combining more than one evidence source "
            "or record before it can be answered?"
        ),
    ),
    QuestionDefinition(
        id="needs_structured_data",
        phase=PHASE_PRE_REASONING,
        type=TYPE_NOUL,
        applicable_when="sql_enabled",
        ui_label="¿Necesita datos estructurados?",
        description="Requiere SQL o registros tabulares.",
        instructions=(
            "Does `user_request` require structured or transactional records "
            "(tables, master data, row-level values) rather than documents?"
        ),
    ),
    QuestionDefinition(
        id="needs_graph",
        phase=PHASE_PRE_REASONING,
        type=TYPE_NOUL,
        ui_label="¿Necesita relaciones del grafo?",
        description="Requiere relaciones entre entidades declaradas.",
        instructions=(
            "Does `user_request` depend on declared relationships between company "
            "entities or items, rather than on document text?"
        ),
    ),
    QuestionDefinition(
        id="needs_timeline",
        phase=PHASE_PRE_REASONING,
        type=TYPE_NOUL,
        ui_label="¿Necesita línea de tiempo?",
        description="El orden de los eventos es material.",
        instructions=(
            "Is the chronological order of events material for answering "
            "`user_request`?"
        ),
    ),
    QuestionDefinition(
        id="needs_state_reconstruction",
        phase=PHASE_PRE_REASONING,
        type=TYPE_NOUL,
        ui_label="¿Necesita reconstruir el estado?",
        description="Hay que reconstruir transiciones de estado.",
        instructions=(
            "Does answering `user_request` require reconstructing how the state "
            "changed across a sequence of records or events?"
        ),
    ),
    QuestionDefinition(
        id="needs_hypothesis_testing",
        phase=PHASE_PRE_REASONING,
        type=TYPE_NOUL,
        ui_label="¿Necesita contrastar hipótesis?",
        description="Explicaciones alternativas deben probarse.",
        instructions=(
            "Does `user_request` require testing competing explanations "
            "(for example a suspicion stated by the user) against the evidence?"
        ),
    ),
    QuestionDefinition(
        id="simple_lookup_sufficient",
        phase=PHASE_PRE_REASONING,
        type=TYPE_NOUL,
        ui_label="¿Basta una consulta simple?",
        description="Camino rápido: una búsqueda o lectura responde.",
        instructions=(
            "Can `user_request` be answered with a single lookup, definition, or "
            "direct source read, without reconstruction or multi-source reasoning?"
        ),
    ),
)


# -----------------------------------------------------------------------------
# POST_RECONSTRUCTION — después de escenario, timeline y transiciones (§14)
# -----------------------------------------------------------------------------

POST_RECONSTRUCTION_QUESTIONS: tuple[QuestionDefinition, ...] = (
    QuestionDefinition(
        id="scenario_completeness",
        phase=PHASE_POST_RECONSTRUCTION,
        type=TYPE_SCORE,
        risk="medium",
        threshold_key="scenario_completeness",
        criteria=[
            "unusable: the scenario could not be interpreted",
            "partial: missing records or unrecoverable fields",
            "usable: enough to reason, with declared gaps",
            "complete: no material gap remains",
        ],
        ui_label="¿Qué tan completo quedó el escenario?",
        description="Score ordinal de completitud del escenario reconstruido.",
        instructions=(
            "How complete is `scenario` for answering `question`, given "
            "`unparsed_items` and `missing_requirements`?"
        ),
    ),
    QuestionDefinition(
        id="state_reconstruction_quality",
        phase=PHASE_POST_RECONSTRUCTION,
        type=TYPE_SCORE,
        risk="medium",
        threshold_key="state_reconstruction_quality",
        criteria=[
            "unreliable: the chain of changes is not supported",
            "weak: some links lack a rule or a record",
            "sound: every confirmed link has its record and rule",
            "strong: every link confirmed and no gap remains",
        ],
        ui_label="¿Qué tan sólida es la reconstrucción?",
        description="Calidad de la cadena de transiciones reconstruida.",
        instructions=(
            "How solid is `transitions` as a reconstruction of how the state "
            "changed, given `rules` and `unresolved_items`?"
        ),
    ),
    QuestionDefinition(
        id="rule_coverage",
        phase=PHASE_POST_RECONSTRUCTION,
        type=TYPE_SCORE,
        risk="medium",
        threshold_key="rule_coverage",
        ui_label="¿Las reglas cubren el caso?",
        description="Cobertura de las reglas aplicables al escenario.",
        instructions=(
            "How well do the rules in `rules` cover the operations observed in "
            "`scenario` for `question`?"
        ),
    ),
    QuestionDefinition(
        id="timeline_coherent",
        phase=PHASE_POST_RECONSTRUCTION,
        type=TYPE_NOUL,
        ui_label="¿La secuencia temporal es coherente?",
        description="El orden reconstruido no se contradice.",
        instructions=(
            "Is `timeline` internally coherent: no event is placed before a "
            "record it depends on, and no unexplained gap breaks the order?"
        ),
    ),
    QuestionDefinition(
        id="critical_transition_missing",
        phase=PHASE_POST_RECONSTRUCTION,
        type=TYPE_NOUL,
        ui_label="¿Falta una transición crítica?",
        description="Hay un salto en la cadena de estados.",
        instructions=(
            "Does `transitions` show a material gap: a change between states that "
            "no record or rule explains?"
        ),
    ),
    QuestionDefinition(
        id="hypothesis_user_supported",
        phase=PHASE_POST_RECONSTRUCTION,
        type=TYPE_NOUL,
        risk="medium",
        ui_label="¿La explicación del usuario está respaldada?",
        description="Hipótesis declarada por el usuario, a favor.",
        instructions=(
            "Does the evidence in `facts` and `transitions` support "
            "`user_hypothesis`?"
        ),
    ),
    QuestionDefinition(
        id="hypothesis_user_contradicted",
        phase=PHASE_POST_RECONSTRUCTION,
        type=TYPE_NOUL,
        risk="medium",
        ui_label="¿La explicación del usuario está contradicha?",
        description="Hipótesis declarada por el usuario, en contra.",
        instructions=(
            "Does the evidence in `facts` and `transitions` contradict "
            "`user_hypothesis`?"
        ),
    ),
    QuestionDefinition(
        id="alternative_hypothesis_supported",
        phase=PHASE_POST_RECONSTRUCTION,
        type=TYPE_NOUL,
        ui_label="¿Hay una explicación alternativa respaldada?",
        description="Otra explicación explica mejor el escenario.",
        instructions=(
            "Does the evidence support an alternative explanation in "
            "`alternative_hypotheses` better than `user_hypothesis`?"
        ),
    ),
    QuestionDefinition(
        id="inference_possible",
        phase=PHASE_POST_RECONSTRUCTION,
        type=TYPE_NOUL,
        risk="medium",
        ui_label="¿La conclusión se desprende de los hechos?",
        description="Existe una regla que conecta premisas y conclusión.",
        instructions=(
            "Can the conclusion in `candidate_conclusion` be derived from "
            "`facts` using a rule in `rules` (not by free interpretation)?"
        ),
    ),
    QuestionDefinition(
        id="critical_unknown_remaining",
        phase=PHASE_POST_RECONSTRUCTION,
        type=TYPE_NOUL,
        ui_label="¿Queda algún desconocido crítico?",
        description="Falta un dato que cambia la conclusión.",
        instructions=(
            "Is there an unknown in `unresolved_items` whose value could change "
            "the conclusion for `question`?"
        ),
    ),
    QuestionDefinition(
        id="hypothesis_supported",
        phase=PHASE_POST_RECONSTRUCTION,
        type=TYPE_NOUL,
        repeatable=True,
        id_template="hypothesis_{index}_supported",
        ui_label="¿Esta explicación está respaldada?",
        description="Por candidato: la evidencia respalda la hipótesis.",
        instructions=(
            "Does the evidence in `facts` and `transitions` support hypothesis "
            "{index} in `hypothesis_candidates`?"
        ),
    ),
    QuestionDefinition(
        id="hypothesis_contradicted",
        phase=PHASE_POST_RECONSTRUCTION,
        type=TYPE_NOUL,
        repeatable=True,
        id_template="hypothesis_{index}_contradicted",
        ui_label="¿Esta explicación está contradicha?",
        description="Por candidato: la evidencia contradice la hipótesis.",
        instructions=(
            "Does the evidence in `facts` and `transitions` contradict hypothesis "
            "{index} in `hypothesis_candidates`?"
        ),
    ),
)


# -----------------------------------------------------------------------------
# PRE_GENERATION — el gate antes del LLM generativo (§16, §17, §19)
# -----------------------------------------------------------------------------

NEXT_ACTION_OPTIONS = (
    "generate_answer",
    "retrieve_more",
    "reconstruct_more",
    "ask_user",
    "abstain",
    "deterministic_answer",
)

NEXT_ACTION_CRITERIA: dict[str, str] = {
    "generate_answer": "Evidence and analysis are ready: write the answer.",
    "retrieve_more": "Material evidence is still missing and retrieval can fix it.",
    "reconstruct_more": "The scenario or the state reconstruction is incomplete.",
    "ask_user": "Only the user can provide the missing fact or the intent.",
    "abstain": "The question cannot be answered with the available evidence.",
    "deterministic_answer": "The conclusion is already established; no generation needed.",
}

GENERATION_TIER_OPTIONS = ("deterministic", "small", "standard", "reasoning")

GENERATION_TIER_CRITERIA: dict[str, str] = {
    "deterministic": "The answer follows directly from confirmed facts; no model needed.",
    "small": "Short synthesis over already-established conclusions.",
    "standard": "Normal synthesis over several evidence pieces.",
    "reasoning": "Complex synthesis requiring supported conclusions to be combined.",
}

PRE_GENERATION_QUESTIONS: tuple[QuestionDefinition, ...] = (
    QuestionDefinition(
        id="analysis_complete",
        phase=PHASE_PRE_GENERATION,
        type=TYPE_NOUL,
        risk="high",
        threshold_key="analysis_complete",
        ui_label="¿El análisis está completo?",
        description="No quedan pasos materiales sin hacer.",
        instructions=(
            "Is the analysis for `question` complete: every required step was "
            "performed and no material step remains?"
        ),
    ),
    QuestionDefinition(
        id="answerable_from_current_evidence",
        phase=PHASE_PRE_GENERATION,
        type=TYPE_NOUL,
        risk="high",
        threshold_key="answerable",
        ui_label="¿Se puede responder con la evidencia actual?",
        description="La evidencia sostiene la respuesta sin inventar hechos.",
        instructions=(
            "Can `question` be answered using `evidence` and `confirmed_facts` "
            "without inventing facts?"
        ),
    ),
    QuestionDefinition(
        id="critical_fact_missing",
        phase=PHASE_PRE_GENERATION,
        type=TYPE_NOUL,
        risk="high",
        ui_label="¿Falta información crítica?",
        description="Falta un dato que cambiaría la respuesta.",
        instructions=(
            "Is a critical fact missing, such that the answer would be a guess?"
        ),
    ),
    QuestionDefinition(
        id="critical_conflict_unresolved",
        phase=PHASE_PRE_GENERATION,
        type=TYPE_NOUL,
        risk="high",
        ui_label="¿Hay un conflicto sin resolver?",
        description="Dos fuentes materiales se contradicen.",
        instructions=(
            "Do two material sources in `evidence` contradict each other without "
            "an authority rule to resolve it?"
        ),
    ),
    QuestionDefinition(
        id="inference_supported",
        phase=PHASE_PRE_GENERATION,
        type=TYPE_NOUL,
        risk="high",
        ui_label="¿La conclusión se desprende de los hechos?",
        description="La conclusión sigue de premisas y reglas.",
        instructions=(
            "Does the conclusion follow from `confirmed_facts` using the rules in "
            "`rules`, rather than from plausible interpretation?"
        ),
    ),
    QuestionDefinition(
        id="expensive_llm_needed",
        phase=PHASE_PRE_GENERATION,
        type=TYPE_NOUL,
        ui_label="¿Hace falta razonamiento generativo avanzado?",
        description="Se requiere generar razonamiento, no redactar.",
        instructions=(
            "Does producing the answer require multi-step generative reasoning "
            "beyond wording the conclusions already established?"
        ),
    ),
    QuestionDefinition(
        id="simple_deterministic_answer_possible",
        phase=PHASE_PRE_GENERATION,
        type=TYPE_NOUL,
        ui_label="¿Basta una respuesta determinística?",
        description="Las conclusiones ya están establecidas en código.",
        instructions=(
            "Are the conclusions already established (confirmed facts plus rule "
            "verdicts) so the answer is a matter of stating them, not deriving them?"
        ),
    ),
    QuestionDefinition(
        id="needs_complex_reasoning_model",
        phase=PHASE_PRE_GENERATION,
        type=TYPE_NOUL,
        ui_label="¿Necesita un modelo de razonamiento?",
        description="El nivel de generación requerido.",
        instructions=(
            "Does writing the answer require a reasoning-grade model, because "
            "several supported conclusions must be combined into new structure?"
        ),
    ),
    QuestionDefinition(
        id="answer_readiness",
        phase=PHASE_PRE_GENERATION,
        type=TYPE_SCORE,
        risk="high",
        threshold_key="answer_readiness",
        criteria=[
            "not ready: the analysis is incomplete",
            "partially ready: some conclusions are established",
            "ready: the answer can be written from the established conclusions",
            "fully ready: the answer follows from the evidence without new derivation",
        ],
        ui_label="¿Qué tan lista está la respuesta?",
        description="Score ordinal de preparación para responder.",
        instructions=(
            "How ready is the answer for `question`, given `analysis` and "
            "`evidence`?"
        ),
    ),
    QuestionDefinition(
        id="evidence_strength",
        phase=PHASE_PRE_GENERATION,
        type=TYPE_SCORE,
        risk="high",
        threshold_key="evidence_strength",
        criteria=[
            "weak: no direct support",
            "partial: some support with gaps",
            "strong: direct support from at least one authoritative source",
            "conclusive: direct authoritative support with no open gap",
        ],
        ui_label="¿Qué fuerza tiene la evidencia?",
        description="Fuerza de la evidencia que sostiene la respuesta.",
        instructions=(
            "How strong is `evidence` as support for the conclusion about "
            "`question`?"
        ),
    ),
    QuestionDefinition(
        id="risk_of_wrong_answer",
        phase=PHASE_PRE_GENERATION,
        type=TYPE_SCORE,
        risk="high",
        threshold_key="risk_of_wrong_answer",
        criteria=[
            "negligible: the answer contradicts nothing and follows from rules",
            "low: minor wording risk only",
            "material: an assumption could change the conclusion",
            "high: the conclusion depends on unverified premises",
        ],
        ui_label="¿Qué riesgo hay de responder mal?",
        description="Riesgo de una respuesta incorrecta con esta evidencia.",
        instructions=(
            "What is the risk that an answer to `question` built from `evidence` "
            "and `analysis` would be wrong or misleading?"
        ),
    ),
    QuestionDefinition(
        id="generation_complexity",
        phase=PHASE_PRE_GENERATION,
        type=TYPE_SCORE,
        ui_label="¿Qué complejidad tiene la redacción?",
        description="Complejidad de la síntesis requerida.",
        instructions=(
            "How complex is the synthesis needed to state the answer for "
            "`question` from the established conclusions?"
        ),
    ),
    QuestionDefinition(
        id="next_action",
        phase=PHASE_PRE_GENERATION,
        type=TYPE_CHOICE,
        risk="high",
        threshold_key="next_action",
        options=NEXT_ACTION_OPTIONS,
        criteria=NEXT_ACTION_CRITERIA,
        ui_label="¿Qué corresponde hacer ahora?",
        description="Acción recomendada; el código decide y ejecuta.",
        instructions=(
            "What is the best next operation for `question`, given `evidence`, "
            "`analysis`, `budget` and `unknowns`?"
        ),
    ),
    QuestionDefinition(
        id="generation_tier",
        phase=PHASE_PRE_GENERATION,
        type=TYPE_CHOICE,
        risk="medium",
        threshold_key="generation_tier",
        options=GENERATION_TIER_OPTIONS,
        criteria=GENERATION_TIER_CRITERIA,
        ui_label="¿Qué nivel de generación necesita?",
        description="Tier sugerido dentro de los candidatos permitidos.",
        instructions=(
            "Which generation tier is sufficient for `question`: none, small, "
            "standard, or reasoning-grade?"
        ),
    ),
)


FINAL_ACTION_OPTIONS = ("approve", "revise", "abstain")

FINAL_ACTION_CRITERIA: dict[str, str] = {
    "approve": "The answer is grounded, complete and does not overstate certainty.",
    "revise": "The answer has a material defect that can be fixed.",
    "abstain": "The answer cannot be grounded in the available evidence.",
}

#: Verificación de la respuesta (§22). Viaja en el pack POST_GENERATION ya
#: existente (grounding + claims): mismo draft, mismo estado, una sola llamada.
POST_GENERATION_QUESTIONS: tuple[QuestionDefinition, ...] = (
    QuestionDefinition(
        id="answer_grounded",
        phase=PHASE_POST_GENERATION,
        type=TYPE_NOUL,
        risk="high",
        threshold_key="answer_grounded",
        ui_label="¿La respuesta está respaldada?",
        description="Los hechos del draft están sostenidos por la evidencia.",
        instructions=(
            "Are the factual claims in `draft_answer` supported by "
            "`evidence_preview`? If the answer says evidence is missing, yes."
        ),
    ),
    QuestionDefinition(
        id="answer_complete",
        phase=PHASE_POST_GENERATION,
        type=TYPE_NOUL,
        ui_label="¿La respuesta está completa?",
        description="Contesta la pregunta sin dejar cabos sueltos.",
        instructions=(
            "Does `draft_answer` fully answer `user_request`, including the "
            "conclusion the evidence supports?"
        ),
    ),
    QuestionDefinition(
        id="answer_addresses_question",
        phase=PHASE_POST_GENERATION,
        type=TYPE_NOUL,
        ui_label="¿Responde la pregunta formulada?",
        description="Ataca la pregunta real, no una vecina.",
        instructions=(
            "Does `draft_answer` address `user_request` as asked, rather than a "
            "related but different question?"
        ),
    ),
    QuestionDefinition(
        id="answer_contains_unsupported_conclusion",
        phase=PHASE_POST_GENERATION,
        type=TYPE_NOUL,
        risk="high",
        ui_label="¿Incluye una conclusión sin respaldo?",
        description="Afirma algo que la evidencia no sostiene.",
        instructions=(
            "Does `draft_answer` state a conclusion that `evidence_preview` and "
            "`confirmed_facts` do not support?"
        ),
    ),
    QuestionDefinition(
        id="answer_overstates_uncertainty",
        phase=PHASE_POST_GENERATION,
        type=TYPE_NOUL,
        ui_label="¿Exagera la certeza?",
        description="Suena concluyente donde hay límites o dudas.",
        instructions=(
            "Does `draft_answer` present as certain something that the evidence "
            "leaves open, unresolved or limited?"
        ),
    ),
    QuestionDefinition(
        id="answer_ignores_material_conflict",
        phase=PHASE_POST_GENERATION,
        type=TYPE_NOUL,
        risk="high",
        ui_label="¿Ignora un conflicto material?",
        description="Omite un desacuerdo entre fuentes que importa.",
        instructions=(
            "Does `draft_answer` omit a material conflict present in the evidence "
            "that the reader needs to know about?"
        ),
    ),
    QuestionDefinition(
        id="answer_quality",
        phase=PHASE_POST_GENERATION,
        type=TYPE_SCORE,
        ui_label="¿Qué calidad tiene la respuesta?",
        description="Score ordinal de la respuesta final.",
        instructions=(
            "How good is `draft_answer` as an answer to `user_request`, given "
            "`evidence_preview`?"
        ),
    ),
    QuestionDefinition(
        id="clarity",
        phase=PHASE_POST_GENERATION,
        type=TYPE_SCORE,
        ui_label="¿Qué tan clara es la respuesta?",
        description="Se entiende sin leer la evidencia.",
        instructions="How clear and readable is `draft_answer`?",
    ),
    QuestionDefinition(
        id="evidence_alignment",
        phase=PHASE_POST_GENERATION,
        type=TYPE_SCORE,
        ui_label="¿Qué tan alineada está con la evidencia?",
        description="Grado de correspondencia con la evidencia.",
        instructions=(
            "How closely does `draft_answer` align with `evidence_preview` and "
            "`confirmed_facts`?"
        ),
    ),
    QuestionDefinition(
        id="final_action",
        phase=PHASE_POST_GENERATION,
        type=TYPE_CHOICE,
        risk="high",
        threshold_key="final_action",
        options=FINAL_ACTION_OPTIONS,
        criteria=FINAL_ACTION_CRITERIA,
        ui_label="¿Qué hacemos con esta respuesta?",
        description="Aprobar, revisar o abstenerse; el código ejecuta.",
        instructions=(
            "Given `draft_answer`, `evidence_preview` and `claim_verification`, "
            "should this answer be approved, revised, or withheld?"
        ),
    ),
)


def register_preflight_questions(registry: QuestionRegistry | None = None) -> QuestionRegistry:
    """Registra las preguntas del preflight. Idempotente."""
    target = registry or _REGISTRY
    target.register_many(PRE_REASONING_QUESTIONS)
    target.register_many(POST_RECONSTRUCTION_QUESTIONS)
    target.register_many(PRE_GENERATION_QUESTIONS)
    target.register_many(POST_GENERATION_QUESTIONS)
    return target


register_preflight_questions()


__all__ = [
    "CAPABILITY_CRITERIA",
    "CAPABILITY_OPTIONS",
    "COMPLEXITY_CRITERIA",
    "COMPLEXITY_LEVELS",
    "GENERATION_TIER_CRITERIA",
    "GENERATION_TIER_OPTIONS",
    "NEXT_ACTION_CRITERIA",
    "NEXT_ACTION_OPTIONS",
    "POST_RECONSTRUCTION_QUESTIONS",
    "PRE_GENERATION_QUESTIONS",
    "PRE_REASONING_QUESTIONS",
    "QuestionDefinition",
    "QuestionRegistry",
    "REASONING_SHAPE_OPTIONS",
    "SHAPE_CRITERIA",
    "TYPE_CHOICE",
    "TYPE_NOUL",
    "TYPE_SCORE",
    "default_registry",
    "get_definition",
    "public_registry",
    "question_version",
    "register_preflight_questions",
    "register_question",
]
