import { NODE_H, NODE_W } from "../../lib/canvasViewport";
import type { LayoutDirection } from "../../lib/graphAutoLayout";
import type { GraphNode } from "../../lib/workflowGraph";

export type Point = { x: number; y: number };

/** Tipo MIME del drag-and-drop desde el catálogo de nodos al lienzo. */
export const NODE_DND_TYPE = "application/x-zent-node";
export type Positions = Map<string, Point>;

const PORT_TOP = 26;
const PORT_STEP = 22;
const PORT_SPREAD = 44;

/** Offset del puerto dentro del nodo (coordenadas locales). */
export function portOffset(index: number, count: number, side: "in" | "out", direction: LayoutDirection): Point {
  if (direction === "TB") {
    const x = NODE_W / 2 + (index - (count - 1) / 2) * PORT_SPREAD;
    return { x, y: side === "in" ? 0 : NODE_H };
  }
  return { x: side === "in" ? 0 : NODE_W, y: PORT_TOP + index * PORT_STEP };
}

export function portPoint(
  node: GraphNode | undefined,
  position: Point | undefined,
  port: string,
  side: "in" | "out",
  direction: LayoutDirection,
): Point {
  if (!node || !position) return { x: 0, y: 0 };
  const ports = side === "out" ? node.output_ports : node.input_ports;
  const idx = Math.max(0, ports.findIndex((p) => p.name === port));
  const off = portOffset(idx, Math.max(1, ports.length), side, direction);
  return { x: position.x + off.x, y: position.y + off.y };
}

/** Curva entre puertos; los retornos (loops) rodean por fuera en vez de cruzar el nodo. */
export function edgePath(a: Point, b: Point, direction: LayoutDirection): string {
  if (direction === "TB") {
    const backward = b.y < a.y + 20;
    const dy = backward ? 90 : Math.max(40, (b.y - a.y) / 2);
    return `M ${a.x} ${a.y} C ${a.x} ${a.y + dy}, ${b.x} ${b.y - dy}, ${b.x} ${b.y}`;
  }
  const backward = b.x < a.x + 20;
  const dx = backward ? 110 : Math.max(40, (b.x - a.x) / 2);
  return `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`;
}

export function wirePath(a: Point, b: Point, direction: LayoutDirection): string {
  if (direction === "TB") return `M ${a.x} ${a.y} C ${a.x} ${a.y + 60}, ${b.x} ${b.y - 60}, ${b.x} ${b.y}`;
  return `M ${a.x} ${a.y} C ${a.x + 60} ${a.y}, ${b.x - 60} ${b.y}, ${b.x} ${b.y}`;
}

/** Etiqueta legible de un puerto de rama. */
export function branchLabel(port: string): string | null {
  if (port === "then") return "sí";
  if (port === "else") return "no";
  if (port === "done") return "fin";
  return null;
}
