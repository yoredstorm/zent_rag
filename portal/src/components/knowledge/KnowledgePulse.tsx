// =============================================================================
// Knowledge Pulse — actividad cognitiva real
// =============================================================================
// Cada nodo es un objeto canónico real; cada línea, una relación real; cada
// pulso, un evento real del feed. Sin partículas decorativas: si no pasa nada,
// el pulso está quieto. El grafo se limita a un vecindario (<= 42 nodos).
// =============================================================================
import { useEffect, useMemo, useRef, useState } from "react";
import { useReducedMotion } from "motion/react";
import { ArrowRight, Graph } from "@phosphor-icons/react";
import { cn, Skeleton } from "../ui";
import type { KnowledgeGraphPayload } from "../../lib/knowledgeModel";
import { objectTypeLabel, statusTone } from "../../lib/knowledgeModel";
import type { KnowledgeFeedItem } from "../../lib/knowledgeActivity";
import { confidenceTone } from "../../lib/knowledgeModel";

const MAX_NODES = 42;
const GOLDEN_ANGLE = 2.399963229728653;

interface PlacedNode {
  id: string;
  name: string;
  type: string;
  status: string;
  domain: string | null;
  confidence: number | null;
  evidence_count: number;
  degree: number;
  x: number;
  y: number;
  r: number;
}

function placeNodes(payload: KnowledgeGraphPayload): PlacedNode[] {
  const nodes = [...payload.nodes]
    .sort((a, b) => b.degree - a.degree)
    .slice(0, MAX_NODES);
  const total = Math.max(1, nodes.length);
  return nodes.map((node, index) => {
    const t = index / total;
    const angle = index * GOLDEN_ANGLE - Math.PI / 2;
    const radius = 6 + Math.sqrt(t) * 36;
    return {
      ...node,
      x: 50 + Math.cos(angle) * radius,
      y: 31 + Math.sin(angle) * radius * 0.62,
      r: 1.1 + Math.min(2.6, Math.sqrt(node.degree + 1) * 0.5),
    };
  });
}

function eventNodeId(event: KnowledgeFeedItem, nodes: PlacedNode[]): string | null {
  const title = event.title.toLowerCase();
  let match: PlacedNode | null = null;
  for (const node of nodes) {
    const name = node.name.trim().toLowerCase();
    if (name.length < 4) continue;
    if (title.includes(name) && (!match || name.length > match.name.length)) {
      match = node;
    }
  }
  return match?.id ?? null;
}

/** Confianza cuando existe; si no, el estado real manda el color. */
function nodeTone(node: PlacedNode): string {
  return node.confidence != null ? confidenceTone(node.confidence) : statusTone(node.status);
}

