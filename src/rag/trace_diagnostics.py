"""Diagnóstico explicable e Invariant Engine — Traceability Schema v2.

Cada hallazgo responde tres preguntas (§18): qué significa (`meaning_code`),
si afectó la respuesta (`impact_code`) y qué corregir (`fix_code`). El código
técnico es secundario en la UI. Severidad y efecto material son ejes separados
(§19): un `WARNING` puede tener `material_effect = false`.

El Invariant Engine convierte cualquier violación en un item de diagnóstico;
nunca queda sólo dentro de un JSON (§24).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

SEVERITY_ORDER = {
    "INFO": 0,
    "NOTICE": 1,
    "WARNING": 2,
    "ERROR": 3,
    "CRITICAL": 4,
}

#: code -> (severity, dimension, material_effect, meaning_code, impact_code, fix_code)
DIAGNOSTIC_DEFINITIONS: dict[str, tuple[str, str, bool, str, str, str | None]] = {
    "EVIDENCE_ID_MISSING": (
        "WARNING",
        "metadata",
        False,
        "missing_evidence_id",
        "no_content_impact",
        "derive_evidence_id",
    ),
    "EVIDENCE_EXCERPT_MISSING": (
        "NOTICE",
        "evidence",
        False,
        "missing_excerpt",
        "no_content_impact",
        "persist_excerpt",
    ),
    "SOURCE_NAME_MISSING": (
        "WARNING",
        "metadata",
        False,
        "missing_source_name",
        "no_content_impact",
        "resolve_source_name",
    ),
    "CANONICAL_SOURCE_ID_MISSING": (
        "WARNING",
        "metadata",
        False,
        "missing_canonical_source",
        "no_content_impact",
        "derive_canonical_source",
    ),
    "CANONICAL_SOURCE_WEAK_IDENTITY": (
        "NOTICE",
        "metadata",
        False,
        "weak_source_identity",
        "no_content_impact",
        "persist_physical_identity",
    ),
    "EVIDENCE_COLLECTION_PARTIAL": (
        "NOTICE",
        "evidence",
        False,
        "partial_evidence_detail",
        "no_content_impact",
        "raise_detail_limit",
    ),
    "EVIDENCE_COLLECTION_EXCEEDS_DECLARED": (
        "WARNING",
        "consistency",
        False,
        "collection_exceeds_declared",
        "no_content_impact",
        "align_counts",
    ),
    "EVIDENCE_DETAIL_UNAVAILABLE": (
        "NOTICE",
        "evidence",
        False,
        "evidence_detail_unavailable",
        "no_content_impact",
        "persist_items_detail",
    ),
    "EVIDENCE_DEDUPLICATED": (
        "INFO",
        "evidence",
        False,
        "evidence_deduplicated",
        "no_content_impact",
        None,
    ),
    "CITATION_DANGLING": (
        "WARNING",
        "consistency",
        False,
        "citation_dangling",
        "possible_unsupported_claim",
        "align_citations",
    ),
    "CITATION_EVIDENCE_REFERENTIAL_INTEGRITY": (
        "WARNING",
        "consistency",
        False,
        "citation_reference_missing",
        "possible_unsupported_claim",
        "align_citations",
    ),
    "ANSWER_CITATION_TRACE_CONSISTENCY": (
        "ERROR",
        "consistency",
        True,
        "answer_citations_missing_from_trace",
        "answer_cites_documents_trace_shows_zero",
        "bind_citations_to_final_package",
    ),
    "AUTHORITATIVE_RESPONSE_CONSISTENCY": (
        "ERROR",
        "consistency",
        True,
        "authoritative_response_inconsistent",
        "answer_contradicts_authoritative_decision",
        "rebuild_from_decision_envelope",
    ),
    "DECISION_VERIFICATION_CONSISTENCY": (
        "ERROR",
        "verification",
        True,
        "decision_verification_inconsistent",
        "decision_verified_invalidated_by_narrative",
        "separate_decision_from_narrative",
    ),
    "NARRATIVE_LLM_CALL_TRACE_CONSISTENCY": (
        "ERROR",
        "verification",
        True,
        "narrative_llm_call_missing_from_generation",
        "generation_under_counts_llm",
        "record_llm_call",
    ),
    "NARRATIVE_TOOL_TRACE_CONSISTENCY": (
        "ERROR",
        "verification",
        True,
        "narrative_retrieval_without_tool_trace",
        "tools_hidden",
        "record_search_call",
    ),
    "NARRATIVE_FAST_PATH_VERIFICATION_MISSING": (
        "ERROR",
        "verification",
        True,
        "narrative_fast_path_without_verifier",
        "flow_shows_unverified",
        "pass_narrative_binding_to_verification",
    ),
    "DECISION_NARRATIVE_SEPARATION": (
        "ERROR",
        "verification",
        True,
        "decision_narrative_not_separated",
        "narrative_failure_degraded_decision",
        "separate_decision_from_narrative",
    ),
    "FAST_PATH_VERIFICATION_CONSISTENCY": (
        "ERROR",
        "verification",
        True,
        "fast_path_verification_inconsistent",
        "verified_response_shown_as_unverified",
        "unify_verification_source",
    ),
    "EVIDENCE_REF_UNRESOLVED": (
        "WARNING",
        "evidence",
        False,
        "evidence_ref_unresolved",
        "decision_evidence_not_hydrated",
        "hydrate_decision_evidence",
    ),
    "EVIDENCE_USED_FOR_DECISION": (
        "INFO",
        "evidence",
        False,
        "evidence_used_for_decision",
        "no_content_impact",
        None,
    ),
    "CITATION_REFERENCES_COLLAPSED": (
        "INFO",
        "evidence",
        False,
        "citation_references_collapsed",
        "no_content_impact",
        "dedupe_citations",
    ),
    "PROBABILITY_MISMATCH": (
        "WARNING",
        "consistency",
        False,
        "confidence_conflict",
        "no_content_impact",
        "separate_probability_confidence",
    ),
    "INVALID_PROBABILITY": (
        "ERROR",
        "consistency",
        False,
        "invalid_probability",
        "no_content_impact",
        "fix_producer",
    ),
    "ACTION_APPLIED_REQUIRED": (
        "WARNING",
        "jev",
        False,
        "applied_flag_conflict",
        "no_content_impact",
        "align_decision_flags",
    ),
    "INSUFFICIENT_THEN_GENERATED": (
        "WARNING",
        "evidence",
        False,
        "insufficient_then_generated",
        "answer_may_be_unsupported",
        "explain_expansion",
    ),
    "EVIDENCE_USED_EXCEEDS_UNIQUE": (
        "ERROR",
        "consistency",
        False,
        "used_exceeds_unique",
        "no_content_impact",
        "fix_counting",
    ),
    "EVIDENCE_CITED_EXCEEDS_USED": (
        "WARNING",
        "consistency",
        False,
        "cited_exceeds_used",
        "no_content_impact",
        "define_citation_scope",
    ),
    "EVIDENCE_SELECTED_EXCEEDS_UNIQUE": (
        "WARNING",
        "consistency",
        False,
        "selected_exceeds_unique",
        "no_content_impact",
        "fix_counting",
    ),
    "DOCUMENTS_USED_EXCEEDS_RETRIEVED": (
        "WARNING",
        "consistency",
        False,
        "used_docs_exceed_retrieved",
        "no_content_impact",
        "fix_counting",
    ),
    "EVIDENCE_DEDUP_ARITHMETIC": (
        "ERROR",
        "consistency",
        False,
        "dedup_arithmetic",
        "no_content_impact",
        "fix_counting",
    ),
    "ANSWER_CALLS_EXCEED_MODEL_CALLS": (
        "ERROR",
        "generation",
        False,
        "answer_calls_exceed_model_calls",
        "no_content_impact",
        "fix_counting",
    ),
    "MATERIAL_FALLBACK_WITHOUT_EVENT": (
        "ERROR",
        "fallbacks",
        False,
        "material_fallback_without_event",
        "no_content_impact",
        "record_recovery_event",
    ),
    "VERIFIED_WITH_MATERIAL_DEGRADATION": (
        "ERROR",
        "verification",
        True,
        "verified_with_degradation",
        "answer_limit_unresolved",
        "fix_verification",
    ),
    "PARALLEL_SPANS": (
        "NOTICE",
        "timing",
        False,
        "parallel_spans",
        "no_content_impact",
        None,
    ),
    "MAX_TOKENS_RECOVERED": (
        "NOTICE",
        "generation",
        False,
        "max_tokens_recovered",
        "no_content_impact",
        None,
    ),
    "MAX_TOKENS_MATERIAL_IMPACT": (
        "WARNING",
        "generation",
        True,
        "max_tokens_impact",
        "answer_may_be_incomplete",
        "review_truncation",
    ),
    "JOURNEY_DUPLICATE_PURPOSE": (
        "WARNING",
        "presentation",
        False,
        "journey_duplicate",
        "no_content_impact",
        "collapse_steps",
    ),
    "VERIFICATION_NOT_OBSERVED": (
        "NOTICE",
        "verification",
        False,
        "verification_not_observed",
        "unknown",
        "persist_verification",
    ),
    "HISTORICAL_TRACE_UPGRADED": (
        "INFO",
        "execution",
        False,
        "historical_trace",
        "reduced_fidelity",
        "use_v2_runtime",
    ),
    "DUPLICATE_EVIDENCE_ID": (
        "WARNING",
        "consistency",
        False,
        "duplicate_evidence_id",
        "no_content_impact",
        "dedupe_evidence",
    ),
    "UNMAPPED_STEPS": (
        "NOTICE",
        "execution",
        False,
        "unmapped_steps",
        "no_content_impact",
        "map_steps",
    ),
}

#: códigos que cuentan como violación de invariante (v1 `diagnostics.invariants`)
INVARIANT_CODES = {
    "PROBABILITY_MISMATCH",
    "INVALID_PROBABILITY",
    "ACTION_APPLIED_REQUIRED",
    "INSUFFICIENT_THEN_GENERATED",
    "EVIDENCE_USED_EXCEEDS_UNIQUE",
    "EVIDENCE_CITED_EXCEEDS_USED",
    "AUTHORITATIVE_RESPONSE_CONSISTENCY",
    "EVIDENCE_SELECTED_EXCEEDS_UNIQUE",
    "DOCUMENTS_USED_EXCEEDS_RETRIEVED",
    "EVIDENCE_DEDUP_ARITHMETIC",
    "ANSWER_CALLS_EXCEED_MODEL_CALLS",
    "MATERIAL_FALLBACK_WITHOUT_EVENT",
    "VERIFIED_WITH_MATERIAL_DEGRADATION",
    "DECISION_VERIFICATION_CONSISTENCY",
    "DECISION_NARRATIVE_SEPARATION",
    "FAST_PATH_VERIFICATION_CONSISTENCY",
    "JOURNEY_DUPLICATE_PURPOSE",
    "DUPLICATE_EVIDENCE_ID",
}

#: códigos que cuentan como gap de datos (v1 `diagnostics.gaps`)
GAP_CODES = {
    "EVIDENCE_ID_MISSING",
    "EVIDENCE_EXCERPT_MISSING",
    "SOURCE_NAME_MISSING",
    "CANONICAL_SOURCE_ID_MISSING",
    "CANONICAL_SOURCE_WEAK_IDENTITY",
    "EVIDENCE_COLLECTION_PARTIAL",
    "EVIDENCE_COLLECTION_EXCEEDS_DECLARED",
    "EVIDENCE_DETAIL_UNAVAILABLE",
    "CITATION_DANGLING",
    "CITATION_EVIDENCE_REFERENTIAL_INTEGRITY",
    "EVIDENCE_REF_UNRESOLVED",
    "VERIFICATION_NOT_OBSERVED",
}

_UNKNOWN_DEFINITION = (
    "NOTICE",
    "execution",
    False,
    "unknown_finding",
    "unknown",
    "review",
)


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def diagnostic_item(
    code: str,
    *,
    params: Mapping[str, Any] | None = None,
    source_event_ids: list[str] | None = None,
    severity: str | None = None,
    dimension: str | None = None,
    material_effect: bool | None = None,
    technical: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    definition = DIAGNOSTIC_DEFINITIONS.get(code, _UNKNOWN_DEFINITION)
    base_severity, base_dimension, base_material, meaning, impact, fix = definition
    item: dict[str, Any] = {
        "code": code,
        "severity": severity or base_severity,
        "dimension": dimension or base_dimension,
        "material_effect": base_material if material_effect is None else bool(material_effect),
        "meaning_code": meaning,
        "impact_code": impact,
        "fix_code": fix,
        "params": dict(params or {}),
    }
    if source_event_ids:
        item["source_event_ids"] = list(source_event_ids)
    if technical:
        item["technical"] = dict(technical)
    return item


def _worst_severity(items: list[dict[str, Any]]) -> str | None:
    if not items:
        return None
    return max(
        (str(item.get("severity") or "NOTICE") for item in items),
        key=lambda severity: SEVERITY_ORDER.get(severity, 1),
    )


def _status_for(severity: str | None, *, observed: bool) -> str:
    if severity is None:
        return "ok" if observed else "unknown"
    if severity == "INFO":
        return "ok"
    if severity == "NOTICE":
        return "notice"
    if severity == "WARNING":
        return "warning"
    return "error"


def run_invariants(
    *,
    evidence: Mapping[str, Any],
    jev: Mapping[str, Any],
    generation: Mapping[str, Any],
    controls: Mapping[str, Any],
    verification: Mapping[str, Any],
    timeline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validaciones explícitas del trace (§24). Devuelve items de diagnóstico."""
    found: list[dict[str, Any]] = []
    counts = _record(evidence.get("counts"))
    unique = _number(counts.get("evidence_unique"))
    retrieved = _number(counts.get("evidence_retrieved"))
    deduplicated = _number(counts.get("evidence_deduplicated"))
    selected = _number(counts.get("evidence_selected"))
    used = _number(counts.get("evidence_used"))
    cited = _number(counts.get("evidence_cited"))
    docs_retrieved = _number(counts.get("documents_retrieved"))
    docs_used = _number(counts.get("documents_used"))
    collection = str(evidence.get("collection") or "complete")

    if unique is not None and used is not None and used > unique:
        found.append(
            diagnostic_item(
                "EVIDENCE_USED_EXCEEDS_UNIQUE",
                params={"used": used, "unique": unique},
            )
        )
    if used is not None and cited is not None and cited > used:
        found.append(
            diagnostic_item(
                "EVIDENCE_CITED_EXCEEDS_USED",
                params={"cited": cited, "used": used},
            )
        )
    # AUTHORITATIVE_RESPONSE_CONSISTENCY: un envelope autoritativo no puede
    # convivir con un estado de respuesta no derivado (contradicción P0).
    envelope = _record(verification.get("decision_envelope"))
    if envelope.get("authoritative") is True:
        declared = str(envelope.get("result") or "").upper()
        answer_state = verification.get("answer_state")
        state = (
            str(answer_state.get("state") or "")
            if isinstance(answer_state, Mapping)
            else str(answer_state or "")
        )
        if declared and state and state != "DERIVED_RESULT":
            found.append(
                diagnostic_item(
                    "AUTHORITATIVE_RESPONSE_CONSISTENCY",
                    params={"result": declared, "answer_state": state},
                )
            )
    # DECISION_VERIFICATION_CONSISTENCY: con DecisionEnvelope autoritativo y un
    # DerivedClaim determinista SUPPORTED, la verificación de la DECISIÓN no
    # puede quedar UNVERIFIED/NOT_VERIFIED.
    decision_verification = _record(verification.get("decision_verification"))
    decision_status = str(decision_verification.get("status") or "")
    supported_claim = next(
        (
            claim
            for claim in _records(verification.get("derived_claims"))
            if claim.get("deterministic") is True
            and str(claim.get("verification_status") or "") == "SUPPORTED"
        ),
        None,
    )
    if (
        envelope.get("authoritative") is True
        and supported_claim is not None
        and decision_status
        and decision_status != "VERIFIED"
    ):
        found.append(
            diagnostic_item(
                "DECISION_VERIFICATION_CONSISTENCY",
                params={
                    "decision_status": decision_status,
                    "operation": supported_claim.get("operation"),
                },
            )
        )
    # DECISION_NARRATIVE_SEPARATION: un fallo narrativo no puede degradar la
    # decisión (ni el estado global cuando la decisión está verificada).
    narrative_verification = _record(verification.get("narrative_verification"))
    narrative_status = str(narrative_verification.get("status") or "")
    fast_steps = [
        step
        for step in timeline
        if str(step.get("type") or "") == "narrative_fast_path"
        or str(step.get("route") or "") == "NARRATIVE_FAST_PATH"
    ]
    fast_narrative = bool(fast_steps)
    declared_llm = sum(int(step.get("llm_calls") or 0) for step in fast_steps)
    recorded_llm = sum(
        1
        for step in timeline
        if str(step.get("type") or "") == "llm"
        and str(step.get("purpose") or "") == "narrative_generation"
    )
    if declared_llm > recorded_llm:
        found.append(
            diagnostic_item(
                "NARRATIVE_LLM_CALL_TRACE_CONSISTENCY",
                params={"declared": declared_llm, "recorded": recorded_llm},
            )
        )
    retrieval_rounds = sum(int(step.get("retrieval_rounds") or 0) for step in fast_steps)
    tool_traces = [
        step
        for step in timeline
        if str(step.get("type") or "") in {"tool_call", "jev_retrieval"}
        and "search" in str(step.get("tool") or "").lower()
    ]
    if retrieval_rounds > 0 and not tool_traces:
        found.append(
            diagnostic_item(
                "NARRATIVE_TOOL_TRACE_CONSISTENCY",
                params={"retrieval_rounds": retrieval_rounds},
            )
        )
    narrative_warnings = [str(item) for item in narrative_verification.get("warnings") or ()]
    if fast_narrative and (
        "NO_VERIFICATION_RECORDED" in narrative_warnings
        or (
            narrative_status in {"", "UNVERIFIED"}
            and not any(
                isinstance(step.get("verification_input"), Mapping)
                for step in timeline
                if str(step.get("type") or "") == "narrative_evidence"
            )
        )
    ):
        found.append(
            diagnostic_item(
                "NARRATIVE_FAST_PATH_VERIFICATION_MISSING",
                params={"narrative_status": narrative_status or "UNVERIFIED"},
            )
        )
    if decision_status == "VERIFIED" and str(verification.get("status") or "") == "UNVERIFIED":
        found.append(
            diagnostic_item(
                "DECISION_NARRATIVE_SEPARATION",
                params={
                    "decision": "VERIFIED",
                    "narrative": narrative_status or "UNKNOWN",
                    "verification": "UNVERIFIED",
                },
            )
        )
    if unique is not None and selected is not None and selected > unique:
        found.append(
            diagnostic_item(
                "EVIDENCE_SELECTED_EXCEEDS_UNIQUE",
                params={"selected": selected, "unique": unique},
            )
        )
    if (
        docs_retrieved is not None
        and docs_used is not None
        and docs_used > docs_retrieved
    ):
        found.append(
            diagnostic_item(
                "DOCUMENTS_USED_EXCEEDS_RETRIEVED",
                params={"used": docs_used, "retrieved": docs_retrieved},
            )
        )
    if (
        collection == "complete"
        and retrieved is not None
        and unique is not None
        and deduplicated is not None
        and retrieved != unique + deduplicated
    ):
        found.append(
            diagnostic_item(
                "EVIDENCE_DEDUP_ARITHMETIC",
                params={
                    "retrieved": retrieved,
                    "unique": unique,
                    "deduplicated": deduplicated,
                },
            )
        )

    calls = _number(generation.get("calls"))
    answer_calls = _number(generation.get("answer_calls"))
    if calls is not None and answer_calls is not None and answer_calls > calls:
        found.append(
            diagnostic_item(
                "ANSWER_CALLS_EXCEED_MODEL_CALLS",
                params={"answer_calls": answer_calls, "model_calls": calls},
            )
        )

    fallbacks = _record(controls.get("fallbacks"))
    fallbacks_material = fallbacks.get("material") is True
    material_controls = _records(controls.get("material_controls"))
    if fallbacks_material and not material_controls and not _records(
        fallbacks.get("events")
    ):
        found.append(diagnostic_item("MATERIAL_FALLBACK_WITHOUT_EVENT"))

    status = str(verification.get("status") or "")
    degradation = _records(verification.get("degradations"))
    material_degradation = [
        item for item in degradation if item.get("material_effect") is True
    ]
    # Si la degradación material existe, la verificación DEBE haber reaccionado
    # (PARTIALLY/UNVERIFIED). Un VERIFIED que la ignore es la violación.
    if status == "VERIFIED" and material_degradation:
        found.append(
            diagnostic_item(
                "VERIFIED_WITH_MATERIAL_DEGRADATION",
                params={
                    "status": status,
                    "degradation": material_degradation[0].get("code"),
                },
                severity="ERROR",
                material_effect=True,
            )
        )

    citations = _record(evidence.get("citations_summary"))
    dangling = [str(item) for item in citations.get("dangling") or [] if str(item)]
    canonical_ids = {
        str(item.get("evidence_id"))
        for item in _records(evidence.get("canonical_evidence"))
        if item.get("evidence_id")
    }
    if dangling and canonical_ids and collection == "complete":
        missing = [item for item in dangling if item not in canonical_ids]
        if missing:
            found.append(
                diagnostic_item(
                    "CITATION_DANGLING",
                    params={"evidence_ids": missing[:8]},
                )
            )

    # El mismo propósito visible no puede aparecer dos veces (§14). Sólo se
    # vigila la generación de respuesta: otras fases pueden repetirse
    # legítimamente (varias rondas de retrieval, varios gates).
    purposes: dict[str, int] = {}
    for node in timeline:
        if node.get("user_visible") is not True:
            continue
        purpose = str(node.get("purpose") or "")
        if purpose == "answer_generation":
            purposes[purpose] = purposes.get(purpose, 0) + 1
    duplicates = [purpose for purpose, count in purposes.items() if count > 1]
    if duplicates:
        found.append(
            diagnostic_item(
                "JOURNEY_DUPLICATE_PURPOSE",
                params={"purposes": duplicates[:4]},
            )
        )
    return found


