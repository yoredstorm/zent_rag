# =============================================================================
# AgentRunState — estado canónico de un run (agregador, no sistema paralelo).
# =============================================================================
# Responde UNA pregunta: «¿cuál es el estado de este run?» sin reconstruirlo
# leyendo cinco subsistemas. NO crea un sistema paralelo: envuelve las
# estructuras que ya existen (EvidenceRegistry/Selection/Sufficiency,
# DecisionEnvelope, DerivedPreparationResult, RunBudgetLedger, ReasoningRunState,
# TurnIntentDecision) y las expone bajo una sola capa con tres niveles de
# autoridad:
#
#   AUTHORITATIVE  decide el resultado (evidencia canónica, DecisionEnvelope,
#                  presupuesto consumido, tools permitidas)
#   DERIVED        se calcula de la autoridad (readiness, plan, presentación)
#   OBSERVATIONAL  JEV shadow, timings, notas; JAMÁS cambia una autoridad
#
# Fase A: los writers publican acá lo mismo que ya escriben en `result`/`adaptive`;
# los readers nuevos consultan esta estructura y los viejos no cambian.
# Fases B-D (docs/architecture/agent_run_state/03-migration-plan.md) migran los
# writers y eliminan recalculadores; acá no se duplica ningún dato: los holders
# guardan REFERENCIAS a los objetos existentes, no copias.
# =============================================================================
from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from src.runtime.runtime_identity import query_fingerprint

if TYPE_CHECKING:  # solo anotaciones: run_state no importa los subsistemas pesados
    from src.agents.runtime.reasoning_step import ReasoningRunState
    from src.runtime.decision_envelope import DecisionEnvelope, FinalizedAnswer
    from src.runtime.derived_guard import DerivedGuardOutcome
    from src.runtime.deterministic_authority import DerivedPreparationResult
    from src.runtime.evidence import (
        EvidenceRegistry,
        EvidenceSelection,
        EvidenceSufficiency,
    )
    from src.runtime.run_budget import RunBudgetLedger
    from src.runtime.turn_intent import TurnIntentDecision

CONTRACT_VERSION = "agent-run-state-1"


class RunPhase(StrEnum):
    """Fases del lifecycle de un run. No reemplaza `status`: lo explica."""

    CREATED = "CREATED"
    CLASSIFIED = "CLASSIFIED"
    PLANNED = "PLANNED"
    EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"
    RETRIEVING = "RETRIEVING"
    REASONING = "REASONING"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    ACTING = "ACTING"
    READY_TO_FINALIZE = "READY_TO_FINALIZE"
    FINALIZED = "FINALIZED"
    ABSTAINED = "ABSTAINED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    LIMIT_REACHED = "LIMIT_REACHED"
    UNDETERMINED = "UNDETERMINED"


#: Fases sin salida. Solo `finish()` las asigna.
TERMINAL_PHASES: frozenset[RunPhase] = frozenset(
    {
        RunPhase.FINALIZED,
        RunPhase.ABSTAINED,
        RunPhase.BLOCKED,
        RunPhase.FAILED,
        RunPhase.LIMIT_REACHED,
        RunPhase.UNDETERMINED,
    }
)

