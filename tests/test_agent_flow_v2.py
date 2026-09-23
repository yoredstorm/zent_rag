# =============================================================================
# Agent flow canónico — el backend es la fuente de verdad del run (§48-§54).
# =============================================================================
# Fixture base: la captura real del Agent Playground que mostraba
# "Decidió el camino → Redactó la respuesta" con ceros inventados.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.agents.runtime.agent_runtime import AgentRunResult
from src.rag.flow_story import (
    STEP_KIND_PHASES,
    UNMAPPED_STEP_PHASE,
    build_flow_events,
    with_story,
)
from src.runtime.agent_flow import (
    _PAYLOAD_KEYS,
    INTENTIONALLY_HIDDEN_STEPS,
    build_agent_flow,
    jev_summary,
    step_to_flow,
    steps_to_flow,
)

#: Pasos reales de la captura: dos llamadas al LLM, routing JEV y search_knowledge.
CAPTURE_STEPS: list[dict] = [
    {
        "type": "llm",
        "step": 0,
        "model": "zent-default",
        "action": {"tool": "search_knowledge"},
        "tokens": 900,
        "latency_ms": 3200.0,
    },
    {
        "type": "tool_routing",
        "mode": "jev",
        "choice": "search_knowledge",
        "confidence": 0.83,
        "certainty": 0.66,
        "needs_tool": True,
        "score": 0.83,
        "certain": True,
        "alternatives": ["query_database"],
        "latency_ms": 41.0,
    },
    {
        "type": "tool_call",
        "tool": "search_knowledge",
        "latency_ms": 810.0,
        "output": "[Doc 1 | source:s-1] Contenido",
        "meta": {
            "source_ids": ["s-1"],
            "evidence": [
                {
                    "ref": "d-1",
                    "document_id": "d-1",
                    "source_id": "s-1",
                    "title": "contrato.pdf",
                    "score": 0.81,
                    "status": "USED",
                }
            ],
            "retrieval": {"chunks": 5, "strategy": "hybrid", "top_score": 0.81},
        },
    },
    {
        "type": "llm",
        "step": 1,
        "model": "zent-default",
        "action": {"answer": "La cláusula aplica..."},
        "tokens": 740,
        "latency_ms": 2100.0,
    },
    {
        "type": "answer_gate",
        "verdict": "approve",
        "score": 0.87,
        "grounded": True,
        "complete": True,
        "quality": 3.0,
        "provider": "jev",
        "mode": "answer_gate",
        "latency_ms": 55.0,
    },
    {"type": "final", "answer": "La cláusula aplica..."},
]

REASONING_STEPS: list[dict] = [
    {"type": "reasoning_classification", "status": "ok", "reasoning": {"shape": "STATE_TRANSITION", "is_complex": True}},
    {"type": "company_context", "status": "ok", "company_context": {"counts": {"concepts": 3, "rules": 2}}},
    {"type": "reasoning_plan", "status": "ok", "plan": {"shape": "STATE_TRANSITION", "question_to_prove": "si el registro necesita CLOSE", "operations": ["reconstruir"], "status": "ready"}},
    {"type": "scenario_parse", "status": "warn", "scenario": {"events": 17, "unparsed": 3}},
    {"type": "state_reconstruction", "status": "ok", "transitions": {"confirmed": 10, "unresolved": 0, "chain": []}},
    {"type": "hypothesis_test", "status": "warn", "hypotheses": {"supported": 1, "rejected": 1, "unresolved": 0, "items": []}},
    {"type": "inference_verification", "status": "ok", "inference": {"verdicts": [{"verdict": "SUPPORTED"}]}},
    {"type": "analysis_completion", "status": "ok", "completion": {"complete": True, "blockers": []}},
    {"type": "tool_call", "tool": "search_knowledge", "latency_ms": 500.0, "output": "registros"},
    {"type": "answer_gate", "verdict": "approve", "grounded": True, "complete": True, "quality": 3.0, "provider": "jev", "latency_ms": 40.0},
    {"type": "final", "answer": "No."},
]


def _result(steps: list[dict], **overrides) -> AgentRunResult:
    payload = dict(
        run_id=uuid4(),
        agent_id=uuid4(),
        organization_id=uuid4(),
        status="completed",
        answer="La cláusula aplica...",
        message="¿aplica la cláusula?",
        steps=steps,
        spans=[
            {"stage": "llm", "name": "llm:zent-default", "duration_ms": 3200.0, "started_ms": 10.0},
            {"stage": "retrieval", "name": "tool:search_knowledge", "duration_ms": 810.0, "started_ms": 3400.0},
            {"stage": "llm", "name": "llm:zent-default", "duration_ms": 2100.0, "started_ms": 4300.0},
        ],
        total_latency_ms=14380.0,
        total_tokens=1640,
        prompt_tokens=1200,
        completion_tokens=440,
        cost=0.000381,
        model="zent-default",
        provider="litellm",
    )
    payload.update(overrides)
    return AgentRunResult(**payload)


