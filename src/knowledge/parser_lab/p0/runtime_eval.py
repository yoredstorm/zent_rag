# =============================================================================
# P0 — Métricas de runtime: retrieval, answerability, decisión determinista,
# consistencia y answer accuracy. Todo offline (InMemory + grounded engine).
# =============================================================================
from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from typing import Any

from src.intelligence.reasoning.grounded_engine import reason_over_evidence
from src.knowledge.parser_lab.p0.evaluate import premise_satisfied
from src.knowledge.parser_lab.p0.golden import best_match
from src.knowledge.parser_lab.p0.state import KnowledgeState
from src.knowledge.rule_compiler.evaluate import evaluate_rule
from src.runtime.decision_envelope import build_decision_envelope
from src.runtime.query_local_rules import compile_query_local_rules
from src.runtime.rule_retrieval import (
    InMemoryRuleIndex,
    InMemoryRuleLookup,
    retrieve_canonical_rules,
)

_DERIVED_STATUSES = {"MATCH", "NO_MATCH"}
_ONTOLOGY_TERMS = (
    "indicate",
    "alphanumeric",
    "position",
    "additional characters",
    "at least",
    "represent",
    "significa",
    "posicional",
)
_SYMBOLS = ("&", "!", "*", "?", "%", "#", "@", "~", "^")


@dataclass
class _UnitEvidenceItem:
    """Unidad del estado como evidencia query-local (mismo contrato chunk)."""

    content: str
    evidence_id: str
    document_id: str
    source_id: str
    page: int | None
    section_path: tuple[str, ...]
    metadata: dict[str, Any]


def _unit_items(state: KnowledgeState) -> list[_UnitEvidenceItem]:
    items: list[_UnitEvidenceItem] = []
    for index, unit in enumerate(state.units):
        content = str(getattr(unit, "content", "") or "")
        if not content.strip():
            continue
        items.append(
            _UnitEvidenceItem(
                content=content,
                evidence_id=f"unit:{index}",
                document_id=str(state.document.id),
                source_id=str(state.document.source_id or ""),
                page=getattr(unit, "page_start", None),
                section_path=tuple(getattr(unit, "section_path", ()) or ()),
                metadata={"document_id": str(state.document.id), "chunk_id": f"unit:{index}"},
            )
        )
    return items


def _fraction(hits: int, total: int) -> float | None:
    if total == 0:
        return None
    return round(hits / total, 4)


def _golden_object(golden: dict[str, Any], object_id: str) -> dict[str, Any] | None:
    for item in golden.get("objects") or []:
        if str(item.get("id")) == object_id:
            return item
    return None


def _expected_rules(state: KnowledgeState, golden: dict[str, Any], query: dict[str, Any]) -> list[Any]:
    expected: list[Any] = []
    canonical = state.haystacks_for("rule")
    canonical = [item for item in canonical if item[2] == "canonical_rule"]
    for object_id in query.get("objects") or []:
        item = _golden_object(golden, object_id)
        if item is None:
            continue
        match = best_match(item, canonical)
        if match.matched and match.produced_index is not None:
            expected.append(canonical[match.produced_index][1])
    return expected


