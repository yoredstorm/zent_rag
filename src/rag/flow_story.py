"""Canonical flow events — la semántica que consume "Ver flujo".

El flow sigue viviendo en `rag_flows.flow` (JSONB). Este módulo NO reemplaza
nada: agrega `flow_version` y `events`, una lista de eventos canónicos con
semántica (fase, tipo, estado, métricas y referencias). El backend entrega
semántica; el portal traduce a lenguaje humano.

Reglas:
- Los eventos son aditivos: los campos históricos (`steps`, `sources`, ...)
  siguen intactos para que un portal viejo siga renderizando.
- Un evento nunca contiene texto de UI ni razonamiento privado (no CoT): sólo
  claves, números, estados y referencias.
- Un dato que no existe no se inventa: se omite la métrica.
"""

from __future__ import annotations

from typing import Any, Mapping

FLOW_VERSION = 2

PHASE_UNDERSTANDING = "understanding"
PHASE_CONTEXT = "context"
PHASE_PLANNING = "planning"
PHASE_EVIDENCE = "evidence"
PHASE_REASONING = "reasoning"
PHASE_DECISION = "decision"
PHASE_GENERATION = "generation"
PHASE_VERIFICATION = "verification"
PHASE_LEARNING = "learning"

#: Orden canónico de las fases en la historia (§4). Fases ausentes no se muestran.
PHASE_ORDER: tuple[str, ...] = (
    PHASE_UNDERSTANDING,
    PHASE_CONTEXT,
    PHASE_PLANNING,
    PHASE_EVIDENCE,
    PHASE_REASONING,
    PHASE_DECISION,
    PHASE_GENERATION,
    PHASE_VERIFICATION,
    PHASE_LEARNING,
)

STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"
STATUS_PENDING = "pending"

#: `type` de los steps del runtime → (fase, tipo canónico).
STEP_KIND_PHASES: dict[str, str] = {
    "reasoning_classification": PHASE_UNDERSTANDING,
    "context": PHASE_CONTEXT,
    "company_context": PHASE_CONTEXT,
    "reasoning_plan": PHASE_PLANNING,
    "response_planning": PHASE_PLANNING,
    "decision": PHASE_DECISION,
    "tool_filter": PHASE_DECISION,
    "tool_routing": PHASE_DECISION,
    "router_fallback": PHASE_DECISION,
    "termination_gate": PHASE_DECISION,
    "answer_gate": PHASE_VERIFICATION,
    "reasoning_incomplete": PHASE_VERIFICATION,
    "answer_revision": PHASE_VERIFICATION,
    "verification": PHASE_VERIFICATION,
    # Agent JEV Loop: juicio del paso y búsqueda dirigida por JEV.
    "agent_step": PHASE_DECISION,
    "jev_retrieval": PHASE_EVIDENCE,
    "scenario_parse": PHASE_REASONING,
    "state_reconstruction": PHASE_REASONING,
    "timeline": PHASE_REASONING,
    "hypothesis_test": PHASE_REASONING,
    "inference_verification": PHASE_VERIFICATION,
    "analysis_completion": PHASE_VERIFICATION,
    "tool_call": PHASE_EVIDENCE,
    "guardrail": PHASE_VERIFICATION,
    "error": PHASE_VERIFICATION,
    "final": PHASE_GENERATION,
    "llm": PHASE_GENERATION,
    "memory": PHASE_LEARNING,
}

#: Claves de un step que NO se copian a `metrics` (ya viven en el evento o son
#: texto de presentación). El resto del step se preserva tal cual: si mañana el
#: runtime agrega una señal, aparece en la historia sin tocar este módulo.
STEP_METRIC_EXCLUDE: frozenset[str] = frozenset(
    {
        "id",
        "type",
        "name",
        "detail",
        "status",
        "ms",
        "duration_ms",
        "unmapped",
        "raw",
        "tool",
        "answer",
    }
)

#: Fase segura para un step sin mapping canónico: se preserva, no se pierde.
UNMAPPED_STEP_PHASE = PHASE_DECISION