_T = RunPhase
#: Transiciones válidas del pipeline. Un intento inválido NO mueve la fase:
#: se registra en `trace.notes` (observacional), nunca rompe el run.
_TRANSITIONS: dict[RunPhase, frozenset[RunPhase]] = {
    _T.CREATED: frozenset({_T.CLASSIFIED, _T.PLANNED}),
    _T.CLASSIFIED: frozenset(
        {
            _T.PLANNED,
            _T.EVIDENCE_REQUIRED,
            _T.RETRIEVING,
            _T.REASONING,
            _T.ACTION_REQUIRED,
            _T.READY_TO_FINALIZE,
        }
    ),
    _T.PLANNED: frozenset(
        {
            _T.EVIDENCE_REQUIRED,
            _T.RETRIEVING,
            _T.REASONING,
            _T.ACTION_REQUIRED,
            _T.READY_TO_FINALIZE,
        }
    ),
    _T.EVIDENCE_REQUIRED: frozenset(
        {_T.RETRIEVING, _T.REASONING, _T.ACTION_REQUIRED, _T.READY_TO_FINALIZE}
    ),
    _T.RETRIEVING: frozenset(
        {_T.REASONING, _T.EVIDENCE_REQUIRED, _T.ACTION_REQUIRED, _T.READY_TO_FINALIZE}
    ),
    _T.REASONING: frozenset(
        {_T.EVIDENCE_REQUIRED, _T.RETRIEVING, _T.ACTION_REQUIRED, _T.READY_TO_FINALIZE}
    ),
    _T.ACTION_REQUIRED: frozenset(
        {_T.ACTING, _T.RETRIEVING, _T.REASONING, _T.READY_TO_FINALIZE}
    ),
    _T.ACTING: frozenset(
        {
            _T.REASONING,
            _T.EVIDENCE_REQUIRED,
            _T.RETRIEVING,
            _T.ACTION_REQUIRED,
            _T.READY_TO_FINALIZE,
        }
    ),
    _T.READY_TO_FINALIZE: TERMINAL_PHASES,
}


def _allowed_transitions(current: RunPhase) -> frozenset[RunPhase]:
    if current in TERMINAL_PHASES:
        return frozenset()
    return frozenset(_TRANSITIONS.get(current, frozenset())) | TERMINAL_PHASES


#: Invariantes que, en modo estricto (`RUNTIME_RUN_STATE_STRICT=on`), bloquean
#: la respuesta por riesgo de corrección (no por bookkeeping).
CRITICAL_INVARIANTS: frozenset[str] = frozenset(
    {
        "authoritative_decision_contradicted",
        "authoritative_decision_replaced",
        "deterministic_finalized_without_envelope",
    }
)


# -----------------------------------------------------------------------------
# Identidad (AUTHORITATIVE): ids y tenant. Inmutable por run.
# -----------------------------------------------------------------------------
@dataclass(kw_only=True)
class RunIdentity:
    run_id: str
    kind: str = "agent"  # "agent" | "rag"
    agent_id: str = ""
    organization_id: str = ""
    conversation_id: str | None = None
    user_id: str | None = None
    deployment_id: str | None = None
    version_id: str | None = None
    environment: str | None = None
    role: str = "admin"
    trace_id: str | None = None
    query_fingerprint: str = ""
    created_at: float = field(default_factory=time.time)

    @classmethod
    def from_request(cls, request: Any, *, run_id: str, kind: str = "agent") -> RunIdentity:
        """Desde un AgentRunRequest (o equivalente) sin acoplarse a su tipo."""
        agent = getattr(request, "agent", None)
        message = str(getattr(request, "message", "") or "")
        return cls(
            run_id=str(run_id),
            kind=kind,
            agent_id=str(getattr(agent, "id", "") or ""),
            organization_id=str(getattr(agent, "organization_id", "") or ""),
            conversation_id=(
                str(request.conversation_id) if getattr(request, "conversation_id", None) else None
            ),
            user_id=str(request.user_id) if getattr(request, "user_id", None) else None,
            deployment_id=(
                str(request.deployment_id) if getattr(request, "deployment_id", None) else None
            ),
            version_id=str(request.version_id) if getattr(request, "version_id", None) else None,
            environment=getattr(request, "environment", None),
            role=str(getattr(request, "role", "") or "admin"),
            trace_id=getattr(request, "trace_id", None),
            query_fingerprint=query_fingerprint(message),
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "kind": self.kind,
            "agent_id": self.agent_id or None,
            "organization_id": self.organization_id or None,
            "conversation_id": self.conversation_id,
            "trace_id": self.trace_id,
            "query_fingerprint": self.query_fingerprint,
            "created_at": self.created_at,
        }


