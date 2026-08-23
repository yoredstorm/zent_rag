# =============================================================================
# Agent Runtime — loop ReAct, tools, guardrails
# =============================================================================
from __future__ import annotations

import asyncio
from typing import ClassVar
from uuid import uuid4

import pytest

from src.agents.runtime.agent_runtime import (
    AgentRunRequest,
    AgentRuntime,
    _parse_action,
)
from src.agents.tools.base import Tool, ToolContext, ToolResult
from src.agents.tools.registry import register_tool
from src.core.domain.entities import Agent, LLMResponse
from src.core.ports import LLMProvider


class _FakeLLM(LLMProvider):
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


class _EchoTool(Tool):
    name: ClassVar[str] = "echo"
    description: ClassVar[str] = "Devuelve el input."
    input_schema: ClassVar[dict] = {
        "type": "object",
        "required": ["text"],
        "properties": {"text": {"type": "string"}},
    }

    def __init__(self) -> None:
        self.calls: list[ToolContext] = []

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        self.calls.append(ctx)
        return ToolResult(output=f"echo: {arguments['text']}")


class _SlowTool(Tool):
    name: ClassVar[str] = "slow"
    description: ClassVar[str] = "Duerme."
    input_schema: ClassVar[dict] = {"type": "object", "properties": {}}
    timeout_seconds: ClassVar[float] = 0.1

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        await asyncio.sleep(5)
        return ToolResult(output="never")


def _agent(**overrides) -> Agent:
    params = {
        "id": uuid4(),
        "organization_id": uuid4(),
        "name": "test-agent",
        "tools": ["echo"],
    }
    params.update(overrides)
    return Agent(**params)


def _request(agent: Agent, message: str = "hola") -> AgentRunRequest:
    return AgentRunRequest(agent=agent, message=message, role="admin")


class TestParseAction:
    def test_parses_tool_json(self) -> None:
        action = _parse_action('{"tool": "echo", "arguments": {"text": "x"}}')
        assert action == {"tool": "echo", "arguments": {"text": "x"}}

    def test_parses_answer_json(self) -> None:
        action = _parse_action('{"answer": "hola"}')
        assert action == {"answer": "hola"}

    def test_fallback_plain_text_as_answer(self) -> None:
        action = _parse_action("No JSON here")
        assert action == {"answer": "No JSON here"}

    def test_extracts_json_from_noise(self) -> None:
        action = _parse_action('Sure! {"tool": "echo", "arguments": {}} ok')
        assert action["tool"] == "echo"


class TestReActLoop:
    @pytest.mark.asyncio
    async def test_full_loop_tool_then_answer(self) -> None:
        register_tool(_EchoTool())
        llm = _FakeLLM(
            [
                '{"tool": "echo", "arguments": {"text": "hello"}}',
                '{"answer": "Todo listo"}',
            ]
        )
        agent = _agent()
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(_request(agent, "saluda"))

        assert result.status == "completed"
        assert result.answer == "Todo listo"
        assert result.total_tokens == 40
        tool_steps = [s for s in result.steps if s["type"] == "tool_call"]
        assert len(tool_steps) == 1
        assert tool_steps[0]["tool"] == "echo"
        assert "echo: hello" in tool_steps[0]["output"]

    @pytest.mark.asyncio
    async def test_direct_answer_without_tools(self) -> None:
        llm = _FakeLLM(['{"answer": "Sin tools"}'])
        agent = _agent(tools=[])
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(_request(agent))
        assert result.status == "completed"
        assert result.answer == "Sin tools"

    @pytest.mark.asyncio
    async def test_max_steps_reached(self) -> None:
        register_tool(_EchoTool())
        llm = _FakeLLM(['{"tool": "echo", "arguments": {"text": "x"}}'] * 20)
        agent = _agent(config_json={"max_steps": 2})
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(_request(agent, "loop"))
        assert result.status == "limit_reached"
        assert any(s.get("detail") == "max_steps reached" for s in result.steps)

    @pytest.mark.asyncio
    async def test_tool_error_becomes_observation_and_continues(self) -> None:
        class _FailingTool(Tool):
            name: ClassVar[str] = "failing"
            description: ClassVar[str] = "Falla."
            input_schema: ClassVar[dict] = {"type": "object", "properties": {}}

            async def execute(self, ctx, arguments) -> ToolResult:
                return ToolResult(error="boom")

        register_tool(_FailingTool())
        llm = _FakeLLM(
            [
                '{"tool": "failing", "arguments": {}}',
                '{"answer": "recuperado"}',
            ]
        )
        agent = _agent(tools=["failing"])
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(_request(agent))
        assert result.status == "completed"
        assert result.answer == "recuperado"
        tool_steps = [s for s in result.steps if s["type"] == "tool_call"]
        assert tool_steps[0]["error"] == "boom"

    @pytest.mark.asyncio
    async def test_tool_timeout_controlled(self) -> None:
        register_tool(_SlowTool())
        llm = _FakeLLM(['{"tool": "slow", "arguments": {}}', '{"answer": "ok"}'])
        agent = _agent(tools=["slow"])
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(_request(agent))
        tool_steps = [s for s in result.steps if s["type"] == "tool_call"]
        assert "timed out" in tool_steps[0]["error"]

    @pytest.mark.asyncio
    async def test_max_tokens_guardrail(self) -> None:
        llm = _FakeLLM(['{"tool": "echo", "arguments": {}}'] * 5, tokens=500)
        agent = _agent(config_json={"max_tokens": 100})
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(_request(agent))
        assert result.status == "limit_reached"
        assert any(s.get("detail") == "max_tokens exceeded" for s in result.steps)

    @pytest.mark.asyncio
    async def test_max_cost_guardrail(self) -> None:
        llm = _FakeLLM(['{"tool": "echo", "arguments": {}}'] * 5, tokens=500)
        agent = _agent(config_json={"max_cost": 0.0001})
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(_request(agent))
        assert result.status == "limit_reached"
        assert any(s.get("detail") == "max_cost exceeded" for s in result.steps)
