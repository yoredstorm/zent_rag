/**
 * Auto-layout por capas (Sugiyama simplificado) para el canvas de workflows.
 *
 * Por qué no ELKjs/Dagre: ELK pesa ~1.4 MB y Dagre ~80 KB minificado sin
 * mantenimiento activo; los grafos de Zent rara vez pasan de 200 nodos y solo
 * necesitan capas + reducción de cruces. Este módulo hace exactamente eso en
 * O(V·E) y es determinista (mismo grafo, mismas posiciones).
 *
 * Solo cambia `position` de los nodos (y `metadata.canvas_direction`). Nunca
 * toca aristas, puertos ni configuración: reorganizar no altera el flujo.
 */
import type { GraphEdge, GraphNode, WorkflowGraph } from "./workflowGraph";
import { NODE_H, NODE_W, nodesBounds } from "./canvasViewport";

export type LayoutDirection = "LR" | "TB";

export const LAYOUT_GAP = {
  LR: { layer: 112, sibling: 40 },
  TB: { layer: 72, sibling: 48 },
} as const;

/** Orientación guardada con el grafo (las posiciones dependen de ella). */
export function graphDirection(graph: WorkflowGraph | null | undefined): LayoutDirection {
  return graph?.metadata?.canvas_direction === "TB" ? "TB" : "LR";
}

type Adjacency = { out: Map<string, GraphEdge[]>; inc: Map<string, GraphEdge[]> };

function adjacency(nodes: GraphNode[], edges: GraphEdge[]): Adjacency {
  const out = new Map<string, GraphEdge[]>();
  const inc = new Map<string, GraphEdge[]>();
  for (const n of nodes) {
    out.set(n.id, []);
    inc.set(n.id, []);
  }
  for (const e of edges) {
    if (!out.has(e.from_node) || !inc.has(e.to_node) || e.from_node === e.to_node) continue;
    out.get(e.from_node)!.push(e);
    inc.get(e.to_node)!.push(e);
  }
  return { out, inc };
}

/** Aristas que cierran ciclos (loops de reintento): se ignoran al asignar capas. */
function backEdges(nodes: GraphNode[], roots: string[], adj: Adjacency): Set<string> {
  const state = new Map<string, 0 | 1 | 2>();
  const back = new Set<string>();
  const visit = (start: string) => {
    const stack: { id: string; i: number }[] = [{ id: start, i: 0 }];
    state.set(start, 1);
    while (stack.length) {
      const top = stack[stack.length - 1];
      const outs = adj.out.get(top.id) ?? [];
      if (top.i >= outs.length) {
        state.set(top.id, 2);
        stack.pop();
        continue;
      }
      const e = outs[top.i++];
      const s = state.get(e.to_node) ?? 0;
      if (s === 1) back.add(e.id);
      else if (s === 0) {
        state.set(e.to_node, 1);
        stack.push({ id: e.to_node, i: 0 });
      }
    }
  };
  for (const r of roots) if ((state.get(r) ?? 0) === 0) visit(r);
  for (const n of nodes) if ((state.get(n.id) ?? 0) === 0) visit(n.id);
  return back;
}

function portIndex(node: GraphNode | undefined, port: string, side: "in" | "out"): number {
  if (!node) return 0;
  const ports = side === "out" ? node.output_ports : node.input_ports;
  return Math.max(0, ports.findIndex((p) => p.name === port));
}

export type LayoutResult = { graph: WorkflowGraph; layers: string[][] };