# -----------------------------------------------------------------------------
# Secciones del estado
# -----------------------------------------------------------------------------
@dataclass(frozen=True, kw_only=True)
class TurnSnapshot:
    """Vista mínima de un turno clasificado por el plan RAG.

    El camino RAG no construye `TurnIntentDecision`; el plan ya trae la ruta.
    El contrato de lectura es el mismo (`intent/route/direct/needs_external_evidence`).
    """

    intent: str = ""
    route: str = ""
    direct: bool = False
    needs_external_evidence: bool | None = None


@dataclass(kw_only=True)
class TurnState:
    """AUTHORITATIVE: qué está haciendo el usuario. Envuelve TurnIntentDecision."""

    decision: TurnIntentDecision | TurnSnapshot | None = None

    @property
    def intent(self) -> str:
        return str(getattr(self.decision, "intent", "") or "")

    @property
    def route(self) -> str:
        return str(getattr(self.decision, "route", "") or "")

    @property
    def direct(self) -> bool:
        return bool(getattr(self.decision, "direct", False))

    @property
    def needs_external_evidence(self) -> bool | None:
        value = getattr(self.decision, "needs_external_evidence", None)
        return bool(value) if value is not None else None

    def to_public_dict(self) -> dict[str, Any]:
        if self.decision is None:
            return {"mode": "off"}
        return {
            "intent": self.intent,
            "route": self.route,
            "direct": self.direct,
            "needs_external_evidence": self.needs_external_evidence,
        }


@dataclass(kw_only=True)
class PlanningState:
    """DERIVED: plan cognitivo, estrategia y contrato de presentación."""

    plan: Any | None = None
    strategy: Any | None = None
    response_plan: dict | None = None
    authorized_scope: Any | None = None


@dataclass(kw_only=True)
class KnowledgeState:
    """DERIVED: entidades, brief y paquete narrativo (presentación del saber)."""

    entities: Any | None = None
    brief: Any | None = None
    narrative_package: Any | None = None
    #: Paquete de generación (dict público) del camino RAG.
    generation_package: dict | None = None
    #: Cobertura narrativa medida (ConceptCoverage) y divergencia detectada:
    #: search pedido por cobertura con evidencia ya completa.
    coverage: tuple[Any, ...] = ()
    coverage_search_after_complete: bool = False