#: Tipos canónicos de los bloques históricos del flow.
BLOCK_KIND_PHASES: dict[str, str] = {
    "decision": PHASE_DECISION,
    "retrieval": PHASE_EVIDENCE,
    "sql": PHASE_EVIDENCE,
    "evidence": PHASE_EVIDENCE,
    "sources": PHASE_EVIDENCE,
    "generation": PHASE_GENERATION,
    "verification": PHASE_VERIFICATION,
    "grounding": PHASE_VERIFICATION,
    "fallback": PHASE_VERIFICATION,
}

_STATUS_MAP = {
    "ok": STATUS_OK,
    "completed": STATUS_OK,
    "success": STATUS_OK,
    "warn": STATUS_WARN,
    "warning": STATUS_WARN,
    "skipped": STATUS_SKIPPED,
    "pending": STATUS_PENDING,
    "error": STATUS_ERROR,
    "failed": STATUS_ERROR,
}

#: `reason` de fallbacks del runtime → tipo canónico. El frontend traduce.
FALLBACK_REASONS = {
    "ungrounded": "grounding_failed",
    "claims_abstain": "claims_abstained",
    "claims_conflict": "claims_conflict",
    "claims_revision": "claims_revised",
    "plan_failed": "plan_failed",
    "preflight_abstained": "judgment_blocked_generation",
}

#: Pack JEV → fase de la historia. El juicio aparece donde ocurrió.
JEV_PACK_PHASES: dict[str, str] = {
    "pre_reasoning": PHASE_PLANNING,
    "post_retrieval": PHASE_EVIDENCE,
    "post_reconstruction": PHASE_REASONING,
    "pre_generation": PHASE_DECISION,
    "post_generation": PHASE_VERIFICATION,
    "agent_step": PHASE_DECISION,
}

#: Bloques históricos que pueden traer un pack JEV con sus respuestas públicas.
JEV_ANSWER_SOURCES: dict[str, str] = {
    "evidence": "post_retrieval",
    "grounding": "post_generation",
}


def canonical_status(value: Any) -> str:
    return _STATUS_MAP.get(str(value or "").strip().lower(), STATUS_OK)


def _event(
    *,
    event_id: str,
    kind: str,
    phase: str,
    status: str = STATUS_OK,
    duration_ms: float | None = None,
    summary: str | None = None,
    metrics: dict | None = None,
    decision: dict | None = None,
    evidence_refs: list | None = None,
    memory_refs: list | None = None,
    entity_refs: list | None = None,
    technical: dict | None = None,
    parent_id: str | None = None,
) -> dict:
    event: dict[str, Any] = {
        "id": event_id,
        "phase": phase,
        "kind": kind,
        "status": status,
    }
    if duration_ms is not None:
        event["duration_ms"] = round(max(0.0, float(duration_ms)), 1)
    if summary:
        event["summary"] = summary
    if metrics:
        event["metrics"] = {key: value for key, value in metrics.items() if value is not None}
    if decision:
        event["decision"] = decision
    if evidence_refs:
        event["evidence_refs"] = list(evidence_refs)
    if memory_refs:
        event["memory_refs"] = list(memory_refs)
    if entity_refs:
        event["entity_refs"] = list(entity_refs)
    if technical:
        event["technical"] = {
            key: value for key, value in technical.items() if value is not None
        }
    if parent_id:
        event["parent_id"] = parent_id
    return event


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        number = float(value)
        return number if number == number else default  # NaN guard
    except (TypeError, ValueError):
        return default


