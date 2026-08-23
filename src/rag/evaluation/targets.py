# =============================================================================
# Evaluation Targets — adaptadores de ejecución (RAG pipeline y Agent Runtime)
# =============================================================================
# Un target responde a la pregunta de cada caso y devuelve un TargetResult
# con la respuesta, contexto recuperado, uso de tokens y latencias. El runner
# solo depende del protocolo EvalTarget (testeable con fakes).
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from src.agents.runtime.agent_runtime import AgentRunRequest, AgentRuntime
from src.core.domain.entities import Agent, RetrievalContext


@dataclass(kw_only=True)
class TargetResult:
    """Resultado crudo de ejecutar un caso contra el sistema evaluado."""

    answer: str
    retrieved: list[dict] = field(default_factory=list)
    retrieval_latency_ms: float = 0.0
    llm_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    status: str = "completed"
    method: str = "rag"
    cost: float = 0.0
    error: str | None = None


def _context_to_dicts(context: RetrievalContext | None) -> list[dict]:
    if context is None:
        return []
    return [
        {
            "document_id": str(chunk.document_id),
            "content": chunk.content[:2000],
            "score": round(float(chunk.score), 4),
            "metadata": dict(chunk.metadata or {}),
        }
        for chunk in context.chunks
    ]


class EvalTarget(Protocol):
    """Protocolo de ejecución para el runner de evaluación."""

    target_type: str
    target_name: str
    target_id: UUID | None

    async def execute(self, question: str, metadata: dict) -> TargetResult: ...


class RAGTarget:
    """Ejecuta casos contra el RAG Orchestrator (retrieval + generación)."""

    target_type = "rag"

    def __init__(
        self,
        orchestrator,
        organization_id: UUID,
        user_id: UUID,
        *,
        target_id: UUID | None = None,
        target_name: str = "",
    ) -> None:
        self._orchestrator = orchestrator
        self._organization_id = organization_id
        self._user_id = user_id
        self.target_id = target_id
        self.target_name = target_name or "rag-pipeline"

    async def execute(self, question: str, metadata: dict) -> TargetResult:
        role = str(metadata.get("role") or "admin")
        top_k = int(metadata.get("top_k") or 200)
        model = metadata.get("model")
        temperature = float(metadata.get("temperature") or 0.3)
        try:
            result = await self._orchestrator.execute(
                organization_id=self._organization_id,
                user_id=self._user_id,
                query=question,
                model=model,
                temperature=temperature,
                top_k=top_k,
                use_cache=False,
                role=role,
            )
        except Exception as exc:
            return TargetResult(
                answer="",
                status="error",
                error=str(exc),
            )

        llm = result.llm_response
        ctx = result.retrieval_context
        return TargetResult(
            answer=llm.content if llm else "",
            retrieved=_context_to_dicts(ctx),
            retrieval_latency_ms=round(
                ctx.retrieval_latency_ms if ctx else 0.0, 2
            ),
            llm_latency_ms=round(llm.latency_ms if llm else 0.0, 2),
            total_latency_ms=round(result.total_latency_ms, 2),
            prompt_tokens=llm.prompt_tokens if llm else 0,
            completion_tokens=llm.completion_tokens if llm else 0,
            total_tokens=llm.total_tokens if llm else 0,
            model=llm.model if llm else "",
            status=str(result.status),
            method=result.method,
            error=result.error_message,
        )


class AgentTarget:
    """Ejecuta casos contra el Agent Runtime (ReAct loop con tools)."""

    target_type = "agent"

    def __init__(
        self,
        runtime: AgentRuntime,
        agent: Agent,
        organization_id: UUID,
        user_id: UUID,
        *,
        org_config: dict | None = None,
        permissions: frozenset[str] | None = None,
    ) -> None:
        self._runtime = runtime
        self._agent = agent
        self._organization_id = organization_id
        self._user_id = user_id
        self._org_config = org_config or {}
        self._permissions = permissions if permissions is not None else frozenset()
        self.target_id: UUID | None = agent.id
        self.target_name = agent.name or str(agent.id)

    async def execute(self, question: str, metadata: dict) -> TargetResult:
        role = str(metadata.get("role") or "admin")
        try:
            result = await self._runtime.run(
                AgentRunRequest(
                    agent=self._agent,
                    message=question,
                    user_id=self._user_id,
                    role=role,
                    permissions=self._permissions,
                    org_config=self._org_config,
                )
            )
        except Exception as exc:
            return TargetResult(
                answer="",
                status="error",
                error=str(exc),
            )

        # El contexto del agente vive en observaciones de tools retrieval.
        retrieved: list[dict] = []
        for step in result.steps:
            if step.get("type") == "tool_call" and step.get("output"):
                retrieved.append(
                    {
                        "document_id": None,
                        "content": str(step["output"])[:2000],
                        "score": 0.0,
                        "metadata": {"tool": step.get("tool", "")},
                    }
                )

        return TargetResult(
            answer=result.answer,
            retrieved=retrieved,
            total_latency_ms=round(result.total_latency_ms, 2),
            total_tokens=result.total_tokens,
            model=self._agent.model or "",
            status=result.status,
            method="agent",
            cost=round(result.cost, 6),
            error=None if result.status == "completed" else "limit_reached_or_error",
        )
