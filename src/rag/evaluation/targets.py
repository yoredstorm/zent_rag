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
    answerability_status: str | None = None  # FASE 23: estado del gate (si aplica)


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


def _agent_answerability_status(result) -> str | None:
    """Estado formal aproximado del gate, para métricas de answerability.

    El runtime del agente no expone un AnswerabilityStatus propio: se deriva
    del veredicto JEV (abstain) y del estado del run. Sin esto,
    `answerability_accuracy` nunca se calcula en runs contra agentes.
    """
    from src.runtime.answer_gate import INSUFFICIENT_ANSWER, RETRIEVAL_UNAVAILABLE_ANSWER

    verdicts = {
        str(step.get("verdict") or "").lower()
        for step in (result.steps or [])
        if isinstance(step, dict) and str(step.get("type") or "") == "answer_gate"
    }
    if "abstain" in verdicts:
        return "HUMAN_REVIEW_REQUIRED"
    if any(
        str(decision.get("action") or "").lower() == "abstain"
        for decision in (result.jev_decisions or [])
        if isinstance(decision, dict)
    ):
        return "HUMAN_REVIEW_REQUIRED"
    answer = str(result.answer or "").strip()
    if answer in (INSUFFICIENT_ANSWER, RETRIEVAL_UNAVAILABLE_ANSWER):
        return "HUMAN_REVIEW_REQUIRED"
    if result.status == "completed":
        return "ANSWERABLE"
    return None


def _retrieved_from_evidence(result) -> list[dict]:
    """Chunks reales del registry de evidencia del run.

    Prefiere `result.evidence_full` (contenido completo, el mismo que vio el
    generador) y cae a `result.evidence` (excerpt 400) si no está. Sin el
    contenido completo el juez marca como alucinación lo que sí está en la
    evidencia, sólo que truncada. El orden sale de la última selección de
    evidencia: así el índice corresponde al `[Doc N]` que vio el generador.
    """
    full = getattr(result, "evidence_full", None)
    if isinstance(full, list) and full:
        items: list | None = [item for item in full if isinstance(item, dict)]
    else:
        evidence = getattr(result, "evidence", None)
        items = evidence.get("items") if isinstance(evidence, dict) else None
    if not isinstance(items, list) or not items:
        return []
    by_id = {
        str(item.get("evidence_id")): item
        for item in items
        if isinstance(item, dict) and item.get("evidence_id")
    }
    order: list[str] = []
    for step in getattr(result, "steps", []) or []:
        if not isinstance(step, dict):
            continue
        selection = step.get("evidence")
        ids = selection.get("evidence_ids") if isinstance(selection, dict) else None
        if isinstance(ids, list) and ids:
            order = [str(item_id) for item_id in ids]
    ordered = [by_id[item_id] for item_id in order if item_id in by_id]
    if not ordered:
        ordered = [item for item in items if isinstance(item, dict)]
    chunks: list[dict] = []
    for item in ordered:
        content = str(item.get("content") or item.get("excerpt") or "").strip()
        if not content:
            continue
        metadata = {
            key: item[key]
            for key in (
                "evidence_id",
                "title",
                "page",
                "section_path",
                "retrieval",
                "source_id",
            )
            if item.get(key) is not None
        }
        chunks.append(
            {
                "document_id": item.get("document_id") or item.get("chunk_id"),
                "content": content,
                "score": float(item.get("score") or 0.0),
                "metadata": metadata,
            }
        )
    return chunks


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
            answerability_status=(
                result.answerability.status.value
                if getattr(result, "answerability", None) is not None
                else None
            ),
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

        # Contexto real del run: fragmentos del registry de evidencia. Fallback
        # legacy a observaciones de tools si el run no registró evidencia.
        retrieved = _retrieved_from_evidence(result)
        if not retrieved:
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
            answerability_status=_agent_answerability_status(result),
        )
