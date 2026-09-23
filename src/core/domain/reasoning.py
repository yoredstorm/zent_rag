# =============================================================================
# Domain Layer — Evidence Reasoning (razonamiento sobre hechos)
# =============================================================================
# Zent podía recuperar documentación correcta y aun así concluir mal porque
# empezaba a redactar antes de reconstruir el escenario. Esta capa modela lo
# que hay que PROBAR, no lo que conviene hacer:
#
#   Company Intelligence  ->  qué es la empresa
#   Memory                ->  qué aprendió Zent operando
#   Judgment Fabric       ->  qué conviene hacer ahora
#   Evidence Reasoning    ->  qué permiten concluir los hechos
#
# Leyes:
#   - Nada se inventa: si falta el layout de un registro fijo, se emite
#     MissingRequirement; no se adivinan posiciones de byte.
#   - DISCOVERED no es premisa firme: genera hipótesis, no conclusión.
#   - El orden de entrada no es el orden cronológico ni el de vigencia.
#   - Un estado desconocido se queda UNKNOWN.
#   - Nunca chain-of-thought: se guardan referencias, no razonamiento privado.
#
# Tipos puros, sin I/O. El motor vive en src/intelligence/reasoning/.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from src.core.domain.research import ResearchBudgets


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Eje 2: forma del razonamiento requerido (ortogonal al intent)
# ---------------------------------------------------------------------------


class ReasoningShape(StrEnum):
    SIMPLE_LOOKUP = "SIMPLE_LOOKUP"
    MULTI_EVIDENCE = "MULTI_EVIDENCE"
    STATE_TRANSITION = "STATE_TRANSITION"
    TEMPORAL_SEQUENCE = "TEMPORAL_SEQUENCE"
    CONSISTENCY_CHECK = "CONSISTENCY_CHECK"
    CAUSAL_ANALYSIS = "CAUSAL_ANALYSIS"
    DIAGNOSTIC = "DIAGNOSTIC"
    HYPOTHESIS_TEST = "HYPOTHESIS_TEST"
    COMPARATIVE_REASONING = "COMPARATIVE_REASONING"
    GRAPH_REASONING = "GRAPH_REASONING"


#: Formas que exigen plan, workspace y gate de completitud.
COMPLEX_SHAPES = frozenset(
    {
        ReasoningShape.MULTI_EVIDENCE,
        ReasoningShape.STATE_TRANSITION,
        ReasoningShape.TEMPORAL_SEQUENCE,
        ReasoningShape.CONSISTENCY_CHECK,
        ReasoningShape.CAUSAL_ANALYSIS,
        ReasoningShape.DIAGNOSTIC,
        ReasoningShape.HYPOTHESIS_TEST,
        ReasoningShape.COMPARATIVE_REASONING,
        ReasoningShape.GRAPH_REASONING,
    }
)


class ReasoningMode(StrEnum):
    """Flag de rollout (§49)."""

    OFF = "off"
    SHADOW = "shadow"
    ON = "on"
    CANARY = "canary"


class ReasoningClassificationSource(StrEnum):
    DETERMINISTIC = "deterministic"
    JUDGE = "judge"
    HYBRID = "hybrid"


@dataclass(frozen=True, kw_only=True)
class ReasoningClassification:
    """Resultado del clasificador: intent existente + forma de razonamiento."""

    shape: ReasoningShape
    intent: str = "general"
    confidence: float = 0.5
    source: ReasoningClassificationSource = ReasoningClassificationSource.DETERMINISTIC
    signals: tuple[str, ...] = ()
    uncertain: bool = False

    @property
    def is_complex(self) -> bool:
        return self.shape in COMPLEX_SHAPES

    def to_dict(self) -> dict:
        return {
            "shape": self.shape.value,
            "intent": self.intent,
            "confidence": self.confidence,
            "source": self.source.value,
            "signals": list(self.signals),
            "uncertain": self.uncertain,
            "is_complex": self.is_complex,
        }


# ---------------------------------------------------------------------------
# Missing requirements: lo que falta NO se inventa
# ---------------------------------------------------------------------------