def _int_or_none(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


# ---------------------------------------------------------------------------
# Bloques históricos → eventos canónicos
# ---------------------------------------------------------------------------


def _decision_event(flow: dict, index: int) -> dict | None:
    decision = flow.get("decision")
    if not isinstance(decision, dict):
        return None
    verdict = flow.get("verdict") if isinstance(flow.get("verdict"), dict) else {}
    if decision.get("evaluated") is False:
        status = STATUS_SKIPPED
    else:
        status = STATUS_WARN if decision.get("fallback_used") else STATUS_OK
    technical: dict[str, Any] = {}
    for key in ("provider", "capability", "mode"):
        if decision.get(key):
            technical[key] = decision[key]
    if isinstance(decision.get("confidence"), (int, float)):
        technical["confidence"] = round(float(decision["confidence"]), 4)
    if decision.get("jev_used") is not None:
        technical["jev_used"] = bool(decision.get("jev_used"))
    metrics: dict[str, Any] = {}
    if verdict.get("route"):
        # La ruta es semántica del backend (SQL/Documentos/...), no texto de UI.
        technical["route"] = str(verdict["route"])[:40]
    if verdict.get("decider"):
        technical["decider"] = str(verdict["decider"])[:40]
    return _event(
        event_id=f"flow-{index}",
        kind="decision",
        phase=PHASE_DECISION,
        status=status,
        duration_ms=_number(decision.get("ms")),
        metrics=metrics,
        technical=technical,
    )


def _retrieval_event(flow: dict, sources: list, index: int) -> dict | None:
    retrieval = flow.get("retrieval")
    if not isinstance(retrieval, dict):
        return None
    chunks = _int_or_none(retrieval.get("chunks")) or 0
    if retrieval.get("used") is not True and chunks == 0:
        return None
    used = len(sources)
    status = STATUS_OK if retrieval.get("used") is not False else STATUS_SKIPPED
    return _event(
        event_id=f"flow-{index}",
        kind="retrieval",
        phase=PHASE_EVIDENCE,
        status=status,
        duration_ms=_number(retrieval.get("ms")),
        metrics={
            "chunks": chunks,
            "sources_total": used or None,
            "sources_used": used or None,
            "sources_discarded": max(0, chunks - used) if chunks and used else None,
            "top_score": _number(retrieval.get("top_score")),
        },
        technical={
            "strategy": retrieval.get("strategy"),
            "candidate_count": _int_or_none(retrieval.get("candidates")),
        },
    )


def _evidence_event(flow: dict, index: int) -> dict | None:
    evidence = flow.get("evidence")
    if not isinstance(evidence, dict):
        return None
    sufficient = evidence.get("sufficient")
    return _event(
        event_id=f"flow-{index}",
        kind="evidence",
        phase=PHASE_EVIDENCE,
        status=STATUS_OK if sufficient else STATUS_WARN,
        duration_ms=_number(evidence.get("ms")),
        metrics={
            "score": _number(evidence.get("score")),
            "sufficient": bool(sufficient) if sufficient is not None else None,
            "items": _int_or_none(evidence.get("items")),
        },
        technical={"reason_code": evidence.get("reason")},
    )


def _sql_event(flow: dict, index: int) -> dict | None:
    sql = flow.get("sql")
    if not isinstance(sql, dict):
        return None
    return _event(
        event_id=f"flow-{index}",
        kind="sql",
        phase=PHASE_EVIDENCE,
        status=STATUS_OK,
        duration_ms=_number(sql.get("ms")),
        metrics={
            "rows": _int_or_none(sql.get("rows")),
            "tables": len(sql.get("tables") or []) or None,
        },
        technical={"truncated": bool(sql.get("truncated"))},
    )


def _sources_event(flow: dict, sources: list, index: int) -> dict | None:
    if not sources:
        return None
    authority_counts: dict[str, int] = {}
    for source in sources:
        level = str((source or {}).get("authority") or "").strip().lower()
        if level:
            authority_counts[level] = authority_counts.get(level, 0) + 1
    items = []
    for position, source in enumerate(sources[:16]):
        item: dict[str, Any] = {
            "ref": str((source or {}).get("document_id") or f"source-{position}"),
            "title": str((source or {}).get("title") or "")[:160],
            "relevance": _number((source or {}).get("score")),
            "status": str((source or {}).get("status") or "USED").upper()[:32],
        }
        if (source or {}).get("authority"):
            item["authority"] = str(source["authority"])[:32].lower()
        items.append(item)
    return _event(
        event_id=f"flow-{index}",
        kind="sources",
        phase=PHASE_EVIDENCE,
        status=STATUS_OK,
        metrics={
            "sources": len(sources),
            "authority_counts": authority_counts or None,
        },
        evidence_refs=[item["ref"] for item in items],
        technical={"items": items},
    )


def _generation_event(flow: dict, index: int) -> dict | None:
    generation = flow.get("generation")
    if not isinstance(generation, dict):
        return None
    skipped = bool(generation.get("skipped"))
    technical: dict[str, Any] = {}
    if generation.get("model"):
        technical["model"] = generation["model"]
    if generation.get("provider"):
        technical["provider"] = generation["provider"]
    for key in ("calls", "answer_calls", "reasoning_calls"):
        if generation.get(key) is not None:
            technical[key] = _int_or_none(generation.get(key))
    return _event(
        event_id=f"flow-{index}",
        kind="generation",
        phase=PHASE_GENERATION,
        status=STATUS_SKIPPED if skipped else STATUS_OK,
        duration_ms=_number(generation.get("ms")),
        metrics={
            "prompt_tokens": _int_or_none(generation.get("prompt_tokens")),
            "completion_tokens": _int_or_none(generation.get("completion_tokens")),
            "total_tokens": _int_or_none(generation.get("total_tokens")),
            "cost_usd": _number(generation.get("cost")),
        },
        technical=technical or None,
    )


def _verification_event(flow: dict, index: int) -> dict | None:
    """Verificación agregada del run (§19, §20). No es un booleano."""
    verification = flow.get("verification")
    if not isinstance(verification, dict):
        return None
    checks = [item for item in (verification.get("checks") or []) if isinstance(item, dict)]
    if not checks:
        return None
    overall = str(verification.get("overall") or "")
    # "partial" no es una incidencia: es un dato honesto de qué se comprobó.
    status = {
        "verified": STATUS_OK,
        "partial": STATUS_OK,
        "not_verified": STATUS_SKIPPED,
        "blocked": STATUS_WARN,
    }.get(overall, STATUS_OK)
    return _event(
        event_id=f"flow-{index}",
        kind="verification",
        phase=PHASE_VERIFICATION,
        status=status,
        metrics={
            "overall": overall or None,
            "checks": [
                {
                    "key": str(check.get("key") or ""),
                    "state": str(check.get("state") or ""),
                    **({"detail": str(check["detail"])[:160]} if check.get("detail") else {}),
                }
                for check in checks[:8]
            ],
        },
        technical={"source": verification.get("source")},
    )


def _grounding_event(flow: dict, index: int) -> dict | None:
    grounding = flow.get("grounding")
    if not isinstance(grounding, dict):
        return None
    grounded = grounding.get("grounded")
    return _event(
        event_id=f"flow-{index}",
        kind="grounding",
        phase=PHASE_VERIFICATION,
        status=STATUS_OK if grounded else STATUS_WARN,
        duration_ms=_number(grounding.get("ms")),
        metrics={
            "score": _number(grounding.get("score")),
            "grounded": bool(grounded) if grounded is not None else None,
        },
        technical={"policy": grounding.get("policy")},
    )


def _question_summaries(answers: Mapping[str, Any] | None, *, phase: str) -> list[dict]:
    """Convierte respuestas públicas de JEV en juicios con decisión y efecto.

    Reutiliza el lector del preflight: la misma semántica que compuso la decisión
    es la que se muestra, sin reinterpretar nada en la UI.
    """
    if not isinstance(answers, Mapping) or not answers:
        return []
    try:
        from src.decision.preflight import build_pack

        pack = build_pack(phase=phase, payload={"answers": answers}, mode="observed")
    except Exception:  # noqa: BLE001 — la historia nunca rompe la respuesta
        return []
    return [question.to_public_dict() for question in pack.questions]


def _jev_pack_event(
    *,
    index: int,
    phase: str,
    status: str,
    questions: list[dict],
    technical: Mapping[str, Any] | None = None,
    decision: Mapping[str, Any] | None = None,
    readiness: Mapping[str, Any] | None = None,
    duration_ms: float | None = None,
) -> dict:
    uncertain = [
        str(question.get("id"))
        for question in questions
        if question.get("decision") == "uncertain" or question.get("ambiguous")
    ]
    effects: list[str] = []
    for question in questions:
        effect = question.get("effect")
        if effect and effect not in effects:
            effects.append(str(effect))
    metrics: dict[str, Any] = {
        "phase": phase,
        "judgment_count": len(questions),
        "questions": questions[:24],
    }
    if effects:
        metrics["effects"] = effects
    if uncertain:
        metrics["uncertain"] = uncertain[:8]
    if readiness:
        metrics["readiness"] = readiness
    return _event(
        event_id=f"jev-{index}",
        kind="jev_pack",
        phase=JEV_PACK_PHASES.get(phase, PHASE_DECISION),
        status=status,
        duration_ms=duration_ms,
        metrics=metrics,
        decision=dict(decision) if decision else None,
        technical=dict(technical or {}) or None,
    )


def _jev_events(flow: dict, start_index: int) -> list[dict]:
    """Un evento por pack JEV: un llamado, N juicios, un efecto (§35, §40)."""
    events: list[dict] = []
    index = start_index
    block = flow.get("jev_preflight")
    decisions: dict[str, dict] = {}
    if isinstance(block, dict):
        for entry in list(block.get("decisions") or []):
            if isinstance(entry, Mapping) and entry.get("phase"):
                decisions[str(entry["phase"])] = dict(entry)
        packs = list(block.get("packs") or [])
    else:
        packs = []

    for pack in packs:
        if not isinstance(pack, Mapping):
            continue
        phase = str(pack.get("phase") or "")
        if not phase:
            continue
        index += 1
        questions = [
            dict(question)
            for question in list(pack.get("questions") or [])
            if isinstance(question, Mapping)
        ]
        status = canonical_status(pack.get("status"))
        if pack.get("cached"):
            status = STATUS_OK if status == STATUS_OK else status
        decision = decisions.get(phase) or {}
        technical: dict[str, Any] = {
            "mode": pack.get("mode"),
            "model": pack.get("model"),
            "cached": bool(pack.get("cached")),
            "question_count": pack.get("question_count"),
        }
        tokens = pack.get("tokens")
        if isinstance(tokens, Mapping) and (tokens.get("input") or tokens.get("output")):
            technical["tokens"] = {
                "input": int(tokens.get("input") or 0),
                "output": int(tokens.get("output") or 0),
            }
        if pack.get("cost_usd"):
            technical["cost_usd"] = _number(pack.get("cost_usd"))
        events.append(
            _jev_pack_event(
                index=index,
                phase=phase,
                status=status,
                questions=questions,
                technical=technical,
                readiness=decision.get("readiness") if isinstance(decision, Mapping) else None,
                decision={
                    "reason_codes": [str(item) for item in (decision.get("reasons") or [])][:8],
                    "action": decision.get("action"),
                    "tier": decision.get("tier"),
                    "allow_generation": decision.get("allow_generation"),
                    "applied": decision.get("applied"),
                    "uncertain_critical": list(decision.get("uncertain_critical") or [])[:8],
                }
                if decision
                else None,
                duration_ms=_number(pack.get("latency_ms")),
            )
        )

    # Packs de las fases de batching ya existentes: evidence gate y verificación.
    for block_key, phase in JEV_ANSWER_SOURCES.items():
        source = flow.get(block_key)
        if not isinstance(source, Mapping) or not source.get("jev_used"):
            continue
        questions = _question_summaries(source.get("jev_answers"), phase=phase)
        if not questions:
            continue
        index += 1
        events.append(
            _jev_pack_event(
                index=index,
                phase=phase,
                status=STATUS_OK,
                questions=questions,
                technical={"judgment_count": len(questions)},
                duration_ms=_number(source.get("ms")),
            )
        )
    return events


def _fallback_events(flow: dict, start_index: int) -> list[dict]:
    fallbacks = flow.get("fallbacks")
    if not isinstance(fallbacks, list):
        return []
    events: list[dict] = []
    for offset, item in enumerate(fallbacks[:8]):
        raw = str(item or "")[:60]
        events.append(
            _event(
                event_id=f"flow-{start_index + offset}",
                kind="fallback",
                phase=PHASE_VERIFICATION,
                status=STATUS_WARN,
                summary=FALLBACK_REASONS.get(raw, raw or "fallback"),
                technical={"raw": raw},
            )
        )
    return events


# ---------------------------------------------------------------------------
# Construcción
# ---------------------------------------------------------------------------


def build_flow_events(flow: dict) -> list[dict]:
    """Eventos canónicos derivados del flow. Función pura.

    Los steps tipados del runtime (razonamiento, tools, gates) tienen prioridad;
    los bloques históricos sólo aportan eventos si no están ya representados.
    """
    events: list[dict] = []
    covered: set[str] = set()
    index = 0

    steps = flow.get("steps") if isinstance(flow.get("steps"), list) else []
    for step in steps:
        if not isinstance(step, dict):
            continue
        kind = str(step.get("type") or "").strip()
        if not kind:
            continue
        phase = STEP_KIND_PHASES.get(kind)
        unmapped = phase is None
        if unmapped:
            # Un step sin mapping canónico NO se descarta: se preserva con su
            # kind original y se marca para que el portal lo cuente (§37).
            phase = UNMAPPED_STEP_PHASE
        index += 1
        covered.add(kind)
        technical: dict[str, Any] = {}
        for extra in ("shape", "detail", "model", "tool", "phase", "trace_id"):
            if step.get(extra) not in (None, ""):
                technical[extra] = step[extra]
        if unmapped or step.get("unmapped") is True:
            technical["unmapped"] = True
        metrics = {}
        for key in ("step", "tokens", "latency_ms"):
            if isinstance(step.get(key), (int, float)):
                metrics[key] = step[key]
        # El resto del step se conserva tal cual (payloads estructurados y
        # señales de gates): la historia no reinterpreta ni rellena nada.
        for key, value in step.items():
            if key in STEP_METRIC_EXCLUDE or key in metrics:
                continue
            if isinstance(value, (dict, list, str, int, float, bool)) and value != "":
                metrics[key] = value
        evidence_refs: list[str] = []
        meta = step.get("meta")
        if isinstance(meta, dict):
            for item in list(meta.get("evidence") or [])[:16]:
                if isinstance(item, dict):
                    ref = str(item.get("ref") or item.get("document_id") or item.get("source_id") or "")
                    if ref:
                        evidence_refs.append(ref)
        # El veredicto del paso JEV viaja como decisión: el portal lo muestra
        # como "JEV decidió: …" sin reinterpretar nada.
        decision: dict[str, Any] | None = None
        if kind == "agent_step":
            action = str(step.get("next_action") or "")
            if action:
                reason = str(step.get("action_reason") or "")
                decision = {
                    "action": action,
                    "reason_codes": [reason] if reason else [],
                    "applied": True,
                }
        events.append(
            _event(
                event_id=str(step.get("id") or f"step-{index}"),
                kind=kind,
                phase=phase,
                status=canonical_status(step.get("status")),
                duration_ms=_number(step.get("duration_ms") or step.get("latency_ms")),
                metrics=metrics or None,
                evidence_refs=evidence_refs or None,
                technical=technical or None,
                decision=decision,
            )
        )

    sources = flow.get("sources") if isinstance(flow.get("sources"), list) else []
    blocks = (
        ("decision", lambda: _decision_event(flow, index + 1)),
        ("retrieval", lambda: _retrieval_event(flow, sources, index + 1)),
        ("sql", lambda: _sql_event(flow, index + 1)),
        ("evidence", lambda: _evidence_event(flow, index + 1)),
        ("sources", lambda: _sources_event(flow, sources, index + 1)),
        ("generation", lambda: _generation_event(flow, index + 1)),
        ("verification", lambda: _verification_event(flow, index + 1)),
        ("grounding", lambda: _grounding_event(flow, index + 1)),
    )
    for kind, factory in blocks:
        if kind in covered:
            continue
        if kind == "sources" and not sources:
            continue
        event = factory()
        if event is None:
            continue
        index += 1
        event["id"] = f"flow-{index}"
        events.append(event)

    if "fallback" not in covered:
        fallback_events = _fallback_events(flow, index + 1)
        index += len(fallback_events)
        events.extend(fallback_events)

    # Juicios previos al generador: un evento por pack JEV (§34, §35).
    jev_events = _jev_events(flow, index)
    events.extend(jev_events)

    order = {phase: position for position, phase in enumerate(PHASE_ORDER)}
    return sorted(events, key=lambda item: order.get(str(item.get("phase")), 99))


def with_story(flow: dict) -> dict:
    """Agrega `flow_version` y `events` al flow. No toca los campos históricos."""
    try:
        enriched = dict(flow)
        enriched["flow_version"] = FLOW_VERSION
        enriched["events"] = build_flow_events(enriched)
        return enriched
    except Exception:  # noqa: BLE001 - el flujo nunca rompe la respuesta
        return flow


__all__ = [
    "BLOCK_KIND_PHASES",
    "FALLBACK_REASONS",
    "FLOW_VERSION",
    "JEV_ANSWER_SOURCES",
    "JEV_PACK_PHASES",
    "PHASE_ORDER",
    "STEP_KIND_PHASES",
    "STEP_METRIC_EXCLUDE",
    "UNMAPPED_STEP_PHASE",
    "build_flow_events",
    "canonical_status",
    "with_story",
]
