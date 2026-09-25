# =============================================================================
# Evidence-first gate — regresión «categoría 31 / byte 105».
# =============================================================================
# El caso real: la fuente ATPCO Cat31_dapp_C.pdf contiene la sección
# «4.6.2 Fee Application (byte 105)» con los valores posibles del byte. El
# retrieval la encuentra, pero la respuesta terminaba en
# «No hay evidencia suficiente en las fuentes consultadas…».
#
# Este archivo reproduce ese falso negativo y lo deja como regresión:
#   1. una sola fuente lógica de evidencia (`evidence_id`) para generador, JEV,
#      citas y «Ver flujo»;
#   2. selección por relevancia y presupuesto, no por posición (`[:3000]`,
#      `[:1500]`);
#   3. política: una respuesta imperfecta se revisa, una respuesta sin evidencia
#      se abstiene.
#
# SOURCE (documento) != EVIDENCE (fragmento) != CLAIM (afirmación respaldada).
# =============================================================================
from __future__ import annotations

from typing import Any, ClassVar
from uuid import uuid4

import pytest

from src.agents.runtime.agent_runtime import AgentRunRequest, AgentRuntime
from src.agents.tools.base import Tool, ToolContext, ToolResult
from src.agents.tools.registry import register_tool
from src.core.domain.adaptive import EvidenceItem
from src.core.domain.entities import Agent, LLMResponse
from src.core.ports import LLMProvider
from src.runtime.evidence import (
    ACTION_ABSTAIN,
    ACTION_ANSWER_WITH_LIMITS,
    ACTION_GENERATE,
    ACTION_RETRIEVE_MORE,
    EvidenceRegistry,
    assess_sufficiency,
    render_evidence,
    select_evidence,
)

PREGUNTA = "cuéntame sobre categoría 31 y el byte 105"

#: Contenido documental del fixture (mismo contenido, no el mismo texto exacto).
FEE_APPLICATION_BYTES_105 = """Section 4.6.2
Fee Application (byte 105)

Once processing has determined the change fee amount, the data in the Fee
Application field (byte 105) will specify how to assess the change fee.

Value 1:
From among all changed fare components, apply the highest change fee.

Value 2:
From among all fare components, changed and unchanged, apply the highest change fee.

Value 3:
Apply the change fee from the first changed fare component.

Value 4:
Apply the sum of all change fees from all changed fare components.

Value 5:
Apply the highest change fee from the fare components changed in this transaction.
"""

FUENTE_CAT31 = "Cat31_dapp_C.pdf"
RELLENO = (
    "General voluntary changes overview. Passenger reissue and revalidation "
    "procedures for voluntary changes across all fare components. "
)


