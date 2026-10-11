# =============================================================================
# Budget Stop Reasons — «¿por qué se detuvo este run?» con razón precisa.
# =============================================================================
from __future__ import annotations

import asyncio
from typing import ClassVar
from uuid import uuid4

import pytest

from src.agents.runtime.agent_runtime import AgentRunRequest, AgentRuntime
from src.agents.tools.base import Tool, ToolContext, ToolResult
from src.agents.tools.registry import register_tool
from src.core.domain.entities import Agent, LLMResponse
from src.core.ports import LLMProvider
from src.runtime.run_budget import STOP_REASONS


@pytest.fixture(autouse=True)
def _runtime_flags_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "RUNTIME_TOOL_ROUTING_MODE", "off")
    monkeypatch.setattr(settings, "RUNTIME_TERMINATION_GATE", "off")
    monkeypatch.setattr(settings, "RUNTIME_ANSWER_GATE", "off")
    monkeypatch.setattr(settings, "RUNTIME_AGENT_JEV_LOOP", "off")
    monkeypatch.setattr(settings, "RUNTIME_SOURCE_AWARE_TOOLS", False)


class _EchoTool(Tool):
    name: ClassVar[str] = "echo"
    description: ClassVar[str] = "Devuelve el input."
    input_schema: ClassVar[dict] = {
        "type": "object",
        "required": ["text"],
        "properties": {"text": {"type": "string"}},
    }

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        return ToolResult(output=f"echo: {arguments['text']}")


class _SlowTool(Tool):
    name: ClassVar[str] = "slow"
    description: ClassVar[str] = "Duerme."
    input_schema: ClassVar[dict] = {"type": "object", "properties": {}}
    timeout_seconds: ClassVar[float] = 30.0

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        await asyncio.sleep(5)
        return ToolResult(output="never")


class _ScriptedLLM(LLMProvider):
    def __init__(self, contents: list[str], tokens: int = 10) -> None:
        self.contents = contents
        self.tokens = tokens
        self.calls = 0

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        idx = min(self.calls, len(self.contents) - 1)
        self.calls += 1
        return LLMResponse(
            content=self.contents[idx],
            model="fake",
            prompt_tokens=self.tokens,
            completion_tokens=self.tokens,
            total_tokens=self.tokens * 2,
        )

    async def generate_stream(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def embed(self, text, model=None):  # pragma: no cover
        raise NotImplementedError

    async def rerank(self, query, documents, model=None, top_n=None):  # pragma: no cover
        return []


def _agent(tools: list[str], limits: dict | None = None) -> Agent:
    config = {"limits": limits} if limits is not None else {}
    return Agent(
        id=uuid4(),
        organization_id=uuid4(),
        name="budget-agent",
        tools=tools,
        config_json=config,
    )


def _request(agent: Agent, message: str = "cuentame sobre el record 4") -> AgentRunRequest:
    return AgentRunRequest(agent=agent, message=message, role="admin")


def _stop_reason(result) -> str:
    state = result.run_state
    assert state is not None
    return state.budget.stop_reason


class TestBudgetStopReasons:
    @pytest.mark.asyncio
    async def test_max_steps_es_step_budget(self) -> None:
        register_tool(_EchoTool())
        llm = _ScriptedLLM(['{"tool": "echo", "arguments": {"text": "x"}}'])
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(_request(_agent(["echo"], {"max_steps": 1})))
        assert result.status == "limit_reached"
        assert _stop_reason(result) == "STEP_BUDGET"

    @pytest.mark.asyncio
    async def test_max_tool_calls_es_tool_budget(self) -> None:
        register_tool(_EchoTool())
        llm = _ScriptedLLM(['{"tool": "echo", "arguments": {"text": "x"}}'])
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(
            _request(_agent(["echo"], {"max_tool_calls": 1, "max_steps": 6}))
        )
        assert result.status == "limit_reached"
        assert _stop_reason(result) == "TOOL_BUDGET"

    @pytest.mark.asyncio
    async def test_tokens_es_token_budget(self) -> None:
        llm = _ScriptedLLM(['{"answer": "ok"}'], tokens=50)
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(
            _request(_agent([], {"max_tokens": 10, "max_total_tokens": 10}))
        )
        assert result.status == "limit_reached"
        assert _stop_reason(result) == "TOKEN_BUDGET"

    @pytest.mark.asyncio
    async def test_timeout_es_time_budget(self) -> None:
        register_tool(_SlowTool())
        llm = _ScriptedLLM(['{"tool": "slow", "arguments": {}}'])
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(
            _request(_agent(["slow"], {"max_execution_seconds": 0.2}))
        )
        assert result.status == "limit_reached"
        assert _stop_reason(result) == "TIME_BUDGET"

    @pytest.mark.asyncio
    async def test_circuito_abierto_es_provider_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.agents.runtime.agent_runtime as runtime_module

        async def _open_circuit(config: dict, organization_id) -> None:
            config["_circuit_open"] = True

        monkeypatch.setattr(runtime_module, "_circuit_check", _open_circuit)
        runtime = AgentRuntime(llm_provider=_ScriptedLLM(['{"answer": "x"}']))
        result = await runtime.run(_request(_agent([])))
        assert result.status == "error"
        assert _stop_reason(result) == "PROVIDER_FAILURE"

    def test_razones_declaradas(self) -> None:
        assert "STEP_BUDGET" in STOP_REASONS
        assert "PROVIDER_RATE_LIMIT" in STOP_REASONS
        assert "COST_BUDGET" in STOP_REASONS