class RequirementKind(StrEnum):
    RECORD_LAYOUT_REQUIRED = "RECORD_LAYOUT_REQUIRED"
    SEQUENCE_FIELD_POSITION_REQUIRED = "SEQUENCE_FIELD_POSITION_REQUIRED"
    ACTION_CODE_SEMANTICS_REQUIRED = "ACTION_CODE_SEMANTICS_REQUIRED"
    EFFECTIVE_DATE_SEMANTICS_REQUIRED = "EFFECTIVE_DATE_SEMANTICS_REQUIRED"
    ENTITY_IDENTIFIER_REQUIRED = "ENTITY_IDENTIFIER_REQUIRED"
    RULE_REQUIRED = "RULE_REQUIRED"
    SCHEMA_REQUIRED = "SCHEMA_REQUIRED"
    AUTHORITY_REQUIRED = "AUTHORITY_REQUIRED"


@dataclass(frozen=True, kw_only=True)
class MissingRequirement:
    """Necesidad de evidencia declarada explícitamente.

    Se resuelve en orden: Company Graph confirmado, metadata estructurada,
    fuentes autoritativas, retrieval, relaciones DISCOVERED como hint.
    Si nada la resuelve, Answerability puede devolver CONTEXT_MISSING.
    """

    kind: RequirementKind
    detail: str
    subject: str = ""
    resolved: bool = False
    resolution: str = ""
    evidence_refs: tuple[str, ...] = ()

    def resolved_by(self, source: str, refs: tuple[str, ...] = ()) -> MissingRequirement:
        return MissingRequirement(
            kind=self.kind,
            detail=self.detail,
            subject=self.subject,
            resolved=True,
            resolution=source,
            evidence_refs=refs,
        )

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "detail": self.detail,
            "subject": self.subject,
            "resolved": self.resolved,
            "resolution": self.resolution,
            "evidence_refs": list(self.evidence_refs),
        }


# ---------------------------------------------------------------------------
# Scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class ScenarioEvent:
    """Evento parseado de un escenario crudo. Campos opcionales de verdad."""

    index: int
    raw_ref: str = ""
    record_type: str = ""
    action: str = ""
    sequence: str = ""
    timestamp: datetime | None = None
    effective_date: datetime | None = None
    discontinue_date: datetime | None = None
    entity_identifiers: tuple[str, ...] = ()
    parsed_fields: dict = field(default_factory=dict)
    schema_ref: str = ""
    confidence: float = 0.0
    parse_issues: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "raw_ref": self.raw_ref,
            "record_type": self.record_type,
            "action": self.action,
            "sequence": self.sequence,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "effective_date": (
                self.effective_date.isoformat() if self.effective_date else None
            ),
            "discontinue_date": (
                self.discontinue_date.isoformat() if self.discontinue_date else None
            ),
            "entity_identifiers": list(self.entity_identifiers),
            "parsed_fields": {
                key: (value.isoformat() if isinstance(value, datetime) else value)
                for key, value in self.parsed_fields.items()
            },
            "schema_ref": self.schema_ref,
            "confidence": self.confidence,
            "parse_issues": list(self.parse_issues),
        }


@dataclass(frozen=True, kw_only=True)
class StructuredScenario:
    """Escenario estructurado. `unparsed_items` nunca se descarta en silencio."""

    scenario_id: UUID = field(default_factory=uuid4)
    items: tuple[str, ...] = ()
    events: tuple[ScenarioEvent, ...] = ()
    entities: tuple[str, ...] = ()
    unparsed_items: tuple[str, ...] = ()
    schema_refs: tuple[str, ...] = ()
    unknown_fields: tuple[str, ...] = ()
    missing_requirements: tuple[MissingRequirement, ...] = ()
    parse_confidence: float = 0.0
    source_refs: tuple[str, ...] = ()

    @property
    def partial(self) -> bool:
        return bool(self.missing_requirements) or bool(self.unparsed_items)

    def to_dict(self) -> dict:
        return {
            "scenario_id": str(self.scenario_id),
            "items": len(self.items),
            "events": [event.to_dict() for event in self.events],
            "entities": list(self.entities),
            "unparsed_items": list(self.unparsed_items),
            "schema_refs": list(self.schema_refs),
            "unknown_fields": list(self.unknown_fields),
            "missing_requirements": [
                item.to_dict() for item in self.missing_requirements
            ],
            "parse_confidence": self.parse_confidence,
            "partial": self.partial,
            "source_refs": list(self.source_refs),
        }


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------


class FactStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    CONFIRMED = "CONFIRMED"
    CONTRADICTED = "CONTRADICTED"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, kw_only=True)
