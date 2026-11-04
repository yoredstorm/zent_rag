import { memo } from "react";
import type { LayoutDirection } from "../../lib/graphAutoLayout";
import type { GraphEdge, GraphNode } from "../../lib/workflowGraph";
import type { RunMark } from "./CanvasNode";
import { edgePath, portPoint, type Positions } from "./geometry";

const WIRE_CLS: Record<string, string> = {
  succeeded: "stroke-ok",
  simulated: "stroke-info",
  failed: "stroke-danger",
  denied: "stroke-danger",
  skipped: "stroke-faint/30",
};

type Props = {
  edges: GraphEdge[];
  nodesById: Map<string, GraphNode>;
  positions: Positions;
  direction: LayoutDirection;
  selectedEdgeId: string | null;
  /** Nodos seleccionados: sus conexiones se resaltan para leer el flujo. */
  focusIds: ReadonlySet<string>;
  overlay?: Record<string, RunMark>;
  onSelectEdge: (id: string) => void;
};

function CanvasEdgesView({ edges, nodesById, positions, direction, selectedEdgeId, focusIds, overlay, onSelectEdge }: Props) {
  const anyFocus = focusIds.size > 0;
  return (
    <>
      {edges.map((e) => {
        const a = nodesById.get(e.from_node);
        const b = nodesById.get(e.to_node);
        if (!a || !b) return null;
        const d = edgePath(
          portPoint(a, positions.get(a.id), e.from_port, "out", direction),
          portPoint(b, positions.get(b.id), e.to_port, "in", direction),
          direction,
        );
        const selected = selectedEdgeId === e.id;
        const ran = overlay?.[e.from_node];
        const incident = focusIds.has(e.from_node) || focusIds.has(e.to_node);
        const stroke = selected
          ? "stroke-accent"
          : ran
            ? WIRE_CLS[ran.status] ?? "stroke-warn"
            : incident
              ? "stroke-accent/80"
              : "stroke-border-strong";
        return (
          <g
            key={e.id}
            className="cursor-pointer"
            data-edge-id={e.id}
            opacity={anyFocus && !incident && !selected ? 0.45 : 1}
            onPointerDown={(ev) => ev.stopPropagation()}
            onClick={(ev) => {
              ev.stopPropagation();
              onSelectEdge(e.id);
            }}
          >
            {ran && ran.status !== "skipped" && (
              <path d={d} fill="none" className={`${WIRE_CLS[ran.status] ?? "stroke-warn"} opacity-25`} strokeWidth={10} strokeLinecap="round" />
            )}
            <path d={d} fill="none" className={stroke} strokeWidth={selected ? 4 : incident ? 3 : 2.5} strokeLinecap="round" />
            <path d={d} fill="none" className="stroke-transparent" strokeWidth={16} />
          </g>
        );
      })}
    </>
  );
}

export const CanvasEdges = memo(CanvasEdgesView);
