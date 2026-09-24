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
    _filter_tools_by_sources,
    _parse_action,
)
from src.agents.tools.base import Tool, ToolContext, ToolResult
from src.agents.tools.registry import register_tool
from src.core.domain.entities import Agent, LLMResponse
from src.core.ports import LLMProvider


@pytest.fixture(autouse=True)
def _runtime_flags_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests no dependen de los flags demo del .env local."""
    from src.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "RUNTIME_TOOL_ROUTING_MODE", "off")
    monkeypatch.setattr(settings, "RUNTIME_TERMINATION_GATE", "off")
    monkeypatch.setattr(settings, "RUNTIME_ANSWER_GATE", "off")
    # El Agent JEV Loop se prueba en su propia clase; por defecto acá queda off
    # para que cada test fije el comportamiento que verifica.
    monkeypatch.setattr(settings, "RUNTIME_AGENT_JEV_LOOP", "off")
    # El filtro por fuentes consulta Postgres; en unit tests se apaga salvo
    # en los casos dedicados (que mockean `_agent_source_types`).
    monkeypatch.setattr(settings, "RUNTIME_SOURCE_AWARE_TOOLS", False)


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

    def test_truncated_answer_json_shows_text_not_json(self) -> None:
        """Un corte por tokens no debe mostrarle el envoltorio al usuario."""
        truncated = (
            '{"answer": "La **Categoría 31** define los cambios voluntarios. '
            'El pasajero reemite el boleto y el sistema revalida (\\u00f3) las tarifas'
        )
        action = _parse_action(truncated)
        assert action.get("tool") is None
        assert action["answer"].startswith("La **Categoría 31** define")
        assert not action["answer"].startswith("{")
        assert '"answer"' not in action["answer"]
        assert "(ó)" in action["answer"]

    def test_truncated_answer_json_with_closing_brace(self) -> None:
        truncated = '{"answer": "uno dos tres\\'
        assert _parse_action(truncated)["answer"] == "uno dos tres"

    def test_prose_mentioning_answer_key_stays_prose(self) -> None:
        """Prosa que menciona la clave no se confunde con un envoltorio."""
        prose = 'El campo "answer": "x" documenta la clave del protocolo.'
        assert _parse_action(prose) == {"answer": prose}


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
    async def test_invalid_tool_json_is_not_shown_as_answer(self) -> None:
        register_tool(_EchoTool())
        broken = (
            '{\n  "tool": "echo",\n  "arguments": {\n'
            '    "text": "hello",\n    "top_k": III\n  }\n}'
        )
        llm = _FakeLLM(
            [
                '{"tool": "echo", "arguments": {"text": "hello"}}',
                broken,
                '{"answer": "Record 4 controla la renumeración."}',
            ]
        )
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(_request(_agent(), "cuentame sobre el record 4"))

        assert result.status == "completed"
        assert result.answer == "Record 4 controla la renumeración."
        assert "top_k" not in result.answer

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

    @pytest.mark.asyncio
    async def test_identical_tool_call_blocked_then_answers(self) -> None:
        echo = _EchoTool()
        register_tool(echo)
        llm = _FakeLLM(
            [
                '{"tool": "echo", "arguments": {"text": "x"}}',
                '{"tool": "echo", "arguments": {"text": "x"}}',
                '{"answer": "El gerente es Miguel"}',
            ]
        )
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(_request(_agent(), "quien es el gerente"))
        assert result.status == "completed"
        assert result.answer == "El gerente es Miguel"
        assert len(echo.calls) == 1
        assert any(
            s.get("detail") == "loop prevention: duplicate tool call without new information"
            for s in result.steps
        )

    @pytest.mark.asyncio
    async def test_max_tokens_with_observations_still_answers(self) -> None:
        register_tool(_EchoTool())
        llm = _FakeLLM(
            [
                '{"tool": "echo", "arguments": {"text": "Miguel Angel Pezzia, Gerente General"}}',
                '{"tool": "echo", "arguments": {"text": "mas contratos"}}',
                '{"answer": "El gerente es Miguel Angel Pezzia"}',
            ],
            tokens=30,
        )
        agent = _agent(config_json={"max_tokens": 80})
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(_request(agent, "quien es el gerente"))
        assert result.status == "completed"
        assert "Miguel" in result.answer
        assert any(s.get("detail") == "max_tokens exceeded" for s in result.steps)


class _FakeSearchTool(Tool):
    """Búsqueda de conocimiento fake: registra las consultas que recibe."""

    name: ClassVar[str] = "search_knowledge"
    description: ClassVar[str] = "Busca en el conocimiento."
    input_schema: ClassVar[dict] = {
        "type": "object",
        "required": ["query"],
        "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}},
    }

    def __init__(self, output: str = "sin resultados") -> None:
        self.queries: list[str] = []
        self._output = output

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        self.queries.append(str(arguments.get("query") or ""))
        return ToolResult(output=self._output)


class _LoopJevClient:
    """Cliente JEV fake para el loop: responde según el paso.

    `evidence_gap_steps` = cuántos pasos dicen "falta evidencia"; después el
    veredicto dice que ya se puede responder.
    """

    def __init__(self, *, evidence_gap_steps: int = 0) -> None:
        self.calls = 0
        self.questions: list[list[str]] = []
        self._gap_steps = evidence_gap_steps

    async def system_one(self, *, state, questions, model, timeout):
        self.calls += 1
        self.questions.append(sorted(questions))
        answers: dict = {}
        gap = self.calls <= self._gap_steps
        for question_id, spec in questions.items():
            qtype = str((spec or {}).get("type") or "noul")
            if qtype == "choice":
                criteria = (spec or {}).get("criteria") or {}
                choice = next(iter(criteria), "none")
                answers[question_id] = {
                    "type": "choice",
                    "choice": choice,
                    "confidence": 0.9,
                    "probabilities": {choice: 0.9},
                }
            elif qtype == "score":
                answers[question_id] = {"type": "score", "score": 2.0, "confidence": 0.8}
            elif question_id == "needs_more_evidence":
                answers[question_id] = {"type": "noul", "noul": 0.9 if gap else 0.1}
            elif question_id == "satisfied":
                answers[question_id] = {"type": "noul", "noul": 0.1 if gap else 0.9}
            else:
                answers[question_id] = {"type": "noul", "noul": 0.5}
        return {
            "model": "jev-loop-test",
            "answers": answers,
            "usage": {"input_tokens": 30, "output_tokens": 8},
        }


def _loop_engine(client) -> object:
    from src.decision.batch import JudgmentCache
    from src.decision.engine import DecisionEngine
    from src.decision.providers.jev import JevDecisionProvider
    from src.decision.settings import DecisionEngineSettings

    settings = DecisionEngineSettings(
        routing_mode="jev",
        canary_percentage=100,
        fallback_model="cheap",
        jev_api_key="test-key",
        batch_mode="on",
    )
    cache = JudgmentCache()
    provider = JevDecisionProvider(settings, client=client, cache=cache)
    return DecisionEngine(provider, settings, jev=provider, cache=cache)


def _install_engine(monkeypatch: pytest.MonkeyPatch, engine) -> None:
    import src.decision.service as service

    monkeypatch.setattr(service, "get_decision_engine", lambda: engine)


class TestAgentJevLoop:
    @pytest.mark.asyncio
    async def test_una_llamada_jev_por_paso_con_el_veredicto_en_el_step(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "RUNTIME_AGENT_JEV_LOOP", "on")
        search = _FakeSearchTool("La política de RRHH dice X.")
        register_tool(search)
        client = _LoopJevClient(evidence_gap_steps=0)
        _install_engine(monkeypatch, _loop_engine(client))
        llm = _FakeLLM(
            [
                '{"tool": "search_knowledge", "arguments": {"query": "politica rrhh"}}',
                '{"answer": "La política es X"}',
            ]
        )
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(
            _request(_agent(tools=["search_knowledge"]), "cual es la politica")
        )

        assert result.status == "completed"
        step_judgments = [s for s in result.steps if s["type"] == "agent_step"]
        assert len(step_judgments) == 1
        assert step_judgments[0]["next_action"] in {"generate_answer", "retrieve_more"}
        assert client.calls == 1
        # El juicio viaja al flujo como pack (una llamada, N preguntas).
        assert result.jev_packs and result.jev_packs[0]["phase"] == "agent_step"
        assert result.jev_mode == "on"

    @pytest.mark.asyncio
    async def test_jev_pide_otra_busqueda_con_consulta_refinada(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "RUNTIME_AGENT_JEV_LOOP", "on")
        search = _FakeSearchTool("No encontré nada sobre eso.")
        register_tool(search)
        client = _LoopJevClient(evidence_gap_steps=1)
        _install_engine(monkeypatch, _loop_engine(client))
        llm = _FakeLLM(
            [
                '{"tool": "search_knowledge", "arguments": {"query": "byte 105"}}',
                '{"answer": "No tengo documentación de la categoría 31."}',
            ]
        )
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(
            _request(
                _agent(tools=["search_knowledge"]),
                "cuentame sobre la categoria 31 y el byte 105",
            )
        )

        retrievals = [s for s in result.steps if s["type"] == "jev_retrieval"]
        assert len(retrievals) == 1
        assert retrievals[0]["round"] == 1
        assert retrievals[0]["reason"] == "evidence_gap"
        assert "cat31" in retrievals[0]["query"].lower()
        # La búsqueda dirigida por JEV se ejecutó de verdad, con la query refinada.
        assert any("cat31" in query.lower() for query in search.queries)
        assert any(
            decision.get("action") == "retrieve_more" for decision in result.jev_decisions
        )

    @pytest.mark.asyncio
    async def test_el_tope_de_rondas_corta_las_reconsultas(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "RUNTIME_AGENT_JEV_LOOP", "on")
        monkeypatch.setattr(settings, "RUNTIME_AGENT_MAX_RETRIEVAL_ROUNDS", 1)
        register_tool(_FakeSearchTool("nada sobre la categoría 31"))
        client = _LoopJevClient(evidence_gap_steps=5)  # siempre pide más
        _install_engine(monkeypatch, _loop_engine(client))
        llm = _FakeLLM(
            [
                '{"tool": "search_knowledge", "arguments": {"query": "categoria 31"}}',
                '{"answer": "No está documentado."}',
            ]
        )
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(
            _request(
                _agent(tools=["search_knowledge"]), "cuentame sobre la categoria 31"
            )
        )
        assert result.status == "completed"
        assert len([s for s in result.steps if s["type"] == "jev_retrieval"]) == 1

    @pytest.mark.asyncio
    async def test_loop_off_conserva_el_comportamiento_previo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        register_tool(_FakeSearchTool("algo"))
        client = _LoopJevClient(evidence_gap_steps=0)
        _install_engine(monkeypatch, _loop_engine(client))
        llm = _FakeLLM(
            [
                '{"tool": "search_knowledge", "arguments": {"query": "x"}}',
                '{"answer": "listo"}',
            ]
        )
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(_request(_agent(tools=["search_knowledge"]), "pregunta"))
        assert result.status == "completed"
        assert not [s for s in result.steps if s["type"] == "agent_step"]
        assert not [s for s in result.steps if s["type"] == "jev_retrieval"]
        assert client.calls == 0
        assert result.jev_packs == []

    @pytest.mark.asyncio
    async def test_shadow_juzga_pero_no_actua(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "RUNTIME_AGENT_JEV_LOOP", "shadow")
        register_tool(_FakeSearchTool("nada"))
        client = _LoopJevClient(evidence_gap_steps=3)
        _install_engine(monkeypatch, _loop_engine(client))
        llm = _FakeLLM(
            [
                '{"tool": "search_knowledge", "arguments": {"query": "categoria 31"}}',
                '{"answer": "No está documentado."}',
            ]
        )
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(
            _request(_agent(tools=["search_knowledge"]), "cuentame sobre la categoria 31")
        )
        assert result.status == "completed"
        # Juzgó y lo registró, pero no lanzó la re-consulta.
        assert [s for s in result.steps if s["type"] == "agent_step"]
        assert not [s for s in result.steps if s["type"] == "jev_retrieval"]
        assert result.jev_mode == "shadow"


class _FailingSqlishTool(Tool):
    """Simula el SQL Expert cuando la pregunta no aplica (error no transitorio)."""

    name: ClassVar[str] = "sqlish"
    description: ClassVar[str] = "Simula SQL que no aplica."
    input_schema: ClassVar[dict] = {
        "type": "object",
        "required": ["q"],
        "properties": {"q": {"type": "string"}},
    }

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        self.calls.append(dict(arguments))
        return ToolResult(error="Cannot generate query for this question")


class _FlakyTool(Tool):
    """Falla una vez por timeout y luego responde (error transitorio)."""

    name: ClassVar[str] = "flaky"
    description: ClassVar[str] = "Falla una vez."
    input_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {"step": {"type": "string"}},
    }

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        self.calls += 1
        if self.calls == 1:
            return ToolResult(error="request timed out")
        return ToolResult(output="ok")


class TestFailedToolGuard:
    @pytest.mark.asyncio
    async def test_failed_tool_not_retried_for_same_question(self) -> None:
        tool = _FailingSqlishTool()
        register_tool(tool)
        llm = _FakeLLM(
            [
                '{"tool": "sqlish", "arguments": {"q": "quien es el empleado"}}',
                '{"tool": "sqlish", "arguments": {"q": "empleado nombre"}}',
                '{"answer": "No tengo esa informacion en las fuentes."}',
            ]
        )
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(
            _request(_agent(tools=["sqlish"]), "quien es el empleado")
        )
        assert result.status == "completed"
        # El segundo intento (argumentos distintos) se bloquea igual.
        assert len(tool.calls) == 1
        assert any(
            s.get("detail") == "tool falló antes: no se reintenta para esta pregunta"
            for s in result.steps
        )

    @pytest.mark.asyncio
    async def test_transient_tool_failure_allows_retry(self) -> None:
        tool = _FlakyTool()
        register_tool(tool)
        llm = _FakeLLM(
            [
                '{"tool": "flaky", "arguments": {"step": "1"}}',
                '{"tool": "flaky", "arguments": {"step": "2"}}',
                '{"answer": "ok"}',
            ]
        )
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(_request(_agent(tools=["flaky"])))
        assert result.status == "completed"
        assert tool.calls == 2


class TestSourceAwareTools:
    def test_pdf_only_drops_sql_tabular_and_api(self) -> None:
        tools, omitted = _filter_tools_by_sources(
            ["search_knowledge", "query_database", "query_tabular_data", "call_api"],
            {"file"},
            api_allowlist=[],
        )
        assert tools == ["search_knowledge"]
        assert {item["tool"] for item in omitted} == {
            "query_database",
            "query_tabular_data",
            "call_api",
        }

    def test_csv_keeps_tabular_but_not_sql(self) -> None:
        tools, omitted = _filter_tools_by_sources(
            ["query_database", "query_tabular_data"],
            {"csv"},
            api_allowlist=[],
        )
        assert tools == ["query_tabular_data"]
        assert [item["tool"] for item in omitted] == ["query_database"]

    def test_sql_and_allowlist_keep_everything(self) -> None:
        tools, omitted = _filter_tools_by_sources(
            ["query_database", "query_tabular_data", "call_api"],
            {"sql"},
            api_allowlist=["api.example.com"],
        )
        assert tools == ["query_database", "query_tabular_data", "call_api"]
        assert omitted == []

    @pytest.mark.asyncio
    async def test_run_records_omitted_tools_in_flow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.agents.runtime import agent_runtime as runtime_module
        from src.core.config import get_settings

        monkeypatch.setattr(get_settings(), "RUNTIME_SOURCE_AWARE_TOOLS", True)

        async def _fake_source_types(agent: Agent) -> set[str]:
            return {"file"}

        monkeypatch.setattr(runtime_module, "_agent_source_types", _fake_source_types)
        register_tool(_EchoTool())
        llm = _FakeLLM(['{"answer": "ok"}'])
        agent = _agent(tools=["echo", "query_database"])
        result = await AgentRuntime(llm_provider=llm).run(_request(agent))
        assert result.status == "completed"
        step = next(s for s in result.steps if s["type"] == "tool_filter")
        assert [item["tool"] for item in step["omitted"]] == ["query_database"]


class TestSqlToolFastReject:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "question",
        [
            "quién es el empleado",
            "que es una factura",
            "explícame la política de vacaciones",
            "hola",
        ],
    )
    async def test_definitional_question_rejected_without_expert(
        self, question: str
    ) -> None:
        from src.agents.tools.tools_builtin import QueryDatabaseTool

        class _ExpertMustNotRun:
            async def execute(self, **kwargs):
                raise AssertionError("el SQL Expert no debe ejecutarse")

        tool = QueryDatabaseTool(_ExpertMustNotRun())
        result = await tool.execute(ToolContext(tenant_id=uuid4()), {"question": question})
        assert result.error
        assert "no parece ser sobre datos" in result.error
        # Sin LLM: debe ser inmediato (el SQL Expert tardaba ~13 s).
        assert result.latency_ms < 1000

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "question",
        ["cuántas ventas hubo ayer", "dame los empleados"],
    )
    async def test_analytical_question_reaches_expert(self, question: str) -> None:
        from src.agents.tools.tools_builtin import QueryDatabaseTool
        from src.core.ports.sql_expert import SqlQueryResult

        seen: list[str] = []

        class _Expert:
            async def execute(self, **kwargs):
                seen.append(kwargs["question"])
                return SqlQueryResult(
                    sql="SELECT 1", columns=["n"], rows=[["1"]], row_count=1
                )

        tool = QueryDatabaseTool(_Expert())
        result = await tool.execute(ToolContext(tenant_id=uuid4()), {"question": question})
        assert result.error is None
        assert seen == [question]
