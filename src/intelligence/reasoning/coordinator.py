# =============================================================================
# Evidence Reasoning Engine (§2/§11/§12/§13/§18-§21/§39/§44/§45)
# =============================================================================
# Coordina el razonamiento sobre hechos. NO es un segundo Cognitive OS ni un
# motor paralelo: reutiliza lo que ya existe.
#
#   - AnalyticalReasoningEngine se usa como AnalyticalStrategy (causal/diagnóstico).
#   - CompanyContextCompiler aporta conceptos, mappings, procesos, autoridad y
#     memoria (Company Intelligence no se redescubre).
#   - CompanyAskService responde las formas de grafo (no se duplica el ruteo).
#   - ResearchBudgets limita pasos, retrieval y costo.
#   - AnswerabilityGate recibe las señales nuevas.
#
# Lo único nuevo es lo que faltaba: forma de razonamiento, plan, escenario,
# timeline, transiciones, hipótesis, verificación de inferencias y el gate de
# completitud.
# =============================================================================
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable, Sequence
from uuid import UUID

from src.core.domain.reasoning import (
    AnalysisCompletion,
    AnswerBlueprint,
    Fact,
    FactStatus,
    HypothesisVerdict,
    MissingRequirement,
    PlanStatus,
    ReasoningClassification,
    ReasoningMode,
    ReasoningOutcome,
    ReasoningPlan,
    ReasoningShape,
    ReasoningStep,
    ReasoningStepStatus,
    ReasoningWorkspace,
)
from src.core.domain.research import ResearchBudgets
from src.infrastructure.observability.logging_config import get_logger
from src.intelligence.loop_guard import LoopGuard
from src.intelligence.reasoning import metrics as reasoning_metrics
from src.intelligence.reasoning.assessment import (
    AnalysisCompletionGate,
    HypothesisEngine,
    InferenceVerifier,
)
from src.intelligence.reasoning.classifier import ReasoningClassifier
from src.intelligence.reasoning.scenario import (
    ScenarioParser,
    schema_from_facts,
)
from src.intelligence.reasoning.sequence import (
    StateTransitionAnalyzer,
    TimelineBuilder,
    chain_values,
    find_sequence_gaps,
)

logger = get_logger(__name__)

#: Operaciones por forma (§13). Ya no hay una lista fija de pasos genéricos.
SHAPE_OPERATIONS: dict[ReasoningShape, tuple[str, ...]] = {
    ReasoningShape.SIMPLE_LOOKUP: (),
    ReasoningShape.MULTI_EVIDENCE: (
        "collect_evidence",
        "weigh_authority",
        "verify_conclusion",
    ),
    ReasoningShape.STATE_TRANSITION: (
        "resolve_schema",
        "parse_events",
        "resolve_rules",
        "build_timeline",
        "build_transitions",
        "test_hypotheses",
        "verify_conclusion",
    ),
    ReasoningShape.TEMPORAL_SEQUENCE: (
        "resolve_schema",
        "parse_events",
        "resolve_rules",
        "build_timeline",
        "test_hypotheses",
        "verify_conclusion",
    ),
    ReasoningShape.CONSISTENCY_CHECK: (
        "collect_evidence",
        "resolve_rules",
        "detect_contradictions",
        "test_hypotheses",
        "verify_conclusion",
    ),
    ReasoningShape.DIAGNOSTIC: (
        "collect_evidence",
        "resolve_rules",
        "find_drivers",
        "inspect_events",
        "test_hypotheses",
        "verify_conclusion",
    ),
    ReasoningShape.HYPOTHESIS_TEST: (
        "resolve_rules",
        "collect_evidence",
        "test_hypotheses",
        "verify_conclusion",
    ),
    ReasoningShape.CAUSAL_ANALYSIS: (
        "calculate_variation",
        "decompose_dimensions",
        "find_drivers",
        "inspect_events",
        "test_causal_support",
    ),
    ReasoningShape.COMPARATIVE_REASONING: (
        "collect_evidence",
        "compare_dimensions",
        "verify_conclusion",
    ),
    ReasoningShape.GRAPH_REASONING: (
        "resolve_entity",
        "traverse_dependencies",
        "evaluate_path_confidence",
        "collect_authority",
        "summarize_impact",
    ),
}

