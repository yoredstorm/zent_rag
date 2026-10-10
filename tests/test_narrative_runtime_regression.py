# =============================================================================
# Regresión viva: «cuentame sobre el cambio de fechas en el record 2».
# La entidad Record 2 no cubre el aspecto «cambio de fechas»: la ruta narrativa
# debe abrir UNA búsqueda dirigida al aspecto y nunca afirmar ausencia de corpus.
# =============================================================================
from __future__ import annotations

from typing import ClassVar
from uuid import uuid4

import pytest

from src.agents.runtime.agent_runtime import AgentRunRequest, AgentRuntime
from src.agents.tools.base import Tool, ToolContext, ToolResult
from src.agents.tools.registry import register_tool
from src.core.domain.entities import Agent, LLMResponse
from src.core.ports import LLMProvider

QUESTION = "cuentame sobre el cambio de fechas en el record 2"
SIMPLE_QUESTION = "qué significa & en Record 2"

INITIAL_EVIDENCE = (
    {
        "content": "Record 2 Footnote: la fare class usa & y guion en la fare family.",
        "title": "Rec2_Cat10.pdf",
        "document_id": "rec2-cat10",
        "source_id": "src-1",
        "score": 0.91,
        "page": 3,
        "section_path": ("Record 2", "Footnote"),
        "aliases": {"cambio de fechas": ["effective date", "discontinue date"]},
    },
    {
        "content": "Record 2 fare class: footnotes y fare family con & y hyphen.",
        "title": "Rec2_Rules.pdf",
        "document_id": "rec2-rules",
        "source_id": "src-2",
        "score": 0.88,
        "page": 4,
        "section_path": ("Record 2", "Fare Class"),
    },
)
DATE_EVIDENCE = (
    {
        "content": (
            "Record 2 Date Processing: el cambio de fechas y las fechas de "
            "efectividad se gobiernan por la effective date y la discontinue date."
        ),
        "title": "Rec2_Dates.pdf",
        "document_id": "rec2-dates",
        "source_id": "src-3",
        "score": 0.80,
        "page": 7,
        "section_path": ("Record 2", "Date Processing"),
    },
)


class _FakeLLM(LLMProvider):
    def __init__(self, contents: list[str], tokens: int = 10) -> None:
        self.contents = contents
        self.tokens = tokens
        self.calls = 0
        self.system_prompts: list[str] = []

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        self.system_prompts.append(str(kwargs.get("system_prompt") or ""))
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


class _NarrativeSearchTool(Tool):
    """Búsqueda fake: la consulta original recibe fare class; la dirigida, fechas."""

    name: ClassVar[str] = "search_knowledge"
    description: ClassVar[str] = "Busca en el conocimiento."
    input_schema: ClassVar[dict] = {
        "type": "object",
        "required": ["query"],
        "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}},
    }

    def __init__(
        self,
        *,
        original: str = QUESTION,
        date_evidence: tuple[dict, ...] = DATE_EVIDENCE,
    ) -> None:
        self.queries: list[str] = []
        self.top_ks: list[int] = []
        self._original = original
        self._date_evidence = date_evidence

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        query = str(arguments.get("query") or "")
        self.queries.append(query)
        self.top_ks.append(int(arguments.get("top_k") or 0))
        directed = query.strip().lower() != self._original.strip().lower()
        evidence = self._date_evidence if directed else INITIAL_EVIDENCE
        return ToolResult(output="resultados", meta={"evidence": list(evidence)})


def _agent(**overrides) -> Agent:
    params = {
        "id": uuid4(),
        "organization_id": uuid4(),
        "name": "narrative-agent",
        "tools": ["search_knowledge"],
    }
    params.update(overrides)
    return Agent(**params)


def _request(agent: Agent, message: str) -> AgentRunRequest:
    return AgentRunRequest(agent=agent, message=message, role="admin")


@pytest.fixture(autouse=True)
def _isolate_tool_registry():
    """Restaura el registry global: la suite no depende del orden de archivos."""
    from src.agents.tools import registry as registry_module

    before = dict(registry_module._tools)
    yield
    registry_module._tools.clear()
    registry_module._tools.update(before)


@pytest.fixture(autouse=True)
def _narrative_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "RUNTIME_NARRATIVE_FAST_PATH", "on")
    monkeypatch.setattr(settings, "RUNTIME_TURN_INTENT", "off")
    monkeypatch.setattr(settings, "RUNTIME_TOOL_ROUTING_MODE", "off")
    monkeypatch.setattr(settings, "RUNTIME_TERMINATION_GATE", "off")
    monkeypatch.setattr(settings, "RUNTIME_ANSWER_GATE", "off")
    monkeypatch.setattr(settings, "RUNTIME_AGENT_JEV_LOOP", "off")
    monkeypatch.setattr(settings, "RUNTIME_SOURCE_AWARE_TOOLS", False)


def _narrative_step(result) -> dict:
    return next(
        step for step in result.steps if step.get("type") == "narrative_fast_path"
    )


@pytest.mark.asyncio
async def test_narrative_top_k_comes_from_agent_config() -> None:
    search = _NarrativeSearchTool()
    register_tool(search)
    llm = _FakeLLM(
        [
            "Record 2 procesa el cambio de fechas con la effective date [Doc: 1]."
        ]
    )
    runtime = AgentRuntime(llm_provider=llm)
    result = await runtime.run(
        _request(_agent(config_json={"retrieval": {"top_k": 10}}), QUESTION)
    )

    step = _narrative_step(result)
    assert step["retrieval_top_k"] == 10
    assert search.top_ks == [10, 10]


