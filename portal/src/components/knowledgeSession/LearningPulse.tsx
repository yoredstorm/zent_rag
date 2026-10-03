// =============================================================================
// LearningPulse — el corazón visual del Live Learning
// =============================================================================
// Núcleo ZENT + nodos reales de la sesión + conexiones reales + pulsos por
// evento. Cada nodo es un objeto canónico; cada línea, una relación; cada
// pulso, un evento durable. Nada decorativo: si no hay evento, no hay pulso.
// =============================================================================
import { useEffect, useMemo, useRef, useState } from "react";
import { useReducedMotion } from "motion/react";
import {
  ArrowsOut,
  Broadcast,
  Graph,
  X,
} from "@phosphor-icons/react";

import type {
  SessionEvent,
  SessionGraph,
  SessionGraphNode,
} from "../../lib/knowledgeSessions";
import { Button } from "../ui/Button";

const MAX_SESSION_NODES = 34;
const MAX_KNOWN_NODES = 18;
const GOLDEN_ANGLE = 2.399963229728653;

interface PlacedNode extends SessionGraphNode {
  x: number;
  y: number;
  connections: number;
}

interface EventPulse {
  id: string;
  x: number;
  y: number;
  radius: number;
  tone: "accent" | "info" | "warn" | "ok";
  label: string;
}

function nodeName(value: unknown): string {
  return String(value ?? "").trim().toLowerCase();
}

function payloadItems(event: SessionEvent): Array<Record<string, unknown>> {
  const data = (event.payload ?? {}) as Record<string, unknown>;
  const items = Array.isArray(data.items)
    ? (data.items as Array<Record<string, unknown>>)
    : [];
  return [data, ...items];
}

function eventNames(event: SessionEvent): string[] {
  const names: string[] = [];
  for (const item of payloadItems(event)) {
    for (const key of ["name", "subject", "object", "object_name", "canonical_name", "merged_alias"]) {
      const value = item[key];
      if (typeof value === "string" && value.trim()) names.push(value.trim());
    }
  }
  return [...new Set(names)];
}

function findNode(
  nodes: PlacedNode[],
  value: string
): PlacedNode | undefined {
  const target = nodeName(value);
  if (!target) return undefined;
  const exact = nodes.find((node) => nodeName(node.name) === target);
  if (exact) return exact;
  if (target.length < 4) return undefined;
  return nodes.find((node) => nodeName(node.name).includes(target));
}

function placeNodes(graph: SessionGraph): PlacedNode[] {
  const degree = new Map<string, number>();
  for (const edge of graph.edges) {
    degree.set(edge.subject, (degree.get(edge.subject) ?? 0) + 1);
    degree.set(edge.object, (degree.get(edge.object) ?? 0) + 1);
  }
  const sessionNodes = graph.nodes
    .filter((node) => !node.known)
    .slice(0, MAX_SESSION_NODES);
  const knownNodes = graph.nodes
    .filter((node) => node.known)
    .slice(0, MAX_KNOWN_NODES);
  const placed: PlacedNode[] = [];

  sessionNodes.forEach((node, index) => {
    const angle = index * GOLDEN_ANGLE - Math.PI / 2;
    placed.push({
      ...node,
      x: 50 + Math.cos(angle) * 27,
      y: 31 + Math.sin(angle) * 27 * 0.62,
      connections: degree.get(node.id) ?? 0,
    });
  });
  knownNodes.forEach((node, index) => {
    const angle = index * GOLDEN_ANGLE + Math.PI / 3;
    placed.push({
      ...node,
      x: 50 + Math.cos(angle) * 13,
      y: 31 + Math.sin(angle) * 13 * 0.62,
      connections: degree.get(node.id) ?? 0,
    });
  });
  return placed;
}

