# =============================================================================
# Agent flow — EL BUILDER CANÓNICO del run de agente (fuente de verdad).
# =============================================================================
# El backend es la única autoridad sobre qué ocurrió: qué decidió Zent, qué JEV
# se ejecutó, qué tools se usaron, qué evidencia se obtuvo, qué verificaciones
# corrieron, tokens, costos y latencias. El portal RENDERIZA; no reconstruye.
#
# Reglas no negociables (docs/architecture/execution-story.md):
#
# - UNKNOWN != ZERO: un valor no medido se OMITE. Nunca `confidence: 0`,
#   `score: 0` ni `tokens: 0` para representar "no disponible".
# - Los raw steps se preservan con su semántica: type + payloads estructurados
#   (reasoning, company_context, plan, scenario, transitions, hypotheses,
#   inference, completion, tool_routing, answer_gate, meta, ...).
# - Un step sin mapping canónico NO se pierde: se emite con su kind original y
#   `technical.unmapped = true` (el portal lo cuenta y avisa).
# - El costo del run es costo de LLM: se reporta como total, no se atribuye a
#   una fase que no lo produjo.
# =============================================================================
from __future__ import annotations

from typing import Any

#: Tipos de step → campos que se copian VERBATIM al flow (nunca se inventan).
_PAYLOAD_KEYS: dict[str, tuple[str, ...]] = {
    "llm": ("step", "model", "action", "tokens", "latency_ms"),
    "tool_call": ("tool", "output", "error", "meta", "latency_ms"),
    "tool_routing": (
        "mode",
        "skip_reason",
        "choice",
        "confidence",
        "certainty",
        "needs_tool",
        "score",
        "certain",
        "alternatives",
        "tools_count",
        "provider",
        "questions",
        "latency_ms",
    ),
    "tool_filter": ("omitted",),
    "answer_gate": (
        "verdict",
        "score",
        "grounded",
        "complete",
        "quality",
        "provider",
        "mode",
        "state_chars",
        "latency_ms",
        "detail",
        "answers",
    ),
    "answer_revision": ("feedback", "latency_ms"),
    "termination_gate": ("stop", "provider", "score", "certain", "detail", "latency_ms"),
    "router_fallback": ("attempts", "final_model"),
    "reasoning_incomplete": ("detail", "shape"),
    "guardrail": ("detail", "tool"),
    "error": ("detail",),
    "final": ("answer", "detail"),
    "context": ("sections",),
    # Razonamiento estructurado (reasoning_step.reasoning_steps_detailed).
    "reasoning_classification": ("reasoning", "detail", "latency_ms"),
    "company_context": ("company_context", "detail", "latency_ms"),
    "reasoning_plan": ("plan", "detail", "latency_ms"),
    "scenario_parse": ("scenario", "detail", "latency_ms"),
    "state_reconstruction": ("transitions", "detail", "latency_ms"),
    "timeline": ("timeline", "detail", "latency_ms"),
    "hypothesis_test": ("hypotheses", "detail", "latency_ms"),
    "inference_verification": ("inference", "detail", "latency_ms"),
    "analysis_completion": ("completion", "detail", "latency_ms"),
    "memory": ("memory", "detail", "latency_ms"),
}

#: Steps que el runtime emite y que NO producen evento canónico por diseño.
#: Debe quedar vacío: todo step observable se mapea. Si un tipo nuevo aparece
#: acá, la razón tiene que estar escrita (test de invariante lo verifica).
INTENTIONALLY_HIDDEN_STEPS: frozenset[str] = frozenset()

#: Tipos que representan una llamada real a JEV (tool routing / gates).
_JEV_STEP_TYPES: dict[str, str] = {
    "tool_routing": "tool_routing",
    "termination_gate": "termination",
    "answer_gate": "answer_gate",
}

STEP_LABEL: dict[str, str] = {
    "llm": "LLM (razonamiento)",
    "tool_call": "Herramienta",
    "tool_routing": "JEV elige herramienta",
    "tool_filter": "Herramientas omitidas",
    "termination_gate": "JEV verifica cierre",
    "answer_gate": "JEV verifica respuesta",
    "answer_revision": "Revisión con feedback de JEV",
    "final": "Respuesta final",
    "guardrail": "Límite",
    "error": "Error",
}

OMIT_REASON_LABEL: dict[str, str] = {
    "no_data_sources": "el agente no tiene fuentes de datos",
    "no_tabular_sources": "el agente no tiene CSV/Excel",
    "no_api_allowlist": "no hay APIs permitidas configuradas",
}