export function KnowledgePulse({
  graph,
  events,
  loading = false,
  onSelect,
}: {
  graph: KnowledgeGraphPayload | null;
  events: KnowledgeFeedItem[];
  loading?: boolean;
  onSelect?: (nodeId: string) => void;
}) {
  const reduceMotion = useReducedMotion();
  const previousIds = useRef<Set<string>>(new Set());
  const [newIds, setNewIds] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<string | null>(null);

  const nodes = useMemo(() => (graph ? placeNodes(graph) : []), [graph]);
  const nodeById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const edges = useMemo(() => {
    if (!graph) return [];
    return graph.edges.filter(
      (edge) => nodeById.has(edge.source) && nodeById.has(edge.target)
    );
  }, [graph, nodeById]);

  useEffect(() => {
    const ids = new Set(nodes.map((node) => node.id));
    if (!reduceMotion) {
      const fresh = new Set<string>();
      for (const id of ids) if (!previousIds.current.has(id)) fresh.add(id);
      setNewIds(fresh);
    }
    previousIds.current = ids;
  }, [nodes, reduceMotion]);

  const pulses = useMemo(() => {
    return events
      .filter((event) => event.kind !== "object")
      .slice(0, 8)
      .map((event) => ({
        event,
        nodeId: eventNodeId(event, nodes),
      }));
  }, [events, nodes]);

  const selectedNode = selected ? nodeById.get(selected) ?? null : null;
  const selectedEvents = selectedNode
    ? events.filter((event) =>
        event.title.toLowerCase().includes(selectedNode.name.trim().toLowerCase())
      )
    : [];

  if (loading && !graph) {
    return <Skeleton className="h-[320px] rounded-lg" />;
  }

  const empty = nodes.length === 0;

  return (
    <section className="panel kh-pulse" data-testid="knowledge-pulse">
      <header className="kh-pulse-head">
        <div className="min-w-0">
          <p className="eyebrow flex items-center gap-2">
            <span className="kh-live-dot" aria-hidden />
            Knowledge Pulse
          </p>
          <h2 className="text-h3 mt-1">Actividad cognitiva</h2>
        </div>
        <span className="text-[11px] text-faint">
          {empty
            ? "Sin actividad"
            : `${nodes.length} nodos · ${edges.length} relaciones visibles`}
        </span>
      </header>

      {empty ? (
        <div className="kh-pulse-empty" data-testid="knowledge-pulse-empty">
          <div className="kh-pulse-empty-rings" aria-hidden>
            <span />
            <span />
            <span />
          </div>
          <p className="max-w-[36ch] text-center text-[13px] leading-relaxed text-faint">
            El pulso aparecerá cuando ZENT reconozca las primeras entidades y
            relaciones de tu negocio.
          </p>
        </div>
      ) : (
        <>
          <div className="kh-pulse-canvas">
            <svg
              viewBox="0 0 100 62"
              className="kh-pulse-svg"
              role="group"
              aria-label={`Knowledge Pulse: ${nodes.length} nodos y ${edges.length} relaciones reales`}
            >
              <g className="kh-pulse-core" aria-hidden>
                <circle cx={50} cy={31} r={3.2} className="kh-core-halo" />
                <circle cx={50} cy={31} r={1.1} className="kh-core-dot" />
              </g>
              <g>
                {edges.map((edge) => {
                  const from = nodeById.get(edge.source);
                  const to = nodeById.get(edge.target);
                  if (!from || !to) return null;
                  return (
                    <line
                      key={edge.id}
                      className="kh-edge"
                      x1={from.x}
                      y1={from.y}
                      x2={to.x}
                      y2={to.y}
                      style={{
                        opacity: 0.12 + Math.max(0, Math.min(1, edge.confidence)) * 0.3,
                      }}
                    >
                      <title>
                        {`${from.name} —${edge.predicate}→ ${to.name}`}
                      </title>
                    </line>
                  );
                })}
              </g>
              {pulses.map(({ event, nodeId }) => {
                const target = nodeId ? nodeById.get(nodeId) : null;
                const x = target?.x ?? 50;
                const y = target?.y ?? 31;
                return (
                  <circle
                    key={event.id}
                    className={cn(
                      "kh-pulse-ring",
                      event.severity === "warning" || event.severity === "error"
                        ? "is-warn"
                        : ""
                    )}
                    cx={x}
                    cy={y}
                    r={target ? target.r + 1 : 2}
                    aria-hidden
                  />
                );
              })}
              <g>
                {nodes.map((node) => {
                  const nodeEvent = events.find((event) =>
                    event.title.toLowerCase().includes(node.name.trim().toLowerCase())
                  );
                  return (
                    <g
                      key={node.id}
                      className={cn(
                        "kh-node",
                        newIds.has(node.id) && "kh-node-new",
                        selected === node.id && "is-selected"
                      )}
                      transform={`translate(${node.x} ${node.y})`}
                      role="button"
                      tabIndex={0}
                      aria-label={`${node.name}, ${objectTypeLabel(node.type)}, ${node.degree} conexiones`}
                      onClick={() =>
                        setSelected(selected === node.id ? null : node.id)
                      }
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          setSelected(selected === node.id ? null : node.id);
                        }
                      }}
                    >
                      <circle r={node.r} className={cn("kh-node-dot", nodeTone(node))} />
                      <title>
                        {`${node.name} · ${objectTypeLabel(node.type)} · ${node.degree} conexiones`}
                        {nodeEvent ? ` — ${nodeEvent.title}` : ""}
                      </title>
                    </g>
                  );
                })}
              </g>
            </svg>
          </div>

          {selectedNode ? (
            <div className="kh-pulse-detail" data-testid="knowledge-pulse-detail">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-text">
                  {selectedNode.name}
                </p>
                <p className="mt-0.5 text-[11px] text-muted">
                  {objectTypeLabel(selectedNode.type)}
                  {selectedNode.domain ? ` · ${selectedNode.domain}` : ""} ·{" "}
                  {selectedNode.degree} conexiones · {selectedNode.evidence_count}{" "}
                  evidencias
                </p>
                {selectedEvents[0] && (
                  <p className="mt-1 line-clamp-2 text-[11px] text-faint">
                    {selectedEvents[0].title}
                  </p>
                )}
              </div>
              {onSelect && (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm shrink-0"
                  onClick={() => onSelect(selectedNode.id)}
                >
                  Abrir objeto
                  <ArrowRight size={12} aria-hidden />
                </button>
              )}
            </div>
          ) : (
            <footer className="kh-pulse-foot">
              <span className="flex items-center gap-1.5">
                <Graph size={12} className="text-faint" aria-hidden />
                Cada nodo y línea es un dato real del modelo.
              </span>
              <span className="text-faint">Pasa el cursor o toca un nodo</span>
            </footer>
          )}
        </>
      )}
    </section>
  );
}