class Fact:
    """Hecho con su procedencia. `authority` conserva el nivel del tenant."""

    statement: str
    status: FactStatus = FactStatus.UNRESOLVED
    evidence_refs: tuple[str, ...] = ()
    authority: str | None = None
    confidence: float = 0.0
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    origin: str = ""
    id: UUID = field(default_factory=uuid4)

    @property
    def usable_as_premise(self) -> bool:
        """Solo un hecho confirmado o respaldado sostiene una premisa."""
        return self.status in (FactStatus.CONFIRMED, FactStatus.SUPPORTED)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "statement": self.statement,
            "status": self.status.value,
            "evidence_refs": list(self.evidence_refs),
            "authority": self.authority,
            "confidence": self.confidence,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
            "origin": self.origin,
        }


# ---------------------------------------------------------------------------
# Timeline: tres órdenes simultáneos
# ---------------------------------------------------------------------------


class TimelineOrder(StrEnum):
    ORIGINAL = "original"
    EFFECTIVE = "effective"
    LOGICAL = "logical"


@dataclass(frozen=True, kw_only=True)
class TimelineEvent:
    scenario_index: int
    position: int
    order_used: TimelineOrder
    criterion: str = ""
    event: ScenarioEvent | None = None

    def to_dict(self) -> dict:
        return {
            "scenario_index": self.scenario_index,
            "position": self.position,
            "order_used": self.order_used.value,
            "criterion": self.criterion,
        }


@dataclass(frozen=True, kw_only=True)
class Timeline:
    original_order: tuple[int, ...] = ()
    effective_order: tuple[int, ...] = ()
    logical_order: tuple[int, ...] = ()
    events: tuple[TimelineEvent, ...] = ()
    criteria: dict = field(default_factory=dict)
    complete: bool = False
    unknown_dates: tuple[int, ...] = ()

    def to_dict(self) -> dict:
        return {
            "original_order": list(self.original_order),
            "effective_order": list(self.effective_order),
            "logical_order": list(self.logical_order),
            "events": [item.to_dict() for item in self.events],
            "criteria": dict(self.criteria),
            "complete": self.complete,
            "unknown_dates": list(self.unknown_dates),
        }


# ---------------------------------------------------------------------------
# State transitions y cadena
# ---------------------------------------------------------------------------


class TransitionStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    SUPPORTED = "SUPPORTED"
    UNRESOLVED = "UNRESOLVED"
    CONTRADICTED = "CONTRADICTED"


UNKNOWN_STATE = "UNKNOWN"


@dataclass(frozen=True, kw_only=True)
class TransitionLink:
    """Un eslabón de la cadena: de un valor de secuencia al siguiente."""

    from_value: str
    to_value: str
    event_ref: str = ""
    rule_refs: tuple[str, ...] = ()
    confidence: float = 0.0
    status: TransitionStatus = TransitionStatus.UNRESOLVED

    def to_dict(self) -> dict:
        return {
            "from": self.from_value,
            "to": self.to_value,
            "event_ref": self.event_ref,
            "rule_refs": list(self.rule_refs),
            "confidence": self.confidence,
            "status": self.status.value,
        }


@dataclass(frozen=True, kw_only=True)
class StateTransition:
    subject: str
    before: str = UNKNOWN_STATE
    event_ref: str = ""
    after: str = UNKNOWN_STATE
    rule_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    status: TransitionStatus = TransitionStatus.UNRESOLVED
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "subject": self.subject,
            "before": self.before,
            "event_ref": self.event_ref,
            "after": self.after,
            "rule_refs": list(self.rule_refs),
            "evidence_refs": list(self.evidence_refs),
            "status": self.status.value,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, kw_only=True)
class StateTransitionSet:
    subject: str = ""
    transitions: tuple[StateTransition, ...] = ()
    chain: tuple[TransitionLink, ...] = ()
    gaps: tuple[str, ...] = ()
    resolved: bool = False

    @property
    def confirmed(self) -> int:
        return sum(
            1 for item in self.transitions if item.status is TransitionStatus.CONFIRMED
        )

    @property
    def unresolved(self) -> int:
        return sum(
            1 for item in self.transitions if item.status is TransitionStatus.UNRESOLVED
        )

    def to_dict(self) -> dict:
        return {
            "subject": self.subject,
            "transitions": [item.to_dict() for item in self.transitions],
            "chain": [item.to_dict() for item in self.chain],
            "gaps": list(self.gaps),
            "resolved": self.resolved,
            "confirmed": self.confirmed,
            "unresolved": self.unresolved,
            "chain_text": " -> ".join(
                [self.chain[0].from_value] + [link.to_value for link in self.chain]
            )
            if self.chain
            else "",
        }


