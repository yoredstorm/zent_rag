// =============================================================================
// MapCanvas — el lienzo del Knowledge Map con LOD real
// =============================================================================
// Solo se dibuja el nivel activo: dominios, temas, objetos o una entidad y su
// vecindario. Nunca el grafo completo. Hover = preview, click = inspeccionar,
// doble click = profundizar.
// =============================================================================
import { useState } from "react";
import { ArrowsOutSimple, Graph } from "@phosphor-icons/react";

import { cn } from "../ui";
import type { MapLayout, MapNode } from "./mapInsights";

const TONE_CLASS: Record<MapNode["tone"], string> = {
  accent: "km-tone-accent",
  info: "km-tone-info",
  muted: "km-tone-muted",
  warn: "km-tone-warn",
  ok: "km-tone-ok",
};

function metaLine(node: MapNode): string {
  const meta = node.meta ?? {};
  const parts: string[] = [];
  if (typeof meta.type === "string") parts.push(String(meta.type));
  if (typeof meta.status === "string") parts.push(String(meta.status));
  if (typeof meta.evidence_count === "number")
    parts.push(`${meta.evidence_count} evidencias`);
  if (typeof meta.confidence === "number")
    parts.push(`confianza ${Math.round(meta.confidence * 100)}%`);
  if (typeof meta.conflicts === "number" && meta.conflicts > 0)
    parts.push(`${meta.conflicts} conflictos`);
  return parts.join(" · ");
}

export function MapCanvas({
  layout,
  selectedId,
  onSelect,
  onDrill,
  pulse = false,
  emptyCopy,
}: {
  layout: MapLayout;
  selectedId: string | null;
  onSelect: (node: MapNode) => void;
  onDrill: (node: MapNode) => void;
  pulse?: boolean;
  emptyCopy?: string;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  const nodeById = new Map(layout.nodes.map((node) => [node.id, node]));
  const hoveredNode = hovered ? nodeById.get(hovered) ?? null : null;

  if (layout.nodes.length === 0) {
    return (
      <div className="km-empty" data-testid="knowledge-map-empty">
        <Graph size={22} className="text-faint" aria-hidden />
        <p className="max-w-[42ch] text-center text-[13px] leading-relaxed text-muted">
          {emptyCopy ??
            "Todavía no hay conocimiento en este nivel. Cuando ZENT aprenda de una fuente, los nodos aparecerán aquí."}
        </p>
      </div>
    );
  }

  return (
    <div className="km-canvas" data-testid="knowledge-map-canvas">
      <svg
        viewBox="0 0 100 62"
        className="km-svg"
        role="group"
        aria-label={`Knowledge Map: ${layout.nodes.length} nodos y ${layout.edges.length} relaciones en este nivel`}
      >
        <g>
          {layout.edges.map((edge) => {
            const from = nodeById.get(edge.source);
            const to = nodeById.get(edge.target);
            if (!from || !to) return null;
            return (
              <line
                key={edge.id}
                className="km-edge"
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
              >
                <title>{edge.label}</title>
              </line>
            );
          })}
        </g>
        <g>
          {layout.nodes.map((node) => {
            const selected = selectedId === node.id;
            const isHovered = hovered === node.id;
            const showLabel =
              layout.nodes.length <= 24 ||
              node.size >= 2.6 ||
              selected ||
              isHovered;
            return (
              <g
                key={node.id}
                className={cn(
                  "km-node",
                  TONE_CLASS[node.tone],
                  selected && "is-selected",
                  isHovered && "is-hovered"
                )}
                transform={`translate(${node.x} ${node.y})`}
                role="button"
                tabIndex={0}
                aria-label={`${node.label}, ${node.sublabel ?? ""}`}
                onMouseEnter={() => setHovered(node.id)}
                onMouseLeave={() => setHovered((value) => (value === node.id ? null : value))}
                onFocus={() => setHovered(node.id)}
                onBlur={() => setHovered((value) => (value === node.id ? null : value))}
                onClick={() => onSelect(node)}
                onDoubleClick={() => onDrill(node)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    onSelect(node);
                  }
                  if (event.key === " ") {
                    event.preventDefault();
                    onDrill(node);
                  }
                }}
              >
                {pulse && <circle r={node.size + 1.6} className="km-node-pulse" aria-hidden />}
                <circle r={node.size} className="km-node-dot" />
                {showLabel && (
                  <text className="km-node-label" y={node.size + 3.2} textAnchor="middle">
                    {node.label.length > 20 ? `${node.label.slice(0, 19)}…` : node.label}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>

      {hoveredNode && (
        <div className="km-hover" data-testid="knowledge-map-hover">
          <p className="text-[12px] font-medium text-text">{hoveredNode.label}</p>
          {hoveredNode.sublabel && (
            <p className="text-[11px] text-muted">{hoveredNode.sublabel}</p>
          )}
          {metaLine(hoveredNode) && (
            <p className="mt-0.5 text-[10px] text-faint">{metaLine(hoveredNode)}</p>
          )}
          <p className="mt-1 flex items-center gap-1 text-[10px] text-faint">
            <ArrowsOutSimple size={10} aria-hidden />
            Click para inspeccionar · doble click para profundizar
          </p>
        </div>
      )}

      <footer className="km-canvas-foot">
        <span className="km-legend">
          <span className="km-legend-dot km-tone-accent" /> conocimiento
        </span>
        <span className="km-legend">
          <span className="km-legend-dot km-tone-info" /> tema o relación
        </span>
        <span className="km-legend">
          <span className="km-legend-dot km-tone-warn" /> conflicto
        </span>
        <span className="text-[11px] text-faint">
          {layout.nodes.length} nodos · {layout.edges.length} relaciones visibles
        </span>
      </footer>
    </div>
  );
}

export default MapCanvas;
