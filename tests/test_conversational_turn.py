# =============================================================================
# Turno conversacional — comportamiento del Agent Runtime.
# =============================================================================
# Reproduce el caso real («hola como estas» con un agente que TIENE
# search_knowledge) y fija el contrato:
#
#   - un turno conversacional no llama search_knowledge;
#   - no produce un evidence_sufficiency en fallo;
#   - el Answer Gate documental se registra como not_applicable (no abstain);
#   - nunca devuelve INSUFFICIENT_ANSWER;
#   - la intención queda visible en el flujo.
#
# Y que un turno mixto con intención material de conocimiento SÍ busca fuentes.
# =============================================================================
from __future__ import annotations

from typing import Any, ClassVar
from uuid import uuid4

import pytest

from src.agents.runtime.agent_runtime import AgentRunRequest, AgentRuntime
from src.agents.tools.base import Tool, ToolContext, ToolResult
from src.agents.tools.registry import register_tool
from src.core.domain.entities import Agent, LLMResponse
from src.core.ports import LLMProvider
from src.runtime.answer_gate import INSUFFICIENT_ANSWER


class _FakeLLM(LLMProvider):
    def __init__(self, contents: list[str], tokens: int = 10) -> None:
        self.contents = contents
        self.tokens = tokens
        self.calls = 0
        self.prompts: list[str] = []

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        index = min(self.calls, len(self.contents) - 1)
        self.calls += 1
        self.prompts.append(prompt)
        return LLMResponse(
            content=self.contents[index],
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


class _SearchStub(Tool):
    name: ClassVar[str] = "search_knowledge"
    description: ClassVar[str] = "Busca en el conocimiento."
    input_schema: ClassVar[dict] = {
        "type": "object",
        "required": ["query"],
        "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}},
    }

    def __init__(self, *, content: str | None = None) -> None:
        self.queries: list[str] = []
        self._content = content

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        self.queries.append(str(arguments.get("query") or ""))
        if self._content is None:
            return ToolResult(output="(no results)", meta={})
        document_id = str(uuid4())
        return ToolResult(
            output=f"[Doc 1 | source:Cat31_dapp_C.pdf] {self._content}",
            meta={
                "source_ids": ["cat31-source"],
                "evidence": [
                    {
                        "ref": document_id,
                        "document_id": document_id,
                        "source_id": "cat31-source",
                        "title": "Cat31_dapp_C.pdf",
                        "score": 0.6,
                        "status": "USED",
                        "content": self._content,
                    }
                ],
            },
        )


class _TurnJudge:
    """JEV fake: intención configurada por test + gate documental honesto."""

    def __init__(
        self,
        *,
        intent: str = "greeting",
        confidence: float = 0.84,
        probabilities: dict[str, float] | None = None,
        needs: float | None = 0.1,
    ) -> None:
        self.intent = intent
        self.confidence = confidence
        self.probabilities = probabilities or {
            intent: confidence,
            "knowledge_question": round(max(0.0, 1.0 - confidence - 0.05), 4),
            "social_conversation": 0.05,
        }
        self.needs = needs
        self.intent_calls = 0
        self.gate_calls = 0

    async def judge(self, *, state, questions, context=None):
        answers: dict[str, Any] = {}
        evidencia = " ".join(
            str(state.get(key) or "") for key in ("evidence", "tool_results")
        ).lower()
        tiene_byte = "byte 105" in evidencia or "fee application" in evidencia
        for question_id, spec in (questions or {}).items():
            if question_id == "conversation_intent":
                self.intent_calls += 1
                answers[question_id] = {
                    "type": "choice",
                    "choice": self.intent,
                    "confidence": self.confidence,
                    "probabilities": dict(self.probabilities),
                }
            elif question_id == "needs_external_evidence":
                answers[question_id] = {
                    "type": "noul",
                    "noul": self.needs if self.needs is not None else 0.5,
                }
            elif question_id in {
                "answer_grounded",
                "evidence_sufficient",
                "evidence_on_topic",
            }:
                self.gate_calls += 1
                answers[question_id] = {"type": "noul", "noul": 0.95 if tiene_byte else 0.1}
            elif question_id == "answer_complete":
                answers[question_id] = {"type": "noul", "noul": 0.9 if tiene_byte else 0.2}
            elif question_id == "answer_quality":
                answers[question_id] = {"type": "score", "score": 3.0 if tiene_byte else 1.0}
            elif question_id == "revision_reason":
                answers[question_id] = {
                    "type": "choice",
                    "choice": "too_verbose" if tiene_byte else "missing_evidence",
                }
            elif (spec or {}).get("type") == "choice":
                criteria = (spec or {}).get("criteria") or {}
                choice = next(iter(criteria), "documents")
                answers[question_id] = {
                    "type": "choice",
                    "choice": choice,
                    "confidence": 0.9,
                    "probabilities": {choice: 0.9},
                }
            elif (spec or {}).get("type") == "score":
                answers[question_id] = {"type": "score", "score": 2.0}
            else:
                answers[question_id] = {"type": "noul", "noul": 0.1 if tiene_byte else 0.9}
        return {"model": "jev-test", "answers": answers}


def _agent() -> Agent:
    return Agent(
        id=uuid4(),
        organization_id=uuid4(),
        name="atpco-agent",
        tools=["search_knowledge"],
        config_json={"purpose": "Resolver consultas sobre tarifas ATPCO"},
    )


def _install_engine(monkeypatch: pytest.MonkeyPatch, engine) -> None:
    import src.decision.service as service

    monkeypatch.setattr(service, "get_decision_engine", lambda: engine)


@pytest.fixture(autouse=True)
def _flags(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "RUNTIME_SOURCE_AWARE_TOOLS", False)
    monkeypatch.setattr(settings, "RUNTIME_TOOL_ROUTING_MODE", "off")
    monkeypatch.setattr(settings, "RUNTIME_TERMINATION_GATE", "off")
    monkeypatch.setattr(settings, "RUNTIME_AGENT_JEV_LOOP", "off")
    monkeypatch.setattr(settings, "RUNTIME_ANSWER_GATE", "on")
    monkeypatch.setattr(settings, "RUNTIME_TURN_INTENT", "on")


async def _run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    llm: _FakeLLM,
    judge: _TurnJudge,
    search: _SearchStub | None = None,
    message: str,
) -> tuple[Any, _SearchStub, _TurnJudge]:
    stub = search or _SearchStub()
    register_tool(stub)
    _install_engine(monkeypatch, judge)
    runtime = AgentRuntime(llm_provider=llm)
    result = await runtime.run(
        AgentRunRequest(agent=_agent(), message=message, role="admin")
    )
    return result, stub, judge


