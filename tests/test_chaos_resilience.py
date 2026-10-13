# =============================================================================
# Chaos / failure testing — matriz de resiliencia (F11).
# =============================================================================
# Hermético (sin red): se inyectan fallos en los límites reales y se verifica
# la política documentada de cada componente:
#   - LLM caído / 429 → el run NO propaga; cierra con estado honesto.
#   - Tool timeout / fallo permanente → observación, sin retry ciego.
#   - Engine JEV roto → el run sigue con reglas.
#   - Redis caído → la caché es fail-soft (no rompe la respuesta).
#   - Reranker caído → orden crudo, sin excepción.
#   - Retry del router → amplificación acotada (1 reintento por candidato).
from __future__ import annotations

import asyncio
from typing import ClassVar
from uuid import uuid4

import pytest

from src.agents.runtime.agent_runtime import AgentRunRequest, AgentRuntime
from src.agents.tools.base import Tool, ToolResult
from src.agents.tools.registry import register_tool
from src.core.domain.entities import Agent, LLMResponse, RetrievalChunk
from src.core.ports import LLMProvider
from src.rag.reranking.reranker import LLMReranker


@pytest.fixture(autouse=True)
def _runtime_flags_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "RUNTIME_TOOL_ROUTING_MODE", "off")
    monkeypatch.setattr(settings, "RUNTIME_TERMINATION_GATE", "off")
    monkeypatch.setattr(settings, "RUNTIME_ANSWER_GATE", "off")
    monkeypatch.setattr(settings, "RUNTIME_AGENT_JEV_LOOP", "off")
    monkeypatch.setattr(settings, "RUNTIME_SOURCE_AWARE_TOOLS", False)