@dataclass(kw_only=True)
class EvidenceView:
    """AUTHORITATIVE: envuelve registry/selection/sufficiency existentes.

    No duplica evidencia: `registry`, `selection` y `sufficiency` son los mismos
    objetos que usa el pipeline. Los sets selected/used/cited son el resumen
    comprobable de la cadena `cited ⊆ used ⊆ selected`.
    """

    registry: EvidenceRegistry | None = None
    selection: EvidenceSelection | None = None
    sufficiency: EvidenceSufficiency | None = None
    canonical_state: Any | None = None  # EvidenceState (objeto o dict público)
    public: dict | None = None  # payload publicado (result.evidence)
    #: Long-context (RAG): stop declarado por el motor y si aplicó.
    long_context_applied: bool = False
    long_context_stop: str = ""
    #: Ronda de retrieval con la que se calculó `sufficiency` (guardia de reuso).
    sufficiency_rounds_left: int | None = None
    retrieval_failed: bool = False
    selected: frozenset[str] = frozenset()
    used: frozenset[str] = frozenset()
    cited: frozenset[str] = frozenset()

    def observe(
        self,
        *,
        registry: Any | None = None,
        selection: Any | None = None,
        sufficiency: Any | None = None,
        canonical_state: Any | None = None,
        public: dict | None = None,
        rounds_left: int | None = None,
    ) -> None:
        """Publica las referencias canónicas (no copia contenido)."""
        if registry is not None:
            self.registry = registry
        if selection is not None:
            self.selection = selection
        if sufficiency is not None:
            self.sufficiency = sufficiency
        if canonical_state is not None:
            self.canonical_state = canonical_state
        if public is not None:
            self.public = public
        if rounds_left is not None:
            self.sufficiency_rounds_left = int(rounds_left)

    def observe_usage(
        self,
        *,
        selected: frozenset[str] | None = None,
        used: frozenset[str] | None = None,
        cited: frozenset[str] | None = None,
    ) -> None:
        """Solo actualiza el eje informado: los sets previos no se pisan."""
        if selected is not None:
            self.selected = selected
        if used is not None:
            self.used = used
        if cited is not None:
            self.cited = cited

    @property
    def complete(self) -> bool:
        """Evidencia completa según la autoridad disponible (sin recalcular)."""
        if self.sufficiency is not None:
            complete = getattr(self.sufficiency, "evidence_complete", None)
            if isinstance(complete, bool):
                return complete
        canonical = self.canonical_state
        if isinstance(canonical, dict):
            if canonical.get("evidence_complete") is not None:
                return bool(canonical.get("evidence_complete"))
        elif canonical is not None:
            return bool(getattr(canonical, "evidence_complete", False))
        return False

    @property
    def insufficient(self) -> bool:
        action = str(getattr(self.sufficiency, "recommended_action", "") or "")
        return action in {"retrieve_more", "abstain"}

    @property
    def can_answer(self) -> bool | None:
        """`generate` de la suficiencia canónica (None = sin autoridad)."""
        sufficiency = self.sufficiency
        if sufficiency is None:
            return None
        generate = getattr(sufficiency, "generate", None)
        return bool(generate) if isinstance(generate, bool) else None

    @property
    def chain_violations(self) -> tuple[str, ...]:
        if self.cited and not self.cited <= self.used:
            return ("cited_not_used",)
        if self.used and not self.used <= self.selected:
            return ("used_not_selected",)
        return ()

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "insufficient": self.insufficient,
            "retrieval_failed": self.retrieval_failed,
            "selected": len(self.selected),
            "used": len(self.used),
            "cited": len(self.cited),
        }


@dataclass(kw_only=True)
class ReasoningView:
    """AUTHORITATIVE (análisis): envuelve ReasoningRunState existente."""

    run: ReasoningRunState | None = None

    @property
    def active(self) -> bool:
        return bool(getattr(self.run, "enabled", False))

    @property
    def is_complex(self) -> bool:
        return bool(getattr(self.run, "is_complex", False))

    @property
    def analysis_complete(self) -> bool:
        return bool(getattr(self.run, "analysis_complete", False))

    @property
    def blocks_early_answer(self) -> bool:
        return bool(getattr(self.run, "blocks_early_answer", False))

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "is_complex": self.is_complex,
            "analysis_complete": self.analysis_complete,
            "blocks_early_answer": self.blocks_early_answer,
        }


@dataclass(kw_only=True)
class ToolState:
    """AUTHORITATIVE: allowlist efectiva del run y tools realmente ejecutadas."""

    allowed: frozenset[str] = frozenset()
    used: frozenset[str] = frozenset()
    calls: int = 0
    #: Observacional: nombre → error de la última ejecución.
    failures: dict[str, str] = field(default_factory=dict)

    def set_allowed(self, tools: Any) -> None:
        """Acepta nombres o Tool objects."""
        names: set[str] = set()
        for tool in tools or ():
            name = getattr(tool, "name", None)
            if name is None and isinstance(tool, str):
                name = tool
            if name:
                names.add(str(name))
        self.allowed = frozenset(names)

    def note_call(self, tool: str) -> bool:
        """Registra una ejecución real. Devuelve si estaba permitida."""
        name = str(tool or "")
        if not name:
            return False
        self.used = self.used | {name}
        self.calls += 1
        return name in self.allowed

    def calls_outside_allowlist(self) -> frozenset[str]:
        return self.used - self.allowed

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "allowed": len(self.allowed),
            "used": len(self.used),
            "calls": self.calls,
        }