def _flow(steps: list[dict] | None = None, **overrides) -> dict:
    return build_agent_flow(
        result=_result(steps if steps is not None else CAPTURE_STEPS, **overrides),
        question="¿aplica la cláusula?",
        agent_tools=("search_knowledge", "query_database"),
        reasoning_mode="on",
        jev_configured=True,
    )


# ---------------------------------------------------------------------------
# §48 — la captura real debe producir Flow v2 completo
# ---------------------------------------------------------------------------


def test_captura_real_produce_flow_v2_con_eventos() -> None:
    flow = _flow()
    assert flow["flow_version"] == 2
    assert flow["events"]
    kinds = [event["kind"] for event in flow["events"]]
    for expected in ("tool_routing", "tool_call", "llm", "answer_gate", "final"):
        assert expected in kinds, f"falta {expected} en la historia"
    assert flow["status"] == "completed"


def test_captura_real_reporta_tokens_y_costo_reales() -> None:
    flow = _flow()
    generation = flow["generation"]
    assert generation["prompt_tokens"] == 1200
    assert generation["completion_tokens"] == 440
    assert generation["total_tokens"] == 1640
    assert generation["cost"] == pytest.approx(0.000381)
    assert generation["calls"] == 2
    assert generation["answer_calls"] == 1
    assert generation["reasoning_calls"] == 1
    assert generation["model"] == "zent-default"


def test_captura_real_jev_intervino_sin_score_global_falso() -> None:
    flow = _flow()
    jev = flow["jev"]
    assert jev["used"] is True
    assert jev["calls"] == 2
    assert sorted(jev["phases"]) == ["answer_gate", "tool_routing"]
    assert jev["verdict"] == "approve"
    # El score del gate pertenece al gate: no se publica como score universal.
    assert jev["score"] == 0.87
    assert flow["decision"]["provider"] == "explicit_target"
    assert "confidence" not in flow["decision"]


def test_captura_real_fuentes_desde_metadata_no_del_texto() -> None:
    flow = _flow()
    assert flow["sources"] == [
        {
            "document_id": "d-1",
            "source_id": "s-1",
            "title": "contrato.pdf",
            "score": 0.81,
            "status": "USED",
            "kind": "document",
        }
    ]


def test_captura_real_verificacion_no_colapsa_a_booleano() -> None:
    flow = _flow()
    verification = flow["verification"]
    assert verification["overall"] == "verified"
    keys = {check["key"] for check in verification["checks"]}
    assert "answer_gate" in keys
    assert "grounding" in keys


def test_captura_real_telemetria_declara_lo_observado() -> None:
    telemetry = _flow()["telemetry"]
    assert telemetry["tools"] == "observed"
    assert telemetry["evidence"] == "observed"
    assert telemetry["generation"] == "observed"
    assert telemetry["memory"] == "not_observed"


def test_timings_usan_spans_sin_doble_conteo() -> None:
    timings = _flow()["timings"]
    assert timings["total_ms"] == 14380.0
    assert timings["llm_ms"] == 5300.0
    assert timings["tools_ms"] == 810.0
    assert timings["gates_ms"] == 96.0
    assert timings["span_stages"] == {"llm": 5300.0, "retrieval": 810.0}


# ---------------------------------------------------------------------------
# §49 — Evidence Reasoning visible en la historia
# ---------------------------------------------------------------------------


def test_evidence_reasoning_visible_en_todas_las_fases() -> None:
    flow = _flow(REASONING_STEPS, answer="No.")
    kinds = [event["kind"] for event in flow["events"]]
    for expected in (
        "reasoning_classification",
        "company_context",
        "reasoning_plan",
        "scenario_parse",
        "state_reconstruction",
        "hypothesis_test",
        "inference_verification",
        "analysis_completion",
    ):
        assert expected in kinds, f"falta {expected}"
    phases = {event["phase"] for event in flow["events"]}
    assert {"understanding", "context", "planning", "reasoning", "verification"} <= phases


def test_reasoning_payloads_no_se_destruyen() -> None:
    flow = _flow(REASONING_STEPS, answer="No.")
    events = {event["kind"]: event for event in flow["events"]}
    assert events["reasoning_plan"]["metrics"]["plan"]["question_to_prove"].startswith("si el")
    assert events["hypotheses" if "hypotheses" in events else "hypothesis_test"]["metrics"][
        "hypotheses"
    ]["rejected"] == 1
    assert events["scenario_parse"]["metrics"]["scenario"]["events"] == 17
    assert events["state_reconstruction"]["metrics"]["transitions"]["confirmed"] == 10
    assert events["analysis_completion"]["metrics"]["completion"]["complete"] is True
    assert events["answer_gate"]["metrics"]["verdict"] == "approve"