def _steps(result) -> dict[str, dict]:
    return {str(step.get("type")): step for step in result.steps}


@pytest.mark.asyncio
async def test_saludo_ambiguo_no_dispara_retrieval_ni_gate_documental(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = _FakeLLM(['{"answer": "¡Hola! Todo bien. ¿En qué te ayudo con ATPCO?"}'])
    judge = _TurnJudge(
        intent="greeting",
        confidence=0.84,
        probabilities={
            "greeting": 0.84,
            "social_conversation": 0.11,
            "knowledge_question": 0.03,
            "complaint": 0.02,
        },
        needs=0.1,
    )

    result, search, judge = await _run(
        monkeypatch, llm=llm, judge=judge, message="hola como estas"
    )

    assert result.status == "completed"
    assert result.answer == "¡Hola! Todo bien. ¿En qué te ayudo con ATPCO?"
    assert result.answer != INSUFFICIENT_ANSWER
    assert search.queries == [], "un saludo no llama search_knowledge"
    assert judge.gate_calls == 0, "el gate documental no se invoca"
    assert llm.calls == 1

    steps = _steps(result)
    intent = steps["conversation_intent"]
    assert intent["intent"] == "greeting"
    assert intent["route"] == "direct"
    assert intent["retrieval"] == "not_applicable"
    assert intent["answer_gate"] == "not_applicable"
    assert intent["provider"] == "jev"
    assert intent["probabilities"]["social_conversation"] == 0.11
    assert steps["answer_gate"]["verdict"] == "not_applicable"
    assert not any(step["type"] == "evidence_sufficiency" for step in result.steps)
    assert result.turn_intent is not None
    assert result.turn_intent["intent"] == "greeting"


@pytest.mark.asyncio
async def test_saludo_obvio_ni_siquiera_gasta_jev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = _FakeLLM(['{"answer": "¡Hola! ¿En qué te ayudo?"}'])
    judge = _TurnJudge()

    result, search, judge = await _run(
        monkeypatch, llm=llm, judge=judge, message="hola"
    )

    assert search.queries == []
    assert judge.intent_calls == 0, "regla obvia: no se consulta a JEV"
    steps = _steps(result)
    assert steps["conversation_intent"]["provider"] == "rules"
    assert steps["conversation_intent"]["route"] == "direct"
    assert result.answer == "¡Hola! ¿En qué te ayudo?"


@pytest.mark.asyncio
async def test_saludo_con_pregunta_de_conocimiento_busca_fuentes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.core.config import get_settings

    monkeypatch.setattr(get_settings(), "RUNTIME_ANSWER_GATE", "off")
    llm = _FakeLLM(
        [
            '{"tool": "search_knowledge", "arguments": {"query": "byte 105"}}',
            '{"answer": "El byte 105 es Fee Application."}',
        ]
    )
    judge = _TurnJudge(intent="greeting", confidence=0.5, needs=0.1)

    result, search, judge = await _run(
        monkeypatch,
        llm=llm,
        judge=judge,
        message="buenas, qué significa byte 105?",
        search=_SearchStub(content="El byte 105 es el campo Fee Application."),
    )

    assert search.queries == ["byte 105"], "la intención material manda"
    assert judge.intent_calls == 0, "las reglas ya vieron conocimiento"
    assert result.turn_intent["intent"] == "knowledge_question"
    assert result.turn_intent["route"] == "knowledge"
    assert result.answer == "El byte 105 es Fee Application."


@pytest.mark.asyncio
async def test_queja_con_pregunta_factual_conserva_el_conocimiento(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.core.config import get_settings

    monkeypatch.setattr(get_settings(), "RUNTIME_ANSWER_GATE", "off")
    llm = _FakeLLM(
        [
            '{"tool": "search_knowledge", "arguments": {"query": "byte 105"}}',
            '{"answer": "El byte 105 es Fee Application."}',
        ]
    )
    judge = _TurnJudge(intent="complaint", confidence=0.6, needs=0.1)

    result, search, judge = await _run(
        monkeypatch,
        llm=llm,
        judge=judge,
        message="me estás respondiendo mal, explícame byte 105",
        search=_SearchStub(content="El byte 105 es el campo Fee Application."),
    )

    assert search.queries, "la pregunta factual no se pierde en la queja"
    assert result.turn_intent["intent"] == "knowledge_question"
    assert "complaint" in result.turn_intent["signals"]


@pytest.mark.asyncio
async def test_queja_simple_responde_directo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = _FakeLLM(['{"answer": "Entiendo. ¿Qué parte de la respuesta te falló?"}'])
    judge = _TurnJudge(intent="complaint", confidence=0.85, needs=0.1)

    result, search, judge = await _run(
        monkeypatch, llm=llm, judge=judge, message="esto no sirve"
    )

    assert search.queries == []
    assert result.answer != INSUFFICIENT_ANSWER
    assert judge.gate_calls == 0
    assert _steps(result)["conversation_intent"]["route"] == "direct"
    assert result.turn_intent["intent"] == "complaint"
    prompt = llm.prompts[0]
    assert "TURNO CONVERSACIONAL" in prompt
    assert "NO digas que no tenés acceso" in prompt


@pytest.mark.asyncio
async def test_pregunta_de_capacidad_usa_la_configuracion_del_agente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = _FakeLLM(
        ['{"answer": "Puedo ayudarte a consultar la base ATPCO configurada."}']
    )
    judge = _TurnJudge()

    result, search, judge = await _run(
        monkeypatch, llm=llm, judge=judge, message="qué puedes hacer?"
    )

    assert search.queries == [], "capacidad no se busca en documentos"
    assert judge.intent_calls == 0, "regla de capacidad: sin JEV"
    prompt = llm.prompts[0]
    assert "CONFIGURACIÓN REAL DEL AGENTE" in prompt
    assert "atpco-agent" in prompt
    assert "Resolver consultas sobre tarifas ATPCO" in prompt
    assert "search_knowledge" in prompt
    assert result.turn_intent["intent"] == "capability_question"


@pytest.mark.asyncio
async def test_conocimiento_sin_evidencia_sigue_siendo_documental(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.core.config import get_settings

    monkeypatch.setattr(get_settings(), "RUNTIME_ANSWER_GATE", "off")
    llm = _FakeLLM(
        [
            '{"tool": "search_knowledge", "arguments": {"query": "byte 999"}}',
            '{"answer": "El byte 999 no está documentado en las fuentes."}',
        ]
    )
    judge = _TurnJudge(intent="greeting", confidence=0.4, needs=0.1)

    result, search, judge = await _run(
        monkeypatch, llm=llm, judge=judge, message="qué significa byte 999?"
    )

    assert search.queries == ["byte 999"]
    assert result.turn_intent["route"] == "knowledge"
    assert result.turn_intent["needs_external_evidence"] is True