# ---------------------------------------------------------------------------
# Hipótesis
# ---------------------------------------------------------------------------


class HypothesisOrigin(StrEnum):
    USER = "USER"
    RULE = "RULE"
    COMPANY_GRAPH = "COMPANY_GRAPH"
    MEMORY = "MEMORY"
    LLM = "LLM"


class HypothesisVerdict(StrEnum):
    SUPPORTED = "SUPPORTED"
    REJECTED = "REJECTED"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, kw_only=True)
class Hypothesis:
    statement: str
    origin: HypothesisOrigin = HypothesisOrigin.USER
    supporting_fact_ids: tuple[UUID, ...] = ()
    contradicting_fact_ids: tuple[UUID, ...] = ()
    missing_requirement_ids: tuple[str, ...] = ()
    verdict: HypothesisVerdict = HypothesisVerdict.UNRESOLVED
    rationale: str = ""
    id: UUID = field(default_factory=uuid4)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "statement": self.statement,
            "origin": self.origin.value,
            "supporting_fact_ids": [str(item) for item in self.supporting_fact_ids],
            "contradicting_fact_ids": [
                str(item) for item in self.contradicting_fact_ids
            ],
            "missing_requirement_ids": list(self.missing_requirement_ids),
            "verdict": self.verdict.value,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, kw_only=True)
class HypothesisSet:
    hypotheses: tuple[Hypothesis, ...] = ()
    user_hypothesis_id: UUID | None = None
    max_hypotheses: int = 4

    @property
    def supported(self) -> tuple[Hypothesis, ...]:
        return tuple(
            item
            for item in self.hypotheses
            if item.verdict is HypothesisVerdict.SUPPORTED
        )

    @property
    def rejected(self) -> tuple[Hypothesis, ...]:
        return tuple(
            item
            for item in self.hypotheses
            if item.verdict is HypothesisVerdict.REJECTED
        )

    @property
    def unresolved(self) -> tuple[Hypothesis, ...]:
        return tuple(
            item
            for item in self.hypotheses
            if item.verdict is HypothesisVerdict.UNRESOLVED
        )

    def by_id(self, hypothesis_id: UUID | None) -> Hypothesis | None:
        if hypothesis_id is None:
            return None
        return next(
            (item for item in self.hypotheses if item.id == hypothesis_id), None
        )

    def to_dict(self) -> dict:
        return {
            "hypotheses": [item.to_dict() for item in self.hypotheses],
            "user_hypothesis_id": (
                str(self.user_hypothesis_id) if self.user_hypothesis_id else None
            ),
            "supported": len(self.supported),
            "rejected": len(self.rejected),
            "unresolved": len(self.unresolved),
        }


# ---------------------------------------------------------------------------
# Verificación de inferencias (premisas -> conclusión)
# ---------------------------------------------------------------------------


class InferenceVerdict(StrEnum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, kw_only=True)
class InferenceRecord:
    """Premisas y conclusión con su veredicto. Sin razonamiento privado."""

    conclusion: str
    premise_refs: tuple[UUID, ...] = ()
    rule_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    verdict: InferenceVerdict = InferenceVerdict.UNRESOLVED
    status: str = "open"
    rationale: str = ""
    id: UUID = field(default_factory=uuid4)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "conclusion": self.conclusion,
            "premise_refs": [str(item) for item in self.premise_refs],
            "rule_refs": list(self.rule_refs),
            "evidence_refs": list(self.evidence_refs),
            "verdict": self.verdict.value,
            "status": self.status,
            "rationale": self.rationale,
        }


# ---------------------------------------------------------------------------
# Plan y workspace
# ---------------------------------------------------------------------------


class ReasoningStepStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"
    DATA_MISSING = "DATA_MISSING"
    CONTEXT_MISSING = "CONTEXT_MISSING"


@dataclass(kw_only=True)
class ReasoningStep:
    name: str
    operation: str
    status: ReasoningStepStatus = ReasoningStepStatus.PENDING
    detail: dict = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "operation": self.operation,
            "status": self.status.value,
            "detail": dict(self.detail),
            "error": self.error,
        }


class PlanStatus(StrEnum):
    DRAFT = "DRAFT"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    BLOCKED = "BLOCKED"


