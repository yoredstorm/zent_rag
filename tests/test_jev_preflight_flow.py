# =============================================================================
# JEV Preflight end-to-end en el RAG orchestrator.
# =============================================================================
# Prueba lo que importa: el juicio previo corre ANTES de pagar el generador.
# - Si el análisis está incompleto y falta un dato crítico, el LLM caro NO se
#   invoca y la respuesta es la abstención estructurada (§59).
# - Si el juicio dice que la conclusión ya está establecida, el generador se
#   omite (§18) y el tier queda registrado.
# - Si todo está listo, la generación ocurre normalmente y el flow publica el
#   pack de juicios (§34, §35, §43).
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from src.core.domain.entities import (
    LLMResponse,
    Organization,
    OrganizationStatus,
    RetrievalChunk,
    RetrievalContext,
)
from src.decision.preflight import ACTION_ABSTAIN
from src.rag.preflight_hook import OrchestratorPreflightHook, PreflightSettings


class FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    @staticmethod
    def _hash_query(organization_id: str, query: str, model: str, role: str = "") -> str:
        return f"hash:{organization_id}:{query}:{model}:{role}"

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ttl_seconds: int = 300) -> None:
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.store

    async def append_to_list(self, key: str, value: str, ttl_seconds: int = 3600) -> None:
        self.lists.setdefault(key, []).append(value)

    async def get_list(self, key: str) -> list[str]:
        return list(self.lists.get(key, []))

    async def trim_list(self, key: str, max_items: int) -> None:
        self.lists[key] = self.lists.get(key, [])[-max_items:]

    async def incr(self, key: str, ttl_seconds: int | None = None, by: int = 1) -> int:
        current = int(self.store.get(key, 0))
        self.store[key] = str(current + by)
        return current + by


class FakeOrganizationRepo:
    def __init__(self, organization: Organization) -> None:
        self.organization = organization

    async def get_by_id(self, organization_id: UUID) -> Organization | None:
        return self.organization if organization_id == self.organization.id else None

    async def check_rate_limit(self, organization_id: UUID) -> bool:
        return True

    async def log_usage(self, **kwargs: Any) -> None:
        return None


class FakeLLM:
    def __init__(self, content: str = "Respuesta generada") -> None:
        self.calls: list[dict] = []
        self.content = content

    async def generate(self, **kwargs: Any) -> LLMResponse:
        self.calls.append(kwargs)
        return LLMResponse(
            content=self.content, model="fake-llm", total_tokens=12, latency_ms=1.0
        )


class FakeEmbed:
    async def embed(
        self, text: str | list[str], model: str | None = None
    ) -> list[float] | list[list[float]]:
        if isinstance(text, list):
            return [[0.1] * 8 for _ in text]
        return [0.1] * 8


