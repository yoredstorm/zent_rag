// =============================================================================
// KnowledgeGraphCanvas — SVG con pan/zoom y selección (FASE 33F)
// =============================================================================
import { MagnifyingGlassMinus, MagnifyingGlassPlus, SquareHalf } from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  type GraphEdge,
  NODE_TYPE_LABELS,
  nodeRadius,
  provenanceColor,
  type PositionedNode,
} from "../../lib/knowledgeGraph";

const VIEW_WIDTH = 960;
const VIEW_HEIGHT = 620;

type Transform = { x: number; y: number; k: number };

export function KnowledgeGraphCanvas({
  nodes,
  edges,
  selectedId,
  visibleIds,
  onSelect,
}: {
  nodes: PositionedNode[];
  edges: GraphEdge[];
  selectedId: string | null;
  visibleIds?: Set<string> | null;
  onSelect: (nodeId: string) => void;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [transform, setTransform] = useState<Transform>({ x: 0, y: 0, k: 1 });
  const dragRef = useRef<{ startX: number; startY: number; tx: number; ty: number } | null>(null);

  const positionById = useMemo(() => {
    const map = new Map<string, PositionedNode>();
    for (const node of nodes) map.set(node.id, node);
    return map;
  }, [nodes]);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      setTransform((current) => {
        const rect = svg.getBoundingClientRect();
        const pointerX = event.clientX - rect.left;
        const pointerY = event.clientY - rect.top;
        const factor = event.deltaY < 0 ? 1.15 : 1 / 1.15;
        const nextK = Math.max(0.35, Math.min(3.5, current.k * factor));
        // Zoom hacia el puntero.
        const wx = (pointerX - current.x) / current.k;
        const wy = (pointerY - current.y) / current.k;
        return { k: nextK, x: pointerX - wx * nextK, y: pointerY - wy * nextK };
      });
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, []);

  const zoomBy = (factor: number) => {
    setTransform((current) => ({
      k: Math.max(0.35, Math.min(3.5, current.k * factor)),
      x: current.x,
      y: current.y,
    }));
  };

  const resetView = () => setTransform({ x: 0, y: 0, k: 1 });

  const labelVisible = (node: PositionedNode, selected: boolean) =>
    node.type === "entity" ||
    node.type === "datasource" ||
    selected ||
    transform.k >= 1.2;

  return (
    <div className="relative overflow-hidden rounded-lg border border-border bg-surface">
      <svg
        ref={svgRef}
        className="block h-full w-full touch-none select-none"
        viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
        role="img"
        aria-label="Knowledge Map: entidades y relaciones del negocio"
        data-testid="graph-canvas"
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          dragRef.current = {
            startX: event.clientX,
            startY: event.clientY,
            tx: transform.x,
            ty: transform.y,
          };
          const target = event.target as Element;
          (target as HTMLElement | SVGElement).setPointerCapture?.(event.pointerId);
        }}
        onPointerMove={(event) => {
          const drag = dragRef.current;
          if (!drag) return;
          setTransform((current) => ({
            ...current,
            x: drag.tx + (event.clientX - drag.startX),
            y: drag.ty + (event.clientY - drag.startY),
          }));
        }}
        onPointerUp={() => {
          dragRef.current = null;
        }}
      >
        <g transform={`translate(${transform.x},${transform.y}) scale(${transform.k})`}>
          {/* Aristas */}
          {edges.map((edge) => {
            const from = positionById.get(edge.from);
            const to = positionById.get(edge.to);
            if (!from || !to) return null;
            if (visibleIds && (!visibleIds.has(from.id) || !visibleIds.has(to.id))) {
              return null;
            }
            const color = provenanceColor(edge.provenance);
            const dashed =
              edge.type === "has_field" || edge.type === "synonym_of" || edge.type === "contains";
            return (
              <g key={edge.id}>
                <line
                  x1={from.x}
                  y1={from.y}
                  x2={to.x}
                  y2={to.y}
                  stroke={color}
                  strokeWidth={1.4}
                  strokeDasharray={dashed ? "5 4" : undefined}
                  strokeOpacity={0.55}
                  aria-hidden
                />
                {edge.type === "relationship" && transform.k >= 0.9 && (
                  <text
                    x={(from.x + to.x) / 2}
                    y={(from.y + to.y) / 2 - 5}
                    textAnchor="middle"
                    fontSize={9}
                    fill="var(--color-muted)"
                    style={{ pointerEvents: "none" }}
                  >
                    {edge.label}
                  </text>
                )}
              </g>
            );
          })}

          {/* Nodos */}
          {nodes.map((node) => {
            const selected = node.id === selectedId;
            const dimmed =
              visibleIds !== null &&
              visibleIds !== undefined &&
              !visibleIds.has(node.id);
            const color = provenanceColor(node.provenance);
            const radius = nodeRadius(node);
            return (
              <g
                key={node.id}
                role="button"
                tabIndex={0}
                aria-label={`${NODE_TYPE_LABELS[node.type]}: ${node.label}${
                  dimmed ? " (oculto por filtros)" : ""
                }`}
                data-testid={`graph-node-${node.id}`}
                className="cursor-pointer outline-none"
                opacity={dimmed ? 0.22 : 1}
                onPointerDown={(event) => event.stopPropagation()}
                onClick={(event) => {
                  event.stopPropagation();
                  onSelect(node.id);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelect(node.id);
                  }
                }}
              >
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={radius + (selected ? 4 : 0)}
                  fill={color}
                  fillOpacity={selected ? 1 : 0.55}
                  stroke={selected ? "var(--color-accent)" : "var(--color-border-strong)"}
                  strokeWidth={selected ? 2.5 : 1}
                />
                {labelVisible(node, selected) && (
                  <text
                    x={node.x}
                    y={node.y + radius + 11}
                    textAnchor="middle"
                    fontSize={node.type === "field" ? 8.5 : 10.5}
                    fontWeight={selected ? 600 : 450}
                    fill="var(--color-text)"
                    className="pointer-events-none"
                    style={{ paintOrder: "stroke", stroke: "var(--color-bg)", strokeWidth: 3 }}
                  >
                    {node.label.length > 28 ? `${node.label.slice(0, 26)}…` : node.label}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>

      {/* Controles flotantes */}
      <div className="absolute right-3 top-3 flex flex-col gap-1.5">
        <button
          type="button"
          className="btn btn-secondary min-h-8 w-8 justify-center px-0"
          aria-label="Acercar"
          data-testid="map-zoom-in"
          onClick={() => zoomBy(1.3)}
        >
          <MagnifyingGlassPlus size={14} aria-hidden />
        </button>
        <button
          type="button"
          className="btn btn-secondary min-h-8 w-8 justify-center px-0"
          aria-label="Alejar"
          data-testid="map-zoom-out"
          onClick={() => zoomBy(1 / 1.3)}
        >
          <MagnifyingGlassMinus size={14} aria-hidden />
        </button>
        <button
          type="button"
          className="btn btn-secondary min-h-8 w-8 justify-center px-0"
          aria-label="Reiniciar vista"
          data-testid="map-reset"
          onClick={resetView}
        >
          <SquareHalf size={14} aria-hidden />
        </button>
      </div>
    </div>
  );
}