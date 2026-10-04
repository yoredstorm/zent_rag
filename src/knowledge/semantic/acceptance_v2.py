# =============================================================================
# Retrieval Acceptance V2 — ¿apareció el CONOCIMIENTO requerido? (§59-60)
# =============================================================================
# La acceptance clásica mide "¿apareció el chunk esperado?". V2 mide:
#
#   definition_recall, rule_recall, exception_recall, symbol_recall,
#   dependency_recall, evidence_recall, semantic_coverage, orphans.
#
# Los probes se derivan del Semantic Fabric (nodos de alto impacto y sus
# dependencias), no solo del enrichment. Determinista y acotado.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.knowledge.acceptance.contracts import probe_id_for

KNOWLEDGE_ACCEPTANCE_VERSION = "knowledge-acceptance-v2"

#: Nodo del fabric -> tipo de probe y prefijo de query.
_PROBE_BY_NODE: dict[str, tuple[str, str]] = {
    "Definition": ("knowledge_definition", "definition of"),
    "Rule": ("knowledge_rule", "rule"),
    "Exception": ("knowledge_exception", "exception"),
    "Symbol": ("knowledge_symbol", "symbol"),
    "Condition": ("knowledge_condition", "condition"),
    "Procedure": ("knowledge_procedure", "procedure"),
    "Claim": ("knowledge_claim", "claim"),
}

#: Tipos de nodo que cuentan para semantic_coverage.
_COVERAGE_TYPES: tuple[str, ...] = tuple(_PROBE_BY_NODE)

#: Relaciones que generan probes de dependencia (el target debe aparecer).
_DEPENDENCY_EDGES: tuple[str, ...] = (
    "DEPENDS_ON",
    "HAS_EXCEPTION",
    "HAS_CONDITION",
)

_MAX_PER_TYPE = 6


def build_knowledge_probes(
    *,
    document,
    nodes: list[dict],
    edges: list[dict],
    max_probes: int = 24,
) -> tuple[list[dict], dict]:
    """Probes V2 desde el fabric: nodos por tipo + dependencias.

    Devuelve (probes, stats). Cada probe conserva el nodo esperado (block id)
    para poder evaluar "¿apareció el conocimiento?" y no solo el chunk.
    """
    node_by_id = {str(node.get("id")): node for node in nodes or ()}
    candidates: dict[str, list[dict]] = {}
    for node in nodes or ():
        node_type = str(node.get("node_type") or "")
        mapping = _PROBE_BY_NODE.get(node_type)
        if mapping is None:
            continue
        label = str(node.get("label") or "").strip()
        if not label:
            continue
        if not (node.get("block_ids") or ()):
            continue
        candidates.setdefault(node_type, []).append(node)

    dependency_probes: list[dict] = []
    for edge in edges or ():
        if str(edge.get("relation_type") or "") not in _DEPENDENCY_EDGES:
            continue
        target = node_by_id.get(str(edge.get("object_id") or ""))
        source = node_by_id.get(str(edge.get("subject_id") or ""))
        if target is None or source is None:
            continue
        label = str(target.get("label") or "").strip()
        if not label or not (target.get("block_ids") or ()):
            continue
        dependency_probes.append(
            {
                "node": target,
                "dependency_of": str(source.get("label") or "")[:160],
                "relation": str(edge.get("relation_type") or ""),
            }
        )

    probes: list[dict] = []
    by_type: dict[str, int] = {}
    total_candidates = sum(len(items) for items in candidates.values())

    def add(node: dict, query_type: str, query: str, metadata: dict) -> None:
        if len(probes) >= max_probes:
            return
        if by_type.get(query_type, 0) >= _MAX_PER_TYPE:
            return
        by_type[query_type] = by_type.get(query_type, 0) + 1
        block_ids = [str(value) for value in (node.get("block_ids") or ())]
        probes.append(
            {
                "probe_id": probe_id_for(document.id, query, query_type),
                "organization_id": document.organization_id,
                "document_id": document.id,
                "workspace_id": document.workspace_id,
                "source_id": document.source_id,
                "query": query[:200],
                "query_type": query_type,
                "semantic_unit_id": None,
                "expected_document_id": str(document.id),
                "expected_section_id": None,
                "expected_unit_id": block_ids[0] if block_ids else None,
                "expected_entity_ids": (str(node.get("id") or ""),),
                "generated_by": "semantic_fabric",
                "generator_version": KNOWLEDGE_ACCEPTANCE_VERSION,
                "metadata": {
                    "node_id": str(node.get("id") or ""),
                    "node_type": str(node.get("node_type") or ""),
                    "node_label": str(node.get("label") or "")[:160],
                    **metadata,
                },
            }
        )

    # Round-robin por tipo para no monopolizar con un solo kind.
    ordered_types = sorted(candidates)
    cursor = 0
    while len(probes) < max_probes and any(
        cursor < len(candidates[node_type]) for node_type in ordered_types
    ):
        for node_type in ordered_types:
            items = candidates[node_type]
            if cursor >= len(items):
                continue
            node = items[cursor]
            query_type, prefix = _PROBE_BY_NODE[node_type]
            add(
                node,
                query_type,
                f"{prefix} {node.get('label')}".strip(),
                {},
            )
        cursor += 1

    for dependency in dependency_probes:
        add(
            dependency["node"],
            "knowledge_dependency",
            f"dependency {dependency['node'].get('label')}".strip(),
            {
                "dependency_of": dependency["dependency_of"],
                "relation": dependency["relation"],
            },
        )

    probed_types = {
        probe["metadata"]["node_type"] for probe in probes if probe["metadata"]
    }
    stats = {
        "version": KNOWLEDGE_ACCEPTANCE_VERSION,
        "candidates": total_candidates,
        "probed": len(probes),
        "orphans": max(0, total_candidates - len(probes)),
        "by_type": by_type,
        "dependencies": len(dependency_probes),
        "coverage_types": sorted(probed_types & set(_COVERAGE_TYPES)),
    }
    return probes, stats