async def retrieval_metrics(state: KnowledgeState, golden: dict[str, Any]) -> dict[str, Any]:
    rules = state.rules
    if not rules:
        return {
            "queries": 0,
            "recall_at_k": None,
            "mrr": None,
            "rule_retrieval_recall": None,
            "premise_retrieval_recall": None,
            "irrelevant_evidence_ratio": None,
            "source_local_success": None,
            "cross_page_evidence_recovery": None,
        }
    index = InMemoryRuleIndex(rules)
    lookup = InMemoryRuleLookup(rules)
    recall_hits = 0
    reciprocal_ranks: list[float] = []
    irrelevant = 0
    retrieved_total = 0
    source_local_hits = 0
    source_local_total = 0
    cross_page_hits = 0
    cross_page_total = 0
    premise_hits = 0
    premise_total = 0
    queries = [q for q in golden.get("queries") or [] if q.get("answerable")]
    for query in queries:
        expected = _expected_rules(state, golden, query)
        result = await retrieve_canonical_rules(
            state.understood.organization_id,
            str(query.get("question") or ""),
            index=index,
            lookup=lookup,
        )
        hits = list(result.supported_rules or [])
        if not hits:
            hits = list(getattr(result, "rules", None) or [])
        retrieved_total += len(hits)
        rank = None
        for position, hit in enumerate(hits, start=1):
            if any(hit is rule or getattr(hit, "rule_id", "") == getattr(rule, "rule_id", "") for rule in expected):
                rank = position
                break
        if rank is not None:
            recall_hits += 1
            reciprocal_ranks.append(1.0 / rank)
            irrelevant += len(hits) - len(expected)
        else:
            irrelevant += len(hits)
            reciprocal_ranks.append(0.0)
        if expected:
            source_local_total += 1
            pages = {
                page
                for item in query.get("objects") or []
                for page in (_golden_object(golden, item) or {}).get("pages") or []
            }
            if any(
                KnowledgeState.rule_pages(rule) & set(int(page) for page in pages)
                for rule in expected
            ):
                source_local_hits += 1
        if query.get("cross_page"):
            cross_page_total += 1
            golden_pages = {
                int(page)
                for item in query.get("objects") or []
                for page in (_golden_object(golden, item) or {}).get("pages") or []
            }
            if any(
                KnowledgeState.rule_pages(rule) & golden_pages for rule in expected
            ):
                cross_page_hits += 1
        if query.get("executable"):
            premise_total += 1
            if expected and any(
                getattr(rule, "executable", False) for rule in expected
            ):
                premise_hits += 1
    return {
        "queries": len(queries),
        "recall_at_k": _fraction(recall_hits, len(queries)),
        "rule_retrieval_recall": _fraction(recall_hits, len(queries)),
        "mrr": round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4) if reciprocal_ranks else None,
        "premise_retrieval_recall": _fraction(premise_hits, premise_total),
        "irrelevant_evidence_ratio": _fraction(irrelevant, retrieved_total),
        "source_local_success": _fraction(source_local_hits, source_local_total),
        "cross_page_evidence_recovery": _fraction(cross_page_hits, cross_page_total),
    }


def _matched_rule_for_query(
    state: KnowledgeState,
    golden: dict[str, Any],
    query: dict[str, Any],
    local_executable: list[Any] | None = None,
) -> tuple[Any | None, list[Any]]:
    expected = _expected_rules(state, golden, query)
    executable = [rule for rule in expected if getattr(rule, "executable", False)]
    if executable:
        return executable[0], expected
    if expected:
        return expected[0], expected
    # Query-local fallback (wiring productivo): si la ingesta no compiló la
    # regla, la consulta la ensambla desde la evidencia del estado.
    if local_executable:
        return local_executable[0], [local_executable[0]]
    return None, expected


def _local_executable_rules(state: KnowledgeState) -> list[Any]:
    items = _unit_items(state)
    if not items:
        return []
    try:
        compilation = compile_query_local_rules(
            items, document_id=str(state.document.id)
        )
    except Exception:  # noqa: BLE001 — métrica fail-soft
        return []
    return [rule for rule in compilation.rules if getattr(rule, "executable", False)]