@dataclass(kw_only=True)
class BudgetState:
    """AUTHORITATIVE: presupuesto consumido. El ledger existente manda."""

    ledger: RunBudgetLedger | None = None
    expensive_calls_after_exhaustion: int = 0
    #: Observacional: el último motivo de corte presupuestario observado.
    last_cut_reason: str = ""

    @property
    def exhausted(self) -> bool:
        ledger = self.ledger
        if ledger is None:
            return False
        remaining_tokens = getattr(ledger, "remaining_tokens", None)
        if remaining_tokens is not None and remaining_tokens <= 0:
            return True
        remaining_cost = getattr(ledger, "remaining_cost_usd", None)
        return remaining_cost is not None and remaining_cost <= 0

    def note_expensive_call(self, kind: str) -> bool:
        """Cuenta un intento de llamada caro. Devuelve si el ledger lo permite."""
        if self.exhausted:
            self.expensive_calls_after_exhaustion += 1
            return False
        return True

    def to_public_dict(self) -> dict[str, Any]:
        ledger = self.ledger
        return {
            "exhausted": self.exhausted,
            "expensive_calls_after_exhaustion": self.expensive_calls_after_exhaustion,
            "remaining_tokens": getattr(ledger, "remaining_tokens", None),
            "remaining_cost_usd": getattr(ledger, "remaining_cost_usd", None),
            "last_cut_reason": self.last_cut_reason or None,
        }


@dataclass(kw_only=True)
class DecisionState:
    """AUTHORITATIVE: DecisionEnvelope + preparación determinista. Inmutable.

    Un envelope ya publicado no se reemplaza en silencio: un reemplazo con
    contenido distinto se registra (`envelope_conflict`) y viola invariantes.
    """

    envelope: DecisionEnvelope | None = None
    #: Envelope publicado como dict (vía RAG antes de migrar sus writers).
    envelope_public: dict | None = None
    prep: DerivedPreparationResult | None = None
    #: Vista pública del grounded reasoning (dict) del camino RAG.
    grounded_public: dict | None = None
    guard: DerivedGuardOutcome | None = None
    finalized: FinalizedAnswer | None = None
    requires_deterministic: bool = False
    authority_prepared: bool = False
    final_state: str = ""
    terminal_message: str = ""
    envelope_conflict: bool = False
    #: OBSERVATIONAL: veredictos JEV (shadow incluido). Nunca deciden acá.
    jev: list[dict] = field(default_factory=list)

    @property
    def authoritative(self) -> bool:
        if self.envelope is not None:
            return bool(getattr(self.envelope, "authoritative", False))
        return bool((self.envelope_public or {}).get("authoritative"))

    def observe_public_envelope(self, public: dict | None) -> None:
        """Para caminos que solo publican el dict (bridge RAG, Fase A)."""
        if isinstance(public, dict):
            self.envelope_public = dict(public)

    def set_envelope(self, envelope: DecisionEnvelope | None) -> None:
        if envelope is None:
            return
        if self.envelope is envelope:
            return
        if self.envelope is None:
            self.envelope = envelope
            return
        if self.envelope == envelope:
            return
        self.envelope_conflict = True
        self.envelope = envelope

    def observe_prep(self, prep: DerivedPreparationResult) -> None:
        self.prep = prep
        self.authority_prepared = True
        self.requires_deterministic = bool(
            getattr(prep, "requires_deterministic_decision", False)
        )
        self.set_envelope(getattr(prep, "authoritative_envelope", None))

    def observe_finalized(self, finalized: FinalizedAnswer | None) -> None:
        if finalized is None:
            return
        self.finalized = finalized
        self.guard = getattr(finalized, "guard", None) or self.guard
        envelope = getattr(finalized, "envelope", None)
        self.set_envelope(envelope)
        if envelope is not None and hasattr(envelope, "to_public_dict"):
            self.observe_public_envelope(envelope.to_public_dict())
        state = str(getattr(finalized, "state", "") or "")
        if state:
            self.final_state = state
        message = str(getattr(finalized, "answer", "") or "")
        if bool(getattr(finalized, "blocked", False)) and message:
            self.terminal_message = message[:240]

    def to_public_dict(self) -> dict[str, Any]:
        envelope = self.envelope
        public = self.envelope_public or {}
        return {
            "authoritative": self.authoritative,
            "requires_deterministic": self.requires_deterministic,
            "state": (
                self.final_state
                or str(getattr(envelope, "state", "") or "")
                or str(public.get("state") or "")
            ),
            "operation": (
                (getattr(envelope, "operation", "") or None)
                if envelope is not None
                else public.get("operation")
            ),
            "result": (
                getattr(envelope, "normalized_result", None)
                if envelope is not None
                else public.get("result")
            ),
            "guard_action": getattr(self.guard, "action", None),
            "envelope_conflict": self.envelope_conflict,
        }