@dataclass(kw_only=True)
class ReasoningPlan:
    """Plan explícito. Las operaciones dependen de la forma (§13), no de una lista fija."""

    question: str
    reasoning_shape: ReasoningShape
    question_to_prove: str = ""
    required_facts: tuple[str, ...] = ()
    required_rules: tuple[str, ...] = ()
    required_schemas: tuple[str, ...] = ()
    required_entities: tuple[str, ...] = ()
    required_relationships: tuple[str, ...] = ()
    requires_scenario_parse: bool = False
    requires_timeline: bool = False
    requires_state_reconstruction: bool = False
    requires_graph_traversal: bool = False
    requires_hypothesis_testing: bool = False
    completion_conditions: tuple[str, ...] = ()
    steps: list[ReasoningStep] = field(default_factory=list)
    budgets: ResearchBudgets = field(default_factory=ResearchBudgets)
    status: PlanStatus = PlanStatus.DRAFT
    id: UUID = field(default_factory=uuid4)

    def step(self, operation: str) -> ReasoningStep | None:
        return next((item for item in self.steps if item.operation == operation), None)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "question": self.question,
            "reasoning_shape": self.reasoning_shape.value,
            "question_to_prove": self.question_to_prove,
            "required_facts": list(self.required_facts),
            "required_rules": list(self.required_rules),
            "required_schemas": list(self.required_schemas),
            "required_entities": list(self.required_entities),
            "required_relationships": list(self.required_relationships),
            "requires_scenario_parse": self.requires_scenario_parse,
            "requires_timeline": self.requires_timeline,
            "requires_state_reconstruction": self.requires_state_reconstruction,
            "requires_graph_traversal": self.requires_graph_traversal,
            "requires_hypothesis_testing": self.requires_hypothesis_testing,
            "completion_conditions": list(self.completion_conditions),
            "steps": [item.to_dict() for item in self.steps],
            "budgets": self.budgets.to_dict(),
            "status": self.status.value,
        }


@dataclass(kw_only=True)
class ReasoningWorkspace:
    """Workspace por request. Estructura y referencias, nunca razonamiento privado."""

    question: str
    reasoning_shape: ReasoningShape
    facts: list[Fact] = field(default_factory=list)
    rules: list[Fact] = field(default_factory=list)
    scenario: StructuredScenario | None = None
    timeline: Timeline | None = None
    transitions: StateTransitionSet | None = None
    hypotheses: HypothesisSet | None = None
    inferences: list[InferenceRecord] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    graph_facts: list[Fact] = field(default_factory=list)
    source_authority: dict = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)
    company_context: dict = field(default_factory=dict)
    retrieval_rounds: int = 0
    id: UUID = field(default_factory=uuid4)

    def add_fact(self, fact: Fact) -> Fact:
        self.facts.append(fact)
        return fact

    def fact(self, fact_id: UUID) -> Fact | None:
        return next((item for item in self.facts if item.id == fact_id), None)

    @property
    def confirmed_facts(self) -> tuple[Fact, ...]:
        return tuple(item for item in self.facts if item.usable_as_premise)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "question": self.question,
            "reasoning_shape": self.reasoning_shape.value,
            "facts": [item.to_dict() for item in self.facts],
            "rules": [item.to_dict() for item in self.rules],
            "scenario": self.scenario.to_dict() if self.scenario else None,
            "timeline": self.timeline.to_dict() if self.timeline else None,
            "transitions": self.transitions.to_dict() if self.transitions else None,
            "hypotheses": self.hypotheses.to_dict() if self.hypotheses else None,
            "inferences": [item.to_dict() for item in self.inferences],
            "unknowns": list(self.unknowns),
            "contradictions": list(self.contradictions),
            "graph_facts": [item.to_dict() for item in self.graph_facts],
            "source_authority": dict(self.source_authority),
            "evidence_refs": list(self.evidence_refs),
            "retrieval_rounds": self.retrieval_rounds,
        }


# ---------------------------------------------------------------------------
# Gate de completitud y resultado
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class CompletionCheck:
    name: str
    satisfied: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "satisfied": self.satisfied, "detail": self.detail}