def premise_pipeline_metrics(state: KnowledgeState, golden: dict[str, Any]) -> dict[str, Any]:
    """Métricas reales de premisas: retrieval, query-local y DerivedClaim."""
    items = _unit_items(state)
    corpus = "\n".join(item.content for item in items)
    lowered = corpus.lower()
    executable_queries = [
        query for query in golden.get("queries") or [] if query.get("executable")
    ]
    if not executable_queries:
        return {
            "premise_retrieval_recall": None,
            "premise_exact_hit_rate": None,
            "premise_lexical_hit_rate": None,
            "premise_source_local_hit_rate": None,
            "premise_closure_success_rate": None,
            "query_local_compilation_success_rate": None,
            "executable_rule_recovery_rate": None,
            "derived_claim_rate": None,
        }
    required_total = 0
    satisfied_total = 0
    exact_hits = 0
    lexical_hits = 0
    compile_hits = 0
    recovery_hits = 0
    derived_hits = 0
    local_executable = _local_executable_rules(state)
    for query in executable_queries:
        objects = [
            item
            for item in golden.get("objects") or []
            if str(item.get("id")) in {str(oid) for oid in query.get("objects") or []}
        ]
        for item in objects:
            for premise in item.get("required_premises") or []:
                required_total += 1
                if premise_satisfied(str(premise), state, item):
                    satisfied_total += 1
        if any(symbol in corpus for symbol in _SYMBOLS):
            exact_hits += 1
        if any(term in lowered for term in _ONTOLOGY_TERMS):
            lexical_hits += 1
        if local_executable:
            compile_hits += 1
            recovery_hits += 1
            grounded = reason_over_evidence(
                question=str(query.get("question") or ""),
                evidence_items=items,
                canonical_rules=local_executable,
            )
            if any(
                getattr(claim, "deterministic", False)
                and getattr(claim, "supported", False)
                for claim in grounded.derivations.claims
            ):
                derived_hits += 1
    count = len(executable_queries)
    return {
        "premise_retrieval_recall": _fraction(satisfied_total, required_total),
        "premise_exact_hit_rate": _fraction(exact_hits, count),
        "premise_lexical_hit_rate": _fraction(lexical_hits, count),
        "premise_source_local_hit_rate": _fraction(exact_hits, count),
        "premise_closure_success_rate": _fraction(satisfied_total, required_total),
        "query_local_compilation_success_rate": _fraction(compile_hits, count),
        "executable_rule_recovery_rate": _fraction(recovery_hits, count),
        "derived_claim_rate": _fraction(derived_hits, count),
    }


def decision_metrics(state: KnowledgeState, golden: dict[str, Any]) -> dict[str, Any]:
    queries = list(golden.get("queries") or [])
    local_executable = _local_executable_rules(state)
    counts = Counter()
    answerable_with_evidence = 0
    answerable = 0
    false_abstention = 0
    hallucination = 0
    executable_total = 0
    deterministic_total = 0
    executable_queries: list[dict[str, Any]] = []
    for query in queries:
        if query.get("answerable"):
            answerable += 1
        rule, expected = _matched_rule_for_query(state, golden, query, local_executable)
        expected_status = query.get("expected_status")
        grounded = None
        envelope = None
        claim_deterministic = False
        actual_status: str | None = None
        if query.get("executable"):
            executable_total += 1
            executable_queries.append(query)
            if rule is None:
                counts["AbstainedIncorrectly"] += 1
                false_abstention += 1
                continue
            if expected:
                answerable_with_evidence += 1
            evaluation = evaluate_rule(rule, query.get("values") or {})
            actual_status = str(evaluation.status)
            grounded = reason_over_evidence(
                question=str(query.get("question") or ""),
                evidence_items=[],
                canonical_rules=[rule],
            )
            envelope = build_decision_envelope(grounded)
            claim_deterministic = any(
                getattr(claim, "deterministic", False)
                and getattr(claim, "supported", False)
                for claim in grounded.derivations.claims
            )
            if envelope is not None and envelope.authoritative:
                deterministic_total += 1
        else:
            # No ejecutable: answerability = evidencia golden recuperada.
            evidence_match = any(
                best_match(
                    _golden_object(golden, object_id) or {},
                    state.haystacks_for(
                        str(
                            (_golden_object(golden, object_id) or {}).get(
                                "semantic_type"
                            )
                        )
                    ),
                ).matched
                for object_id in query.get("objects") or []
            )
            if evidence_match:
                answerable_with_evidence += 1
                counts["Correct"] += 1
            elif query.get("answerable"):
                counts["AbstainedIncorrectly"] += 1
                false_abstention += 1
            else:
                counts["AbstainedCorrectly"] += 1
            continue
        derived = claim_deterministic or actual_status in _DERIVED_STATUSES
        unsupported = derived and not expected
        if unsupported:
            hallucination += 1
            counts["UnsupportedHallucination"] += 1
        elif expected_status is not None:
            if actual_status == expected_status:
                counts["Correct"] += 1
            elif actual_status in _DERIVED_STATUSES:
                counts["Incorrect"] += 1
            else:
                counts["AbstainedIncorrectly"] += 1
                false_abstention += 1
        else:
            if derived:
                counts["Correct"] += 1
            else:
                counts["AbstainedIncorrectly"] += 1
                false_abstention += 1
    total_answers = sum(counts.values())
    return {
        "queries_total": len(queries),
        "answerable_with_evidence_rate": _fraction(answerable_with_evidence, answerable),
        "false_abstention_rate": _fraction(false_abstention, answerable),
        "unsupported_hallucination_rate": _fraction(hallucination, len(queries)),
        "deterministic_decision_rate": _fraction(deterministic_total, executable_total),
        "executable_queries": executable_total,
        "answer_counts": dict(counts),
        "answer_accuracy": _fraction(
            counts["Correct"],
            counts["Correct"] + counts["Incorrect"] + counts["UnsupportedHallucination"],
        ),
        "correct_rate": _fraction(counts["Correct"], total_answers),
        "_executable_query_ids": [str(q.get("id")) for q in executable_queries],
    }