@dataclass(kw_only=True)
class AnswerState:
    """DERIVED del resultado autoritativo: texto final y cierre del run."""

    text: str = ""
    status: str = ""
    answer_state: dict = field(default_factory=dict)
    citations: tuple[str, ...] = ()
    gate: Any | None = None  # AnswerGateResult (observacional en esta capa)
    guard_overrides: int = 0

    @property
    def present(self) -> bool:
        return bool(self.text.strip())

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "present": self.present,
            "chars": len(self.text),
            "citations": len(self.citations),
            "answer_state": self.answer_state.get("state") or None,
            "guard_overrides": self.guard_overrides,
        }


@dataclass(kw_only=True)
class TraceState:
    """OBSERVATIONAL: lifecycle, notas de transición y violaciones de invariantes."""

    phase_history: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    steps_count: int = 0
    spans_count: int = 0
    latency_ms: float = 0.0

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "violations": list(self.violations),
            "steps": self.steps_count,
            "spans": self.spans_count,
            "latency_ms": round(self.latency_ms, 2),
            "phase_history": list(self.phase_history[-12:]),
        }


@dataclass(kw_only=True)
class AgentRunState:
    """Estado canónico de un run: una sola estructura consultable.

    Los writers publican acá y siguen actualizando `result`/`adaptive` (Fase A).
    """

    identity: RunIdentity
    phase: RunPhase = RunPhase.CREATED
    turn: TurnState = field(default_factory=TurnState)
    plan: PlanningState = field(default_factory=PlanningState)
    knowledge: KnowledgeState = field(default_factory=KnowledgeState)
    evidence: EvidenceView = field(default_factory=EvidenceView)
    reasoning: ReasoningView = field(default_factory=ReasoningView)
    tools: ToolState = field(default_factory=ToolState)
    budget: BudgetState = field(default_factory=BudgetState)
    decisions: DecisionState = field(default_factory=DecisionState)
    answer: AnswerState = field(default_factory=AnswerState)
    trace: TraceState = field(default_factory=TraceState)

    # ------------------------------------------------------------------ lifecycle
    @property
    def terminal(self) -> bool:
        return self.phase in TERMINAL_PHASES

    def try_advance(self, phase: RunPhase, *, detail: str = "") -> bool:
        """Transición validada. Inválida = nota observacional, nunca excepción."""
        if phase == self.phase:
            return True
        if phase not in _allowed_transitions(self.phase):
            self.trace.notes.append(f"phase_rejected:{self.phase}->{phase}")
            return False
        self.phase = phase
        self.trace.phase_history.append(
            {"phase": str(phase), "detail": detail[:200], "at_ms": round(time.time() * 1000)}
        )
        return True

    def finish(self, *, status: str, answer: str, answer_state: dict | None) -> RunPhase:
        """Cierra el run con la fase terminal que corresponde al resultado real."""
        terminal = terminal_phase_for(status=status, answer=answer, answer_state=answer_state)
        if self.phase not in TERMINAL_PHASES:
            self.try_advance(terminal, detail=f"status={status}")
        else:
            self.phase = terminal
        return self.phase

    # ------------------------------------------------------------------ invariantes
    def check_invariants(self) -> tuple[str, ...]:
        """Invariantes comprobables del run. [] = consistente.

        No lanza: las violaciones se registran y se publican para traza.
        """
        violations: list[str] = []
        decisions = self.decisions
        evidence = self.evidence
        answer = self.answer

        # 1. Fase terminal con respuesta obligatoria => answer != vacío.
        if self.phase in (
            RunPhase.FINALIZED,
            RunPhase.LIMIT_REACHED,
            RunPhase.ABSTAINED,
        ) and not answer.present:
            violations.append(f"terminal_phase_without_answer:{self.phase}")

        # 2. DETERMINISTIC_DECISION => DecisionEnvelope existe.
        if (
            self.phase == RunPhase.FINALIZED
            and decisions.requires_deterministic
            and not decisions.authoritative
        ):
            violations.append("deterministic_finalized_without_envelope")

        # 3. DecisionEnvelope autoritativo => el resultado no se contradice.
        if decisions.authoritative and self.phase == RunPhase.FINALIZED:
            guard_action = str(getattr(decisions.guard, "action", "") or "")
            if guard_action == "internal_conflict":
                violations.append("authoritative_decision_contradicted")

        # 4. budget.exhausted => ninguna llamada cara posterior.
        if self.budget.expensive_calls_after_exhaustion:
            violations.append(
                "expensive_calls_after_budget_exhausted:"
                f"{self.budget.expensive_calls_after_exhaustion}"
            )

        # 5. tool_call => tool ∈ effective_allowed_tools.
        unknown_tools = self.tools.calls_outside_allowlist()
        if unknown_tools:
            violations.append(
                "tool_executed_outside_allowlist:" + ",".join(sorted(unknown_tools))
            )

        # 6. evidence.cited ⊆ evidence.used ⊆ evidence.selected.
        for chain in evidence.chain_violations:
            violations.append(f"evidence_chain:{chain}")

        # 7. analysis_complete=False + razonamiento complejo => sin cierre normal.
        if self.phase == RunPhase.FINALIZED and self.reasoning.blocks_early_answer:
            violations.append("incomplete_analysis_finalized")

        # 8. retrieval_failed != evidence_insufficient (realidades distintas).
        if evidence.retrieval_failed and decisions.final_state == "INSUFFICIENT_EVIDENCE":
            violations.append("retrieval_failure_reported_as_insufficiency")

        # 9. La autoridad no se reemplaza con contenido distinto en silencio.
        if decisions.envelope_conflict:
            violations.append("authoritative_decision_replaced")

        # 10. Cobertura narrativa vs evidencia canónica: pedir búsqueda por
        # cobertura cuando la evidencia ya es completa es una divergencia.
        if (
            self.phase == RunPhase.FINALIZED
            and self.evidence.complete
            and self.knowledge.coverage_search_after_complete
        ):
            violations.append("coverage_search_after_evidence_complete")

        return tuple(violations)

    # ------------------------------------------------------------------ proyección
    def critical_violations(self) -> tuple[str, ...]:
        """Violaciones que en modo estricto bloquean la respuesta."""
        return tuple(
            violation
            for violation in self.trace.violations
            if violation.split(":", 1)[0] in CRITICAL_INVARIANTS
        )

    def to_public_dict(self) -> dict[str, Any]:
        """Vista compacta para traza/diagnóstico. No reemplaza payloads API."""
        return {
            "contract": CONTRACT_VERSION,
            "phase": str(self.phase),
            "terminal": self.terminal,
            "identity": self.identity.to_public_dict(),
            "turn": self.turn.to_public_dict(),
            "knowledge": {
                "coverage": len(self.knowledge.coverage),
                "coverage_search_after_complete": self.knowledge.coverage_search_after_complete,
            },
            "evidence": self.evidence.to_public_dict(),
            "reasoning": self.reasoning.to_public_dict(),
            "tools": self.tools.to_public_dict(),
            "budget": self.budget.to_public_dict(),
            "decision": self.decisions.to_public_dict(),
            "answer": self.answer.to_public_dict(),
            "trace": self.trace.to_public_dict(),
        }