def _documento_grande(*, relleno_chars: int = 3_400) -> str:
    """Output de retrieval con el chunk relevante DESPUÉS del corte viejo de 3000."""
    irrelevante = (RELLENO * ((relleno_chars // len(RELLENO)) + 1))[:relleno_chars]
    return (
        f"[Doc 1 | source:cat35-handbook.pdf] {irrelevante}\n\n"
        f"[Doc 2 | source:{FUENTE_CAT31}] {FEE_APPLICATION_BYTES_105}"
    )


def _item(
    content: str,
    *,
    title: str = FUENTE_CAT31,
    score: float = 0.5,
    document_id: str | None = None,
    **extra: Any,
) -> EvidenceItem:
    return EvidenceItem(
        source_type="qdrant",
        content=content,
        score=score,
        document_id=document_id or str(uuid4()),
        title=title,
        **extra,
    )


def _meta_evidencia(*, relleno_chars: int = 3_400) -> dict:
    """`meta` de search_knowledge: fragmento irrelevante largo + el relevante."""
    irrelevante = (RELLENO * ((relleno_chars // len(RELLENO)) + 1))[:relleno_chars]
    documento_id = str(uuid4())
    return {
        "source_ids": ["cat31-source-id"],
        "evidence": [
            {
                "ref": "doc-irrelevante",
                "document_id": str(uuid4()),
                "source_id": "cat35-source-id",
                "title": "cat35-handbook.pdf",
                "score": 0.42,
                "status": "USED",
                "content": irrelevante,
            },
            {
                "ref": documento_id,
                "document_id": documento_id,
                "source_id": "cat31-source-id",
                "chunk_id": f"{documento_id}:4.6.2",
                "title": FUENTE_CAT31,
                "score": 0.51,
                "status": "USED",
                "content": FEE_APPLICATION_BYTES_105,
                "section_path": ["4.6.2"],
                "retrieval": "entity_lexical",
            },
        ],
    }


class _FakeLLM(LLMProvider):
    def __init__(self, contents: list[str], tokens: int = 10) -> None:
        self.contents = contents
        self.tokens = tokens
        self.calls = 0
        self.prompts: list[str] = []

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        idx = min(self.calls, len(self.contents) - 1)
        self.calls += 1
        self.prompts.append(prompt)
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


class _SearchStub(Tool):
    """search_knowledge fake con la evidencia estructurada real de la tool."""

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
        relleno_chars: int = 3_400,
        respuestas: list[tuple[str, dict]] | None = None,
    ) -> None:
        self.queries: list[str] = []
        self._relleno_chars = relleno_chars
        #: Respuestas por llamada (output, meta). Sin lista, siempre el fixture.
        self._respuestas = respuestas

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        self.queries.append(str(arguments.get("query") or ""))
        if self._respuestas:
            index = min(len(self.queries) - 1, len(self._respuestas) - 1)
            output, meta = self._respuestas[index]
            return ToolResult(output=output, meta=meta)
        return ToolResult(
            output=_documento_grande(relleno_chars=self._relleno_chars),
            meta=_meta_evidencia(relleno_chars=self._relleno_chars),
        )


class _Judge:
    """Juez honesto: sólo puede juzgar con el estado que recibe.

    Si la evidencia que recibe no menciona «byte 105», no puede decir que la
    respuesta está respaldada. `overrides` fuerza respuestas puntuales (para
    probar presentación, claims y demás señales sin mentir sobre la evidencia).
    """

    def __init__(self, **overrides: Any) -> None:
        self.overrides = overrides
        self.states: list[dict] = []
        self.questions: list[dict] = []

    def evidence_present(self, state: dict) -> bool:
        evidencia = " ".join(
            str(state.get(key) or "")
            for key in ("evidence", "evidence_index", "tool_results")
        ).lower()
        return "byte 105" in evidencia or "fee application" in evidencia

    async def judge(self, *, state, questions, context=None):
        self.states.append(state)
        self.questions.append(questions or {})
        presente = self.evidence_present(state)
        evidencia = str(state.get("evidence") or "").lower()
        answers: dict = {}
        for question_id, spec in (questions or {}).items():
            if question_id in self.overrides:
                answers[question_id] = self.overrides[question_id]
                continue
            spec = spec or {}
            if question_id.startswith("claim_"):
                # Honesto: el claim se juzga por su texto contra la evidencia.
                claim = str(spec.get("instructions") or "").split("Claim: ", 1)[-1].lower()
                tokens = {token.strip(".,:;") for token in claim.split() if len(token) > 4}
                compartidos = sum(1 for token in tokens if token in evidencia)
                if question_id.endswith("_contradicted"):
                    answers[question_id] = {"type": "noul", "noul": 0.1}
                elif compartidos >= 1:
                    answers[question_id] = {"type": "noul", "noul": 0.9}
                else:
                    answers[question_id] = {"type": "noul", "noul": 0.1}
                continue
            if question_id in {"answer_grounded", "evidence_sufficient", "evidence_on_topic"}:
                answers[question_id] = {"type": "noul", "noul": 0.95 if presente else 0.1}
            elif question_id == "answer_complete":
                answers[question_id] = {"type": "noul", "noul": 0.9 if presente else 0.2}
            elif question_id == "answer_quality":
                answers[question_id] = {"type": "score", "score": 3.0 if presente else 1.0}
            elif question_id == "answer_explains_key_reason":
                answers[question_id] = {"type": "noul", "noul": 0.9 if presente else 0.1}
            elif question_id == "answer_is_needlessly_verbose":
                answers[question_id] = {"type": "noul", "noul": 0.1 if presente else 0.5}
            elif question_id == "important_context_missing":
                answers[question_id] = {"type": "noul", "noul": 0.1 if presente else 0.9}
            elif question_id in {"structure", "usefulness"}:
                answers[question_id] = {"type": "score", "score": 3.0 if presente else 1.0}
            elif question_id == "revision_reason":
                answers[question_id] = {
                    "type": "choice",
                    "choice": "missing_evidence" if not presente else "too_verbose",
                }
            elif spec.get("type") == "score":
                answers[question_id] = {"type": "score", "score": 2.0}
            elif spec.get("type") == "choice":
                criteria = spec.get("criteria") or {}
                choice = next(iter(criteria), "none")
                answers[question_id] = {
                    "type": "choice",
                    "choice": choice,
                    "confidence": 0.9,
                    "probabilities": {choice: 0.9},
                }
            else:
                answers[question_id] = {
                    "type": "noul",
                    "noul": 0.1 if presente else 0.9,
                }
        return {"model": "jev-test", "answers": answers}


def _agent(tools: list[str]) -> Agent:
    return Agent(
        id=uuid4(),
        organization_id=uuid4(),
        name="atpco-agent",
        tools=list(tools),
    )


def _install_engine(monkeypatch: pytest.MonkeyPatch, engine) -> None:
    import src.decision.service as service

    monkeypatch.setattr(service, "get_decision_engine", lambda: engine)


@pytest.fixture(autouse=True)
def _flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flags fijos: los tests no dependen del .env local (hermético)."""
    from src.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "RUNTIME_SOURCE_AWARE_TOOLS", False)
    monkeypatch.setattr(settings, "RUNTIME_TOOL_ROUTING_MODE", "off")
    monkeypatch.setattr(settings, "RUNTIME_TERMINATION_GATE", "off")
    monkeypatch.setattr(settings, "RUNTIME_AGENT_JEV_LOOP", "off")
    monkeypatch.setattr(settings, "RUNTIME_ANSWER_GATE", "on")
    monkeypatch.setattr(settings, "RUNTIME_AGENT_MAX_RETRIEVAL_ROUNDS", 2)


async def _run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    llm: _FakeLLM,
    judge: _Judge | None = None,
    search: _SearchStub | None = None,
    message: str = PREGUNTA,
    tools: list[str] | None = None,
) -> tuple[Any, _SearchStub]:
    stub = search or _SearchStub()
    register_tool(stub)
    if judge is not None:
        _install_engine(monkeypatch, judge)
    runtime = AgentRuntime(llm_provider=llm)
    result = await runtime.run(
        AgentRunRequest(
            agent=_agent(tools or ["search_knowledge"]),
            message=message,
            role="admin",
        )
    )
    return result, stub


# ---------------------------------------------------------------------------
# Coherencia del chequeo determinista: toda la evidencia del run, no la selección
# ---------------------------------------------------------------------------

#: Texto real de la fuente: la jerarquía del byte 105 está en el procedimiento.
JERARQUIA_BYTE_105 = (
    "Fee Application (byte 105). Determine the highest Fee Application value of "
    "all fare components on the previous ticket according to this hierarchy, "
    "reading from top to bottom: 3 Sum of the change fees of all changed fare "
    "components, 2 Highest change fee among all fare components, changed and "
    "unchanged, 5 Highest change fee among all fare components within changed "
    "pricing units, 4 Highest change fee within changed pricing units, "
    "1 Highest change fee among all changed fare components."
)


@pytest.mark.asyncio
async def test_la_jerarquia_respaldada_en_otra_ronda_no_se_marca(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caso real: el fragmento con la jerarquía quedó fuera de la selección del
    último refresh, pero el modelo lo vio (está en la evidencia del run). Marcarlo
    como inventado producía una respuesta que se contradecía."""
    from src.core.config import get_settings

    monkeypatch.setattr(get_settings(), "RUNTIME_EVIDENCE_BUDGET_CHARS", 1500)
    stub = _SearchStub(
        respuestas=[
            (
                _documento_grande(),
                {
                    "evidence": [
                        {
                            "ref": "grande",
                            "document_id": "grande",
                            "title": FUENTE_CAT31,
                            "score": 0.9,
                            "content": "Byte 105 Fee Application categoría 31. "
                            + (RELLENO * 400),
                        },
                        {
                            "ref": "jerarquia",
                            "document_id": "jerarquia",
                            "title": FUENTE_CAT31,
                            "score": 0.5,
                            "content": JERARQUIA_BYTE_105,
                        },
                    ]
                },
            )
        ]
    )
    llm = _FakeLLM(
        [
            '{"tool": "search_knowledge", "arguments": {"query": "categoría 31 byte 105"}}',
            (
                '{"answer": "El byte 105 decide cómo se aplica el fee. La jerarquía '
                "documentada, de mayor a menor prioridad, es: 3, 2, 5, 4, 1 [Doc 1].\"}"
            ),
        ]
    )
    result, _ = await _run(monkeypatch, llm=llm, judge=_Judge(), search=stub)

    revisiones = [
        step for step in result.steps if step["type"] == "answer_revision"
    ]
    assert not any("jerarquía" in str(step.get("detail")) for step in revisiones)
    assert "3, 2, 5, 4, 1" in result.answer


@pytest.mark.asyncio
async def test_respuesta_que_se_contradice_se_revisa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """«La información disponible no contiene…» seguido de la explicación."""
    stub = _SearchStub()
    llm = _FakeLLM(
        [
            '{"tool": "search_knowledge", "arguments": {"query": "categoría 31 byte 105"}}',
            (
                '{"answer": "La información disponible no contiene una definición '
                "técnica del byte 105.\\n\\n### Byte 105\\nEl byte 105 es el campo Fee "
                'Application [Doc 1]."}'
            ),
            '{"answer": "El byte 105 es el campo Fee Application: decide cómo aplicar '
            'el cambio de tarifa [Doc 1]."}',
        ]
    )
    result, _ = await _run(monkeypatch, llm=llm, judge=_Judge(), search=stub)

    revisiones = [step for step in result.steps if step["type"] == "answer_revision"]
    assert any("contradice" in str(step.get("detail")) for step in revisiones)
    assert "no contiene" not in result.answer.lower()
    assert "Fee Application" in result.answer


# ---------------------------------------------------------------------------
# Regresión: repetir la misma pregunta no puede perder la evidencia
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repetir_la_misma_pregunta_no_bloquea_la_busqueda(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caso real: la 1.ª vez respondió; la 2.ª y 3.ª dijeron «sin evidencia».

    El runtime es un singleton de proceso y `LoopGuard` recordaba la llamada del
    run anterior: la búsqueda quedaba bloqueada como «duplicate tool call» y el
    agente respondía sin evidencia.
    """
    from src.runtime.answer_gate import INSUFFICIENT_ANSWER

    search = _SearchStub()
    register_tool(search)
    _install_engine(monkeypatch, _Judge())
    # Un solo runtime (como en la API) y la misma secuencia pregunta→respuesta
    # repetida tres veces.
    llm = _FakeLLM(
        [
            '{"tool": "search_knowledge", "arguments": {"query": "categoría 31 byte 105"}}',
            '{"answer": "El byte 105 es Fee Application (sección 4.6.2) [Doc 1]."}',
        ]
        * 3
    )
    runtime = AgentRuntime(llm_provider=llm)
    agent = _agent(["search_knowledge"])

    respuestas = []
    for _ in range(3):
        result = await runtime.run(
            AgentRunRequest(agent=agent, message=PREGUNTA, role="admin")
        )
        respuestas.append(result)

    assert len(search.queries) == 3, "cada run debe poder buscar: el guard es por run"
    for result in respuestas:
        assert "loop prevention" not in str(result.steps)
        assert result.answer != INSUFFICIENT_ANSWER
        assert "Fee Application" in result.answer


@pytest.mark.asyncio
async def test_la_misma_llamada_dentro_del_run_sigue_bloqueada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El guard conserva su función: repetir la misma tool en el mismo run se corta."""
    search = _SearchStub()
    register_tool(search)
    llm = _FakeLLM(
        [
            '{"tool": "search_knowledge", "arguments": {"query": "categoría 31 byte 105"}}',
            '{"tool": "search_knowledge", "arguments": {"query": "categoría 31 byte 105"}}',
            '{"answer": "El byte 105 es Fee Application [Doc 1]."}',
        ]
    )
    result, _ = await _run(monkeypatch, llm=llm, judge=_Judge(), search=search)

    assert len(search.queries) == 1
    assert any(
        step.get("detail") == "loop prevention: duplicate tool call without new information"
        for step in result.steps
    )
    assert "Fee Application" in result.answer


# ---------------------------------------------------------------------------
# §18 — Truncamiento: la posición del chunk no decide qué evidencia llega
# ---------------------------------------------------------------------------


def test_truncamiento_ciego_pierde_el_chunk_relevante_y_la_seleccion_no() -> None:
    """El sistema antiguo cortaba el string: lo relevante se perdía por posición."""
    crudo = _documento_grande(relleno_chars=3_400)
    assert "Fee Application" not in crudo[:3000]  # el corte viejo del runtime
    assert "Fee Application" not in crudo[:1500]  # el corte viejo del gate

    registry = EvidenceRegistry()
    registry.add_from_meta(_meta_evidencia(relleno_chars=3_400))
    selection = select_evidence(registry.all_items(), PREGUNTA)
    assert "byte 105" in render_evidence(selection)
    # Los ids son del registry; el orden de la selección es por relevancia.
    assert set(selection.ids) == {"E1", "E2"}
    # El chunk relevante entró primero por match de entidad, no por posición.
    assert selection.matches[0].match == "exact_entity_match"
    assert selection.matches[0].evidence_id == "E2"


def test_selector_reparte_presupuesto_y_marca_lo_que_entra_incompleto() -> None:
    items = [
        _item(FEE_APPLICATION_BYTES_105, title=FUENTE_CAT31, score=0.4),
        _item(RELLENO * 400, title="otro.pdf", score=0.9),
    ]
    selection = select_evidence(items, PREGUNTA, budget_chars=1_200, max_item_chars=1_000)
    assert selection.items
    assert selection.chars <= 1_200
    # El fragmento relevante entra completo; el resto usa lo que queda del
    # presupuesto y queda marcado como incompleto (no se finge que entró todo).
    assert selection.matches[0].complete is True
    assert any(match.complete is False for match in selection.matches)


def test_selector_descarta_lo_que_no_cabe_en_el_presupuesto() -> None:
    items = [
        _item(FEE_APPLICATION_BYTES_105, title=FUENTE_CAT31, score=0.4),
        _item(RELLENO * 400, title="otro.pdf", score=0.9),
    ]
    selection = select_evidence(items, PREGUNTA, budget_chars=800, max_item_chars=1_000)
    assert len(selection.items) == 1
    assert selection.dropped


def test_registry_no_duplica_y_conserva_el_contenido_completo() -> None:
    registry = EvidenceRegistry()
    meta = _meta_evidencia()
    primero, nuevos = registry.add_from_meta(meta)
    assert nuevos == 2
    repetido, nuevos_otra_vez = registry.add_from_meta(meta)
    assert nuevos_otra_vez == 0
    assert [item.evidence_id for item in repetido] == ["E1", "E2"]
    largo = [item for item in primero if item.title == FUENTE_CAT31][0]
    # El registry guarda el fragmento completo; el recorte es del selector.
    assert "Value 5" in largo.content
    assert len(largo.content) == len(FEE_APPLICATION_BYTES_105)


def test_sin_contenido_no_hay_evidencia_solo_fuente() -> None:
    """SOURCE != EVIDENCE: un ítem sin fragmento no entra al registry."""
    registry = EvidenceRegistry()
    _, nuevos = registry.add_from_meta(
        {"evidence": [{"ref": "doc-1", "document_id": "doc-1", "title": "Cat31_dapp_C.pdf"}]}
    )
    assert nuevos == 0
    assert registry.is_empty()


# ---------------------------------------------------------------------------
# §10 — Evidence Sufficiency
# ---------------------------------------------------------------------------


def test_suficiencia_exact_match_permite_generar() -> None:
    registry = EvidenceRegistry()
    registry.add_from_meta(_meta_evidencia())
    sufficiency = assess_sufficiency(registry.all_items(), PREGUNTA)
    assert sufficiency.has_evidence is True
    assert sufficiency.exact_entity_match is True
    assert sufficiency.entity_coverage == 1.0
    assert sufficiency.entities_asked == ("categoría 31", "byte 105")
    assert sufficiency.recommended_action == ACTION_GENERATE


def test_suficiencia_sin_evidencia_pide_buscar_antes_de_abstenerse() -> None:
    vacio = assess_sufficiency([], PREGUNTA, retrieval_rounds_left=2)
    assert vacio.has_evidence is False
    assert vacio.recommended_action == ACTION_RETRIEVE_MORE
    agotado = assess_sufficiency([], PREGUNTA, retrieval_rounds_left=0)
    assert agotado.recommended_action == ACTION_ABSTAIN


def test_suficiencia_entidad_ausente_no_se_disfraza_de_respuesta() -> None:
    """«byte 105» con un documento que no lo menciona ≠ evidencia."""
    registry = EvidenceRegistry()
    registry.add_from_meta(
        {
            "evidence": [
                {
                    "ref": "cat35",
                    "document_id": "cat35",
                    "title": "cat35-handbook.pdf",
                    "score": 0.6,
                    "content": "La categoría 35 cubre cambios voluntarios de tarifa.",
                }
            ]
        }
    )
    sufficiency = assess_sufficiency(registry.all_items(), PREGUNTA)
    assert sufficiency.entity_coverage == 0.0
    assert sufficiency.exact_entity_match is False
    assert sufficiency.recommended_action in {ACTION_RETRIEVE_MORE, ACTION_ABSTAIN}
    assert sufficiency.missing_entities == ("categoría 31", "byte 105")


def test_suficiencia_parcial_declara_lo_que_falta() -> None:
    registry = EvidenceRegistry()
    registry.add_from_meta(
        {
            "evidence": [
                {
                    "ref": "cat31",
                    "document_id": "cat31",
                    "title": FUENTE_CAT31,
                    "score": 0.5,
                    "content": "Category 31 voluntary changes: reissue and revalidation rules.",
                }
            ]
        }
    )
    sufficiency = assess_sufficiency(registry.all_items(), PREGUNTA)
    assert sufficiency.entity_coverage == 0.5
    assert sufficiency.missing_entities == ("byte 105",)
    assert sufficiency.recommended_action == ACTION_GENERATE


# ---------------------------------------------------------------------------
# §7, §8, §14 — Política del gate: contenido ≠ presentación
# ---------------------------------------------------------------------------


class _GateEngine:
    def __init__(self, answers: dict) -> None:
        self.answers = answers
        self.state: dict = {}

    async def judge(self, *, state, questions, context=None):
        self.state = state
        return {"model": "jev-test", "answers": dict(self.answers)}


class _ClaimGateEngine:
    """Gate que además juzga claims: sólo el de Fee Application está respaldado."""

    def __init__(self, answers: dict) -> None:
        self.answers = answers
        self.state: dict = {}

    async def judge(self, *, state, questions, context=None):
        self.state = state
        answers = dict(self.answers)
        for question_id, spec in (questions or {}).items():
            if not question_id.startswith("claim_"):
                continue
            claim = str((spec or {}).get("instructions") or "").split("Claim: ", 1)[-1]
            respaldado = "fee application" in claim.lower()
            if question_id.endswith("_supported"):
                answers[question_id] = {"type": "noul", "noul": 0.9 if respaldado else 0.1}
            else:
                answers[question_id] = {"type": "noul", "noul": 0.1}
        return {"model": "jev-test", "answers": answers}


@pytest.mark.asyncio
async def test_gate_presentacion_mediocre_revisa_y_nunca_se_abstiene() -> None:
    from src.runtime.answer_gate import judge_answer

    engine = _GateEngine(
        {
            "answer_grounded": {"type": "noul", "noul": 0.95},
            "answer_complete": {"type": "noul", "noul": 0.9},
            "answer_quality": {"type": "score", "score": 1.0},
            "structure": {"type": "score", "score": 1.0},
            "revision_reason": {"type": "choice", "choice": "poor_structure"},
        }
    )
    result = await judge_answer(
        engine=engine,
        mode="on",
        user_request=PREGUNTA,
        draft="El byte 105 es Fee Application.",
        evidence=[_item(FEE_APPLICATION_BYTES_105)],
        settings=object(),
        retrieval_rounds_left=0,
    )
    assert result.verdict == "revise"
    assert result.grounding_verdict == "SUPPORTED"
    assert result.presentation_verdict == "needs_revision"
    assert result.score < 1.0  # el score de compatibilidad no se infla


@pytest.mark.asyncio
async def test_gate_con_evidencia_relevante_no_responde_falta_de_evidencia() -> None:
    """El falso negativo original: evidencia presente + borrador flojo → revisar."""
    from src.runtime.answer_gate import judge_answer

    engine = _GateEngine(
        {
            "answer_grounded": {"type": "noul", "noul": 0.1},
            "answer_complete": {"type": "noul", "noul": 0.2},
            "answer_quality": {"type": "score", "score": 1.0},
        }
    )
    result = await judge_answer(
        engine=engine,
        mode="on",
        user_request=PREGUNTA,
        draft="No estoy seguro.",
        evidence=[_item(FEE_APPLICATION_BYTES_105)],
        settings=object(),
        retrieval_rounds_left=0,
    )
    assert result.verdict == "revise"
    assert result.grounding_verdict == "PARTIAL"
    assert result.evidence_used is True


@pytest.mark.asyncio
async def test_gate_sin_evidencia_usable_pide_buscar_y_luego_se_abstiene() -> None:
    from src.runtime.answer_gate import judge_answer

    engine = _GateEngine(
        {
            "answer_grounded": {"type": "noul", "noul": 0.1},
            "answer_complete": {"type": "noul", "noul": 0.1},
            "answer_quality": {"type": "score", "score": 0.0},
        }
    )
    con_presupuesto = await judge_answer(
        engine=engine,
        mode="on",
        user_request="¿qué significa byte 999?",
        draft="Puede ser cualquiera.",
        evidence=[],
        settings=object(),
        retrieval_rounds_left=1,
    )
    assert con_presupuesto.verdict == ACTION_RETRIEVE_MORE
    sin_presupuesto = await judge_answer(
        engine=engine,
        mode="on",
        user_request="¿qué significa byte 999?",
        draft="Puede ser cualquiera.",
        evidence=[],
        settings=object(),
        retrieval_rounds_left=0,
    )
    assert sin_presupuesto.verdict == ACTION_ABSTAIN
    assert sin_presupuesto.grounding_verdict == "UNSUPPORTED"


@pytest.mark.asyncio
async def test_gate_evidencia_irrelevante_no_sostiene_la_respuesta() -> None:
    """Documento de otra categoría: no cuenta como evidencia de lo pedido."""
    from src.runtime.answer_gate import judge_answer

    engine = _GateEngine(
        {
            "answer_grounded": {"type": "noul", "noul": 0.2},
            "answer_complete": {"type": "noul", "noul": 0.2},
            "answer_quality": {"type": "score", "score": 1.0},
        }
    )
    irrelevante = _item("La categoría 35 cubre cambios voluntarios.", title="cat35-handbook.pdf")
    con_presupuesto = await judge_answer(
        engine=engine,
        mode="on",
        user_request=PREGUNTA,
        draft="El byte 105 es Fee Application.",
        evidence=[irrelevante],
        settings=object(),
        retrieval_rounds_left=2,
    )
    assert con_presupuesto.verdict == ACTION_RETRIEVE_MORE
    agotado = await judge_answer(
        engine=engine,
        mode="on",
        user_request=PREGUNTA,
        draft="El byte 105 es Fee Application.",
        evidence=[irrelevante],
        settings=object(),
        retrieval_rounds_left=0,
    )
    assert agotado.verdict == ACTION_ABSTAIN


@pytest.mark.asyncio
async def test_gate_responde_con_limites_cuando_falta_una_entidad() -> None:
    from src.runtime.answer_gate import judge_answer

    engine = _GateEngine(
        {
            "answer_grounded": {"type": "noul", "noul": 0.9},
            "answer_complete": {"type": "noul", "noul": 0.9},
            "answer_quality": {"type": "score", "score": 3.0},
        }
    )
    result = await judge_answer(
        engine=engine,
        mode="on",
        user_request=PREGUNTA,
        draft="La categoría 31 cubre cambios voluntarios.",
        evidence=[
            _item(
                "Category 31 voluntary changes: reissue and revalidation rules.",
                section_path=("1",),
            )
        ],
        settings=object(),
        retrieval_rounds_left=0,
    )
    assert result.verdict == ACTION_ANSWER_WITH_LIMITS
    assert result.missing_entities == ("byte 105",)
    assert result.grounding_verdict == "SUPPORTED"


@pytest.mark.asyncio
async def test_gate_verifica_por_claim_y_no_anula_la_respuesta_entera() -> None:
    from src.runtime.answer_gate import judge_answer

    engine = _ClaimGateEngine(
        {
            "answer_grounded": {"type": "noul", "noul": 0.9},
            "answer_complete": {"type": "noul", "noul": 0.9},
            "answer_quality": {"type": "score", "score": 3.0},
        }
    )
    draft = (
        "El byte 105 es el campo Fee Application. "
        "Siempre se cobran todas las penalidades del contrato."
    )
    result = await judge_answer(
        engine=engine,
        mode="on",
        user_request=PREGUNTA,
        draft=draft,
        evidence=[_item(FEE_APPLICATION_BYTES_105)],
        settings=object(),
        retrieval_rounds_left=0,
    )
    assert result.claims_summary.get("supported", 0) >= 1
    assert result.unsupported_claims  # el claim inventado queda identificado
    assert result.verdict == "revise"  # se revisa; no se anula la respuesta
    # El claim juzgado viaja al flujo con su veredicto (no se pierde la señal).
    claims = [step for step in [result.to_step()] if step.get("claims")]
    assert claims[0]["claims"]["unsupported"] >= 1


@pytest.mark.asyncio
async def test_gate_entrega_al_juez_la_misma_evidencia_que_ve_el_generador() -> None:
    from src.runtime.answer_gate import judge_answer

    engine = _GateEngine(
        {
            "answer_grounded": {"type": "noul", "noul": 0.95},
            "answer_complete": {"type": "noul", "noul": 0.9},
            "answer_quality": {"type": "score", "score": 3.0},
        }
    )
    registry = EvidenceRegistry()
    registry.add_from_meta(_meta_evidencia(relleno_chars=3_400))
    selection = select_evidence(registry.all_items(), PREGUNTA)
    await judge_answer(
        engine=engine,
        mode="on",
        user_request=PREGUNTA,
        draft="El byte 105 es Fee Application.",
        evidence=list(selection.items),
        settings=object(),
    )
    assert "byte 105" in str(engine.state["evidence"])
    assert "E2" in str(engine.state["evidence_index"])
    assert engine.state["evidence_signals"].startswith("fragmentos=")


# ---------------------------------------------------------------------------
# §16 — Regresión obligatoria byte 105 (end-to-end por el runtime)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repro_byte_105_no_debe_terminar_en_insuficiente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REPRODUCCIÓN: la evidencia se recupera, el borrador es correcto y aún así
    el gate respondía «No hay evidencia suficiente…» porque JEV veía una versión
    recortada de la evidencia (3000 chars en el historial, 1500 en el gate)."""
    from src.runtime.answer_gate import INSUFFICIENT_ANSWER

    llm = _FakeLLM(
        [
            '{"tool": "search_knowledge", "arguments": {"query": "categoría 31 byte 105"}}',
            (
                '{"answer": "El byte 105 es el campo Fee Application: indica cómo '
                "aplicar el cambio de tarifa. El valor 2 usa el fee más alto entre "
                'todos los fare components, cambiados y no cambiados."}'
            ),
        ]
    )
    result, search = await _run(monkeypatch, llm=llm, judge=_Judge())

    assert search.queries
    assert result.answer != INSUFFICIENT_ANSWER
    assert "Fee Application" in result.answer
    # La evidencia llegó completa al generador (y al gate).
    assert llm.calls == 2
    assert "Value 5" in llm.prompts[-1]
    # Y quedó observable, con ids, en el flujo.
    assert result.evidence and result.evidence["count"] == 2
    assert result.evidence_sufficiency["exact_entity_match"] is True
    assert result.evidence_sufficiency["entity_coverage"] == 1.0
    assert result.citations
    assert {citation["evidence_id"] for citation in result.citations} == {"E1", "E2"}


@pytest.mark.asyncio
async def test_caso_a_pregunta_documental_con_match_exacto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = _FakeLLM(
        [
            '{"tool": "search_knowledge", "arguments": {"query": "byte 105"}}',
            '{"answer": "El byte 105 es Fee Application [Doc 2]."}',
        ]
    )
    result, _ = await _run(monkeypatch, llm=llm, judge=_Judge())
    gate = next(step for step in result.steps if step["type"] == "answer_gate")
    assert gate["verdict"] == "approve"
    assert gate["grounding_verdict"] == "SUPPORTED"
    assert set(gate["evidence_ids"]) == {"E1", "E2"}
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_caso_c_jev_pide_otra_busqueda_y_luego_responde(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El gate pide evidencia (no abstención) y el runtime ejecuta la búsqueda."""
    malo_output = "[Doc 1 | source:cat35-handbook.pdf] La categoría 35 cubre cambios."
    malo_meta = {
        "evidence": [
            {
                "ref": "cat35",
                "document_id": "cat35",
                "title": "cat35-handbook.pdf",
                "score": 0.4,
                "content": "La categoría 35 cubre cambios voluntarios.",
            }
        ]
    }
    stub = _SearchStub(
        respuestas=[
            (malo_output, malo_meta),
            (_documento_grande(), _meta_evidencia()),
        ]
    )
    llm = _FakeLLM(
        [
            '{"tool": "search_knowledge", "arguments": {"query": "categoria 31"}}',
            '{"answer": "El byte 105 es Fee Application, sección 4.6.2."}',
        ]
    )
    result, search = await _run(monkeypatch, llm=llm, judge=_Judge(), search=stub)

    assert search.queries
    assert "cat31" in search.queries[1].lower()
    retrievals = [step for step in result.steps if step["type"] == "jev_retrieval"]
    assert retrievals and retrievals[0]["round"] == 1
    assert result.answer != "No hay evidencia suficiente en las fuentes consultadas para responder con confianza. Probá reformular la pregunta o cargar más información."


@pytest.mark.asyncio
async def test_caso_d_evidencia_insuficiente_se_abstiene(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Entidad inexistente: se busca, no aparece y la respuesta se abstiene."""
    from src.runtime.answer_gate import INSUFFICIENT_ANSWER

    stub = _SearchStub(
        respuestas=[
            (
                "[Doc 1 | source:cat35] La categoría 35 cubre cambios.",
                {
                    "evidence": [
                        {
                            "ref": "cat35",
                            "document_id": "cat35",
                            "title": "cat35-handbook.pdf",
                            "score": 0.4,
                            "content": "La categoría 35 cubre cambios voluntarios.",
                        }
                    ]
                },
            )
        ]
    )
    llm = _FakeLLM(
        [
            '{"tool": "search_knowledge", "arguments": {"query": "byte 999"}}',
            '{"answer": "El byte 999 no está documentado."}',
        ]
    )
    result, search = await _run(
        monkeypatch,
        llm=llm,
        judge=_Judge(),
        search=stub,
        message="¿qué significa byte 999?",
    )
    assert result.answer == INSUFFICIENT_ANSWER
    assert len(search.queries) >= 1
    gates = [step for step in result.steps if step["type"] == "answer_gate"]
    # Primero pide más evidencia; agotado el presupuesto, se abstiene.
    assert gates[0]["verdict"] == "retrieve_more"
    assert gates[-1]["verdict"] == "abstain"
    assert gates[-1]["grounding_verdict"] == "UNSUPPORTED"


@pytest.mark.asyncio
async def test_caso_f_presentacion_pobre_se_revisa_no_se_abstiene(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evidencia correcta + respuesta correcta + mala estructura → revisar."""
    judge = _Judge(
        structure={"type": "score", "score": 1.0},
        revision_reason={"type": "choice", "choice": "poor_structure"},
    )
    llm = _FakeLLM(
        [
            '{"tool": "search_knowledge", "arguments": {"query": "byte 105"}}',
            '{"answer": "Fee Application."}',
            '{"answer": "El byte 105 es Fee Application (sección 4.6.2) y decide cómo aplicar el cambio de tarifa [Doc 2]."}',
        ]
    )
    result, _ = await _run(monkeypatch, llm=llm, judge=judge)
    revisiones = [step for step in result.steps if step["type"] == "answer_revision"]
    assert revisiones
    assert result.answer != "No hay evidencia suficiente en las fuentes consultadas para responder con confianza. Probá reformular la pregunta o cargar más información."
    assert "Fee Application" in result.answer


@pytest.mark.asyncio
async def test_caso_h_jev_aprueba_y_el_claim_unsupported_se_revisa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claim sin respaldo en una respuesta respaldada: revisión, no abstención."""
    llm = _FakeLLM(
        [
            '{"tool": "search_knowledge", "arguments": {"query": "byte 105"}}',
            (
                '{"answer": "El byte 105 es Fee Application. Siempre se cobran '
                'todas las penalidades del contrato."}'
            ),
            '{"answer": "El byte 105 es Fee Application y decide cómo aplicar el cambio de tarifa [Doc 2]."}',
        ]
    )
    result, _ = await _run(monkeypatch, llm=llm, judge=_Judge())
    gate = next(step for step in result.steps if step["type"] == "answer_gate")
    assert gate["claims"]["supported"] >= 1
    assert result.answer.startswith("El byte 105 es Fee Application")


@pytest.mark.asyncio
async def test_caso_k_varias_fuentes_y_citas_por_evidence_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meta = _meta_evidencia()
    meta["evidence"].append(
        {
            "ref": "guia-interna",
            "document_id": "guia-interna",
            "title": "Guia_interna_cambios.pdf",
            "score": 0.6,
            "content": "La guía interna explica que el campo Fee Application aplica al cambio de tarifa.",
            "retrieval": "lexical",
        }
    )
    stub = _SearchStub(respuestas=[(_documento_grande(), meta)])
    llm = _FakeLLM(
        [
            '{"tool": "search_knowledge", "arguments": {"query": "byte 105 fee application"}}',
            '{"answer": "El byte 105 es Fee Application [Doc 1] y la guía interna lo confirma [Doc 3]."}',
        ]
    )
    result, _ = await _run(monkeypatch, llm=llm, judge=_Judge(), search=stub)
    assert result.evidence["count"] == 3
    citadas = {citation["evidence_id"] for citation in result.citations if citation["cited"]}
    assert len(citadas) >= 1
    assert all(citation["evidence_id"] for citation in result.citations)


@pytest.mark.asyncio
async def test_caso_l_evidencia_relevante_despues_de_mucho_texto_irrelevante(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El chunk relevante vive más allá de los viejos cortes de 3000/1500."""
    stub = _SearchStub(relleno_chars=8_000)
    llm = _FakeLLM(
        [
            '{"tool": "search_knowledge", "arguments": {"query": "categoría 31 byte 105"}}',
            '{"answer": "El byte 105 es Fee Application (sección 4.6.2)."}',
        ]
    )
    result, _ = await _run(monkeypatch, llm=llm, judge=_Judge(), search=stub)
    assert "Fee Application" in llm.prompts[-1]
    assert "Fee Application" in result.answer
    gate = next(step for step in result.steps if step["type"] == "answer_gate")
    assert gate["verdict"] in {"approve", "answer_with_limits"}
    assert set(gate["evidence_ids"]) == {"E1", "E2"}


@pytest.mark.asyncio
async def test_caso_e_claim_sin_respaldo_se_revisa_y_no_sobrevive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Una afirmación inventada se corrige; la respuesta respaldada se mantiene."""
    llm = _FakeLLM(
        [
            '{"tool": "search_knowledge", "arguments": {"query": "byte 105"}}',
            (
                '{"answer": "El byte 105 es Fee Application. Siempre se cobran '
                'todas las penalidades del contrato."}'
            ),
            '{"answer": "El byte 105 es Fee Application y decide cómo aplicar el cambio de tarifa [Doc 2]."}',
        ]
    )
    result, _ = await _run(monkeypatch, llm=llm, judge=_Judge())
    assert "penalidades" not in result.answer
    revisiones = [step for step in result.steps if step["type"] == "answer_revision"]
    assert revisiones
    gates = [step for step in result.steps if step["type"] == "answer_gate"]
    assert gates[0]["verdict"] == "revise"
    assert gates[0]["claims"]["unsupported"] >= 1
    assert gates[-1]["verdict"] == "approve"


@pytest.mark.asyncio
async def test_caso_j_cierre_por_termination_tambien_verifica_la_respuesta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El cierre por termination no saltea el verificador: sin evidencia, abstiene."""
    from src.core.config import get_settings
    from src.runtime.answer_gate import INSUFFICIENT_ANSWER

    monkeypatch.setattr(get_settings(), "RUNTIME_TERMINATION_GATE", "on")
    stub = _SearchStub(
        respuestas=[
            (
                "[Doc 1 | source:cat35] La categoría 35 cubre cambios.",
                {
                    "evidence": [
                        {
                            "ref": "cat35",
                            "document_id": "cat35",
                            "title": "cat35-handbook.pdf",
                            "score": 0.4,
                            "content": "La categoría 35 cubre cambios voluntarios.",
                        }
                    ]
                },
            )
        ]
    )
    llm = _FakeLLM(
        [
            '{"tool": "search_knowledge", "arguments": {"query": "byte 999"}}',
            '{"answer": "El byte 999 no está documentado."}',
        ]
    )
    result, _ = await _run(
        monkeypatch,
        llm=llm,
        judge=_Judge(),
        search=stub,
        message="¿qué significa byte 999?",
    )
    assert result.answer == INSUFFICIENT_ANSWER
    gates = [step for step in result.steps if step["type"] == "answer_gate"]
    assert gates and gates[-1]["verdict"] == "abstain"


@pytest.mark.asyncio
async def test_observabilidad_honesta_sin_ceros_inventados(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin entidades en la pregunta no se publica cobertura de entidades."""
    llm = _FakeLLM(
        [
            '{"tool": "search_knowledge", "arguments": {"query": "cambios voluntarios"}}',
            '{"answer": "Los cambios voluntarios se rigen por la categoría 31."}',
        ]
    )
    result, _ = await _run(
        monkeypatch,
        llm=llm,
        judge=_Judge(),
        message="¿qué dice el manual sobre cambios voluntarios de tarifa?",
    )
    sufficiency = result.evidence_sufficiency
    assert "entity_coverage" not in sufficiency
    assert "exact_entity_match" not in sufficiency
    assert sufficiency["has_evidence"] is True
    assert sufficiency["supporting_chunks"] == 2


# ---------------------------------------------------------------------------
# §17 — Casos negativos de conflicto entre fuentes
# ---------------------------------------------------------------------------


def test_conflicto_entre_fuentes_no_se_resuelve_solo() -> None:
    """Dos fuentes contradictorias → conflicto declarado, no una síntesis."""
    from src.rag.adaptive.claims import (
        ClaimJudgment,
        ClaimVerdict,
        ClaimVerification,
        response_policy,
    )

    verification = ClaimVerification(
        claims=[
            ClaimJudgment(text="El fee es 100.", verdict=ClaimVerdict.SUPPORTED.value),
            ClaimJudgment(text="El fee es 200.", verdict=ClaimVerdict.CONTRADICTED.value),
        ]
    )
    assert response_policy(verification) == "conflict"


def test_respuesta_parcial_no_se_anula_cuando_hay_contenido_respaldado() -> None:
    from src.rag.adaptive.claims import (
        ClaimJudgment,
        ClaimVerdict,
        ClaimVerification,
        response_policy,
    )

    verification = ClaimVerification(
        claims=[
            ClaimJudgment(text="El byte 105 es Fee Application.", verdict=ClaimVerdict.SUPPORTED.value),
            ClaimJudgment(text="a", verdict=ClaimVerdict.UNSUPPORTED.value),
            ClaimJudgment(text="b", verdict=ClaimVerdict.UNSUPPORTED.value),
            ClaimJudgment(text="c", verdict=ClaimVerdict.UNSUPPORTED.value),
            ClaimJudgment(text="d", verdict=ClaimVerdict.UNSUPPORTED.value),
        ]
    )
    assert response_policy(verification, retrieval_budget_left=0) == "answer_with_limits"
    sin_respaldo = ClaimVerification(
        claims=[
            ClaimJudgment(text=str(i), verdict=ClaimVerdict.UNSUPPORTED.value)
            for i in range(4)
        ]
    )
    assert response_policy(sin_respaldo, retrieval_budget_left=0) == "abstain"
