# =============================================================================
# Graph-based Reasoning — bounded lineage traversal (Phase 29D)
# =============================================================================
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GraphTraversalResult:
    paths: list[list[dict[str, Any]]] = field(default_factory=list)
    nodes_visited: int = 0
    truncated: bool = False
    explanation: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "paths": self.paths,
            "nodes_visited": self.nodes_visited,
            "truncated": self.truncated,
            "explanation": list(self.explanation),
        }


class GraphReasoningEngine:
    """Traversal acotado sobre aristas tipo lineage (ECG)."""

    def traverse(
        self,
        start_node: str,
        edges: list[dict[str, Any]],
        *,
        max_depth: int = 4,
        max_nodes: int = 50,
        allowed_edge_types: set[str] | list[str] | None = None,
    ) -> GraphTraversalResult:
        allowed = set(allowed_edge_types) if allowed_edge_types else None
        adj: dict[str, list[dict[str, Any]]] = {}
        for e in edges:
            rel = str(e.get("relation") or e.get("edge_type") or "")
            if allowed is not None and rel not in allowed:
                continue
            src = str(e.get("upstream_id") or e.get("from") or e.get("source") or "")
            dst = str(e.get("downstream_id") or e.get("to") or e.get("target") or "")
            if not src or not dst:
                continue
            adj.setdefault(src, []).append(
                {
                    "from": src,
                    "to": dst,
                    "relation": rel,
                    "upstream_type": e.get("upstream_type"),
                    "downstream_type": e.get("downstream_type"),
                }
            )

        result = GraphTraversalResult()
        queue: deque[tuple[str, list[dict[str, Any]], int]] = deque()
        queue.append((start_node, [], 0))
        seen_nodes = {start_node}
        result.nodes_visited = 1

        while queue:
            node, path, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for edge in adj.get(node, []):
                nxt = edge["to"]
                new_path = path + [edge]
                result.paths.append(new_path)
                expl = " → ".join(
                    [start_node]
                    + [f"{p['relation']} {p['to']}" for p in new_path]
                )
                # Prefer ASCII explanation without arrow token for docs — keep path join clear
                result.explanation.append(
                    " | ".join(
                        [start_node]
                        + [f"{p['relation']} {p['to']}" for p in new_path]
                    )
                )
                if nxt in seen_nodes:
                    continue
                if result.nodes_visited >= max_nodes:
                    result.truncated = True
                    return result
                seen_nodes.add(nxt)
                result.nodes_visited += 1
                queue.append((nxt, new_path, depth + 1))

        # Deduplicate explanations while preserving order
        seen_e: set[str] = set()
        unique_expl: list[str] = []
        for e in result.explanation:
            if e not in seen_e:
                seen_e.add(e)
                unique_expl.append(e)
        result.explanation = unique_expl
        return result

    def path_explanation(self, path: list[dict[str, Any]], *, start: str) -> str:
        parts = [start]
        for p in path:
            parts.append(f"{p.get('relation')} {p.get('to')}")
        return " | ".join(parts)