# -----------------------------------------------------------------------------
# Cierre del run
# -----------------------------------------------------------------------------
def terminal_phase_for(*, status: str, answer: str, answer_state: dict | None) -> RunPhase:
    """Mapea el resultado real a la fase terminal. Código decide; nunca el texto."""
    state = str((answer_state or {}).get("state") or "")
    if status in ("error", "failed"):
        return RunPhase.FAILED
    if status == "limit_reached":
        return RunPhase.LIMIT_REACHED
    if status in ("awaiting_approval", "blocked"):
        return RunPhase.BLOCKED
    from src.runtime.answer_state import (
        ABSTAINED_STATES,
        OPERATIONAL_FAILURE_STATES,
        UNDETERMINED_STATES,
    )

    if state in OPERATIONAL_FAILURE_STATES:
        return RunPhase.BLOCKED
    if state in ABSTAINED_STATES:
        return RunPhase.ABSTAINED
    if state in UNDETERMINED_STATES:
        return RunPhase.UNDETERMINED
    if str(answer or "").strip():
        return RunPhase.FINALIZED
    return RunPhase.BLOCKED


def strict_mode_enabled(settings: Any) -> bool:
    """`RUNTIME_RUN_STATE_STRICT=on` activa el fail-closed por invariantes."""
    value = str(
        getattr(settings, "RUNTIME_RUN_STATE_STRICT", "off") or "off"
    ).strip().lower()
    return value in ("on", "1", "true", "yes")