#: Condiciones de completitud por forma (§11).
SHAPE_COMPLETION: dict[ReasoningShape, tuple[str, ...]] = {
    ReasoningShape.STATE_TRANSITION: (
        "schema_resolved_or_declared_missing",
        "events_parsed",
        "transitions_built",
        "user_hypothesis_evaluated",
    ),
    ReasoningShape.TEMPORAL_SEQUENCE: (
        "events_parsed",
        "timeline_ordered_with_criterion",
        "user_hypothesis_evaluated",
    ),
    ReasoningShape.CONSISTENCY_CHECK: (
        "evidence_collected",
        "contradictions_registered",
    ),
    ReasoningShape.DIAGNOSTIC: ("evidence_collected", "hypotheses_evaluated"),
    ReasoningShape.HYPOTHESIS_TEST: ("hypotheses_evaluated",),
    ReasoningShape.GRAPH_REASONING: ("graph_facts_collected", "paths_evaluated"),
    ReasoningShape.MULTI_EVIDENCE: ("evidence_collected", "authority_weighed"),
    ReasoningShape.CAUSAL_ANALYSIS: ("evidence_collected", "drivers_ranked"),
    ReasoningShape.COMPARATIVE_REASONING: ("evidence_collected",),
}


# ---------------------------------------------------------------------------
# Estrategias
# ---------------------------------------------------------------------------


@dataclass
class ReasoningStrategy:
    """Base de estrategia. Sólo declara si aplica y ejecuta operaciones."""

    name: str = "base"
    shapes: tuple[ReasoningShape, ...] = ()

    def applies(self, shape: ReasoningShape) -> bool:
        return shape in self.shapes

    def plan_operations(self, shape: ReasoningShape, question: str) -> tuple[str, ...]:
        return SHAPE_OPERATIONS.get(shape, ())


@dataclass
class AnalyticalStrategy(ReasoningStrategy):
    """Reutiliza AnalyticalReasoningEngine para análisis causal/diagnóstico.

    No duplica el motor analítico: le pide su Research Plan y lo integra como
    sub-operaciones de la forma correspondiente.
    """

    analytical: object | None = None
    name: str = "analytical"
    shapes: tuple[ReasoningShape, ...] = (
        ReasoningShape.CAUSAL_ANALYSIS,
        ReasoningShape.DIAGNOSTIC,
    )

    def research_plan(self, question: str):
        if self.analytical is None:
            return None
        builder = getattr(self.analytical, "build_research_plan", None)
        if builder is None:
            return None
        try:
            return builder(question)
        except Exception as exc:  # noqa: BLE001 - la estrategia nunca rompe el plan
            logger.warning("analytical strategy failed", error=str(exc)[:150])
            return None


@dataclass
class GraphReasoningStrategy(ReasoningStrategy):
    """Formas de grafo: delega en CompanyAskService (no se duplica el ruteo)."""

    ask: Callable[..., Awaitable[object]] | None = None
    name: str = "graph"
    shapes: tuple[ReasoningShape, ...] = (ReasoningShape.GRAPH_REASONING,)


# ---------------------------------------------------------------------------
# Motor
# ---------------------------------------------------------------------------

KnowledgeSearch = Callable[..., Awaitable[list[dict]]]
CompanyContextProvider = Callable[..., Awaitable[object]]