def test_tool_routing_conserva_choice_y_confianza() -> None:
    events = {event["kind"]: event for event in _flow()["events"]}
    routing = events["tool_routing"]
    assert routing["metrics"]["choice"] == "search_knowledge"
    assert routing["metrics"]["confidence"] == 0.83
    assert routing["metrics"]["alternatives"] == ["query_database"]


# ---------------------------------------------------------------------------
# §7, §50 — unknown no es cero
# ---------------------------------------------------------------------------


def test_sin_mediciones_no_se_inventan_ceros() -> None:
    result = AgentRunResult(
        run_id=uuid4(),
        agent_id=uuid4(),
        organization_id=uuid4(),
        status="completed",
        answer="ok",
        steps=[{"type": "final", "answer": "ok"}],
    )
    flow = build_agent_flow(result=result, question="hola", agent_tools=())
    assert "confidence" not in flow["decision"]
    assert "score" not in flow["jev"]
    assert "quality" not in flow["jev"]
    assert flow["jev"]["used"] is False
    assert "prompt_tokens" not in flow["generation"]
    assert "cost" not in flow["generation"]
    assert "calls" not in flow["generation"]
    telemetry = flow["telemetry"]
    assert telemetry["generation"] == "not_available"
    assert telemetry["cost"] == "not_available"
    assert telemetry["tools"] == "not_applicable"


def test_jev_passthrough_no_cuenta_como_intervencion() -> None:
    steps = [
        {"type": "tool_routing", "mode": "passthrough", "skip_reason": "too_few_tools", "tools_count": 1},
        {"type": "answer_gate", "provider": "skip", "mode": "off"},
        {"type": "final", "answer": "ok"},
    ]
    response = steps_to_flow(steps)
    assert response["jev"]["used"] is False
    assert response["jev"]["calls"] == 0
    assert "score" not in response["jev"]


def test_verificacion_parcial_cuando_falta_el_respaldo() -> None:
    steps = [dict(step) for step in CAPTURE_STEPS]
    gate = next(step for step in steps if step["type"] == "answer_gate")
    gate.pop("grounded")
    flow = _flow(steps)
    assert flow["verification"]["overall"] == "partial"
    event = next(event for event in flow["events"] if event["kind"] == "verification")
    # "partial" no es una incidencia: no debe pintar el run como warning (§47).
    assert event["status"] == "ok"


def test_abstencion_marca_verificacion_bloqueada() -> None:
    steps = [
        {"type": "answer_gate", "verdict": "abstain", "provider": "jev", "grounded": False},
        {"type": "final", "answer": "No tengo suficiente información."},
    ]
    flow = _flow(steps)
    assert flow["verification"]["overall"] == "blocked"
    event = next(event for event in flow["events"] if event["kind"] == "verification")
    assert event["status"] == "warn"


# ---------------------------------------------------------------------------
# §37, §54 — ningún step se pierde en silencio
# ---------------------------------------------------------------------------


def test_step_desconocido_se_preserva_y_se_marca() -> None:
    flow = _flow(CAPTURE_STEPS + [{"type": "paso_futuro", "status": "ok", "payload": {"x": 1}}])
    event = next(event for event in flow["events"] if event["kind"] == "paso_futuro")
    assert event["phase"] == UNMAPPED_STEP_PHASE
    assert event["technical"]["unmapped"] is True
    assert event["metrics"]["payload"] == {"x": 1}


def test_invariante_todo_step_runtime_tiene_mapping_o_razon() -> None:
    sin_mapeo = set(_PAYLOAD_KEYS) - set(STEP_KIND_PHASES) - set(INTENTIONALLY_HIDDEN_STEPS)
    assert sin_mapeo == set(), (
        "estos steps del runtime no llegan a la historia y no están declarados "
        f"como ocultos a propósito: {sorted(sin_mapeo)}"
    )


def test_step_to_flow_conserva_campos_de_gate() -> None:
    entry = step_to_flow(next(step for step in CAPTURE_STEPS if step["type"] == "answer_gate"))
    assert entry["type"] == "answer_gate"
    assert entry["verdict"] == "approve"
    assert entry["grounded"] is True
    assert entry["quality"] == 3.0
    assert entry["provider"] == "jev"
    assert "unmapped" not in entry


# ---------------------------------------------------------------------------
# §3, §13 — contrato del SSE
# ---------------------------------------------------------------------------