def evaluate_knowledge_acceptance(
    outcomes: list | tuple,
    *,
    stats: dict | None = None,
) -> dict:
    """Métricas V2 desde los outcomes reales de los probes."""
    by_type: dict[str, dict[str, int]] = {}
    passed_total = 0
    total = 0
    for outcome in outcomes or ():
        if isinstance(outcome, dict):
            query_type = str(outcome.get("query_type") or "")
            passed = bool(outcome.get("passed"))
        else:
            query_type = str(getattr(outcome, "query_type", "") or "")
            passed = bool(getattr(outcome, "passed", False))
        bucket = by_type.setdefault(query_type, {"passed": 0, "total": 0})
        bucket["total"] += 1
        total += 1
        if passed:
            bucket["passed"] += 1
            passed_total += 1

    def recall(query_type: str) -> float | None:
        bucket = by_type.get(query_type)
        if not bucket or bucket["total"] == 0:
            return None
        return round(bucket["passed"] / bucket["total"], 4)

    probed_types = {
        query_type.removeprefix("knowledge_")
        for query_type in by_type
        if query_type.startswith("knowledge_")
    }
    covered_types = {
        query_type.removeprefix("knowledge_")
        for query_type, bucket in by_type.items()
        if query_type.startswith("knowledge_") and bucket["passed"] > 0
    }
    semantic_coverage = (
        round(len(covered_types) / len(probed_types), 4) if probed_types else None
    )
    return {
        "version": KNOWLEDGE_ACCEPTANCE_VERSION,
        "probes": total,
        "passed": passed_total,
        "evidence_recall": round(passed_total / total, 4) if total else None,
        "definition_recall": recall("knowledge_definition"),
        "rule_recall": recall("knowledge_rule"),
        "exception_recall": recall("knowledge_exception"),
        "symbol_recall": recall("knowledge_symbol"),
        "dependency_recall": recall("knowledge_dependency"),
        "semantic_coverage": semantic_coverage,
        "by_type": {
            query_type: dict(bucket) for query_type, bucket in sorted(by_type.items())
        },
        "orphans": int((stats or {}).get("orphans") or 0),
        "candidates": int((stats or {}).get("candidates") or 0),
        "probed": int((stats or {}).get("probed") or total),
        "coverage_types": sorted(covered_types),
    }


def probe_payloads_to_objects(payloads: list[dict]) -> list:
    """Dicts de build_knowledge_probes -> RetrievalProbe (contrato acceptance)."""
    from src.knowledge.acceptance.contracts import RetrievalProbe

    probes = []
    for payload in payloads:
        try:
            probes.append(
                RetrievalProbe(
                    probe_id=str(payload.get("probe_id") or ""),
                    organization_id=UUID(str(payload["organization_id"])),
                    document_id=UUID(str(payload["document_id"])),
                    workspace_id=(
                        UUID(str(payload["workspace_id"]))
                        if payload.get("workspace_id")
                        else None
                    ),
                    source_id=(
                        UUID(str(payload["source_id"]))
                        if payload.get("source_id")
                        else None
                    ),
                    query=str(payload.get("query") or ""),
                    query_type=str(payload.get("query_type") or "semantic_paraphrase"),
                    expected_document_id=str(payload.get("expected_document_id") or ""),
                    expected_section_id=payload.get("expected_section_id"),
                    expected_unit_id=payload.get("expected_unit_id"),
                    expected_entity_ids=tuple(
                        payload.get("expected_entity_ids") or ()
                    ),
                    generated_by=str(payload.get("generated_by") or "semantic_fabric"),
                    generator_version=str(payload.get("generator_version") or ""),
                    policy_version=str(payload.get("policy_version") or ""),
                    metadata=dict(payload.get("metadata") or {}),
                )
            )
        except Exception as exc:  # noqa: BLE001 — un probe inválido no frena
            try:
                from src.infrastructure.observability.logging_config import (
                    get_logger,
                )

                get_logger(__name__).debug(
                    "knowledge probe payload skipped", error=str(exc)[:160]
                )
            except Exception:  # noqa: BLE001
                pass
            continue
    return probes


__all__ = [
    "KNOWLEDGE_ACCEPTANCE_VERSION",
    "build_knowledge_probes",
    "evaluate_knowledge_acceptance",
    "probe_payloads_to_objects",
]
