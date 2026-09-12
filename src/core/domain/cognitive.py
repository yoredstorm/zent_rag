# =============================================================================
# Domain Layer — Cognitive OS (Phase 3)
# =============================================================================
# Contratos puros del supervisor cognitivo: complejidad, presupuesto, tareas,
# task graph (DAG validado), mensajes entre agentes y blackboard de evidencia.
#
# Leyes:
#   - Toda tarea/run pertenece a UNA organización (tenant isolation).
#   - El task graph es un DAG: sin ciclos, sin dependencias desconocidas,
#     sin claves duplicadas.
#   - Los agentes NO se pasan conversaciones libres: AgentMessage transporta
#     conclusiones/evidencia, nunca chain-of-thought.
#   - El presupuesto es explícito y validado; el supervisor no puede excederlo.
#
# Sin I/O. Planificación determinista; la ejecución de especialistas llega en
# fases posteriores.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ComplexityLevel(StrEnum):
    """Cognitive complexity router (brief §5)."""

    L0_DIRECT = "L0"
    L1_RETRIEVAL = "L1"
    L2_ANALYSIS = "L2"
    L3_MULTI_SOURCE = "L3"
    L4_MULTI_SPECIALIST = "L4"
    L5_DEEP_INVESTIGATION = "L5"


class CognitiveRunStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CognitiveTaskStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class ExecutionStatus(StrEnum):
    """Estado de una ejecución de especialista (brief §56)."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentMessageType(StrEnum):
    """Brief §25: structured agent-to-agent messages (no free chat)."""

    TASK = "task"
    FINDING = "finding"
    EVIDENCE = "evidence"
    QUESTION = "question"
    CHALLENGE = "challenge"
    RESPONSE = "response"
    CONFLICT = "conflict"
    HANDOFF = "handoff"
    FINAL_CANDIDATE = "final_candidate"


# ---------------------------------------------------------------------------
# Complexity classifier (deterministic, ES/EN)
# ---------------------------------------------------------------------------

_DEFINITION_MARKERS = (
    "qué significa",
    "que significa",
    "significa",
    "definición",
    "definicion",
    "what does",
    "what is",
)
_COMPARISON_MARKERS = (
    "compara",
    "comparar",
    "comparación",
    "comparacion",
    "versus",
    " vs ",
    "diferencia",
    "contrasta",
    "compare",
)
_TEMPORAL_MARKERS = (
    "vigente",
    "vigentes",
    "versión",
    "version",
    "cambió",
    "cambio",
    "cambios",
    "histórico",
    "historico",
    "supersed",
    "effective",
    "antes de",
    "después de",
    "ultimos",
    "últimos",
    "años",
    "anos",
)
_ANALYTICAL_MARKERS = (
    "resume",
    "resumen",
    "analiza",
    "analizar",
    "riesgo",
    "riesgos",
    "impacto",
    "impacta",
    "evalúa",
    "evalua",
    "explica",
    "por qué",
    "por que",
    "identifica",
)
_MULTI_MARKERS = (
    "todos",
    "todas",
    "cada",
    "múltiples",
    "multiples",
    "proveedores",
    "fuentes",
)
_CONFLICT_MARKERS = ("contradic", "conflicto", "conflictos", "inconsistencia")


def classify_complexity(query: str) -> ComplexityLevel:
    """Least sufficient level (brief §5). Uses the smallest level that fits."""
    text = " ".join((query or "").lower().split())
    if not text:
        return ComplexityLevel.L1_RETRIEVAL
    if any(marker in text for marker in _DEFINITION_MARKERS):
        return ComplexityLevel.L0_DIRECT
    score = 0
    if any(marker in text for marker in _COMPARISON_MARKERS):
        score += 2
    if any(marker in text for marker in _TEMPORAL_MARKERS):
        score += 1
    if any(marker in text for marker in _ANALYTICAL_MARKERS):
        score += 1
    if any(marker in text for marker in _MULTI_MARKERS):
        score += 1
    if any(marker in text for marker in _CONFLICT_MARKERS):
        score += 1
    if len(text.split()) > 60:
        score += 1
    if score <= 0:
        return ComplexityLevel.L1_RETRIEVAL
    if score == 1:
        return ComplexityLevel.L2_ANALYSIS
    if score == 2:
        return ComplexityLevel.L3_MULTI_SOURCE
    if score == 3:
        return ComplexityLevel.L4_MULTI_SPECIALIST
    return ComplexityLevel.L5_DEEP_INVESTIGATION


# ---------------------------------------------------------------------------
# Budget / scope
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class CognitiveBudget:
    """Per-request budget (brief §54); the supervisor must respect it."""

    max_agents: int = 4
    max_llm_calls: int = 12
    max_tokens: int = 24000
    max_cost_usd: float = 1.0
    max_seconds: float = 120.0
    max_tool_calls: int = 20
    max_debate_rounds: int = 0

    def __post_init__(self) -> None:
        if self.max_agents < 1:
            raise ValueError("CognitiveBudget.max_agents must be >= 1")
        if self.max_llm_calls < 0:
            raise ValueError("CognitiveBudget.max_llm_calls must be >= 0")
        if self.max_tokens < 0:
            raise ValueError("CognitiveBudget.max_tokens must be >= 0")
        if self.max_cost_usd <= 0:
            raise ValueError("CognitiveBudget.max_cost_usd must be > 0")
        if self.max_seconds <= 0:
            raise ValueError("CognitiveBudget.max_seconds must be > 0")
        if self.max_tool_calls < 0:
            raise ValueError("CognitiveBudget.max_tool_calls must be >= 0")
        if self.max_debate_rounds < 0:
            raise ValueError("CognitiveBudget.max_debate_rounds must be >= 0")

    def to_dict(self) -> dict:
        return {
            "max_agents": self.max_agents,
            "max_llm_calls": self.max_llm_calls,
            "max_tokens": self.max_tokens,
            "max_cost_usd": self.max_cost_usd,
            "max_seconds": self.max_seconds,
            "max_tool_calls": self.max_tool_calls,
            "max_debate_rounds": self.max_debate_rounds,
        }


@dataclass(frozen=True, kw_only=True)
class CognitiveScope:
    """Security context inherited by every task (brief §58)."""

    organization_id: UUID
    workspace_id: UUID | None = None
    user_id: UUID | None = None
    role: str = "admin"
    groups: tuple[str, ...] = ()
    source_ids: tuple[UUID, ...] = ()
    knowledge_base_id: UUID | None = None

    def to_dict(self) -> dict:
        return {
            "organization_id": str(self.organization_id),
            "workspace_id": str(self.workspace_id) if self.workspace_id else None,
            "user_id": str(self.user_id) if self.user_id else None,
            "role": self.role,
            "groups": list(self.groups),
            "source_ids": [str(s) for s in self.source_ids],
            "knowledge_base_id": (
                str(self.knowledge_base_id) if self.knowledge_base_id else None
            ),
        }


# ---------------------------------------------------------------------------
# Declarative agent definitions (brief §7)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class KnowledgeAgentDefinition:
    id: str
    name: str
    description: str = ""
    capabilities: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    required_permissions: tuple[str, ...] = ()
    supported_tasks: tuple[str, ...] = ()
    preferred_model_role: str = "REASONER"
    max_steps: int = 6
    max_tokens: int = 4000
    max_cost_usd: float = 0.25
    can_delegate: bool = False
    can_debate: bool = False
    requires_verification: bool = False
    security_level: str = "standard"

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("KnowledgeAgentDefinition.id must not be empty")
        if not self.name.strip():
            raise ValueError("KnowledgeAgentDefinition.name must not be empty")
        for field_name, value in (
            ("max_steps", self.max_steps),
            ("max_tokens", self.max_tokens),
        ):
            if value <= 0:
                raise ValueError(f"KnowledgeAgentDefinition.{field_name} must be > 0")
        if self.max_cost_usd <= 0:
            raise ValueError("KnowledgeAgentDefinition.max_cost_usd must be > 0")


# ---------------------------------------------------------------------------
# Task graph (brief §6)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class CognitiveTask:
    run_id: UUID
    key: str
    description: str
    agent_id: str = ""
    depends_on: tuple[str, ...] = ()
    status: CognitiveTaskStatus = CognitiveTaskStatus.PENDING
    position: int = 0
    input_scope: dict = field(default_factory=dict)
    output_contract: dict = field(default_factory=dict)
    budget: CognitiveBudget | None = None
    id: UUID = field(default_factory=uuid4)
    result: dict | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("CognitiveTask.key must not be empty")
        if not self.description.strip():
            raise ValueError("CognitiveTask.description must not be empty")
        if self.position < 0:
            raise ValueError("CognitiveTask.position must be >= 0")


@dataclass(frozen=True, kw_only=True)
class CognitiveTaskGraph:
    """Validated DAG. Construction is the validation gate."""

    tasks: tuple[CognitiveTask, ...]

    def __post_init__(self) -> None:
        keys = [task.key for task in self.tasks]
        if len(set(keys)) != len(keys):
            raise ValueError("CognitiveTaskGraph has duplicate task keys")
        known = set(keys)
        for task in self.tasks:
            missing = [dep for dep in task.depends_on if dep not in known]
            if missing:
                raise ValueError(
                    f"CognitiveTaskGraph task '{task.key}' depends on unknown "
                    f"tasks: {missing}"
                )
        self._assert_acyclic()

    def _assert_acyclic(self) -> None:
        remaining = {task.key: set(task.depends_on) for task in self.tasks}
        resolved: set[str] = set()
        while remaining:
            ready = [key for key, deps in remaining.items() if deps <= resolved]
            if not ready:
                raise ValueError("CognitiveTaskGraph contains a cycle")
            for key in ready:
                resolved.add(key)
                remaining.pop(key)

    def task(self, key: str) -> CognitiveTask | None:
        for task in self.tasks:
            if task.key == key:
                return task
        return None

    def ready_keys(self, completed: set[str]) -> tuple[str, ...]:
        done = set(completed)
        return tuple(
            task.key
            for task in self.tasks
            if task.status is CognitiveTaskStatus.PENDING
            and task.key not in done
            and set(task.depends_on) <= done
        )

    def topological_order(self) -> tuple[str, ...]:
        remaining = {task.key: set(task.depends_on) for task in self.tasks}
        done: set[str] = set()
        ordered: list[str] = []
        while remaining:
            for task in self.tasks:
                if task.key in remaining and set(task.depends_on) <= done:
                    ordered.append(task.key)
                    done.add(task.key)
                    remaining.pop(task.key)
                    break
            else:  # pragma: no cover - constructor already guarantees acyclicity
                raise ValueError("CognitiveTaskGraph contains a cycle")
        return tuple(ordered)


# ---------------------------------------------------------------------------
# Run + messages + blackboard
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class CognitiveRun:
    organization_id: UUID
    query: str
    complexity: ComplexityLevel
    id: UUID = field(default_factory=uuid4)
    workspace_id: UUID | None = None
    status: CognitiveRunStatus = CognitiveRunStatus.PLANNED
    budget: CognitiveBudget = field(default_factory=CognitiveBudget)
    scope: dict = field(default_factory=dict)
    plan: dict = field(default_factory=dict)
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("CognitiveRun.query must not be empty")


@dataclass(frozen=True, kw_only=True)
class AgentMessage:
    """Structured message; never full chain-of-thought (brief §25/§57)."""

    run_id: UUID
    type: AgentMessageType
    from_agent: str
    to_agent: str | None = None
    task_key: str | None = None
    text: str = ""
    claim_ids: tuple[UUID, ...] = ()
    evidence_ids: tuple[UUID, ...] = ()
    confidence: float | None = None
    metadata: dict = field(default_factory=dict)
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.from_agent.strip():
            raise ValueError("AgentMessage.from_agent must not be empty")
        if not self.text.strip() and not self.claim_ids and not self.evidence_ids:
            raise ValueError(
                "AgentMessage requires text, claim_ids or evidence_ids"
            )
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("AgentMessage.confidence must be within [0, 1]")


@dataclass(frozen=True, kw_only=True)
class AgentExecution:
    """Una ejecución de especialista dentro de un run (brief §56).

    Métricas de presupuesto por tarea: llamadas LLM, tokens, costo y latencia.
    """

    run_id: UUID
    task_id: UUID
    agent_id: str
    id: UUID = field(default_factory=uuid4)
    status: ExecutionStatus = ExecutionStatus.RUNNING
    started_at: datetime = field(default_factory=_utcnow)
    finished_at: datetime | None = None
    latency_ms: float = 0.0
    llm_calls: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    error: str | None = None
    result: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.agent_id.strip():
            raise ValueError("AgentExecution.agent_id must not be empty")
        if self.latency_ms < 0 or self.llm_calls < 0 or self.tokens < 0:
            raise ValueError("AgentExecution metrics must be >= 0")
        if self.cost_usd < 0:
            raise ValueError("AgentExecution.cost_usd must be >= 0")


class EvidenceBlackboard:
    """Per-run shared workspace (brief §26); conclusions + evidence only."""

    def __init__(self, *, run_id: UUID) -> None:
        self.run_id = run_id
        self._messages: list[AgentMessage] = []
        self._findings: list[dict] = []
        self._questions: list[str] = []
        self._conflicts: list[dict] = []
        self._evidence_ids: list[UUID] = []

    def record_message(self, message: AgentMessage) -> None:
        if message.run_id != self.run_id:
            raise ValueError("AgentMessage.run_id does not match this blackboard")
        self._messages.append(message)
        self._evidence_ids.extend(message.evidence_ids)

    def record_finding(
        self,
        *,
        text: str,
        subject: str,
        predicate: str,
        object_value: str | None = None,
        evidence_ids: tuple[UUID, ...] = (),
        confidence: float = 0.0,
    ) -> UUID:
        if not text.strip() or not subject.strip() or not predicate.strip():
            raise ValueError("findings require text, subject and predicate")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("finding confidence must be within [0, 1]")
        finding_id = uuid4()
        self._findings.append(
            {
                "id": str(finding_id),
                "text": text,
                "subject": subject,
                "predicate": predicate,
                "object_value": object_value,
                "evidence_ids": [str(e) for e in evidence_ids],
                "confidence": confidence,
            }
        )
        self._evidence_ids.extend(evidence_ids)
        return finding_id

    def record_question(self, text: str) -> None:
        if not text.strip():
            raise ValueError("question text must not be empty")
        self._questions.append(text)

    def record_conflict(
        self, *, from_claim_id: UUID, to_claim_id: UUID, reason: str = ""
    ) -> None:
        self._conflicts.append(
            {
                "from_claim_id": str(from_claim_id),
                "to_claim_id": str(to_claim_id),
                "reason": reason,
            }
        )

    def snapshot(self) -> dict:
        return {
            "run_id": str(self.run_id),
            "messages": len(self._messages),
            "findings": len(self._findings),
            "questions": len(self._questions),
            "conflicts": len(self._conflicts),
            "evidence_ids": list(self._evidence_ids),
        }