export function LearningPulse({
  graph,
  events,
  active,
  metrics,
}: {
  graph: SessionGraph | null;
  events: SessionEvent[];
  active: boolean;
  metrics: Record<string, number>;
}) {
  const reduceMotion = useReducedMotion();
  const [selected, setSelected] = useState<string | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const previousNodeIds = useRef<Set<string>>(new Set());
  const previousEdgeIds = useRef<Set<string>>(new Set());
  const [newNodeIds, setNewNodeIds] = useState<Set<string>>(new Set());
  const [newEdgeIds, setNewEdgeIds] = useState<Set<string>>(new Set());

  const nodes = useMemo(() => (graph ? placeNodes(graph) : []), [graph]);
  const nodeById = useMemo(
    () => new Map(nodes.map((node) => [node.id, node])),
    [nodes]
  );
  const edges = useMemo(() => {
    if (!graph) return [];
    return graph.edges.filter(
      (edge) => nodeById.has(edge.subject) && nodeById.has(edge.object)
    );
  }, [graph, nodeById]);

  useEffect(() => {
    const ids = new Set(nodes.map((node) => node.id));
    if (!reduceMotion) {
      const fresh = new Set<string>();
      for (const id of ids) if (!previousNodeIds.current.has(id)) fresh.add(id);
      setNewNodeIds(fresh);
    }
    previousNodeIds.current = ids;
  }, [nodes, reduceMotion]);

  useEffect(() => {
    const ids = new Set(edges.map((edge) => edge.id));
    if (!reduceMotion) {
      const fresh = new Set<string>();
      for (const id of ids) if (!previousEdgeIds.current.has(id)) fresh.add(id);
      setNewEdgeIds(fresh);
    }
    previousEdgeIds.current = ids;
  }, [edges, reduceMotion]);

  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFullscreen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fullscreen]);

  const pulses = useMemo<EventPulse[]>(() => {
    const recent = events.slice(-14);
    const result: EventPulse[] = [];
    for (const event of recent) {
      const names = eventNames(event);
      let target: PlacedNode | undefined;
      for (const name of names) {
        target = findNode(nodes, name);
        if (target) break;
      }
      const tone: EventPulse["tone"] =
        event.event_type === "CONFLICT_DETECTED"
          ? "warn"
          : event.event_type === "ENTITY_MATCHED" ||
              event.event_type === "ENTITY_MERGED"
            ? "info"
            : event.event_type === "KNOWLEDGE_READY" ||
                event.event_type === "SOURCE_AVAILABLE"
              ? "ok"
              : "accent";
      result.push({
        id: `pulse-${event.seq}`,
        x: target?.x ?? 50,
        y: target?.y ?? 31,
        radius: target ? Math.max(2, Math.sqrt(target.connections + 1) * 0.9) : 3,
        tone,
        label: event.message,
      });
    }
    return result;
  }, [events, nodes]);

  const selectedNode = selected ? nodeById.get(selected) ?? null : null;
  const selectedEvents = selectedNode
    ? events
        .filter((event) =>
          eventNames(event).some(
            (name) => nodeName(name) === nodeName(selectedNode.name)
          )
        )
        .slice(-2)
    : [];

  const canvas = (
    <>
      <div className="ks-pulse-canvas">
        <svg
          viewBox="0 0 100 62"
          className="ks-pulse-svg"
          role="group"
          aria-label={`Knowledge Pulse: ${nodes.length} nodos y ${edges.length} relaciones reales de esta sesión`}
        >
          <g aria-hidden>
            <circle cx={50} cy={31} r={4.4} className="ks-pulse-core-halo" />
            <circle cx={50} cy={31} r={1.6} className="ks-pulse-core" />
            <text x={50} y={36.6} textAnchor="middle" className="ks-pulse-core-label">
              ZENT
            </text>
          </g>
          <g>
            {edges.map((edge) => {
              const from = nodeById.get(edge.subject);
              const to = nodeById.get(edge.object);
              if (!from || !to) return null;
              return (
                <line
                  key={edge.id}
                  className={`ks-pulse-edge ${newEdgeIds.has(edge.id) ? "is-new" : ""}`}
                  x1={from.x}
                  y1={from.y}
                  x2={to.x}
                  y2={to.y}
                >
                  <title>{edge.predicate}</title>
                </line>
              );
            })}
          </g>
          {pulses.map((pulse) => (
            <circle
              key={pulse.id}
              className={`ks-pulse-ring is-${pulse.tone}`}
              cx={pulse.x}
              cy={pulse.y}
              r={pulse.radius}
              aria-hidden
            >
              <title>{pulse.label}</title>
            </circle>
          ))}
          <g>
            {nodes.map((node) => (
              <g
                key={node.id}
                className={`ks-pulse-node ${node.known ? "is-known" : "is-session"} ${
                  newNodeIds.has(node.id) ? "is-new" : ""
                } ${selected === node.id ? "is-selected" : ""}`}
                transform={`translate(${node.x} ${node.y})`}
                role="button"
                tabIndex={0}
                aria-label={`${node.name}, ${node.known ? "ya conocido" : "nuevo"}, ${node.connections} conexiones`}
                onClick={() => setSelected(selected === node.id ? null : node.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setSelected(selected === node.id ? null : node.id);
                  }
                }}
              >
                <circle
                  r={1.4 + Math.min(2.2, Math.sqrt(node.connections + 1) * 0.5)}
                  className="ks-pulse-node-dot"
                />
                <title>
                  {`${node.name} · ${node.known ? "ya existía en ZENT" : "nuevo en esta sesión"} · ${node.connections} conexiones`}
                </title>
              </g>
            ))}
          </g>
        </svg>
        {nodes.length === 0 && (
          <p className="ks-pulse-empty-copy">
            {active
              ? "El conocimiento aparecerá aquí en tiempo real: cada entidad y cada relación viene de un evento real."
              : "Esta sesión no registró conexiones entre entidades."}
          </p>
        )}
      </div>

      {selectedNode ? (
        <div className="ks-pulse-detail" data-testid="learning-pulse-detail">
          <div className="min-w-0">
            <p className="truncate text-[13px] font-medium text-text">
              {selectedNode.name}
            </p>
            <p className="mt-0.5 text-[11px] text-muted">
              {selectedNode.known ? "Ya existía en ZENT" : "Nuevo en esta sesión"} ·{" "}
              {selectedNode.connections} conexiones
            </p>
            {selectedEvents[0] && (
              <p className="mt-1 line-clamp-2 text-[11px] text-faint">
                {selectedEvents[0].message}
              </p>
            )}
          </div>
          <Button size="sm" variant="ghost" onClick={() => setSelected(null)}>
            Cerrar
          </Button>
        </div>
      ) : (
        <footer className="ks-pulse-foot">
          <span className="ks-legend">
            <span className="ks-legend-dot is-session" /> nuevo en la sesión
          </span>
          <span className="ks-legend">
            <span className="ks-legend-dot is-known" /> ya existía en ZENT
          </span>
          <span className="text-[11px] text-faint">
            {nodes.length} nodos · {edges.length} relaciones
          </span>
        </footer>
      )}
    </>
  );

  return (
    <section
      className={`panel ks-learning-pulse ${fullscreen ? "is-fullscreen" : ""}`}
      data-testid="knowledge-pulse"
    >
      <header className="panel-header">
        <div className="min-w-0">
          <p className="eyebrow flex items-center gap-2">
            <Broadcast size={12} weight="fill" className="text-accent" aria-hidden />
            Knowledge Pulse
          </p>
          <h2 className="text-h3">El conocimiento apareciendo</h2>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-faint">
            {metrics.entities ?? 0} conceptos · {metrics.relationships ?? 0} relaciones
          </span>
          <Button
            size="sm"
            variant="ghost"
            leadingIcon={fullscreen ? X : ArrowsOut}
            onClick={() => setFullscreen((value) => !value)}
          >
            {fullscreen ? "Salir" : "Pantalla completa"}
          </Button>
        </div>
      </header>
      {canvas}
      {fullscreen && (
        <span className="sr-only">
          Vista de pantalla completa del Knowledge Pulse. Escape para salir.
        </span>
      )}
      {nodes.length === 0 && !active && (
        <p className="sr-only">
          <Graph size={12} aria-hidden /> Sin grafo de sesión.
        </p>
      )}
    </section>
  );
}

export default LearningPulse;
