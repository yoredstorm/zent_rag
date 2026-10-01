// =============================================================================
// KnowledgeGraphLive — solo lo relevante de la sesión
// =============================================================================
// Nunca los 10.000 nodos: conceptos de la sesión + conexiones relevantes con
// el conocimiento existente. Los nodos nuevos aparecen con una animación
// sutil; las conexiones se dibujan cuando el evento real ocurre.
// =============================================================================
import { useEffect, useMemo, useRef, useState } from "react";

import type { SessionGraph, SessionGraphNode } from "../../lib/knowledgeSessions";

const KNOWN_ACCENT = "var(--zent-info, #75aaf6)";
const SESSION_ACCENT = "var(--zent-accent, #34d3a6)";

interface PlacedNode extends SessionGraphNode {
  x: number;
  y: number;
  connections: number;
}

function truncate(value: string, max = 16): string {
  const text = (value || "").trim();
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

export function KnowledgeGraphLive({
  graph,
  active,
  height = 360,
}: {
  graph: SessionGraph | null;
  active: boolean;
  height?: number;
}) {
  const previousIdsRef = useRef<Set<string>>(new Set());
  const [newIds, setNewIds] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<string | null>(null);

  const layout = useMemo(() => {
    const nodes = graph?.nodes ?? [];
    const edges = graph?.edges ?? [];
    if (nodes.length === 0) return { nodes: [], edges: [] };

    const degree = new Map<string, number>();
    for (const edge of edges) {
      degree.set(edge.subject, (degree.get(edge.subject) ?? 0) + 1);
      degree.set(edge.object, (degree.get(edge.object) ?? 0) + 1);
    }

    const sessionNodes = nodes.filter((node) => !node.known);
    const knownNodes = nodes.filter((node) => node.known);
    const cx = 50;
    const cy = 30;

    const placed = new Map<string, PlacedNode>();
    const placeRing = (
      list: SessionGraphNode[],
      radius: number,
      phase: number
    ) => {
      const total = Math.max(1, list.length);
      list.forEach((node, index) => {
        const angle = phase + (index / total) * Math.PI * 2;
        placed.set(node.id, {
          ...node,
          x: cx + Math.cos(angle) * radius,
          y: cy + Math.sin(angle) * radius * 0.62,
          connections: degree.get(node.id) ?? 0,
        });
      });
    };

    if (sessionNodes.length === 0) {
      placeRing(knownNodes, 22, -Math.PI / 2);
    } else {
      placeRing(sessionNodes, 15, -Math.PI / 2);
      // Los vecinos conocidos se acomodan junto a su nodo de sesión.
      const neighbors = new Map<string, number[]>();
      for (const edge of edges) {
        const subject = placed.get(edge.subject);
        const object = placed.get(edge.object);
        if (subject && object) {
          if (!subject.known && object.known) {
            neighbors.set(object.id, [
              ...(neighbors.get(object.id) ?? []),
              Math.atan2(subject.y - cy, subject.x - cx),
            ]);
          }
          if (subject.known && !object.known) {
            neighbors.set(subject.id, [
              ...(neighbors.get(subject.id) ?? []),
              Math.atan2(object.y - cy, object.x - cx),
            ]);
          }
        }
      }
      knownNodes.forEach((node, index) => {
        const angles = neighbors.get(node.id);
        const angle = angles?.length
          ? angles.reduce((a, b) => a + b, 0) / angles.length
          : -Math.PI / 2 + (index / Math.max(1, knownNodes.length)) * Math.PI * 2;
        placed.set(node.id, {
          ...node,
          x: cx + Math.cos(angle) * 26,
          y: cy + Math.sin(angle) * 26 * 0.62,
          connections: degree.get(node.id) ?? 0,
        });
      });
    }

    const placedNodes = Array.from(placed.values());
    const validEdges = edges.filter(
      (edge) => placed.has(edge.subject) && placed.has(edge.object)
    );
    return { nodes: placedNodes, edges: validEdges };
  }, [graph]);

  // Nodos vistos: solo los nuevos de la última actualización se animan.
  useEffect(() => {
    const ids = new Set(layout.nodes.map((node) => node.id));
    const fresh = new Set<string>();
    for (const id of ids) {
      if (!previousIdsRef.current.has(id)) fresh.add(id);
    }
    previousIdsRef.current = ids;
    setNewIds(fresh);
  }, [layout.nodes]);

  const selectedNode = layout.nodes.find((node) => node.id === selected) ?? null;

  if (!graph || (graph.nodes.length === 0 && !active)) {
    return (
      <div className="ks-graph-empty" data-testid="knowledge-graph-empty">
        <p className="text-[13px] text-faint">
          El grafo aparecerá cuando ZENT reconozca las primeras entidades de esta
          sesión.
        </p>
      </div>
    );
  }

  return (
    <div className="ks-graph" data-testid="knowledge-graph">
      <svg
        viewBox="0 0 100 60"
        style={{ height, width: "100%" }}
        role="group"
        aria-label={`Grafo de la sesión: ${graph.nodes.length} nodos y ${graph.edges.length} relaciones`}
      >
        <g className="ks-edges">
          {layout.edges.map((edge) => {
            const subject = layout.nodes.find((node) => node.id === edge.subject);
            const object = layout.nodes.find((node) => node.id === edge.object);
            if (!subject || !object) return null;
            return (
              <line
                key={edge.id}
                className="ks-edge"
                x1={subject.x}
                y1={subject.y}
                x2={object.x}
                y2={object.y}
              >
                <title>{`${subject.name} —${edge.predicate}→ ${object.name}`}</title>
              </line>
            );
          })}
        </g>
        <g className="ks-nodes">
          {layout.nodes.map((node) => (
            <g
              key={node.id}
              className={`ks-node ${node.known ? "is-known" : "is-session"} ${
                selected === node.id ? "is-selected" : ""
              }`}
              transform={`translate(${node.x} ${node.y})`}
              onClick={() => setSelected(selected === node.id ? null : node.id)}
              role="button"
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  setSelected(selected === node.id ? null : node.id);
                }
              }}
            >
              <circle
                className={newIds.has(node.id) ? "ks-node-new" : ""}
                r={node.known ? 1.7 : 2.5}
                fill={node.known ? "var(--zent-surface, #0f141b)" : SESSION_ACCENT}
                stroke={node.known ? KNOWN_ACCENT : SESSION_ACCENT}
                strokeWidth={node.known ? 0.45 : 0}
              />
              {!node.known && (
                <text className="ks-node-label" y={4.4} textAnchor="middle">
                  {truncate(node.name)}
                </text>
              )}
              <title>
                {`${node.name}${node.known ? " (ya existía en ZENT)" : " (nuevo en esta sesión)"} · ${node.connections} conexiones`}
              </title>
            </g>
          ))}
        </g>
      </svg>
      <footer className="ks-graph-foot">
        <span className="ks-legend">
          <span className="ks-legend-dot is-session" /> nuevo en la sesión
        </span>
        <span className="ks-legend">
          <span className="ks-legend-dot is-known" /> ya existía en ZENT
        </span>
        <span className="text-faint text-[11px]">
          {graph.nodes.length} nodos · {graph.edges.length} relaciones
        </span>
      </footer>
      {selectedNode && (
        <div className="ks-graph-detail" data-testid="graph-node-detail">
          <strong className="text-text">{selectedNode.name}</strong>
          <span className="text-muted">
            {selectedNode.known ? "Ya existía en ZENT" : "Descubierto en esta sesión"}
            {" · "}
            {selectedNode.connections} conexiones
          </span>
        </div>
      )}
    </div>
  );
}

export default KnowledgeGraphLive;
