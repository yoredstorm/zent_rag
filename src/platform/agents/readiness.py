# =============================================================================
# Agent Readiness — readiness score 0-100 + checklist del ciclo de vida
# =============================================================================
# Servicio puro: recibe los agregados del agente y decide qué tan listo está
# para producción. Los pesos están documentados en cada criterio.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field

from src.core.domain.entities import Agent, AgentStatus, AgentVersionStatus


@dataclass(frozen=True)
class ReadinessItem:
    key: str
    label: str
    met: bool
    weight: int
    detail: str = ""


@dataclass(frozen=True)
class ReadinessResult:
    score: int
    items: list[ReadinessItem] = field(default_factory=list)

    def checklist(self) -> list[dict]:
        return [
            {
                "key": i.key,
                "label": i.label,
                "met": i.met,
                "weight": i.weight,
                "detail": i.detail,
            }
            for i in self.items
        ]


class AgentReadinessService:
    """Calcula readiness (0-100) de un agente a partir de sus agregados."""

    @staticmethod
    def compute(
        agent: Agent,
        *,
        has_eval_dataset: bool,
        has_healthy_deployment: bool,
        has_ready_version: bool,
        knowledge_configured: bool,
        has_data_source: bool,
        sql_expert_enabled: bool,
    ) -> ReadinessResult:
        model_configured = bool(agent.model)
        prompt_configured = bool((agent.system_prompt or "").strip())

        items: list[ReadinessItem] = [
            ReadinessItem(
                "model", "Modelo configurado", model_configured, 15,
                agent.model or "Sin modelo asignado",
            ),
            ReadinessItem(
                "prompt", "Prompt configurado", prompt_configured, 15,
                "Prompt en blanco" if not prompt_configured else "Prompt listo",
            ),
            ReadinessItem(
                "knowledge", "Knowledge configurada", knowledge_configured, 20,
                "Sin knowledge bases vinculadas" if not knowledge_configured else "KB vinculada",
            ),
            ReadinessItem(
                "datasource", "Fuente de datos conectada", has_data_source, 10,
                "Sin fuentes de datos" if not has_data_source else "Fuente disponible",
            ),
            ReadinessItem(
                "evaluation", "Dataset de evaluación", has_eval_dataset, 10,
                "Sin datasets" if not has_eval_dataset else "Dataset presente",
            ),
            ReadinessItem(
                "security", "Chequeos de seguridad", bool(agent.tools), 10,
                "Sin tools" if not agent.tools else f"{len(agent.tools)} tools",
            ),
            ReadinessItem(
                "version", "Versión lista", has_ready_version, 10,
                "Sin versión ready/production" if not has_ready_version else "Versión lista",
            ),
            ReadinessItem(
                "deployment", "Deployment activo", has_healthy_deployment, 10,
                "Sin deployment healthy" if not has_healthy_deployment else "Deployment healthy",
            ),
            # Items informativos del checklist Go Live (no pesan en el score).
            ReadinessItem(
                "rate_limits", "Rate limits configurados", True, 0,
                "Rate limit por organización activo",
            ),
            ReadinessItem(
                "observability", "Observabilidad activa", True, 0,
                "Usage events + audit + métricas habilitados",
            ),
        ]
        score = sum(i.weight for i in items if i.met)
        score = max(0, min(100, score))
        return ReadinessResult(score=score, items=items)

    @staticmethod
    def compute_status(
        agent: Agent,
        *,
        has_healthy_deployment: bool,
        has_ready_version: bool,
    ) -> AgentStatus:
        """Estado del ciclo de vida computado (archive es explícito)."""
        if agent.status == AgentStatus.ARCHIVED:
            return AgentStatus.ARCHIVED
        if has_healthy_deployment:
            return AgentStatus.DEPLOYED
        if has_ready_version:
            return AgentStatus.READY
        if bool(agent.model) and bool((agent.system_prompt or "").strip()):
            return AgentStatus.CONFIGURED
        return AgentStatus.DRAFT


# Estados de versión que cuentan como "lista" para readiness/status.
READY_VERSION_STATUSES = {
    AgentVersionStatus.READY,
    AgentVersionStatus.STAGING,
    AgentVersionStatus.PRODUCTION,
}