@dataclass
class EvidenceReasoningEngine:
    """Coordinador del razonamiento sobre hechos."""

    budgets: ResearchBudgets = field(default_factory=ResearchBudgets)
    loop_guard: LoopGuard = field(default_factory=LoopGuard)
    classifier: ReasoningClassifier = field(default_factory=ReasoningClassifier)
    parser: ScenarioParser = field(default_factory=ScenarioParser)
    timeline_builder: TimelineBuilder = field(default_factory=TimelineBuilder)
    analyzer: StateTransitionAnalyzer = field(default_factory=StateTransitionAnalyzer)
    hypothesis_engine: HypothesisEngine = field(default_factory=HypothesisEngine)
    verifier: InferenceVerifier = field(default_factory=InferenceVerifier)
    gate: AnalysisCompletionGate = field(default_factory=AnalysisCompletionGate)
    strategies: tuple[ReasoningStrategy, ...] = ()
    knowledge_search: KnowledgeSearch | None = None
    company_context_provider: CompanyContextProvider | None = None
    discovery_emitter: Callable[..., Awaitable[None]] | None = None
    authority_resolver: Callable[..., Awaitable[dict]] | None = None
    memory_recorder: Callable[..., Awaitable[None]] | None = None
    max_requirements: int = 6

    # ------------------------------------------------------------------
    async def reason(
        self,
        question: str,
        *,
        organization_id: UUID | None = None,
        intent: str = "general",
        company_context: dict | None = None,
        scenario_text: str | None = None,
        as_of: datetime | None = None,
        mode: ReasoningMode = ReasoningMode.ON,
        agent_id: UUID | None = None,
        memory_hints: tuple[str, ...] = (),
    ) -> ReasoningOutcome:
        """Razona sobre la pregunta y, si hay, sobre el escenario crudo.

        `scenario_text` permite separar el escenario del texto de la pregunta
        (registros pegados en el mensaje, salida de una tool, contexto de
        workflow). Si no se pasa, se parsea la pregunta completa.
        """
        started = time.monotonic()
        classification = await self.classifier.classify(question, intent=intent)
        reasoning_metrics.record_classification(classification.shape.value)

        if not classification.is_complex:
            # Fast path: sin plan, sin workspace, sin retrieval extra (§10).
            return ReasoningOutcome(
                activated=False,
                classification=classification,
                latency_ms=(time.monotonic() - started) * 1000,
            )

        reasoning_metrics.record_activation(classification.shape.value, mode.value)
        compiled = company_context
        if compiled is None and self.company_context_provider is not None and organization_id:
            compiled = await self._compile_company_context(
                organization_id, question, agent_id=agent_id, as_of=as_of
            )
        context_dict = _as_dict(compiled)
        if context_dict:
            reasoning_metrics.record_company_context(
                {
                    "concepts": len(context_dict.get("concepts") or ()),
                    "mappings": len(context_dict.get("mappings") or ()),
                    "processes": len(context_dict.get("processes") or ()),
                    "systems": len(context_dict.get("systems") or ()),
                    "memories": len(context_dict.get("memories") or ()),
                }
            )

        plan = self.build_plan(question, classification)
        workspace = ReasoningWorkspace(
            question=question,
            reasoning_shape=classification.shape,
            company_context=context_dict,
        )
        await self._resolve_authority(workspace, organization_id)
        self._collect_graph_facts(workspace, context_dict)

        # La adquisición corre si hay buscador de evidencia o una organización
        # que consultar: sin organización, igual se razona con lo disponible.
        if self.knowledge_search is not None or organization_id is not None:
            await self._acquire_evidence(
                plan, workspace, organization_id=organization_id, question=question
            )

        # Los schemas se registran ANTES de parsear: si no hay layout conocido,
        # el parser declara el requisito en lugar de inventar posiciones.
        for schema in schema_from_facts(workspace.rules):
            self.parser.register_schema(schema)
        raw_scenario = scenario_text if scenario_text is not None else question
        scenario = self.parser.parse(
            raw_scenario,
            company_context=context_dict,
            evidence_texts=tuple(workspace.evidence_refs[:5]),
        )
        workspace.scenario = scenario
        reasoning_metrics.record_scenario(
            organization_id,
            len(scenario.events),
            (scenario.missing_requirements[0].kind.value if scenario.missing_requirements else ""),
        )
        reasoning_metrics.record_requirements(scenario.missing_requirements)

        if plan.requires_timeline:
            workspace.timeline = self.timeline_builder.build(scenario)
        if plan.requires_state_reconstruction:
            workspace.transitions = self.analyzer.analyze(
                scenario=scenario,
                timeline=workspace.timeline,
                rules=workspace.rules,
                facts=workspace.facts,
            )
            reasoning_metrics.record_transitions(workspace.transitions)
            self._register_gaps(workspace)
        if plan.requires_hypothesis_testing:
            workspace.hypotheses = await self.hypothesis_engine.evaluate(
                question=question,
                workspace=workspace,
                rules=workspace.rules,
                memory_hints=memory_hints,
            )
            reasoning_metrics.record_hypotheses(workspace.hypotheses)

        self._verify_conclusion(plan, workspace)
        completion = self.gate.evaluate(plan=plan, workspace=workspace)
        reasoning_metrics.record_completion(completion.complete)
        plan.status = (
            PlanStatus.COMPLETE if completion.complete else PlanStatus.INCOMPLETE
        )

        await self._maybe_emit_discovery(organization_id, workspace)
        blueprint = self.build_blueprint(
            question=question,
            workspace=workspace,
            completion=completion,
            classification=classification,
        )
        elapsed = time.monotonic() - started
        reasoning_metrics.record_run(
            shape=classification.shape.value,
            seconds=elapsed,
            cost_usd=0.0,
            retrieval_rounds=workspace.retrieval_rounds,
        )
        await self._record_memory(
            organization_id,
            workspace=workspace,
            completion=completion,
            classification=classification,
            latency_ms=elapsed * 1000,
        )
        return ReasoningOutcome(
            activated=True,
            classification=classification,
            plan=plan,
            workspace=workspace,
            completion=completion,
            blueprint=blueprint,
            reason_codes=completion.reason_codes,
            latency_ms=elapsed * 1000,
            abstain=not completion.complete,
        )

    # ------------------------------------------------------------------
    def build_plan(
        self, question: str, classification: ReasoningClassification
    ) -> ReasoningPlan:
        """Plan por forma. `question_to_prove` es operacional, no una conclusión."""
        shape = classification.shape
        operations = SHAPE_OPERATIONS.get(shape, ())
        strategy = next(
            (item for item in self.strategies if item.applies(shape)), None
        )
        if strategy is not None:
            operations = strategy.plan_operations(shape, question) or operations
        steps = [
            ReasoningStep(name=operation.replace("_", " "), operation=operation)
            for operation in operations[: self.budgets.max_steps]
        ]
        plan = ReasoningPlan(
            question=question,
            reasoning_shape=shape,
            question_to_prove=question_to_prove(question, shape),
            requires_scenario_parse=parse_step_required(shape),
            requires_timeline=shape
            in (
                ReasoningShape.STATE_TRANSITION,
                ReasoningShape.TEMPORAL_SEQUENCE,
            ),
            requires_state_reconstruction=shape is ReasoningShape.STATE_TRANSITION,
            requires_graph_traversal=shape is ReasoningShape.GRAPH_REASONING,
            requires_hypothesis_testing=shape
            in (
                ReasoningShape.STATE_TRANSITION,
                ReasoningShape.TEMPORAL_SEQUENCE,
                ReasoningShape.DIAGNOSTIC,
                ReasoningShape.CONSISTENCY_CHECK,
                ReasoningShape.HYPOTHESIS_TEST,
            ),
            completion_conditions=SHAPE_COMPLETION.get(shape, ()),
            steps=steps,
            budgets=self.budgets,
        )
        return plan

    # ------------------------------------------------------------------
    async def _compile_company_context(
        self,
        organization_id: UUID,
        question: str,
        *,
        agent_id: UUID | None,
        as_of: datetime | None,
    ):
        provider = self.company_context_provider
        if provider is None:
            return None
        try:
            return await provider(
                organization_id, question, agent_id=agent_id, as_of=as_of
            )
        except Exception as exc:  # noqa: BLE001 - sin contexto se puede razonar igual
            logger.warning("reasoning company context failed", error=str(exc)[:150])
            return None

    async def _resolve_authority(
        self, workspace: ReasoningWorkspace, organization_id: UUID | None
    ) -> None:
        """§7: la autoridad configurada del tenant entra al workspace."""
        if self.authority_resolver is None or organization_id is None:
            return
        try:
            workspace.source_authority = dict(
                await self.authority_resolver(organization_id) or {}
            )
        except Exception as exc:  # noqa: BLE001 - sin autoridad se declara conflicto
            logger.warning("reasoning authority failed", error=str(exc)[:150])

    def _collect_graph_facts(
        self, workspace: ReasoningWorkspace, company_context: dict | None
    ) -> None:
        """§21: las relaciones del grafo son evidencia con su status intacto."""
        if not company_context:
            return
        for item in company_context.get("mappings") or ():
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "").lower()
            fact_status = (
                FactStatus.CONFIRMED
                if status in ("confirmed", "auto_confirmed")
                else FactStatus.SUPPORTED
                if status == "supported"
                else FactStatus.UNRESOLVED
            )
            workspace.graph_facts.append(
                Fact(
                    statement=(
                        f"{item.get('concept', '')} se representa en "
                        f"{item.get('field', '')}"
                    ),
                    status=fact_status,
                    evidence_refs=(str(item.get("id") or ""),),
                    authority=item.get("authority_level"),
                    confidence=float(item.get("confidence") or 0.0),
                    origin="company_graph",
                )
            )
        for item in company_context.get("dependencies") or ():
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "").lower()
            workspace.graph_facts.append(
                Fact(
                    statement=(
                        f"{item.get('from', '')} {item.get('type', '')} "
                        f"{item.get('to', '')}"
                    ),
                    status=(
                        FactStatus.CONFIRMED
                        if status in ("confirmed", "auto_confirmed")
                        else FactStatus.UNRESOLVED
                    ),
                    origin="company_graph",
                )
            )

    def _register_gaps(self, workspace: ReasoningWorkspace) -> None:
        transitions = workspace.transitions
        if transitions is None:
            return
        for previous, current in find_sequence_gaps(transitions):
            workspace.unknowns.append(
                f"Salto de numeración entre {previous} y {current}"
            )

    async def _acquire_evidence(
        self,
        plan: ReasoningPlan,
        workspace: ReasoningWorkspace,
        *,
        organization_id: UUID,
        question: str,
    ) -> None:
        """§20: adquisición por requisito, no retrieval genérico repetido."""
        requirements = self._requirements_for(plan, workspace)
        step = plan.step("collect_evidence") or plan.step("resolve_rules")
        search = self.knowledge_search
        if search is None:
            for requirement in requirements:
                reasoning_metrics.record_requirements([requirement])
            return
        resolved = 0
        for requirement in requirements:
            if workspace.retrieval_rounds >= plan.budgets.max_retrieval_calls:
                break
            query = requirement.detail or requirement.subject
            fingerprint = _fingerprint(query)
            if not self.loop_guard.check(fingerprint, observation_context=query[:80]):
                if step is not None:
                    step.status = ReasoningStepStatus.BLOCKED
                    step.error = "loop_guard"
                break
            try:
                hits = await search(organization_id, query, limit=4)
            except Exception as exc:  # noqa: BLE001 - la falta de evidencia no rompe
                logger.warning("reasoning evidence failed", error=str(exc)[:150])
                hits = []
            workspace.retrieval_rounds += 1
            if hits:
                resolved += 1
                workspace.evidence_refs.extend(
                    str(hit.get("document_id") or hit.get("ref") or "")
                    for hit in hits[:2]
                )
                # Se incorporan VARIOS hits, no sólo el primero: si no, una
                # fuente autoritativa posterior nunca llega al razonamiento.
                for hit in hits[:2]:
                    statement = _evidence_statement([hit])
                    if any(
                        fact.statement == statement for fact in workspace.rules
                    ):
                        continue
                    workspace.rules.append(
                        Fact(
                            statement=statement,
                            status=FactStatus.SUPPORTED,
                            evidence_refs=(
                                str(hit.get("document_id") or ""),
                            ),
                            authority=_authority_for_hit(workspace, hit),
                            confidence=float(hit.get("score") or 0.5),
                            origin="retrieval",
                        )
                    )
        if step is not None:
            step.detail = {"requirements": len(requirements), "resolved": resolved}
            step.status = (
                ReasoningStepStatus.DONE
                if resolved
                else ReasoningStepStatus.CONTEXT_MISSING
            )

    def _requirements_for(
        self,
        plan: ReasoningPlan,
        workspace: ReasoningWorkspace,
    ) -> list[MissingRequirement]:
        from src.core.domain.reasoning import RequirementKind

        requirements: list[MissingRequirement] = []
        if plan.reasoning_shape in (
            ReasoningShape.STATE_TRANSITION,
            ReasoningShape.TEMPORAL_SEQUENCE,
        ):
            requirements.append(
                MissingRequirement(
                    kind=RequirementKind.RULE_REQUIRED,
                    detail="reglas que gobiernan la secuencia y su renumeración",
                    subject="sequence rules",
                )
            )
            requirements.append(
                MissingRequirement(
                    kind=RequirementKind.ACTION_CODE_SEMANTICS_REQUIRED,
                    detail="semántica de los códigos de acción de los registros",
                    subject="action codes",
                )
            )
        elif plan.reasoning_shape is ReasoningShape.GRAPH_REASONING:
            requirements.append(
                MissingRequirement(
                    kind=RequirementKind.AUTHORITY_REQUIRED,
                    detail="fuente autoritativa de las dependencias afectadas",
                    subject="authority",
                )
            )
        else:
            requirements.append(
                MissingRequirement(
                    kind=RequirementKind.RULE_REQUIRED,
                    detail="reglas o políticas aplicables a la pregunta",
                    subject="rules",
                )
            )
        return requirements[: max(1, self.max_requirements)]

    def _verify_conclusion(
        self, plan: ReasoningPlan, workspace: ReasoningWorkspace
    ) -> None:
        """§29/§30: las premisas pueden ser ciertas y la conclusión no seguirse."""
        if not plan.requires_state_reconstruction and not plan.requires_hypothesis_testing:
            return
        hypotheses = workspace.hypotheses
        if hypotheses is None:
            return
        premise_pool = [fact for fact in workspace.rules if fact.usable_as_premise]
        premise_pool.extend(
            fact
            for fact in workspace.graph_facts
            if fact.status is FactStatus.CONFIRMED
        )
        for hypothesis in hypotheses.hypotheses:
            rule_refs = tuple(
                str(fact.id)
                for fact in workspace.rules
                if fact.usable_as_premise
            )
            workspace.inferences.append(
                self.verifier.verify(
                    conclusion=hypothesis.statement,
                    premises=premise_pool[:6],
                    rule_refs=rule_refs,
                )
            )
        reasoning_metrics.record_inferences(workspace.inferences)

    # ------------------------------------------------------------------
    async def _record_memory(
        self,
        organization_id: UUID | None,
        *,
        workspace: ReasoningWorkspace,
        completion: AnalysisCompletion,
        classification: ReasoningClassification,
        latency_ms: float,
    ) -> None:
        """§66: memoria operativa del razonamiento. Nunca chain-of-thought.

        Memoria dice qué aprendió Zent operando; no prueba hechos del dominio.
        """
        if self.memory_recorder is None or organization_id is None:
            return
        hypotheses = workspace.hypotheses
        payload = {
            "reasoning_shape": classification.shape.value,
            "analysis_complete": completion.complete,
            "outcome": "complete" if completion.complete else "abstained",
            "retrieval_rounds": workspace.retrieval_rounds,
            "hypotheses_tested": len(hypotheses.hypotheses) if hypotheses else 0,
            "company_context_used": bool(workspace.company_context),
            "memory_ids_used": sorted(
                str(item.get("id"))
                for item in (workspace.company_context.get("memories") or ())
                if isinstance(item, dict) and item.get("id")
            ),
            "cost_usd": 0.0,
            "latency_ms": round(latency_ms, 2),
        }
        try:
            await self.memory_recorder(organization_id, payload)
        except Exception as exc:  # noqa: BLE001 - la memoria nunca rompe el run
            logger.warning("reasoning memory event failed", error=str(exc)[:150])

    async def _maybe_emit_discovery(
        self, organization_id: UUID | None, workspace: ReasoningWorkspace
    ) -> None:
        """§41/§42: el runtime NO escribe en el grafo; emite candidatos."""
        if self.discovery_emitter is None or organization_id is None:
            return
        transitions = workspace.transitions
        if transitions is None or not transitions.transitions:
            return
        statement = "La renumeración reasigna secuencias existentes"
        if not any(statement.lower() in fact.statement.lower() for fact in workspace.rules):
            return
        try:
            await self.discovery_emitter(
                organization_id,
                subject=transitions.subject or "sequence",
                statement=statement,
                evidence_refs=tuple(workspace.evidence_refs[:3]),
            )
        except Exception as exc:  # noqa: BLE001 - nunca rompe el razonamiento
            logger.warning("reasoning discovery emit failed", error=str(exc)[:150])

    def build_blueprint(
        self,
        *,
        question: str,
        workspace: ReasoningWorkspace,
        completion: AnalysisCompletion,
        classification: ReasoningClassification,
    ) -> AnswerBlueprint:
        """§44/§45: respuesta estructurada, sin hedging vacío."""
        hypotheses = workspace.hypotheses
        user = hypotheses.by_id(hypotheses.user_hypothesis_id) if hypotheses else None
        transitions = workspace.transitions
        limitations = list(workspace.unknowns)
        sections: list[str] = []

        conclusion = ""
        if user is not None:
            if user.verdict is HypothesisVerdict.REJECTED:
                conclusion = (
                    f"No. La hipótesis de que {user.statement.lower()} no está "
                    f"respaldada: {user.rationale}."
                )
            elif user.verdict is HypothesisVerdict.SUPPORTED:
                conclusion = (
                    f"Sí. Según la secuencia reconstruida, {user.statement.lower()} "
                    f"({user.rationale})."
                )
            else:
                missing = ", ".join(user.missing_requirement_ids) or "evidencia crítica"
                conclusion = (
                    "No puedo determinarlo todavía. Falta verificar: " + missing + "."
                )
        elif transitions and transitions.transitions:
            conclusion = (
                "La secuencia reconstruida tiene "
                f"{len(transitions.transitions)} transiciones "
                f"({transitions.confirmed} confirmadas, {transitions.unresolved} sin resolver)."
            )
        else:
            conclusion = (
                "No hay material suficiente para concluir sobre el escenario."
            )

        flow = ""
        if transitions and transitions.chain:
            flow = " -> ".join(chain_values(transitions))
        observed_flow = (
            f"Secuencia observada: {flow}" if flow else ""
        )

        evidence_summary = tuple(
            {
                "statement": fact.statement[:200],
                "status": fact.status.value,
                "authority": fact.authority,
                "evidence_refs": list(fact.evidence_refs[:3]),
            }
            for fact in (list(workspace.rules) + list(workspace.graph_facts))[:5]
        )
        hypothesis_summary = tuple(
            {
                "statement": item.statement,
                "verdict": item.verdict.value,
                "origin": item.origin.value,
                "rationale": item.rationale,
            }
            for item in (hypotheses.hypotheses if hypotheses else ())
        )
        if not completion.complete:
            limitations.append(
                "Análisis incompleto: " + ", ".join(completion.blockers[:4])
            )
        if workspace.scenario and workspace.scenario.missing_requirements:
            limitations.append(
                "Faltan requisitos: "
                + ", ".join(
                    item.kind.value
                    for item in workspace.scenario.missing_requirements
                    if not item.resolved
                )
            )
        for name, value in (
            ("conclusion", conclusion),
            ("observed_flow", observed_flow),
            ("evidence_summary", evidence_summary),
            ("hypothesis_summary", hypothesis_summary),
            ("limitations", tuple(limitations)),
        ):
            if value:
                sections.append(name)
        confidence = (
            "high"
            if completion.complete and user is not None and user.verdict is HypothesisVerdict.SUPPORTED
            else "medium"
            if completion.complete
            else "insufficient"
        )
        return AnswerBlueprint(
            conclusion=conclusion,
            observed_flow=observed_flow,
            evidence_summary=evidence_summary,
            hypothesis_summary=hypothesis_summary,
            limitations=tuple(dict.fromkeys(limitations)),
            confidence=confidence,
            section_names=tuple(sections),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def question_to_prove(question: str, shape: ReasoningShape) -> str:
    """§12: proposición operacional verificable. No cambia la intención."""
    text = " ".join((question or "").split())
    if shape is ReasoningShape.STATE_TRANSITION:
        return (
            "Determine whether the supplied event sequence requires an additional "
            "closing event under the applicable rules."
        )
    if shape is ReasoningShape.TEMPORAL_SEQUENCE:
        return (
            "Determine the order in which the supplied events take effect under the "
            "applicable validity rules."
        )
    if shape is ReasoningShape.CONSISTENCY_CHECK:
        return "Determine whether the supplied events are mutually consistent."
    if shape is ReasoningShape.GRAPH_REASONING:
        return "Determine which entities are affected through the company graph."
    if shape is ReasoningShape.HYPOTHESIS_TEST:
        return f"Determine whether the stated hypothesis holds: {text[:200]}"
    if shape is ReasoningShape.DIAGNOSTIC:
        return "Determine the most supported explanation for the observed failure."
    if shape is ReasoningShape.CAUSAL_ANALYSIS:
        return "Determine which factors explain the observed variation."
    return f"Determine: {text[:200]}"


def parse_step_required(shape: ReasoningShape) -> bool:
    return shape in (
        ReasoningShape.STATE_TRANSITION,
        ReasoningShape.TEMPORAL_SEQUENCE,
    )


def _as_dict(compiled: object) -> dict:
    if compiled is None:
        return {}
    if isinstance(compiled, dict):
        return compiled
    to_dict = getattr(compiled, "to_dict", None)
    if callable(to_dict):
        try:
            return dict(to_dict())
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _fingerprint(query: str) -> object:
    from src.core.domain.intelligence import ToolFingerprint

    return ToolFingerprint.compute(
        tool="evidence_reasoning_requirement",
        source=None,
        arguments={"q": (query or "").strip().lower()[:200]},
        query=query or "",
        agent_id=None,
        organization_id="system",
    )


def _evidence_statement(hits: Sequence[dict]) -> str:
    """Texto del hit, acotado. El enunciado es la regla/definición recuperada."""
    first = hits[0] if hits else {}
    content = " ".join(str(first.get("content") or "").split())
    return content[:220] or "evidencia recuperada"


def _authority_for_hit(workspace: ReasoningWorkspace, hit: dict) -> str:
    """Nivel de autoridad del tenant para la fuente del hit, si está configurado.

    La coincidencia es por nombre de fuente dentro del título o del id del
    documento: la autoridad se resuelve por tenant, no por score vectorial.
    """
    authority = workspace.source_authority or {}
    if not authority:
        return ""
    haystack = " ".join(
        [
            str(hit.get("title") or ""),
            str(hit.get("source_name") or ""),
            str(hit.get("document_id") or ""),
        ]
    ).lower()
    for source_name, level in authority.items():
        token = str(source_name).strip().lower()
        if token and token in haystack:
            return str(level)
    return ""


def _authority_for(workspace: ReasoningWorkspace, requirement: MissingRequirement) -> str:
    authority = workspace.source_authority or {}
    key = (requirement.subject or "").lower()
    for name, level in authority.items():
        if key and key in str(name).lower():
            return str(level)
    return ""


__all__ = [
    "AnalyticalStrategy",
    "EvidenceReasoningEngine",
    "GraphReasoningStrategy",
    "ReasoningStrategy",
    "SHAPE_COMPLETION",
    "SHAPE_OPERATIONS",
    "parse_step_required",
    "question_to_prove",
]