def test_payload_del_run_incluye_flow_y_tokens() -> None:
    from src.api.routes.agent_runs import _run_payload

    result = _result(CAPTURE_STEPS)
    payload = _run_payload(result, _flow())
    assert payload["run_id"] == str(result.run_id)
    assert payload["flow"]["flow_version"] == 2
    assert payload["prompt_tokens"] == 1200
    assert payload["completion_tokens"] == 440
    assert payload["total_tokens"] == 1640
    assert payload["cost"] == pytest.approx(0.000381)
    assert payload["provider"] == "litellm"
    assert payload["model"] == "zent-default"
    assert payload["steps"]


def test_flow_sin_steps_sigue_siendo_v2() -> None:
    flow = _flow([{"type": "final", "answer": "ok"}])
    assert flow["flow_version"] == 2
    assert flow["events"]


# ---------------------------------------------------------------------------
# §26-§29 — memoria por run (endpoint existente, probado acá)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_impact_por_run_delega_en_el_servicio(monkeypatch) -> None:
    import src.api.routes.memory as memory_routes

    captured: dict = {}

    class FakeService:
        async def run_impact(self, organization_id, *, run_id=None, conversation_id=None):
            captured["run_id"] = run_id
            return {"used": [{"memory_id": "m1"}, {"memory_id": "m2"}], "created": [{"memory_id": "m3"}],
                    "reinforced": [], "contradicted": []}

    class FakeCtx:
        organization_id = uuid4()

    monkeypatch.setattr(memory_routes, "require_permission", lambda *a, **k: FakeCtx())
    monkeypatch.setattr(memory_routes, "_service", lambda: FakeService())
    run_id = uuid4()
    payload = await memory_routes.run_impact(run_id, request=None)  # type: ignore[arg-type]
    assert captured["run_id"] == run_id
    assert len(payload["used"]) == 2
    assert len(payload["created"]) == 1


# ---------------------------------------------------------------------------
# §32 — endpoint genérico de ejecuciones
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executions_endpoint_normaliza_agente_sin_flow(monkeypatch) -> None:
    import src.api.routes.executions as executions

    class FakeCtx:
        organization_id = uuid4()

    run_id = uuid4()

    async def fake_get_flow(organization_id, run_id):  # noqa: ANN001
        return None

    async def fake_get_run(organization_id, run_id):  # noqa: ANN001
        return {"status": "completed", "steps": CAPTURE_STEPS}

    monkeypatch.setattr(executions, "require_permission", lambda *a, **k: FakeCtx())
    import src.agents.runtime.trace_store as store

    monkeypatch.setattr(store, "get_flow", fake_get_flow)
    monkeypatch.setattr(store, "get_run", fake_get_run)
    monkeypatch.setattr(store, "ensure_agent_runs_table", lambda: _noop())

    payload = await executions.execution_flow("agent", str(run_id), request=None)  # type: ignore[arg-type]
    # Run viejo sin flow persistido: se declara v1, no se fabrican eventos.
    assert payload["flow"]["flow_version"] == 1
    assert "events" not in payload["flow"]
    assert payload["flow"]["steps"]


@pytest.mark.asyncio
async def test_executions_endpoint_rechaza_kind_invalido(monkeypatch) -> None:
    import src.api.routes.executions as executions

    class FakeCtx:
        organization_id = uuid4()

    monkeypatch.setattr(executions, "require_permission", lambda *a, **k: FakeCtx())
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await executions.execution_flow("nope", str(uuid4()), request=None)  # type: ignore[arg-type]


async def _noop() -> None:
    return None


# ---------------------------------------------------------------------------
# Compatibilidad: el portal viejo sigue leyendo name/status/ms/detail
# ---------------------------------------------------------------------------


def test_campos_de_compatibilidad_presentes() -> None:
    flow = with_story({"steps": steps_to_flow(CAPTURE_STEPS)["steps"]})
    for event in flow["events"]:
        assert event["id"] and event["phase"] and event["kind"]
    entry = step_to_flow(CAPTURE_STEPS[0])
    assert entry["name"] == "LLM (razonamiento)"
    assert entry["status"] == "ok"
    assert entry["ms"] == 3200.0
    assert isinstance(entry["detail"], str)


def test_build_flow_events_sigue_siendo_puro() -> None:
    flow = {"steps": [{"type": "final", "answer": "ok"}]}
    first = build_flow_events(flow)
    second = build_flow_events(flow)
    assert first == second


def test_jev_summary_ignora_passthrough() -> None:
    assert jev_summary([{"type": "tool_routing", "mode": "passthrough"}])["used"] is False
    assert jev_summary([{"type": "tool_routing", "mode": "jev", "choice": "x"}])["used"] is True