@pytest.mark.asyncio
async def test_partial_material_opens_directed_coverage_search() -> None:
    search = _NarrativeSearchTool()
    register_tool(search)
    llm = _FakeLLM(
        [
            "Según la evidencia, Record 2 procesa el cambio de fechas con la "
            "effective date y la discontinue date [Doc: 1]."
        ]
    )
    runtime = AgentRuntime(llm_provider=llm)
    result = await runtime.run(_request(_agent(), QUESTION))

    step = _narrative_step(result)
    assert step["coverage_rounds"] == 1
    assert step["retrieval_rounds"] == 2
    assert step["coverage_decision_reason"] == "PARTIAL_MATERIAL"
    assert step["coverage_stop_reason"] == "COVERAGE_COMPLETE"
    assert step["entity_coverage"][0]["label"].lower() == "record 2"
    assert step["entity_coverage"][0]["status"] == "COVERED"
    assert step["aspect_coverage"][0]["label"].lower() == "cambio de fechas"
    assert step["aspect_coverage"][0]["status"] == "COVERED"
    assert step["final_aspect_coverage"] == ["COVERED"]
    assert step["narrative_frames"][0]["relation"] == "aspect_of"
    # La consulta dirigida usa el aspecto (con aliases documentales), no repite
    # la pregunta original.
    assert len(search.queries) == 2
    directed = search.queries[1].lower()
    assert directed != QUESTION.lower()
    assert "effective date" in directed or "discontinue date" in directed
    assert "record 2" in directed
    assert llm.calls == 1
    assert "no encontré" not in result.answer.lower()


@pytest.mark.asyncio
async def test_missing_aspect_after_search_declares_soft_limitation() -> None:
    search = _NarrativeSearchTool(date_evidence=INITIAL_EVIDENCE)
    register_tool(search)
    llm = _FakeLLM(
        [
            "Record 2 usa Fare Class y Footnote [Doc: 1]."
        ]
    )
    runtime = AgentRuntime(llm_provider=llm)
    result = await runtime.run(_request(_agent(), QUESTION))

    step = _narrative_step(result)
    assert step["coverage_rounds"] == 1
    assert step["retrieval_rounds"] == 2
    assert step["coverage_stop_reason"] == "COVERAGE_PARTIAL"
    assert step["final_aspect_coverage"] in (["MISSING"], ["PARTIAL_MATERIAL"])
    answer = result.answer.lower()
    assert "no encontré evidencia suficiente" in answer
    assert "documento no contiene" not in answer
    assert "corpus no contiene" not in answer


@pytest.mark.asyncio
async def test_external_category_claim_is_not_delivered() -> None:
    search = _NarrativeSearchTool()
    register_tool(search)
    llm = _FakeLLM(
        [
            "Record 2 procesa el cambio de fechas con la effective date [Doc: 1].\n\n"
            "## Implicación práctica\n"
            "Category 15 is Seasonality: conviene revisar esa categoría."
        ]
    )
    runtime = AgentRuntime(llm_provider=llm)
    result = await runtime.run(_request(_agent(), QUESTION))

    step = _narrative_step(result)
    assert step["external_claims_removed"] >= 1
    assert "category 15" not in result.answer.lower()
    assert "implicación práctica" not in result.answer.lower()
    narrative_evidence = next(
        s for s in result.steps if s.get("type") == "narrative_evidence"
    )
    assert narrative_evidence["external_claims_removed"] >= 1


@pytest.mark.asyncio
async def test_multitopic_entity_and_effective_dates() -> None:
    question = "cuentame sobre record 2 y las fechas de efectividad"
    search = _NarrativeSearchTool(original=question)
    register_tool(search)
    llm = _FakeLLM(
        [
            "Record 2 cubre las fechas de efectividad con la effective date y la "
            "discontinue date [Doc: 1]."
        ]
    )
    runtime = AgentRuntime(llm_provider=llm)
    result = await runtime.run(_request(_agent(), question))

    step = _narrative_step(result)
    assert len(step["narrative_frames"]) == 2
    assert step["coverage_rounds"] == 1
    assert step["retrieval_rounds"] == 2
    assert step["coverage_stop_reason"] == "COVERAGE_COMPLETE"
    assert len(search.queries) == 2
    assert "fechas de efectividad" in search.queries[1].lower()
    assert "record 2" in search.queries[1].lower()


@pytest.mark.asyncio
async def test_simple_query_stays_in_one_retrieval_round() -> None:
    search = _NarrativeSearchTool(original=SIMPLE_QUESTION)
    register_tool(search)
    llm = _FakeLLM(["El símbolo & en Record 2 indica la fare family [Doc: 1]."])
    runtime = AgentRuntime(llm_provider=llm)
    result = await runtime.run(_request(_agent(), SIMPLE_QUESTION))

    step = _narrative_step(result)
    assert step["coverage_rounds"] == 0
    assert step["retrieval_rounds"] == 1
    assert step["coverage_stop_reason"] == "INITIAL_COMPLETE"
    assert len(search.queries) == 1
    assert llm.calls == 1