VERDICT_LABEL: dict[str, str] = {
    "approve": "aprobada",
    "revise": "revisar",
    "revise_exhausted": "aprobada (revisión ya usada)",
    "abstain": "abstención",
}

SKIP_REASON_LABEL: dict[str, str] = {
    "no_engine": "JEV no configurado",
    "no_payload": "JEV sin respuesta",
}

#: Herramientas que traen evidencia documental/estructurada.
_RETRIEVAL_TOOL_MARKERS = ("kb", "search", "retrieve", "rag")


def _num(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _clean(value: Any) -> Any:
    """None se omite; dicts/listas se limpian recursivamente. Cero se conserva."""
    if value is None:
        return None
    if isinstance(value, dict):
        cleaned = {str(key): _clean(item) for key, item in value.items()}
        return {key: item for key, item in cleaned.items() if item is not None} or None
    if isinstance(value, (list, tuple)):
        items = [_clean(item) for item in value]
        return [item for item in items if item is not None] or None
    return value


def _skip_detail(step: dict[str, Any]) -> str:
    """Detalle honesto cuando el router no consultó a JEV."""
    reason = str(step.get("skip_reason") or "")
    if reason in SKIP_REASON_LABEL:
        return SKIP_REASON_LABEL[reason]
    if reason == "too_few_tools":
        count = _int(step.get("tools_count"))
        plural = "herramientas activas" if count != 1 else "herramienta activa"
        return f"JEV no consultado · {count} {plural}"
    return "JEV no consultado"


def _detail_for(step: dict[str, Any], step_type: str) -> str:
    if step_type == "tool_routing":
        if str(step.get("mode") or "") == "passthrough":
            return _skip_detail(step)
        choice = str(step.get("choice") or "—")
        parts = [choice]
        confidence = _num(step.get("confidence"))
        if confidence > 0:
            parts.append(f"confianza {confidence:.2f}")
        score = _num(step.get("score"))
        if score > 0:
            parts.append(f"score {score:.2f}")
        if step.get("certain") is False:
            parts.append("sin certeza (decide el LLM)")
        return " · ".join(parts)
    if step_type == "answer_gate":
        verdict = VERDICT_LABEL.get(str(step.get("verdict") or ""), str(step.get("verdict") or ""))
        parts = []
        if step.get("grounded") is True:
            parts.append("respaldada")
        elif step.get("grounded") is False:
            parts.append("sin respaldo")
        if step.get("complete") is True:
            parts.append("completa")
        elif step.get("complete") is False:
            parts.append("incompleta")
        quality = _num(step.get("quality"))
        if quality > 0:
            parts.append(f"calidad {quality:g}/3")
        if verdict:
            parts.append(f"→ {verdict}")
        return " · ".join(parts)
    if step_type == "termination_gate":
        return "cerró el run" if step.get("stop") else "continuó"
    if step_type == "answer_revision":
        return str(step.get("feedback") or "corrección pedida por JEV")[:200]
    if step_type == "tool_call":
        if step.get("error"):
            return str(step["error"])[:160]
        if step.get("output"):
            return str(step["output"])[:120]
        return "herramienta"
    if step_type == "tool_filter":
        omitted = step.get("omitted") if isinstance(step.get("omitted"), list) else []
        parts = []
        for item in omitted:
            if not isinstance(item, dict):
                continue
            tool = str(item.get("tool") or "herramienta")
            reason = OMIT_REASON_LABEL.get(
                str(item.get("reason") or ""), str(item.get("reason") or "")
            )
            parts.append(f"{tool} ({reason})" if reason else tool)
        return " · ".join(parts) or "sin cambios"
    if step_type == "llm":
        return " · ".join(
            part
            for part in (
                str(step.get("model") or ""),
                f"{_int(step.get('tokens'))} tokens" if _num(step.get("tokens")) > 0 else "",
                ", ".join(str(k) for k in step["action"]) if isinstance(step.get("action"), dict) else "",
            )
            if part
        )
    return str(step.get("detail") or step.get("status") or "")[:160]


def _status_for(step: dict[str, Any], step_type: str) -> str:
    if step.get("error") or step_type == "tool_filter":
        return "warn"
    if str(step.get("verdict") or "") == "abstain":
        return "warn"
    if step.get("status") == "warn":
        return "warn"
    return "ok"


def step_to_flow(step: dict[str, Any]) -> dict[str, Any]:
    """Un raw step → entrada de timeline, preservando su semántica completa.

    Conserva los campos históricos (`name/status/ms/detail`) para portales
    viejos y agrega `type` + payloads estructurados sin rellenar ceros.
    """
    if not isinstance(step, dict):
        return {}
    step_type = str(step.get("type") or "")
    entry: dict[str, Any] = {
        "name": (
            str(step.get("tool") or "herramienta")
            if step_type == "tool_call"
            else STEP_LABEL.get(step_type, step_type or "paso")
        ),
        "status": _status_for(step, step_type),
        "ms": round(_num(step.get("latency_ms") or step.get("ms")), 2),
        "detail": _detail_for(step, step_type)[:200],
        "type": step_type or "llm",
        **({"tool": str(step.get("tool") or "")} if step_type == "tool_call" else {}),
        **(
            {"latency_ms": round(_num(step.get("latency_ms")), 2)}
            if step_type
            else {}
        ),
    }
    keys = _PAYLOAD_KEYS.get(step_type)
    if keys is None:
        # Tipo sin mapping canónico: se preserva COMPLETO (claves planas) y se
        # marca para que el portal lo cuente como no mapeado (§37).
        for key, value in step.items():
            if key == "type" or key in entry:
                continue
            cleaned = _clean(value)
            if cleaned is not None:
                entry[key] = cleaned
        entry["unmapped"] = True
        return entry
    for key in keys:
        # Los campos de compatibilidad (name/status/ms/detail/tool) ya tienen su
        # versión legible: no se pisan con el valor crudo.
        if key in entry:
            continue
        cleaned = _clean(step.get(key))
        if cleaned is None:
            continue
        entry[key] = cleaned
    return entry


def steps_to_flow(steps: Any) -> dict[str, Any]:
    """Timeline + resumen JEV. Compatibilidad con el camino de dispatch."""
    rows = [step for step in (steps or []) if isinstance(step, dict)] if isinstance(steps, list) else []
    timeline = [step_to_flow(step) for step in rows]
    return {"steps": timeline, "jev": jev_summary(rows)}


# ---------------------------------------------------------------------------
# Resúmenes (JEV, fuentes, generación, verificación, tiempos, telemetría)
# ---------------------------------------------------------------------------


def jev_summary(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Qué JEV corrió de verdad. `passthrough` y `provider=skip` NO cuentan."""
    calls = 0
    phases: list[str] = []
    verdict: str | None = None
    grounded: bool | None = None
    complete: bool | None = None
    quality: float | None = None
    score: float | None = None
    reused = False
    for step in steps:
        step_type = str(step.get("type") or "")
        phase = _JEV_STEP_TYPES.get(step_type)
        if phase is None:
            continue
        provider = str(step.get("provider") or "jev")
        mode = str(step.get("mode") or "")
        if mode == "passthrough" or provider == "skip":
            continue
        calls += 1
        if phase not in phases:
            phases.append(phase)
        if step.get("reused") is True or step.get("cached") is True:
            reused = True
        if step_type == "answer_gate":
            if step.get("verdict"):
                verdict = str(step["verdict"])
            if isinstance(step.get("grounded"), bool):
                grounded = bool(step["grounded"])
            if isinstance(step.get("complete"), bool):
                complete = bool(step["complete"])
            if _num(step.get("quality")) > 0:
                quality = round(_num(step.get("quality")), 2)
            if _num(step.get("score")) > 0:
                score = round(_num(step.get("score")), 4)
    summary: dict[str, Any] = {"used": calls > 0, "calls": calls}
    if phases:
        summary["phases"] = phases
    if verdict:
        summary["verdict"] = verdict
    if grounded is not None:
        summary["grounded"] = grounded
    if complete is not None:
        summary["complete"] = complete
    if quality is not None:
        summary["quality"] = quality
    if score is not None:
        summary["score"] = score
    if reused:
        summary["reused"] = True
    return summary


def collect_sources(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fuentes reales del run, desde la metadata estructurada de las tools."""
    sources: dict[str, dict[str, Any]] = {}
    for step in steps:
        if str(step.get("type") or "") != "tool_call":
            continue
        meta = step.get("meta") if isinstance(step.get("meta"), dict) else {}
        evidence = meta.get("evidence") if isinstance(meta.get("evidence"), list) else []
        for item in evidence:
            if not isinstance(item, dict):
                continue
            ref = str(item.get("ref") or item.get("document_id") or item.get("source_id") or "")
            if not ref:
                continue
            current = sources.get(ref)
            score = _num(item.get("score"))
            if current is None:
                sources[ref] = {
                    "document_id": item.get("document_id"),
                    "source_id": item.get("source_id"),
                    "title": item.get("title"),
                    "score": round(score, 4),
                    "status": str(item.get("status") or "USED"),
                    "kind": "document",
                    **({"authority": item["authority"]} if item.get("authority") else {}),
                }
            elif score > _num(current.get("score")):
                current["score"] = round(score, 4)
    return list(sources.values())[:16]


def generation_summary(
    result: Any, steps: list[dict[str, Any]]
) -> dict[str, Any]:
    """Bloque de generación: N llamadas, no todo atribuido a la última."""
    llm_steps = [step for step in steps if str(step.get("type") or "") == "llm"]
    answer_calls = 0
    reasoning_calls = 0
    llm_ms = 0.0
    for step in llm_steps:
        action = step.get("action") if isinstance(step.get("action"), dict) else {}
        llm_ms += _num(step.get("latency_ms"))
        if action.get("answer"):
            answer_calls += 1
        elif action.get("tool"):
            reasoning_calls += 1
    payload: dict[str, Any] = {}
    if getattr(result, "model", None):
        payload["model"] = str(result.model)
    if getattr(result, "provider", None):
        payload["provider"] = str(result.provider)
    prompt_tokens = _int(getattr(result, "prompt_tokens", 0))
    completion_tokens = _int(getattr(result, "completion_tokens", 0))
    total_tokens = _int(getattr(result, "total_tokens", 0))
    if prompt_tokens or completion_tokens or total_tokens:
        payload["prompt_tokens"] = prompt_tokens
        payload["completion_tokens"] = completion_tokens
        payload["total_tokens"] = total_tokens
    cost = _num(getattr(result, "cost", 0.0))
    if cost > 0:
        payload["cost"] = round(cost, 6)
    if llm_steps:
        payload["calls"] = len(llm_steps)
        if answer_calls:
            payload["answer_calls"] = answer_calls
        if reasoning_calls:
            payload["reasoning_calls"] = reasoning_calls
        if llm_ms > 0:
            payload["ms"] = round(llm_ms, 1)
        payload["skipped"] = False
    return payload


_VERIFICATION_LABELS: dict[str, str] = {
    "analysis_complete": "análisis",
    "inference_supported": "inferencia",
    "answer_gate": "verificación de respuesta",
    "grounding": "respaldo en fuentes",
    "claims": "afirmaciones",
}


def verification_summary(steps: list[dict[str, Any]], flow: dict[str, Any]) -> dict[str, Any]:
    """Verificación real: varias comprobaciones, nunca un booleano (§19, §20)."""
    checks: list[dict[str, Any]] = []
    completion = None
    inference = None
    answer_gate = None
    for step in steps:
        step_type = str(step.get("type") or "")
        if step_type == "analysis_completion" and isinstance(step.get("completion"), dict):
            completion = step["completion"]
        elif step_type == "inference_verification" and isinstance(step.get("inference"), dict):
            inference = step["inference"]
        elif step_type == "answer_gate":
            answer_gate = step

    if completion is not None:
        complete = completion.get("complete")
        if isinstance(complete, bool):
            checks.append(
                {
                    "key": "analysis_complete",
                    "state": "ok" if complete else "blocked",
                    "detail": ",".join(str(item) for item in (completion.get("blockers") or [])[:3])
                    or None,
                }
            )
    if inference is not None:
        verdicts = inference.get("verdicts") if isinstance(inference.get("verdicts"), list) else []
        unsupported = [item for item in verdicts if str((item or {}).get("verdict")) != "SUPPORTED"]
        if verdicts:
            checks.append(
                {
                    "key": "inference_supported",
                    "state": "blocked" if unsupported else "ok",
                    "detail": f"{len(unsupported)} sin respaldo" if unsupported else None,
                }
            )
    if answer_gate is not None:
        verdict = str(answer_gate.get("verdict") or "")
        provider = str(answer_gate.get("provider") or "jev")
        if provider == "skip":
            checks.append({"key": "answer_gate", "state": "not_observed", "detail": None})
        else:
            state = "blocked" if verdict == "abstain" else "warn" if verdict == "revise" else "ok"
            checks.append({"key": "answer_gate", "state": state, "detail": verdict or None})
        if isinstance(answer_gate.get("grounded"), bool):
            checks.append(
                {
                    "key": "grounding",
                    "state": "ok" if answer_gate["grounded"] else "blocked",
                    "detail": None,
                }
            )
    grounding_block = flow.get("grounding")
    if isinstance(grounding_block, dict) and grounding_block.get("grounded") is not None:
        checks.append(
            {
                "key": "grounding",
                "state": "ok" if grounding_block.get("grounded") else "blocked",
                "detail": str(grounding_block.get("policy") or "") or None,
            }
        )

    overall = _verification_overall(checks)
    payload: dict[str, Any] = {"overall": overall}
    if checks:
        payload["checks"] = checks
    payload["source"] = "agent_runtime"
    return payload


def _verification_overall(checks: list[dict[str, Any]]) -> str:
    if not checks:
        return "not_verified"
    states = {str(check.get("state")) for check in checks}
    if "blocked" in states:
        return "blocked"
    if "warn" in states:
        return "partial"
    grounding = next((c for c in checks if c.get("key") == "grounding"), None)
    # Sin respaldo en fuentes declarado, el run queda "verificado parcialmente":
    # no se dice "Verificada" si sólo corrió el gate de respuesta (§20).
    if grounding is None or grounding.get("state") != "ok":
        return "partial"
    return "verified"


def timing_summary(result: Any, steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Tiempos por categoría sin doble conteo: spans para I/O, steps para gates."""
    spans = [span for span in (getattr(result, "spans", None) or []) if isinstance(span, dict)]
    span_stages: dict[str, float] = {}
    llm_ms = 0.0
    tools_ms = 0.0
    for span in spans:
        stage = str(span.get("stage") or "other")
        duration = _num(span.get("duration_ms"))
        span_stages[stage] = round(span_stages.get(stage, 0.0) + duration, 2)
        if stage == "llm":
            llm_ms += duration
        else:
            tools_ms += duration
    gates_ms = round(
        sum(
            _num(step.get("latency_ms"))
            for step in steps
            if str(step.get("type") or "") in {"tool_routing", "answer_gate", "termination_gate"}
        ),
        1,
    )
    total = round(_num(getattr(result, "total_latency_ms", 0.0)), 1)
    payload: dict[str, Any] = {"total_ms": total}
    if llm_ms > 0:
        payload["llm_ms"] = round(llm_ms, 1)
    if tools_ms > 0:
        payload["tools_ms"] = round(tools_ms, 1)
    if gates_ms > 0:
        payload["gates_ms"] = gates_ms
    if span_stages:
        payload["span_stages"] = span_stages
    attributed = round(llm_ms + tools_ms + gates_ms, 1)
    if total > 0 and attributed > 0 and total > attributed:
        payload["unattributed_ms"] = round(total - attributed, 1)
    return payload


def telemetry_completeness(
    *,
    steps: list[dict[str, Any]],
    jev: dict[str, Any],
    generation: dict[str, Any],
    verification: dict[str, Any],
    sources: list[dict[str, Any]],
    timings: dict[str, Any],
    cost: float,
    decision: dict[str, Any],
    agent_tools: tuple[str, ...] = (),
    reasoning_mode: str = "",
    jev_configured: bool | None = None,
) -> dict[str, str]:
    """Qué señales llegaron de verdad: observed | not_applicable | not_available."""
    types = {str(step.get("type") or "") for step in steps}
    reasoning_steps = {
        "reasoning_classification",
        "reasoning_plan",
        "scenario_parse",
        "state_reconstruction",
        "hypothesis_test",
        "inference_verification",
        "analysis_completion",
    }
    has_reasoning = bool(types & reasoning_steps)
    reasoning_off = str(reasoning_mode or "").lower() in {"", "off"}
    tool_steps = [step for step in steps if str(step.get("type") or "") == "tool_call"]
    retrieval_ran = any(
        any(marker in str(step.get("tool") or "").lower() for marker in _RETRIEVAL_TOOL_MARKERS)
        for step in tool_steps
    )
    payload: dict[str, str] = {
        "routing": "observed" if decision else "not_available",
        "reasoning": "observed" if has_reasoning else ("not_applicable" if reasoning_off else "not_available"),
        "company_context": "observed"
        if "company_context" in types
        else ("not_applicable" if reasoning_off or not has_reasoning else "not_available"),
        "jev": "observed"
        if jev.get("used")
        else ("not_available" if jev_configured is False else "not_applicable"),
        "tools": "observed"
        if tool_steps
        else ("not_applicable" if not agent_tools else "not_available"),
        "evidence": "observed"
        if sources
        else ("not_applicable" if not retrieval_ran else "not_available"),
        "generation": "observed" if generation else "not_available",
        "verification": "observed"
        if verification.get("checks")
        else ("not_available" if not jev_configured else "not_applicable"),
        "cost": "observed" if cost > 0 else "not_available",
        "timings": "observed" if timings.get("span_stages") else "not_available",
        # La memoria se resuelve contra Memory Events por run: el flow no la ve.
        "memory": "not_observed",
    }
    return payload


def agent_decision_provenance(
    *,
    confidence: float | None,
    provider: str,
    capability: str,
    reason: str,
    mode: str,
) -> dict[str, Any]:
    """Procedencia honesta de la decisión (§9). Unknown != 0."""
    payload: dict[str, Any] = {
        "evaluated": True,
        "provider": provider,
        "capability": capability,
        "reason": reason,
        "mode": mode,
        "fallback_used": False,
    }
    if confidence is not None:
        payload["confidence"] = round(float(confidence), 4)
    return payload


def _route_for(steps: list[dict[str, Any]]) -> str:
    tools = [
        str(step.get("tool") or "").lower()
        for step in steps
        if str(step.get("type") or "") == "tool_call"
    ]
    if any(tool == "query_database" or "sql" in tool for tool in tools):
        return "SQL"
    if any(any(marker in tool for marker in _RETRIEVAL_TOOL_MARKERS) for tool in tools):
        return "Documentos"
    if tools:
        return "Herramientas"
    return "Directa"


def build_agent_flow(
    *,
    result: Any,
    question: str = "",
    method: str = "agent",
    capability: str = "agent.execute",
    decision_provider: str = "explicit_target",
    decision_reason: str = "user_selected_agent",
    decision_confidence: float | None = None,
    agent_tools: tuple[str, ...] = (),
    reasoning_mode: str = "",
    jev_configured: bool | None = None,
) -> dict[str, Any]:
    """Flow canónico v2 de un AgentRunResult. El portal NO reconstruye nada."""
    from src.rag.flow_story import with_story

    steps = [step for step in (getattr(result, "steps", None) or []) if isinstance(step, dict)]
    timeline = [step_to_flow(step) for step in steps]
    jev = jev_summary(steps)
    sources = collect_sources(steps)
    generation = generation_summary(result, steps)
    verification = verification_summary(steps, {})
    timings = timing_summary(result, steps)
    route = _route_for(steps)
    decider = "JEV" if jev.get("used") else "Agente"
    decision = agent_decision_provenance(
        confidence=decision_confidence,
        provider=decision_provider,
        capability=capability,
        reason=decision_reason,
        mode="ReAct + JEV" if jev.get("used") else "ReAct",
    )
    telemetry = telemetry_completeness(
        steps=steps,
        jev=jev,
        generation=generation,
        verification=verification,
        sources=sources,
        timings=timings,
        cost=_num(getattr(result, "cost", 0.0)),
        decision=decision,
        agent_tools=agent_tools,
        reasoning_mode=reasoning_mode,
        jev_configured=jev_configured,
    )
    flow: dict[str, Any] = {
        "execution": {
            "kind": "agent_run",
            "id": str(getattr(result, "run_id", "") or "") or None,
            "agent_id": str(getattr(result, "agent_id", "") or "") or None,
        },
        "organization_id": str(getattr(result, "organization_id", "") or "") or None,
        "method": method,
        "status": str(getattr(result, "status", "") or ""),
        "question": (question or "")[:2000] or None,
        "verdict": {"decider": decider, "route": route},
        "decision": decision,
        "jev": jev,
        "generation": generation,
        "verification": verification,
        "timings": timings,
        "telemetry": telemetry,
        "steps": timeline,
        "sources": sources,
        "fallbacks": [
            str(step.get("detail") or "")[:120]
            for step in steps
            if str(step.get("type") or "") == "guardrail"
        ][:8],
    }
    if getattr(result, "injection_detected", False):
        flow["injection_detected"] = True
    if getattr(result, "trace_id", None):
        flow["trace_id"] = str(result.trace_id)
    return with_story({key: value for key, value in flow.items() if value is not None})
