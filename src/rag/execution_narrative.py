"""Presentational projection of canonical execution state.

This module groups and normalizes facts already emitted by the runtime. It never
changes evidence sufficiency, routing, grounding, generation, or verification.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

NARRATIVE_SCHEMA_VERSION = 1

_ANSWERED_OUTCOMES = {
    "ANSWERED",
    "ANSWERED_WITH_LIMITS",
    "RETRIED_AND_ANSWERED",
}
_RETRY_ACTIONS = {"retrieve_more", "search_knowledge"}
_MATERIAL_FALLBACKS = {
    "claims_answer_with_limits",
    "partial_evidence_answer_with_limits",
    "figures_unverified",
    "hierarchy_unverified",
    "disclaimer_contradiction",
}
_UUIDISH = re.compile(r"[0-9a-fA-F-]{32,36}")
_GENERATED_NAME = re.compile(r"^documento\s+[0-9a-f]{6,}$", re.IGNORECASE)
_UNAVAILABLE_NAME = "Fuente sin nombre"


def _base_name(value: str) -> str:
    return value.replace("\\", "/").rstrip("/").split("/")[-1].strip()


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalized(value: Any) -> str:
    return re.sub(r"\s+", " ", _text(value)).casefold()


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _step(flow: Mapping[str, Any], kind: str) -> dict[str, Any]:
    return next(
        (
            item
            for item in _records(flow.get("steps"))
            if _text(item.get("type")) == kind
        ),
        {},
    )


def _steps(flow: Mapping[str, Any], kind: str) -> list[dict[str, Any]]:
    return [
        item
        for item in _records(flow.get("steps"))
        if _text(item.get("type")) == kind
    ]


def _anchor_label(value: Any) -> str:
    if not isinstance(value, Mapping):
        return _text(value)
    for key in ("label", "value", "text", "anchor", "entity", "name"):
        label = _text(value.get(key))
        if label:
            return label
    return ""


def _anchor_values(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [label for item in value if (label := _anchor_label(item))]


def _coverage(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        rows: list[dict[str, Any]] = []
        for label, state in value.items():
            row = _record(state)
            row.setdefault("label", _text(label))
            rows.append(row)
        return rows
    return _records(value)


def _verification(flow: Mapping[str, Any]) -> dict[str, Any]:
    block = _record(flow.get("verification"))
    fallbacks = [_text(item) for item in list(flow.get("fallbacks") or [])]
    fallback_code = _text(block.get("fallback_code")) or next(
        (item for item in fallbacks if item), ""
    )
    affected_outcome = block.get("affected_outcome")
    if affected_outcome is None:
        affected_outcome = fallback_code in _MATERIAL_FALLBACKS
    return {
        "overall": _text(block.get("overall")) or "not_verified",
        "checks": _records(block.get("checks")),
        "primary_available": block.get("primary_available"),
        "fallback_used": bool(block.get("fallback_used") or fallback_code),
        "fallback_code": fallback_code or None,
        "affected_outcome": bool(affected_outcome),
        "corrections": _records(block.get("corrections")),
        "source_event_ids": [],
    }


def _canonical_evidence(flow: Mapping[str, Any]) -> dict[str, Any]:
    package = _step(flow, "generation_package")
    state = _record(package.get("evidence"))
    anchors = _step(flow, "anchor_roles")
    if not state and anchors:
        state = {
            "evidence_complete": (
                not anchors.get("missing_documentable_evidence")
                and not anchors.get("conflicts")
            ),
            "generation_mode": anchors.get("decision"),
            "missing_documentable_evidence": anchors.get(
                "missing_documentable_evidence"
            ),
            "conflicts": anchors.get("conflicts"),
            "coverage": anchors.get("requirement_coverage"),
        }
    missing = list(
        state.get("missing_documentable_evidence")
        or package.get("missing_evidence")
        or []
    )
    conflicts = list(state.get("conflicts") or package.get("contradictions") or [])
    state_requirements = state.get("requirements")
    requirements = (
        list(state_requirements)
        if isinstance(state_requirements, Sequence)
        and not isinstance(state_requirements, (str, bytes))
        else []
    )
    declared = state.get("evidence_complete")
    if declared is not None:
        complete: bool | None = bool(declared)
    elif package.get("ready") is not None:
        complete = bool(package.get("ready"))
    else:
        complete = None
    return {
        "complete": complete,
        "generation_mode": _text(
            state.get("generation_mode") or package.get("mode")
        ),
        "missing_documentable_evidence": missing,
        "conflicts": conflicts,
        "coverage_ratio": _number(state.get("coverage")),
        "requirements": requirements,
        "documents": [],
        "document_count": 0,
        "passage_count": 0,
        "searches": [],
    }


def _display_name(source: Mapping[str, Any]) -> str:
    """Fallback de identidad: título → filename → original/uploaded → uri → sentinel."""
    for key in (
        "document_name",
        "display_name",
        "source_title",
        "document_title",
        "title",
        "filename",
        "original_filename",
        "uploaded_filename",
        "source_uri",
    ):
        value = _text(source.get(key))
        if not value or _UUIDISH.fullmatch(value):
            continue
        if _GENERATED_NAME.match(value):
            continue
        if key == "source_uri":
            value = _base_name(value)
        if value:
            return value
    return _UNAVAILABLE_NAME


def _document_key(source: Mapping[str, Any]) -> str:
    document_id = _text(source.get("document_id"))
    if document_id:
        return f"document:{document_id}"
    source_id = _text(source.get("source_id"))
    filename = _normalized(source.get("filename") or source.get("title"))
    return f"source:{source_id}:{filename}"


def _passage_key(source: Mapping[str, Any]) -> str:
    evidence_id = _text(source.get("evidence_id"))
    if evidence_id:
        return f"evidence:{evidence_id}"
    excerpt = _text(
        source.get("excerpt") or source.get("content") or source.get("snippet")
    )
    digest = hashlib.sha256(_normalized(excerpt).encode("utf-8")).hexdigest()[:16]
    return (
        f"fallback:{_text(source.get('page'))}:"
        f"{_normalized(source.get('section'))}:{digest}"
    )


def _group_documents(
    sources: list[dict[str, Any]], diagnostics: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    seen_passages: set[str] = set()
    for source in sources:
        key = _document_key(source)
        passage_key = f"{key}:{_passage_key(source)}"
        if passage_key in seen_passages:
            continue
        seen_passages.add(passage_key)
        name = _display_name(source)
        if name == _UNAVAILABLE_NAME:
            diagnostics.append(
                {
                    "code": "SOURCE_NAME_MISSING",
                    "field": key,
                    "raw_value": source.get("title"),
                    "source_event_id": None,
                }
            )
        document = grouped.setdefault(
            key,
            {
                "document_key": key,
                "document_id": _text(source.get("document_id")) or None,
                "source_id": _text(source.get("source_id")) or None,
                "display_name": name,
                "title": name,
                "passage_count": 0,
                "passages": [],
            },
        )
        section_path = source.get("section_path")
        if isinstance(section_path, (list, tuple)):
            section = " · ".join(str(part) for part in section_path if str(part).strip())
        else:
            section = _text(source.get("section"))
        document["passages"].append(
            {
                "evidence_id": _text(source.get("evidence_id")) or None,
                "page": source.get("page"),
                "section": section or None,
                "excerpt": _text(
                    source.get("excerpt")
                    or source.get("content")
                    or source.get("snippet")
                ),
                "status": _text(source.get("status")) or "USED",
                "relevance": _number(source.get("score")),
                "source_event_ids": [],
            }
        )
        document["passage_count"] = len(document["passages"])
    return list(grouped.values())


def _understanding(flow: Mapping[str, Any]) -> dict[str, Any]:
    anchors = _step(flow, "anchor_roles")
    package = _step(flow, "generation_package")
    canonical_anchors = _records(_record(package.get("evidence")).get("anchors"))

    def values_for(role: str) -> list[str]:
        return [
            _text(item.get("value"))
            for item in canonical_anchors
            if _text(item.get("role")) == role and _text(item.get("value"))
        ]

    return {
        "intent_code": _text(flow.get("intent")),
        "task_code": "rule_application" if anchors.get("application") else "",
        "observed_summary": _text(anchors.get("detail")),
        "application": _text(anchors.get("application")),
        "question": _text(package.get("question") or flow.get("question")),
        "fields": _anchor_values(anchors.get("fields")) or values_for("field_anchor"),
        "rules": _anchor_values(anchors.get("rules")) or values_for("rule_anchor"),
        "references": _anchor_values(anchors.get("references")),
        "examples": _anchor_values(anchors.get("examples")) or values_for("example_value"),
        "entities": _anchor_values(anchors.get("entities")),
        "source_event_ids": ([
            _text(anchors.get("id"))
        ] if anchors.get("id") else []),
    }


def _requirements(flow: Mapping[str, Any]) -> list[dict[str, Any]]:
    anchors = _step(flow, "anchor_roles")
    package = _step(flow, "generation_package")
    canonical_anchors = _records(_record(package.get("evidence")).get("anchors"))
    coverage = {
        _text(item.get("label") or item.get("anchor") or item.get("requirement")): item
        for item in _coverage(anchors.get("requirement_coverage"))
    }
    requirements: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for anchor in canonical_anchors:
        label = _text(anchor.get("value"))
        if not label:
            continue
        source_required = anchor.get("requires_source_match") is not False
        kind = "DOCUMENTABLE" if source_required else "USER_INPUT"
        identity = (kind, _normalized(label))
        if identity in seen:
            continue
        seen.add(identity)
        requirements.append(
            {
                "id": f"{'documentable' if source_required else 'user-input'}:{_normalized(label)}",
                "label": label,
                "kind": kind,
                "status": (
                    "FOUND"
                    if source_required and anchor.get("found") is True
                    else "MISSING"
                    if source_required
                    else "PROVIDED"
                ),
                "source_required": source_required,
                "evidence_refs": list(anchor.get("evidence_refs") or []),
                "source_event_ids": [],
            }
        )
    for key in ("fields", "rules", "references", "entities"):
        for label in _anchor_values(anchors.get(key)):
            identity = ("DOCUMENTABLE", _normalized(label))
            if identity in seen:
                continue
            seen.add(identity)
            state = _record(coverage.get(label))
            requirements.append(
                {
                    "id": f"documentable:{_normalized(label)}",
                    "label": label,
                    "kind": "DOCUMENTABLE",
                    "status": _text(state.get("status")) or "UNKNOWN",
                    "source_required": True,
                    "evidence_refs": list(state.get("evidence_refs") or []),
                    "source_event_ids": [],
                }
            )
    for label in _anchor_values(anchors.get("examples")):
        identity = ("USER_INPUT", _normalized(label))
        if identity in seen:
            continue
        seen.add(identity)
        requirements.append(
            {
                "id": f"user-input:{_normalized(label)}",
                "label": label,
                "kind": "USER_INPUT",
                "status": "PROVIDED",
                "source_required": False,
                "evidence_refs": [],
                "source_event_ids": [],
            }
        )
    return requirements


def _applied_decisions(
    flow: Mapping[str, Any], events: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    decisions = _records(_record(flow.get("jev_preflight")).get("decisions"))
    applied: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def append(item: Mapping[str, Any], source_event_id: str | None = None) -> None:
        if item.get("applied") is not True:
            return
        phase = _text(item.get("phase"))
        action = _text(item.get("action"))
        question_id = _text(item.get("question_id"))
        identity = (phase, action, question_id)
        if identity in seen:
            return
        seen.add(identity)
        index = len(applied) + 1
        applied.append(
            {
                "id": f"decision:{index}:{phase or 'unknown'}",
                "phase": phase,
                "question_id": question_id or None,
                "action": action,
                "decider": _text(item.get("decider")) or "JEV",
                "reason_codes": list(
                    item.get("reasons") or item.get("reason_codes") or []
                ),
                "impact_code": _text(item.get("effect")) or action or "APPLIED",
                "affected_event_ids": list(item.get("affected_event_ids") or []),
                "source_event_ids": (
                    [source_event_id]
                    if source_event_id
                    else list(item.get("source_event_ids") or [])
                ),
            }
        )

    for item in decisions:
        append(item)
    for event in events:
        if _text(event.get("kind")) != "jev_pack":
            continue
        decision = _record(event.get("decision"))
        metrics = _record(event.get("metrics"))
        decision.setdefault("phase", metrics.get("phase"))
        append(decision, _text(event.get("id")) or None)
    return applied


def _probability(
    value: Any,
    *,
    field: str,
    diagnostics: list[dict[str, Any]],
    source_event_id: str | None = None,
) -> float | None:
    number = _number(value)
    if number is None:
        return None
    if 0.0 <= number <= 1.0:
        return number
    diagnostics.append(
        {
            "code": "INVALID_PROBABILITY",
            "field": field,
            "raw_value": value,
            "source_event_id": source_event_id,
        }
    )
    return None


def _judgments(
    flow: Mapping[str, Any],
    applied: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    packs = _records(_record(flow.get("jev_preflight")).get("packs"))
    applied_by_question = {
        _text(item.get("question_id")): item["id"]
        for item in applied
        if _text(item.get("question_id"))
    }
    judgments: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def append(
        *,
        question: Mapping[str, Any],
        phase: str,
        pack_id: str,
        source_event_id: str | None = None,
    ) -> None:
        question_id = _text(question.get("id"))
        identity = (phase, question_id)
        if identity in seen:
            return
        seen.add(identity)
        distribution = _record(question.get("distribution"))
        probabilities = _record(distribution.get("probabilities"))
        alternatives = [
            {
                "key": key,
                "probability": _probability(
                    value,
                    field=f"judgments.{question_id}.alternatives.{key}",
                    diagnostics=diagnostics,
                    source_event_id=source_event_id,
                ),
            }
            for key, value in probabilities.items()
        ]
        judgments.append(
            {
                "id": question_id,
                "pack_id": pack_id,
                "phase": phase,
                "question_code": question_id,
                "type": _text(question.get("type")).upper() or "NOUL",
                "answer": question.get("decision"),
                "probability": _probability(
                    question.get("confidence"),
                    field=f"judgments.{question_id}.probability",
                    diagnostics=diagnostics,
                    source_event_id=source_event_id,
                ),
                "certainty": _probability(
                    question.get("certainty"),
                    field=f"judgments.{question_id}.certainty",
                    diagnostics=diagnostics,
                    source_event_id=source_event_id,
                ),
                "confidence_band": question.get("confidence_band"),
                "ambiguous": bool(question.get("ambiguous")),
                "alternatives": alternatives,
                "applied_decision_id": applied_by_question.get(question_id),
                "effect_code": question.get("effect"),
                "source_event_ids": [source_event_id] if source_event_id else [],
                "distribution": distribution,
            }
        )

    for pack_index, pack in enumerate(packs, start=1):
        phase = _text(pack.get("phase"))
        for question in _records(pack.get("questions")):
            append(
                question=question,
                phase=phase,
                pack_id=f"pack:{pack_index}:{phase or 'unknown'}",
            )
    for event in events:
        if _text(event.get("kind")) != "jev_pack":
            continue
        metrics = _record(event.get("metrics"))
        phase = _text(metrics.get("phase")) or _text(event.get("phase"))
        event_id = _text(event.get("id")) or None
        for question in _records(metrics.get("questions")):
            append(
                question=question,
                phase=phase,
                pack_id=f"event:{event_id or 'unknown'}",
                source_event_id=event_id,
            )
    return judgments


def _model_calls(flow: Mapping[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    llm_steps = _steps(flow, "llm")
    for index, item in enumerate(llm_steps, start=1):
        action = _record(item.get("action"))
        explicit = _text(item.get("purpose")).upper()
        if explicit in {"ANALYSIS", "ANSWER", "REVISION"}:
            purpose = explicit
        elif action.get("answer") is not None:
            purpose = "ANSWER"
        elif action.get("revision") is not None:
            purpose = "REVISION"
        elif action.get("tool") is not None or (index == 1 and len(llm_steps) > 1):
            purpose = "ANALYSIS"
        else:
            purpose = "UNKNOWN"
        tokens = _record(item.get("tokens"))
        calls.append(
            {
                "id": _text(item.get("id")) or f"model-call:{index}",
                "sequence": index,
                "purpose": purpose,
                "model": item.get("model"),
                "provider": item.get("provider"),
                "duration_ms": _number(
                    item.get("duration_ms") or item.get("latency_ms")
                ),
                "input_tokens": tokens.get("input"),
                "output_tokens": tokens.get("output"),
                "total_tokens": (
                    item.get("tokens")
                    if isinstance(item.get("tokens"), (int, float))
                    else tokens.get("total")
                ),
                "cost_usd": _number(item.get("cost_usd")),
                "source_event_ids": (
                    [_text(item.get("id"))] if item.get("id") else []
                ),
            }
        )
    if calls:
        return calls

    generation = _record(flow.get("generation"))
    if generation.get("skipped") is not False:
        return calls
    reasoning_count = int(_number(generation.get("reasoning_calls")) or 0)
    answer_count = int(_number(generation.get("answer_calls")) or 0)
    declared_count = int(_number(generation.get("calls")) or 0)
    purposes = ["ANALYSIS"] * reasoning_count + ["ANSWER"] * answer_count
    total = max(declared_count, len(purposes), 1)
    purposes.extend(["UNKNOWN"] * (total - len(purposes)))
    for index, purpose in enumerate(purposes, start=1):
        calls.append(
            {
                "id": f"model-call:{index}",
                "sequence": index,
                "purpose": purpose,
                "model": generation.get("model"),
                "provider": generation.get("provider"),
                "duration_ms": (
                    _number(generation.get("ms")) if total == 1 else None
                ),
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
                "cost_usd": None,
                "source_event_ids": [],
            }
        )
    return calls


def _searches(flow: Mapping[str, Any]) -> list[dict[str, Any]]:
    searches: list[dict[str, Any]] = []
    for step in _records(flow.get("steps")):
        kind = _text(step.get("type"))
        tool = _text(step.get("tool")).lower()
        if kind not in {"retrieval", "jev_retrieval"} and not (
            kind == "tool_call" and any(key in tool for key in ("search", "knowledge", "retriev"))
        ):
            continue
        searches.append(
            {
                "index": len(searches) + 1,
                "kind": kind,
                "duration_ms": _number(
                    step.get("duration_ms") or step.get("latency_ms")
                ),
                "source_event_id": _text(step.get("id")) or None,
            }
        )
    return searches


def _journey(
    flow: Mapping[str, Any],
    *,
    understanding: Mapping[str, Any],
    requirements: list[dict[str, Any]],
    evidence: Mapping[str, Any],
    judgments: list[dict[str, Any]],
    applied: list[dict[str, Any]],
    model_calls: list[dict[str, Any]],
    verification: Mapping[str, Any],
) -> list[dict[str, Any]]:
    journey: list[dict[str, Any]] = []

    def emit(kind: str, **payload: Any) -> None:
        sequence = len(journey) + 1
        journey.append(
            {
                "id": f"journey:{sequence}:{kind.lower()}",
                "kind": kind,
                "sequence": sequence,
                "source_event_ids": payload.pop("source_event_ids", []),
                **payload,
            }
        )

    if any(understanding.get(key) for key in ("fields", "rules", "examples", "question")):
        emit("QUERY_UNDERSTOOD")
    if requirements:
        emit("REQUIREMENTS_IDENTIFIED")
    searches = list(evidence.get("searches") or [])
    if searches or evidence.get("document_count"):
        emit("KNOWLEDGE_SEARCHED", iteration=1)
    if evidence.get("document_count"):
        emit("EVIDENCE_FOUND")
    if judgments:
        emit("JEV_CHECKED")
    for decision in applied:
        emit("JEV_CHANGED_PATH", decision_id=decision["id"])
        if decision.get("action") in _RETRY_ACTIONS:
            emit(
                "SEARCH_RETRIED",
                decision_id=decision["id"],
                caused_by_event_id=decision["id"],
                iteration=2,
            )
    if evidence.get("complete") is True:
        emit("EVIDENCE_COMPLETE")
    elif evidence.get("complete") is False:
        emit("EVIDENCE_INCOMPLETE")
    for call in model_calls:
        kind = {
            "ANALYSIS": "LLM_ANALYZED",
            "ANSWER": "ANSWER_DRAFTED",
            "REVISION": "ANSWER_REVISED",
        }.get(call["purpose"], "LLM_PROCESSED")
        emit(kind, call_id=call["id"])
    for revision in _steps(flow, "answer_revision"):
        emit(
            "ANSWER_REVISED",
            source_event_ids=(
                [_text(revision.get("id"))] if revision.get("id") else []
            ),
        )
    if verification.get("checks") or verification.get("overall") != "not_verified":
        emit("ANSWER_VERIFIED")
    return journey


def _explicit_abstention(verification: Mapping[str, Any]) -> bool:
    return any(
        check.get("key") == "answer_gate" and check.get("detail") == "abstain"
        for check in _records(verification.get("checks"))
    )


def _answer_delivered(flow: Mapping[str, Any]) -> bool:
    final = any(
        item.get("type") == "final" and item.get("status") != "error"
        for item in _records(flow.get("steps"))
    )
    return final or _record(flow.get("generation")).get("skipped") is False


def _outcome(
    flow: Mapping[str, Any],
    evidence: Mapping[str, Any],
    verification: Mapping[str, Any],
    applied: list[dict[str, Any]],
) -> dict[str, Any]:
    status = _text(flow.get("status"))
    answer_delivered = _answer_delivered(flow)
    overall = _text(verification.get("overall")) or "not_verified"
    applied_retry = any(item.get("action") in _RETRY_ACTIONS for item in applied)
    if _explicit_abstention(verification):
        code, reason = "ABSTAINED", "explicit_abstention"
    elif status in {"failed", "error"} and not answer_delivered:
        code, reason = "FAILED", "execution_failed"
    elif overall == "blocked" and not answer_delivered:
        code, reason = "BLOCKED", "verification_blocked"
    elif answer_delivered and (
        evidence.get("complete") is False
        or overall == "partial"
        or verification.get("affected_outcome") is True
    ):
        code = "ANSWERED_WITH_LIMITS"
        if overall == "partial":
            reason = "verification_partial"
        elif evidence.get("complete") is False:
            reason = "evidence_incomplete"
        else:
            reason = "material_fallback"
    elif answer_delivered and applied_retry:
        code, reason = "RETRIED_AND_ANSWERED", "retry_applied"
    elif answer_delivered:
        code, reason = "ANSWERED", "answer_delivered"
    else:
        code, reason = "BLOCKED", "answer_not_delivered"
    return {
        "code": code,
        "reason_code": reason,
        "evidence_state": (
            "complete"
            if evidence.get("complete") is True
            else "incomplete"
            if evidence.get("complete") is False
            else "unknown"
        ),
        "verification_state": overall,
        "final_status": status,
        "material_fallback": verification.get("affected_outcome") is True,
        "answer_delivered": answer_delivered,
    }


def _response_shape(flow: Mapping[str, Any]) -> dict[str, Any]:
    step = _step(flow, "response_presentation")
    return {key: value for key, value in step.items() if key not in {"type", "id"}}


def _trace_overrides(
    *,
    trace: Mapping[str, Any] | None,
    documents: list[dict[str, Any]],
    judgments: list[dict[str, Any]],
    applied: list[dict[str, Any]],
    model_calls: list[dict[str, Any]],
    verification: dict[str, Any],
) -> dict[str, Any]:
    """Deriva evidencia/juicios/decisiones/llamadas del trace canónico v2.

    Sin trace (llamadas directas de tests o flows sin proyección) se conserva
    el cálculo local; con trace, TODO sale de la misma estructura v2 para que
    la historia y la vista técnica no puedan discrepar.
    """
    if not isinstance(trace, Mapping) or trace.get("schema_version") != 2:
        return {
            "documents": documents,
            "judgments": judgments,
            "applied": applied,
            "influenced": None,
            "model_calls": model_calls,
            "verification": verification,
        }
    evidence_block = _record(trace.get("evidence"))
    trace_documents: list[dict[str, Any]] = []
    for doc in _records(evidence_block.get("documents")):
        name = (
            _text(doc.get("document_name"))
            or _text(doc.get("display_name"))
            or _UNAVAILABLE_NAME
        )
        passages: list[dict[str, Any]] = []
        for item in _records(doc.get("items")):
            section = item.get("section_path")
            section_text = (
                " · ".join(str(part) for part in section if str(part).strip())
                if isinstance(section, (list, tuple))
                else _text(item.get("section"))
            )
            passages.append(
                {
                    "evidence_id": _text(item.get("evidence_id")) or None,
                    "page": item.get("page"),
                    "section": section_text or None,
                    "excerpt": _text(
                        item.get("excerpt") or item.get("content") or item.get("snippet")
                    ),
                    "status": _text(item.get("status")) or "USED",
                    "relevance": _number(item.get("score")),
                    "cited": item.get("cited") is True,
                    "used": item.get("used_in_answer") is True,
                    "source_event_ids": [],
                }
            )
        trace_documents.append(
            {
                "document_key": _text(doc.get("document_key")),
                "document_id": _text(doc.get("document_id")) or None,
                "source_id": _text(doc.get("source_id")) or None,
                "display_name": name,
                "title": name,
                "canonical_source_id": doc.get("canonical_source_id"),
                "name_missing": bool(doc.get("name_missing")),
                "passage_count": len(passages),
                "passages": passages,
            }
        )

    trace_judgments: list[dict[str, Any]] = []
    for judgment in _records(_record(trace.get("jev")).get("judgments")):
        interpretation = _record(judgment.get("interpretation"))
        alternatives = [
            {
                "key": _text(option.get("key")),
                "probability": option.get("probability"),
            }
            for option in _records(interpretation.get("options"))
        ] or _records(judgment.get("alternatives"))
        trace_judgments.append(
            {
                "id": _text(judgment.get("id")) or _text(judgment.get("judgment_id")),
                "pack_id": "trace",
                "phase": _text(judgment.get("phase")),
                "question_code": _text(judgment.get("question_code"))
                or _text(judgment.get("id")),
                "type": _text(judgment.get("type")).upper() or "NOUL",
                "answer": judgment.get("answer"),
                "probability": interpretation.get("selected_probability"),
                "certainty": interpretation.get("certainty"),
                "confidence_band": interpretation.get("band"),
                "ambiguous": bool(interpretation.get("ambiguous")),
                "alternatives": alternatives,
                "applied_decision_id": judgment.get("applied_decision_id"),
                "effect_code": judgment.get("effect_code"),
                "source_event_ids": list(judgment.get("source_event_ids") or []),
                "distribution": _record(judgment.get("raw")).get("distribution") or {},
            }
        )

    trace_applied: list[dict[str, Any]] = []
    for decision in _records(_record(trace.get("jev")).get("decisions_applied")):
        effects = list(decision.get("effect_codes") or [])
        trace_applied.append(
            {
                "id": _text(decision.get("decision_id")) or _text(decision.get("id")),
                "phase": _text(decision.get("phase")),
                "question_id": _text(decision.get("question_id")) or None,
                "action": _text(decision.get("action")),
                "decider": _text(decision.get("provider")) or "JEV",
                "reason_codes": list(decision.get("reason_codes") or []),
                "impact_code": effects[0] if effects else _text(decision.get("action")),
                "affected_event_ids": [],
                "source_event_ids": list(decision.get("source_event_ids") or []),
            }
        )

    generation = _record(trace.get("generation"))
    purpose_map = {
        "reasoning": "ANALYSIS",
        "tool_decision": "ANALYSIS",
        "answer_generation": "ANSWER",
        "revision": "REVISION",
    }
    trace_calls: list[dict[str, Any]] = []
    for call in _records(generation.get("call_details")):
        trace_calls.append(
            {
                "id": _text(call.get("id")) or f"model-call:{call.get('sequence')}",
                "sequence": call.get("sequence"),
                "purpose": purpose_map.get(_text(call.get("purpose")), "UNKNOWN"),
                "model": call.get("model"),
                "provider": call.get("provider"),
                "duration_ms": call.get("duration_ms"),
                "input_tokens": call.get("input_tokens"),
                "output_tokens": call.get("output_tokens"),
                "total_tokens": call.get("total_tokens"),
                "cost_usd": call.get("cost_usd"),
                "source_event_ids": list(call.get("source_event_ids") or []),
            }
        )
    if not trace_calls and generation.get("calls"):
        declared = int(_number(generation.get("calls")) or 0)
        reasoning = int(_number(generation.get("reasoning_calls")) or 0)
        answers = int(_number(generation.get("answer_calls")) or 0)
        purposes = ["ANALYSIS"] * reasoning + ["ANSWER"] * answers
        purposes.extend(["UNKNOWN"] * max(0, declared - len(purposes)))
        for index, purpose in enumerate(purposes, start=1):
            trace_calls.append(
                {
                    "id": f"model-call:{index}",
                    "sequence": index,
                    "purpose": purpose,
                    "model": generation.get("model"),
                    "provider": generation.get("provider"),
                    "duration_ms": generation.get("duration_ms")
                    if declared == 1
                    else None,
                    "input_tokens": None,
                    "output_tokens": None,
                    "total_tokens": None,
                    "cost_usd": None,
                    "source_event_ids": [],
                }
            )

    trace_verification = _record(trace.get("verification"))
    signals = _record(trace_verification.get("signals"))
    status = _text(trace_verification.get("status"))
    overall = {
        "VERIFIED": "verified",
        "PARTIALLY_VERIFIED": "partial",
        "INSUFFICIENT_EVIDENCE": "blocked",
        "CONFLICTING_EVIDENCE": "partial",
        "UNVERIFIED": "not_verified",
    }.get(status, "not_verified")
    trace_verification_override = {
        "overall": overall,
        "checks": _records(trace_verification.get("checks")),
        "primary_available": signals.get("grounded"),
        "fallback_used": bool(signals.get("fallback_used")),
        "fallback_code": signals.get("fallback_code"),
        "affected_outcome": bool(signals.get("material_fallback"))
        or any(
            item.get("material_effect") is True
            for item in _records(trace_verification.get("degradations"))
        ),
        "corrections": [],
        "source_event_ids": [],
        # Separación decisión/narrativa: la historia muestra ambos estados sin
        # recalcularlos (schema v2 manda).
        "decision_status": signals.get("decision_status")
        or _record(trace_verification.get("decision_verification")).get("status"),
        "narrative_status": signals.get("narrative_status")
        or _record(trace_verification.get("narrative_verification")).get("status"),
        "decision_grounding": trace_verification.get("decision_grounding"),
        "narrative_grounding": trace_verification.get("narrative_grounding"),
        "decision_verification": _record(
            trace_verification.get("decision_verification")
        ),
        "narrative_verification": _record(
            trace_verification.get("narrative_verification")
        ),
    }

    return {
        "documents": trace_documents,
        "judgments": trace_judgments,
        "applied": trace_applied,
        "influenced": len(_records(_record(trace.get("jev")).get("material_decisions"))),
        "model_calls": trace_calls,
        "verification": trace_verification_override,
    }


def build_execution_narrative(
    flow: Mapping[str, Any],
    events: list[dict[str, Any]],
    trace: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an additive narrative without changing any canonical decision."""
    diagnostics: list[dict[str, Any]] = []
    evidence = _canonical_evidence(flow)
    documents = _group_documents(_records(flow.get("sources")), diagnostics)
    understanding = _understanding(flow)
    requirements = _requirements(flow)
    applied = _applied_decisions(flow, events)
    judgments = _judgments(flow, applied, diagnostics, events)
    model_calls = _model_calls(flow)
    verification = _verification(flow)
    overrides = _trace_overrides(
        trace=trace,
        documents=documents,
        judgments=judgments,
        applied=applied,
        model_calls=model_calls,
        verification=verification,
    )
    documents = overrides["documents"]
    judgments = overrides["judgments"]
    applied = overrides["applied"]
    model_calls = overrides["model_calls"]
    verification = overrides["verification"]
    evidence["documents"] = documents
    evidence["document_count"] = len(documents)
    evidence["passage_count"] = sum(item["passage_count"] for item in documents)
    evidence["searches"] = _searches(flow)
    outcome = _outcome(flow, evidence, verification, applied)
    journey = _journey(
        flow,
        understanding=understanding,
        requirements=requirements,
        evidence=evidence,
        judgments=judgments,
        applied=applied,
        model_calls=model_calls,
        verification=verification,
    )
    if outcome["code"] in _ANSWERED_OUTCOMES:
        sequence = len(journey) + 1
        journey.append(
            {
                "id": f"journey:{sequence}:answer_delivered",
                "kind": "ANSWER_DELIVERED",
                "sequence": sequence,
                "source_event_ids": [],
            }
        )
    jev = _record(flow.get("jev_preflight"))
    packs = _records(jev.get("packs"))
    timings = _record(flow.get("timings"))
    generation = _record(flow.get("generation"))
    influenced = overrides.get("influenced")
    return {
        "schema_version": NARRATIVE_SCHEMA_VERSION,
        "outcome": outcome,
        "summary": {
            # Con trace canónico manda la intervención material; sin trace se
            # conserva la semántica histórica (decisiones aplicadas).
            "decisions_influenced": influenced
            if influenced is not None
            else len(applied),
            "judgment_count": len(judgments),
            "jev_calls": max(
                sum(1 for item in packs if item.get("status", "ok") == "ok"),
                sum(1 for item in events if _text(item.get("kind")) == "jev_pack"),
            ),
            "total_ms": _number(timings.get("total_ms")),
            "cost_usd": _number(generation.get("cost")),
        },
        "understanding": understanding,
        "requirements": requirements,
        "journey": journey,
        "judgments": judgments,
        "applied_decisions": applied,
        "evidence": evidence,
        "model_calls": model_calls,
        "verification": verification,
        "response_shape": _response_shape(flow),
        "learning": {},
        "diagnostics": diagnostics,
        "source_event_count": len(events),
    }


__all__ = ["NARRATIVE_SCHEMA_VERSION", "build_execution_narrative"]