def build_diagnostics(
    *,
    evidence: Mapping[str, Any],
    jev: Mapping[str, Any],
    generation: Mapping[str, Any],
    controls: Mapping[str, Any],
    verification: Mapping[str, Any],
    timeline: list[dict[str, Any]],
    timing: Mapping[str, Any] | None = None,
    memory: Mapping[str, Any] | None = None,
    cost: Mapping[str, Any] | None = None,
    sources: Mapping[str, Any] | None = None,
    extra_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compone items + dimensiones + consistencia + proyección v1."""
    items: list[dict[str, Any]] = []
    items.extend(extra_items or [])
    for raw in _records(evidence.get("diagnostics")):
        code = str(raw.get("code") or "")
        params = {key: value for key, value in raw.items() if key != "code"}
        items.append(diagnostic_item(code, params=params))
    for raw in _records(jev.get("diagnostics")):
        code = str(raw.get("code") or "")
        params = {key: value for key, value in raw.items() if key != "code"}
        items.append(diagnostic_item(code, params=params))
    items.extend(
        run_invariants(
            evidence=evidence,
            jev=jev,
            generation=generation,
            controls=controls,
            verification=verification,
            timeline=timeline,
        )
    )
    for warning in _records(controls.get("generation_warnings")):
        code = (
            "MAX_TOKENS_MATERIAL_IMPACT"
            if warning.get("material_effect") is True
            else "MAX_TOKENS_RECOVERED"
        )
        items.append(
            diagnostic_item(
                code,
                params={
                    "impact": warning.get("impact"),
                    "checks": warning.get("checks"),
                },
            )
        )

    timing_for_findings = _record(timing)
    if timing_for_findings.get("parallel") is True:
        items.append(
            diagnostic_item(
                "PARALLEL_SPANS",
                params={
                    "wall_clock_ms": timing_for_findings.get("wall_clock_ms"),
                    "accumulated_ms": timing_for_findings.get("accumulated_ms"),
                },
            )
        )

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        key = (str(item.get("code")), str(sorted(item.get("params", {}).items())))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    dimensions: dict[str, dict[str, Any]] = {}
    timing_block = _record(timing)
    memory_block = _record(memory)
    cost_block = _record(cost)
    observed = {
        "execution": True,
        "evidence": evidence.get("counts", {}).get("evidence_retrieved") is not None
        or bool(evidence.get("canonical_evidence")),
        "jev": bool(jev.get("executed")),
        "generation": generation.get("calls") is not None
        or generation.get("observed") is True,
        "verification": str(verification.get("status") or "") != "UNVERIFIED"
        or bool(verification.get("checks")),
        "memory": memory_block.get("observed") is True,
        "timing": timing_block.get("wall_clock_ms") is not None,
        "cost": cost_block.get("total_usd") is not None,
        "metadata": bool(evidence.get("canonical_evidence")),
        "consistency": True,
    }
    for dimension in (
        "execution",
        "evidence",
        "jev",
        "generation",
        "verification",
        "memory",
        "timing",
        "cost",
        "metadata",
        "consistency",
    ):
        dimension_items = [
            item for item in deduped if item.get("dimension") == dimension
        ]
        severity = _worst_severity(dimension_items)
        dimensions[dimension] = {
            "status": _status_for(severity, observed=bool(observed.get(dimension))),
            "severity": severity,
            "findings": len(dimension_items),
        }

    hygiene = [
        item
        for item in deduped
        if item.get("dimension") in {"consistency", "metadata"}
    ]
    hygiene_severity = _worst_severity(hygiene)
    if hygiene_severity in {"ERROR", "CRITICAL"}:
        consistency = "inconsistent"
    elif hygiene_severity == "WARNING":
        consistency = "partial"
    elif hygiene_severity in {"INFO", "NOTICE"}:
        consistency = "consistent_with_notes"
    else:
        consistency = "consistent"

    overall_candidates = [
        item
        for item in deduped
        if item.get("dimension") in {"execution", "evidence", "jev", "generation", "verification"}
        or item.get("material_effect") is True
    ]
    overall_severity = _worst_severity(overall_candidates)
    global_status = _status_for(
        overall_severity,
        observed=dimensions["execution"]["status"] != "unknown",
    )

    def _legacy_projection(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Vista v1: código + campos planos (compatibilidad de tests y portal)."""
        projection: list[dict[str, Any]] = []
        for item in items:
            entry: dict[str, Any] = {"code": item.get("code")}
            for key, value in _record(item.get("params")).items():
                entry.setdefault(key, value)
            projection.append(entry)
        return projection

    invariants = _legacy_projection(
        [item for item in deduped if item.get("code") in INVARIANT_CODES]
    )
    gaps = _legacy_projection(
        [item for item in deduped if item.get("code") in GAP_CODES]
    )

    return {
        "items": deduped,
        "invariants": invariants,
        "gaps": gaps,
        "dimensions": dimensions,
        "consistency": {
            "status": consistency,
            "findings": len(hygiene),
            "response_quality": verification.get("status"),
        },
        "overall": {
            "status": global_status,
            "severity": overall_severity,
            "findings": len(deduped),
        },
        "sources": dict(sources or {}),
    }


__all__ = [
    "DIAGNOSTIC_DEFINITIONS",
    "GAP_CODES",
    "INVARIANT_CODES",
    "SEVERITY_ORDER",
    "build_diagnostics",
    "diagnostic_item",
    "run_invariants",
]