class FakeVectorStore:
    def __init__(self, context: RetrievalContext) -> None:
        self.context = context

    async def search(self, **kwargs: Any) -> RetrievalContext:
        return self.context

    async def upsert(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def upsert_batch(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def delete_by_organization(self, organization_id: UUID) -> None:
        return None


def _organization() -> Organization:
    return Organization(
        id=uuid4(),
        name="Test",
        status=OrganizationStatus.ACTIVE,
    )


def _retrieval(*, score: float = 0.9) -> RetrievalContext:
    return RetrievalContext(
        chunks=[
            RetrievalChunk(
                document_id=uuid4(),
                content="Registro 1 OPEN | Registro 2 UPDATE | Registro 3 CLOSE",
                score=score,
                metadata={"filename": "secuencia.txt"},
            )
        ],
        query_embedding=[0.1] * 8,
        retrieval_latency_ms=1.0,
    )


#: Preguntas cuyo default "sano" es NO (nada falta, nada sobra, nada es caro).
_NEGATIVE_BY_DEFAULT = {
    "critical_fact_missing",
    "critical_conflict_unresolved",
    "critical_transition_missing",
    "critical_unknown_remaining",
    "simple_lookup_sufficient",
    "expensive_llm_needed",
    "needs_complex_reasoning_model",
    "simple_deterministic_answer_possible",
    "answer_contains_unsupported_conclusion",
    "answer_overstates_uncertainty",
    "answer_ignores_material_conflict",
}


class PackJudge:
    """Judge que responde por id de pregunta con valores fijos.

    El default es "todo en orden": las preguntas negativas (¿falta algo?,
    ¿hace falta el modelo caro?) responden NO y el resto responde YES.
    """

    def __init__(self, noul_default: float = 0.9, answers: dict | None = None) -> None:
        self.calls = 0
        self.noul_default = noul_default
        self.answers = answers or {}

    def _default_noul(self, question_id: str) -> float:
        if question_id in _NEGATIVE_BY_DEFAULT or question_id.startswith("critical_"):
            return round(1.0 - self.noul_default, 4)
        return self.noul_default

    async def judge(self, *, state, questions, context=None):
        self.calls += 1
        answers: dict[str, Any] = {}
        for question_id, spec in questions.items():
            if question_id in self.answers:
                answers[question_id] = self.answers[question_id]
                continue
            qtype = str((spec or {}).get("type") or "noul")
            if qtype == "choice":
                criteria = (spec or {}).get("criteria") or {}
                choice = next(iter(criteria), "generate_answer")
                answers[question_id] = {
                    "type": "choice",
                    "choice": choice,
                    "confidence": 0.9,
                    "probabilities": {choice: 0.9},
                }
            elif qtype == "score":
                answers[question_id] = {"type": "score", "score": 2.5, "confidence": 0.9}
            else:
                answers[question_id] = {
                    "type": "noul",
                    "noul": self._default_noul(question_id),
                }
        return {
            "model": "jev-test",
            "answers": answers,
            "usage": {"input_tokens": 30, "output_tokens": 10},
        }


def _build_orchestrator(*, llm: FakeLLM, vector_store: FakeVectorStore, hook):
    from src.agents.runtime.orchestrator import RAGOrchestrator

    return RAGOrchestrator(
        organization_repo=FakeOrganizationRepo(_organization()),
        vector_store=vector_store,
        llm_provider=llm,
        embedding_provider=FakeEmbed(),
        cache_provider=FakeCache(),
        score_threshold=0.0,
        preflight_hook=hook,
    )


async def _execute(orchestrator, organization_id: UUID):
    return await orchestrator.execute(
        organization_id=organization_id,
        user_id=uuid4(),
        query="¿El registro necesita un CLOSE?",
        role="admin",
        model="fake-llm",
    )


@pytest.fixture(autouse=True)
def _isolated_preflight_state():
    """Cada test arranca con el buffer de observaciones y la política limpios."""
    from src.decision import preflight_report
    from src.decision.confidence import reset_policy

    reset_policy()
    preflight_report.clear_observations()
    yield
    preflight_report.clear_observations()


@pytest.mark.asyncio
async def test_juicio_incompleto_no_invoca_el_generador() -> None:
    judge = PackJudge(
        answers={
            "analysis_complete": {"type": "noul", "noul": 0.04},
            "critical_fact_missing": {"type": "noul", "noul": 0.95},
            "next_action": {
                "type": "choice",
                "choice": ACTION_ABSTAIN,
                "confidence": 0.9,
                "probabilities": {ACTION_ABSTAIN: 0.9},
            },
        }
    )
    hook = OrchestratorPreflightHook(
        PreflightSettings(mode="on", reasoning_first=False), judge=judge
    )
    llm = FakeLLM()
    orchestrator = _build_orchestrator(
        llm=llm, vector_store=FakeVectorStore(_retrieval(score=0.5)), hook=hook
    )
    result = await _execute(orchestrator, orchestrator._organization_repo.organization.id)

    assert llm.calls == []  # el LLM caro NO se invocó (§59)
    assert result.llm_response is not None
    assert result.llm_response.model == "preflight"
    assert result.llm_response.content
    flow = result.flow if isinstance(result.flow, dict) else {}
    packs = [
        event
        for event in flow.get("events", [])
        if isinstance(event, dict) and event.get("kind") == "jev_pack"
    ]
    assert packs, "la historia debe publicar el pack de juicio"
    pre_generation = next(
        pack
        for pack in packs
        if (pack.get("metrics") or {}).get("phase") == "pre_generation"
    )
    assert pre_generation["decision"]["allow_generation"] is False
    assert pre_generation["decision"]["action"] in ("abstain", "retrieve_more")


@pytest.mark.asyncio
async def test_juicio_listo_genera_con_tier_barato() -> None:
    judge = PackJudge(
        answers={
            "generation_tier": {
                "type": "choice",
                "choice": "small",
                "confidence": 0.9,
                "probabilities": {"small": 0.9},
            },
            "expensive_llm_needed": {"type": "noul", "noul": 0.05},
            "needs_complex_reasoning_model": {"type": "noul", "noul": 0.05},
            "simple_deterministic_answer_possible": {"type": "noul", "noul": 0.05},
        }
    )
    hook = OrchestratorPreflightHook(
        PreflightSettings(mode="on", reasoning_first=False, small_model="cheap-model"),
        judge=judge,
    )
    llm = FakeLLM()
    orchestrator = _build_orchestrator(
        llm=llm, vector_store=FakeVectorStore(_retrieval(score=0.9)), hook=hook
    )
    result = await _execute(orchestrator, orchestrator._organization_repo.organization.id)

    assert len(llm.calls) == 1
    assert llm.calls[0]["model"] == "cheap-model"  # tier pequeño aplicado
    assert result.llm_response is not None
    assert result.llm_response.content == "Respuesta generada"


@pytest.mark.asyncio
async def test_sin_hook_el_camino_legacy_no_cambia() -> None:
    llm = FakeLLM()
    orchestrator = _build_orchestrator(
        llm=llm, vector_store=FakeVectorStore(_retrieval()), hook=None
    )
    result = await _execute(orchestrator, orchestrator._organization_repo.organization.id)
    assert len(llm.calls) == 1
    assert result.llm_response is not None


@pytest.mark.asyncio
async def test_shadow_no_cambia_la_ejecucion_pero_registra_el_juicio() -> None:
    judge = PackJudge(
        answers={
            "analysis_complete": {"type": "noul", "noul": 0.02},
            "critical_fact_missing": {"type": "noul", "noul": 0.98},
            "next_action": {
                "type": "choice",
                "choice": ACTION_ABSTAIN,
                "confidence": 0.95,
                "probabilities": {ACTION_ABSTAIN: 0.95},
            },
        }
    )
    hook = OrchestratorPreflightHook(
        PreflightSettings(mode="shadow", reasoning_first=False), judge=judge
    )
    llm = FakeLLM()
    orchestrator = _build_orchestrator(
        llm=llm, vector_store=FakeVectorStore(_retrieval(score=0.5)), hook=hook
    )
    result = await _execute(orchestrator, orchestrator._organization_repo.organization.id)

    # Shadow: la generación ocurre igual (§64).
    assert len(llm.calls) == 1
    flow = result.flow if isinstance(result.flow, dict) else {}
    block = flow.get("jev_preflight")
    assert isinstance(block, dict)
    assert block["mode"] == "shadow"
    decisions = block.get("decisions") or []
    assert decisions and decisions[0]["applied"] is False