class _BrokenLLM(LLMProvider):
    """Proveedor caído: todos los intentos revientan."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error or RuntimeError("provider down")

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        self.calls += 1
        raise self.error

    async def generate_stream(self, *args, **kwargs):  # pragma: no cover
        self.calls += 1
        raise self.error

    async def embed(self, text, model=None):  # pragma: no cover
        raise self.error

    async def rerank(self, query, documents, model=None, top_n=None):  # pragma: no cover
        return []


class _RateLimitedLLM(_BrokenLLM):
    """429 del proveedor (no reintentable en el runtime: lo hace el router)."""

    def __init__(self) -> None:
        exc = RuntimeError("429 too many requests")
        exc.status_code = 429  # type: ignore[attr-defined]
        super().__init__(exc)


class _ScriptedLLM(LLMProvider):
    def __init__(self, contents: list[str]) -> None:
        self.contents = contents
        self.calls = 0

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        idx = min(self.calls, len(self.contents) - 1)
        self.calls += 1
        return LLMResponse(
            content=self.contents[idx],
            model="fake",
            prompt_tokens=5,
            completion_tokens=5,
            total_tokens=10,
        )

    async def generate_stream(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def embed(self, text, model=None):  # pragma: no cover
        raise NotImplementedError

    async def rerank(self, query, documents, model=None, top_n=None):  # pragma: no cover
        return []


class _PermanentFailTool(Tool):
    name: ClassVar[str] = "chaos_permanent"
    description: ClassVar[str] = "Falla siempre de forma permanente."
    input_schema: ClassVar[dict] = {"type": "object", "properties": {}}

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, ctx, arguments) -> ToolResult:
        self.calls += 1
        # Sin marcadores de error transitorio: la tool no aplica y no se
        # reintenta para esta pregunta.
        return ToolResult(error="boom")


class _TimeoutTool(Tool):
    name: ClassVar[str] = "chaos_timeout"
    description: ClassVar[str] = "No responde nunca."
    input_schema: ClassVar[dict] = {"type": "object", "properties": {}}
    timeout_seconds: ClassVar[float] = 0.05

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, ctx, arguments) -> ToolResult:
        self.calls += 1
        await asyncio.sleep(5)
        return ToolResult(output="nunca")


def _agent(**overrides) -> Agent:
    params = {
        "id": uuid4(),
        "organization_id": uuid4(),
        "name": "chaos-agent",
        "tools": ["chaos_permanent"],
    }
    params.update(overrides)
    return Agent(**params)


class TestLLMCaido:
    @pytest.mark.asyncio
    async def test_provider_down_no_propaga_y_cierra_honesto(self) -> None:
        llm = _BrokenLLM()
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(AgentRunRequest(agent=_agent(), message="¿hay stock?", role="admin"))
        assert result.status == "error"
        assert llm.calls == 1  # el runtime no reintenta: lo hace el router/proveedor
        assert isinstance(result.answer, str)
        assert any(step.get("type") == "error" for step in result.steps)
        # Sin llamada exitosa no hay línea `llm` ni tokens contabilizados.
        assert not [s for s in result.steps if s.get("type") == "llm"]
        assert int(getattr(result, "total_tokens", 0) or 0) == 0

    @pytest.mark.asyncio
    async def test_429_no_multiplica_llamadas(self) -> None:
        llm = _RateLimitedLLM()
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(
            AgentRunRequest(agent=_agent(), message="¿cuál es la política?", role="admin")
        )
        assert result.status == "error"
        assert llm.calls == 1

    def test_provider_failure_esta_clasificado(self) -> None:
        from src.runtime.failure_taxonomy import FailureClass, classify_stop_reason

        info = classify_stop_reason("PROVIDER_FAILURE")
        assert info is not None
        assert info.failure_class is FailureClass.PROVIDER_FAILURE
        assert info.operational is True


class TestToolsCaidas:
    @pytest.mark.asyncio
    async def test_timeout_no_se_reintenta_y_el_run_define(self) -> None:
        tool = _TimeoutTool()
        register_tool(tool)
        llm = _ScriptedLLM(
            [
                '{"tool": "chaos_timeout", "arguments": {}}',
                '{"answer": "responde con lo disponible"}',
            ]
        )
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(
            AgentRunRequest(
                agent=_agent(tools=["chaos_timeout"]),
                message="cuentame sobre el record 4",
                role="admin",
            )
        )
        assert tool.calls == 1  # un timeout no dispara reintentos ciegos
        tool_steps = [s for s in result.steps if s.get("type") == "tool_call"]
        assert any("timed out" in str(s.get("error") or "") for s in tool_steps)
        assert result.answer

    @pytest.mark.asyncio
    async def test_fallo_permanente_no_se_reintenta(self) -> None:
        tool = _PermanentFailTool()
        register_tool(tool)
        llm = _ScriptedLLM(
            [
                '{"tool": "chaos_permanent", "arguments": {}}',
                '{"tool": "chaos_permanent", "arguments": {}}',
                '{"answer": "sin datos de esa herramienta"}',
            ]
        )
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(
            AgentRunRequest(
                agent=_agent(tools=["chaos_permanent"]),
                message="cuentame sobre el record 4",
                role="admin",
            )
        )
        assert tool.calls == 1  # el segundo pedido lo bloquea el guard de tools fallidas
        assert result.status == "completed"
        assert result.answer


class TestDependenciasCaidas:
    @pytest.mark.asyncio
    async def test_engine_jev_roto_el_run_sigue_con_reglas(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _explode():
            raise RuntimeError("jev unavailable")

        import src.decision.service as decision_service

        monkeypatch.setattr(decision_service, "get_decision_engine", _explode)
        llm = _ScriptedLLM(['{"answer": "respuesta por reglas"}'])
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(
            AgentRunRequest(agent=_agent(tools=[]), message="¿qué es ZENT?", role="admin")
        )
        assert result.status == "completed"
        assert result.answer

    @pytest.mark.asyncio
    async def test_redis_caido_la_cache_es_fail_soft(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.infrastructure.redis.cache as cache_module

        async def _no_redis():
            raise ConnectionError("redis down")

        monkeypatch.setattr(cache_module, "_get_redis", _no_redis)
        cache = cache_module.RedisCache()
        assert await cache.get("k") is None
        await cache.set("k", "v", ttl_seconds=5)  # no lanza
        assert await cache.get_list("k") == []
        await cache.delete("k")  # no lanza
        assert await cache.exists("k") is False

    @pytest.mark.asyncio
    async def test_reranker_caido_devuelve_orden_crudo(self) -> None:
        chunks = [
            RetrievalChunk(document_id=uuid4(), content=f"doc {i}", score=0.9 - i / 10)
            for i in range(3)
        ]
        reranker = LLMReranker(llm_provider=_BrokenLLM())
        out = await reranker.rerank(query="¿política de cambios?", chunks=chunks, top_n=3)
        assert [c.document_id for c in out] == [c.document_id for c in chunks]


class TestAmplificacionDeRetry:
    @pytest.mark.asyncio
    async def test_retry_acotado_por_candidato(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.infrastructure.llm import router as router_module
        from src.infrastructure.llm.router import ResolvedRoute, generate_routed

        monkeypatch.setattr(router_module, "_TRANSIENT_RETRY_SECONDS", 0.0)
        calls: list[str] = []

        class _Transient(Exception):
            status_code = 529

            def __init__(self) -> None:
                super().__init__("model busy")

        async def _generate(prompt: str, *, model: str, **kwargs: object):
            calls.append(model)
            raise _Transient()

        route = ResolvedRoute(primary="prov-a/x", fallback="prov-b/y", alias=None)
        with pytest.raises(_Transient) as excinfo:
            await generate_routed(_generate, prompt="p", route=route)
        # 1 reintento por candidato: 2 candidatos → 4 intentos máximo.
        assert len(calls) == 4
        attempts = getattr(excinfo.value, "llm_attempts", [])
        assert len(attempts) == 4
        assert all(item["status"] == "provider_error" for item in attempts)

    def test_factor_de_amplificacion_documentado(self) -> None:
        """external_requests / logical_request <= candidatos x (1 + retry)."""
        from src.infrastructure.llm.router import ResolvedRoute

        route = ResolvedRoute(primary="prov-a/x", fallback="prov-b/y", alias=None)
        candidates = len(route.candidates())
        max_attempts = candidates * 2  # 1 reintento por candidato
        assert max_attempts == 4