@dataclass(frozen=True, kw_only=True)
class AnalysisCompletion:
    """Evaluación determinística: ¿se puede concluir o hay que abstenerse?"""

    complete: bool
    checks: tuple[CompletionCheck, ...] = ()
    blockers: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "complete": self.complete,
            "checks": [item.to_dict() for item in self.checks],
            "blockers": list(self.blockers),
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, kw_only=True)
class AnswerBlueprint:
    """Respuesta estructurada para casos complejos (§44)."""

    conclusion: str = ""
    observed_flow: str = ""
    evidence_summary: tuple[dict, ...] = ()
    hypothesis_summary: tuple[dict, ...] = ()
    limitations: tuple[str, ...] = ()
    confidence: str = "insufficient"
    section_names: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "conclusion": self.conclusion,
            "observed_flow": self.observed_flow,
            "evidence_summary": [dict(item) for item in self.evidence_summary],
            "hypothesis_summary": [dict(item) for item in self.hypothesis_summary],
            "limitations": list(self.limitations),
            "confidence": self.confidence,
            "sections": list(self.section_names),
        }


@dataclass(frozen=True, kw_only=True)
class ReasoningOutcome:
    """Salida del motor. `activated=False` significa fast path (sin costo extra)."""

    activated: bool
    classification: ReasoningClassification
    plan: ReasoningPlan | None = None
    workspace: ReasoningWorkspace | None = None
    completion: AnalysisCompletion | None = None
    blueprint: AnswerBlueprint | None = None
    reason_codes: tuple[str, ...] = ()
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    abstain: bool = False

    def to_dict(self) -> dict:
        return {
            "activated": self.activated,
            "classification": self.classification.to_dict(),
            "plan": self.plan.to_dict() if self.plan else None,
            "workspace": self.workspace.to_dict() if self.workspace else None,
            "completion": self.completion.to_dict() if self.completion else None,
            "blueprint": self.blueprint.to_dict() if self.blueprint else None,
            "reason_codes": list(self.reason_codes),
            "latency_ms": round(self.latency_ms, 2),
            "cost_usd": round(self.cost_usd, 6),
            "abstain": self.abstain,
        }

    def public_trace(self) -> dict:
        """Traza operacional mostrable (§46). Nunca razonamiento privado."""
        if not self.activated or self.workspace is None:
            return {
                "activated": False,
                "shape": self.classification.shape.value,
                "reason": "simple_lookup_fast_path",
            }
        workspace = self.workspace
        scenario = workspace.scenario
        timeline = workspace.timeline
        transitions = workspace.transitions
        hypotheses = workspace.hypotheses
        return {
            "activated": True,
            "shape": self.classification.shape.value,
            "scenario_events": len(scenario.events) if scenario else 0,
            "schemas_resolved": len(scenario.schema_refs) if scenario else 0,
            "schemas_missing": len(scenario.missing_requirements) if scenario else 0,
            "timeline_events": len(timeline.events) if timeline else 0,
            "timeline_complete": bool(timeline.complete) if timeline else False,
            "transitions_confirmed": transitions.confirmed if transitions else 0,
            "transitions_unresolved": transitions.unresolved if transitions else 0,
            "hypotheses_tested": len(hypotheses.hypotheses) if hypotheses else 0,
            "hypotheses_supported": len(hypotheses.supported) if hypotheses else 0,
            "hypotheses_rejected": len(hypotheses.rejected) if hypotheses else 0,
            "inferences": len(workspace.inferences),
            "critical_unknowns": len(workspace.unknowns),
            "analysis_complete": bool(self.completion.complete) if self.completion else False,
            "retrieval_rounds": workspace.retrieval_rounds,
        }


__all__ = [
    "AnalysisCompletion",
    "AnswerBlueprint",
    "COMPLEX_SHAPES",
    "CompletionCheck",
    "Fact",
    "FactStatus",
    "Hypothesis",
    "HypothesisOrigin",
    "HypothesisSet",
    "HypothesisVerdict",
    "InferenceRecord",
    "InferenceVerdict",
    "MissingRequirement",
    "PlanStatus",
    "ReasoningClassification",
    "ReasoningClassificationSource",
    "ReasoningMode",
    "ReasoningOutcome",
    "ReasoningPlan",
    "ReasoningShape",
    "ReasoningStep",
    "ReasoningStepStatus",
    "ReasoningWorkspace",
    "RequirementKind",
    "ScenarioEvent",
    "StateTransition",
    "StateTransitionSet",
    "StructuredScenario",
    "Timeline",
    "TimelineEvent",
    "TimelineOrder",
    "TransitionLink",
    "TransitionStatus",
    "UNKNOWN_STATE",
]