export function autoLayout(graph: WorkflowGraph, direction: LayoutDirection = "LR"): LayoutResult {
  const nodes = graph.nodes;
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const adj = adjacency(nodes, graph.edges);
  const roots = [
    ...graph.entrypoints.filter((id) => byId.has(id)),
    ...nodes.filter((n) => n.type.startsWith("trigger_")).map((n) => n.id),
  ];
  const back = backEdges(nodes, roots, adj);
  const forward = graph.edges.filter((e) => !back.has(e.id) && byId.has(e.from_node) && byId.has(e.to_node) && e.from_node !== e.to_node);

  const isolated = new Set(
    nodes
      .filter((n) => (adj.out.get(n.id)?.length ?? 0) === 0 && (adj.inc.get(n.id)?.length ?? 0) === 0 && !roots.includes(n.id))
      .map((n) => n.id),
  );

  // Capas por camino más largo (Kahn sobre el DAG sin aristas de retorno).
  const indeg = new Map<string, number>(nodes.map((n) => [n.id, 0]));
  for (const e of forward) indeg.set(e.to_node, (indeg.get(e.to_node) ?? 0) + 1);
  const layer = new Map<string, number>();
  const queue = nodes.filter((n) => (indeg.get(n.id) ?? 0) === 0 && !isolated.has(n.id)).map((n) => n.id);
  // Los triggers/entrypoints arrancan primero para fijar el orden inicial.
  queue.sort((a, b) => Number(roots.includes(b)) - Number(roots.includes(a)));
  for (const id of queue) layer.set(id, 0);
  const order: string[] = [];
  while (queue.length) {
    const id = queue.shift()!;
    order.push(id);
    for (const e of forward.filter((x) => x.from_node === id)) {
      layer.set(e.to_node, Math.max(layer.get(e.to_node) ?? 0, (layer.get(id) ?? 0) + 1));
      indeg.set(e.to_node, (indeg.get(e.to_node) ?? 0) - 1);
      if (indeg.get(e.to_node) === 0) queue.push(e.to_node);
    }
  }

  const layerCount = Math.max(0, ...[...layer.values()].map((l) => l + 1));
  const layers: string[][] = Array.from({ length: layerCount }, () => []);
  for (const id of order) layers[layer.get(id) ?? 0].push(id);

  // Reducción de cruces: barycenter alternando barridos hacia abajo y arriba.
  const pos = new Map<string, number>();
  const reindex = () => layers.forEach((ids) => ids.forEach((id, i) => pos.set(id, i)));
  reindex();
  const preds = (id: string) => forward.filter((e) => e.to_node === id);
  const succs = (id: string) => forward.filter((e) => e.from_node === id);
  const bary = (id: string, down: boolean): number | null => {
    const links = down ? preds(id) : succs(id);
    if (links.length === 0) return null;
    let sum = 0;
    for (const e of links) {
      const other = down ? e.from_node : e.to_node;
      const port = down ? portIndex(byId.get(e.from_node), e.from_port, "out") : portIndex(byId.get(e.to_node), e.to_port, "in");
      sum += (pos.get(other) ?? 0) + port * 0.01;
    }
    return sum / links.length;
  };
  for (let sweep = 0; sweep < 6; sweep += 1) {
    const down = sweep % 2 === 0;
    const range = down ? layers.map((_, i) => i).slice(1) : layers.map((_, i) => i).slice(0, -1).reverse();
    for (const li of range) {
      const current = layers[li];
      const keyed = current.map((id, i) => ({ id, key: bary(id, down) ?? i, i }));
      keyed.sort((a, b) => a.key - b.key || a.i - b.i);
      layers[li] = keyed.map((k) => k.id);
      reindex();
    }
  }

  // Coordenadas: eje de capa fijo; eje transversal alineado al promedio de
  // predecesores sin solaparse (pasada hacia adelante + compactación).
  const gap = LAYOUT_GAP[direction];
  const along = direction === "LR" ? NODE_W + gap.layer : NODE_H + gap.layer;
  const pitch = direction === "LR" ? NODE_H + gap.sibling : NODE_W + gap.sibling;
  const cross = new Map<string, number>();
  layers.forEach((ids, li) => {
    const desired = ids.map((id, i) => {
      if (li === 0) return i * pitch;
      const ps = preds(id).map((e) => cross.get(e.from_node)).filter((v): v is number => v !== undefined);
      return ps.length ? ps.reduce((a, b) => a + b, 0) / ps.length : i * pitch;
    });
    const placed: number[] = [];
    desired.forEach((d, i) => {
      placed[i] = i === 0 ? d : Math.max(d, placed[i - 1] + pitch);
    });
    // Si la pasada empujó todo hacia abajo, recentrar el bloque en su deseo medio.
    const shift = desired.reduce((a, b) => a + b, 0) / Math.max(1, desired.length) - placed.reduce((a, b) => a + b, 0) / Math.max(1, placed.length);
    ids.forEach((id, i) => cross.set(id, placed[i] + Math.min(0, shift)));
  });

  const minCross = Math.min(0, ...cross.values());
  const before = nodesBounds(nodes) ?? { x: 0, y: 0, w: 0, h: 0 };
  const origin = { x: Number.isFinite(before.x) ? before.x : 0, y: Number.isFinite(before.y) ? before.y : 0 };
  const positions = new Map<string, { x: number; y: number }>();
  layers.forEach((ids, li) =>
    ids.forEach((id) => {
      const c = (cross.get(id) ?? 0) - minCross;
      positions.set(
        id,
        direction === "LR"
          ? { x: Math.round(origin.x + li * along), y: Math.round(origin.y + c) }
          : { x: Math.round(origin.x + c), y: Math.round(origin.y + li * along) },
      );
    }),
  );

  // Nodos sueltos: fila/columna aparte para no mezclarlos con el flujo.
  if (isolated.size) {
    const placedBounds = nodesBounds([...positions.values()].map((p) => ({ position: p }))) ?? { x: origin.x, y: origin.y, w: 0, h: 0 };
    [...isolated].forEach((id, i) => {
      positions.set(
        id,
        direction === "LR"
          ? { x: Math.round(origin.x + i * (NODE_W + gap.sibling)), y: Math.round(placedBounds.y + placedBounds.h + 96) }
          : { x: Math.round(placedBounds.x + placedBounds.w + 96), y: Math.round(origin.y + i * (NODE_H + gap.sibling)) },
      );
    });
  }

  const next: WorkflowGraph = {
    ...graph,
    nodes: nodes.map((n) => ({ ...n, position: positions.get(n.id) ?? n.position })),
    edges: graph.edges,
    metadata: { ...graph.metadata, canvas_direction: direction },
  };
  return { graph: next, layers };
}

