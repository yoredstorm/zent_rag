# =============================================================================
# Workflow Context — contexto semántico compartido por run
# (Workflow Semantic Core, Fase 1).
#
# Secciones explícitas; separa estado de runtime, estado persistible y estado
# sensible. Vive en memoria durante el run: la persistencia (contribuciones y
# proyección) llega en Fase 7. Sin I/O.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from src.platform.workflows.values import jsonable

CONTEXT_SCHEMA_VERSION = 1

CONTEXT_SECTIONS: tuple[str, ...] = (
    "identity",
    "trigger",
    "data",
    "knowledge",
    "evidence_refs",
    "claim_refs",
    "entity_refs",
    "findings",
    "decisions",
    "artifacts",
    "variables",
    "execution",
    "security",
)

# Estado que puede proyectarse a DB/auditoría (Fase 7).
PERSISTED_SECTIONS: tuple[str, ...] = (
    "identity",
    "trigger",
    "data",
    "knowledge",
    "evidence_refs",
    "claim_refs",
    "entity_refs",
    "findings",
    "decisions",
    "artifacts",
    "variables",
    "execution",
)

# Estado que jamás sale del proceso: no se persiste ni viaja al LLM.
RUNTIME_ONLY_SECTIONS: tuple[str, ...] = ("security",)

# Secciones permitidas en un prompt de agente.
LLM_VISIBLE_SECTIONS: tuple[str, ...] = (
    "trigger",
    "data",
    "knowledge",
    "evidence_refs",
    "claim_refs",
    "entity_refs",
    "findings",
    "decisions",
    "artifacts",
)

# Secciones que un nodo puede contribuir (merge validado por ContextMerger).
WRITABLE_SECTIONS: tuple[str, ...] = (
    "data",
    "knowledge",
    "evidence_refs",
    "claim_refs",
    "entity_refs",
    "findings",
    "decisions",
    "artifacts",
    "variables",
)

# Alias cortos usados por los contratos de nodo (`context_writes`).
SECTION_ALIASES: dict[str, str] = {
    "evidence": "evidence_refs",
    "claims": "claim_refs",
    "entities": "entity_refs",
}


def normalize_section(name: str) -> str | None:
    """Normaliza alias y valida la sección. None si no existe."""
    key = str(name or "").strip()
    if not key:
        return None
    key = SECTION_ALIASES.get(key, key)
    return key if key in CONTEXT_SECTIONS else None


def is_writable_section(name: str) -> bool:
    return normalize_section(name) in WRITABLE_SECTIONS


@dataclass(frozen=True, kw_only=True)
class WorkflowIdentity:
    """Identidad del run: org/workspace/workflow/actor/correlación."""

    organization_id: UUID
    workflow_id: UUID
    run_id: UUID
    actor_type: str = "system"
    actor_id: UUID | None = None
    workspace_id: UUID | None = None
    correlation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "organization_id": str(self.organization_id),
            "workflow_id": str(self.workflow_id),
            "run_id": str(self.run_id),
            "actor_type": self.actor_type,
            "actor_id": str(self.actor_id) if self.actor_id else None,
            "workspace_id": str(self.workspace_id) if self.workspace_id else None,
            "correlation_id": self.correlation_id,
        }


@dataclass(frozen=True, kw_only=True)
class TriggerSnapshot:
    """Disparador que originó el run, normalizado."""

    source: str = "manual"
    event_type: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return jsonable(
            {
                "source": self.source,
                "event_type": self.event_type,
                "payload": self.payload,
                "occurred_at": self.occurred_at,
            }
        )


@dataclass
class WorkflowContext:
    """Contexto semántico compartido por run (brief §2).

    - `data` / `knowledge`: slots por clave (`dict`), cada entrada es un
      `WorkflowValue.to_dict()`.
    - `evidence_refs` / `claim_refs` / `entity_refs` / `findings` /
      `decisions` / `artifacts`: listas de referencias auditables.
    - `variables`: paridad con las variables del runtime (`rctx.variables`).
    - `execution`: resumen por nodo (status/error/duration).
    - `security`: runtime-only; nunca se persiste ni viaja al LLM.
    """

    identity: WorkflowIdentity
    trigger: TriggerSnapshot
    schema_version: int = CONTEXT_SCHEMA_VERSION
    data: dict[str, Any] = field(default_factory=dict)
    knowledge: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    claim_refs: list[dict[str, Any]] = field(default_factory=list)
    entity_refs: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)
    execution: dict[str, Any] = field(default_factory=dict)
    security: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_execution(
        cls,
        execution: Any,
        *,
        payload: dict[str, Any] | None = None,
        event_type: str | None = None,
    ) -> "WorkflowContext":
        """Construye el contexto desde el `ExecutionContext` del runtime.

        El tipo se declara `Any` para no acoplar este módulo al runtime
        (evita ciclos de import).
        """
        source = event_type or str(getattr(execution, "trigger_type", "") or "manual")
        identity = WorkflowIdentity(
            organization_id=execution.organization_id,
            workflow_id=execution.workflow_id,
            run_id=execution.run_id,
            actor_type=str(getattr(execution, "actor_type", "") or "system"),
            actor_id=getattr(execution, "actor_id", None),
            workspace_id=getattr(execution, "workspace_id", None),
            correlation_id=getattr(execution, "correlation_id", None),
        )
        trigger = TriggerSnapshot(
            source=source,
            event_type=event_type or getattr(execution, "trigger_type", None),
            payload=dict(payload or {}),
        )
        return cls(identity=identity, trigger=trigger)

    def section(self, name: str) -> Any:
        key = normalize_section(name)
        if key is None:
            return None
        return getattr(self, key, None)

    def to_dict(
        self,
        *,
        sections: tuple[str, ...] | None = None,
        include_runtime: bool = False,
    ) -> dict[str, Any]:
        """Proyección JSON-safe del contexto.

        Por defecto excluye `security` (runtime-only). `include_runtime=True`
        solo la incluye si se pide explícitamente en `sections`.
        """
        wanted = tuple(sections) if sections is not None else PERSISTED_SECTIONS
        out: dict[str, Any] = {}
        for name in wanted:
            key = normalize_section(name)
            if key is None:
                continue
            if key in RUNTIME_ONLY_SECTIONS and not include_runtime:
                continue
            value = getattr(self, key, None)
            if isinstance(value, (WorkflowIdentity, TriggerSnapshot)):
                value = value.to_dict()
            out[key] = jsonable(value)
        return out

    def snapshot(self) -> dict[str, Any]:
        """Proyección persistible (sin `security`)."""
        return self.to_dict()


__all__ = [
    "CONTEXT_SCHEMA_VERSION",
    "CONTEXT_SECTIONS",
    "LLM_VISIBLE_SECTIONS",
    "PERSISTED_SECTIONS",
    "RUNTIME_ONLY_SECTIONS",
    "SECTION_ALIASES",
    "TriggerSnapshot",
    "WRITABLE_SECTIONS",
    "WorkflowContext",
    "WorkflowIdentity",
    "is_writable_section",
    "normalize_section",
]