def observe_violations(path: str, violations: Iterable[str]) -> None:
    """Métrica de invariantes violados (fail-soft, nunca rompe el run)."""
    try:
        from src.infrastructure.observability.metrics import (
            zent_run_state_violations_total,
        )

        for violation in violations or ():
            zent_run_state_violations_total.labels(
                path=path, kind=str(violation).split(":", 1)[0]
            ).inc()
    except Exception:  # noqa: BLE001
        pass


def finalize_state(
    state: AgentRunState,
    *,
    status: str,
    answer: str,
    answer_state: dict | None = None,
    citations: list[dict] | None = None,
    evidence_public: dict | None = None,
    steps_count: int = 0,
    spans_count: int = 0,
    latency_ms: float = 0.0,
) -> tuple[str, ...]:
    """Cierra el estado y evalúa invariantes. Devuelve las violaciones."""
    state.answer.text = str(answer or "")
    state.answer.status = str(status or "")
    state.answer.answer_state = dict(answer_state or {})
    state.decisions.final_state = str((answer_state or {}).get("state") or "")
    state.trace.steps_count = int(steps_count)
    state.trace.spans_count = int(spans_count)
    state.trace.latency_ms = float(latency_ms)
    if evidence_public is not None:
        state.evidence.observe(public=evidence_public)
    if citations:
        cited_ids = {
            str(entry.get("evidence_id") or "")
            for entry in citations
            if isinstance(entry, dict) and entry.get("evidence_id")
        }
        if cited_ids:
            state.answer.citations = tuple(sorted(cited_ids))
            if not state.evidence.cited:
                state.evidence.observe_usage(cited=frozenset(cited_ids))
    state.finish(status=status, answer=answer, answer_state=answer_state)
    violations = state.check_invariants()
    state.trace.violations[:] = list(violations)
    if violations:
        state.trace.notes.append("invariants_violated:" + "|".join(violations[:4]))
    return violations


__all__ = [
    "AgentRunState",
    "AnswerState",
    "BudgetState",
    "CONTRACT_VERSION",
    "CRITICAL_INVARIANTS",
    "DecisionState",
    "EvidenceView",
    "KnowledgeState",
    "PlanningState",
    "ReasoningView",
    "RunIdentity",
    "RunPhase",
    "TERMINAL_PHASES",
    "ToolState",
    "TraceState",
    "TurnSnapshot",
    "TurnState",
    "finalize_state",
    "observe_violations",
    "strict_mode_enabled",
    "terminal_phase_for",
]