// ---------------------------------------------------------------------------
// Métricas (tests y diagnóstico)
// ---------------------------------------------------------------------------

type Seg = { a: { x: number; y: number }; b: { x: number; y: number }; from: string; to: string };

function segments(graph: WorkflowGraph, direction: LayoutDirection): Seg[] {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const out: Seg[] = [];
  for (const e of graph.edges) {
    const a = byId.get(e.from_node);
    const b = byId.get(e.to_node);
    if (!a || !b) continue;
    out.push({
      a: direction === "LR" ? { x: a.position.x + NODE_W, y: a.position.y + NODE_H / 2 } : { x: a.position.x + NODE_W / 2, y: a.position.y + NODE_H },
      b: direction === "LR" ? { x: b.position.x, y: b.position.y + NODE_H / 2 } : { x: b.position.x + NODE_W / 2, y: b.position.y },
      from: e.from_node,
      to: e.to_node,
    });
  }
  return out;
}

function cross2(o: { x: number; y: number }, a: { x: number; y: number }, b: { x: number; y: number }) {
  return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
}

/** Cruces de aristas como segmentos rectos entre puertos (aproximación). */
export function countEdgeCrossings(graph: WorkflowGraph, direction: LayoutDirection = graphDirection(graph)): number {
  const segs = segments(graph, direction);
  let count = 0;
  for (let i = 0; i < segs.length; i += 1) {
    for (let j = i + 1; j < segs.length; j += 1) {
      const s = segs[i];
      const t = segs[j];
      if ([s.from, s.to].some((id) => id === t.from || id === t.to)) continue;
      const d1 = cross2(t.a, t.b, s.a);
      const d2 = cross2(t.a, t.b, s.b);
      const d3 = cross2(s.a, s.b, t.a);
      const d4 = cross2(s.a, s.b, t.b);
      if (d1 * d2 < 0 && d3 * d4 < 0) count += 1;
    }
  }
  return count;
}

/** Pares de nodos cuyas cajas se solapan. */
export function countNodeOverlaps(graph: WorkflowGraph): number {
  let count = 0;
  const ns = graph.nodes;
  for (let i = 0; i < ns.length; i += 1) {
    for (let j = i + 1; j < ns.length; j += 1) {
      const a = ns[i].position;
      const b = ns[j].position;
      if (Math.abs(a.x - b.x) < NODE_W && Math.abs(a.y - b.y) < NODE_H) count += 1;
    }
  }
  return count;
}