def consistency_metrics(
    state: KnowledgeState,
    golden: dict[str, Any],
    *,
    runs: int = 100,
) -> dict[str, Any]:
    rules = list(state.rules)
    local_executable = _local_executable_rules(state)
    if not rules and not local_executable:
        return {"runs_per_query": runs, "consistency_rate": None, "queries": 0}
    stable_queries = 0
    total_queries = 0
    for query in golden.get("queries") or []:
        if not query.get("executable"):
            continue
        rule, expected = _matched_rule_for_query(state, golden, query, local_executable)
        if rule is None:
            continue
        total_queries += 1
        signatures: set[tuple[Any, ...]] = set()
        candidates = rules or [rule]
        for run in range(runs):
            shuffled = list(candidates)
            # Reproducibilidad determinista, no criptografía.
            random.Random(run).shuffle(shuffled)  # noqa: S311
            grounded = reason_over_evidence(
                question=str(query.get("question") or ""),
                evidence_items=[],
                canonical_rules=shuffled,
            )
            envelope = build_decision_envelope(grounded)
            claims = tuple(
                sorted(
                    f"{getattr(claim, 'operation', '')}:{getattr(claim, 'result', '')}"
                    for claim in grounded.derivations.claims
                    if getattr(claim, "deterministic", False)
                )
            )
            signatures.add(
                (
                    grounded.answerability,
                    envelope.normalized_result if envelope is not None else None,
                    claims,
                )
            )
        if len(signatures) == 1:
            stable_queries += 1
    return {
        "runs_per_query": runs,
        "queries": total_queries,
        "consistency_rate": _fraction(stable_queries, total_queries),
    }


async def runtime_metrics(
    state: KnowledgeState,
    golden: dict[str, Any],
    *,
    consistency_runs: int = 100,
) -> dict[str, Any]:
    retrieval = await retrieval_metrics(state, golden)
    retrieval.update(premise_pipeline_metrics(state, golden))
    decision = decision_metrics(state, golden)
    consistency = consistency_metrics(state, golden, runs=consistency_runs)
    return {
        "retrieval": retrieval,
        "decision": decision,
        "consistency": consistency,
    }


__all__ = [
    "consistency_metrics",
    "decision_metrics",
    "retrieval_metrics",
    "runtime_metrics",
]
