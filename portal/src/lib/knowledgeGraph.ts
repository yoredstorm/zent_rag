// =============================================================================
// Knowledge Graph — tipos, fetch y layout determinista (FASE 33F)
// =============================================================================
// Sin dependencias nuevas: layout de fuerzas simple y determinista para
// grafos acotados (el endpoint limita nodos/aristas). El mapa nunca carga
// grafos enormes de golpe.
// =============================================================================
import { api } from "../api";

export type GraphNodeType =
  | "datasource"
  | "entity"
  | "field"
  | "metric"
  | "dimension"
  | "rule"
  | "synonym"
  | "verified_question";

export type GraphNode = {
  id: string;
  type: GraphNodeType;
  label: string;
  description: string;
  confidence: number;
  provenance: string;
  status: string;
  source_id: string | null;
  source_name: string | null;
  last_learned_at: string | null;
  validation_state: string;
  metadata: Record<string, unknown>;
};

export type GraphEdge = {
  id: string;
  type: string;
  from: string;
  to: string;
  label: string;
  confidence: number;
  provenance: string;
  status: string;
  cardinality: string | null;
  evidence: string[];
  evidence_detail: Array<Record<string, unknown>>;
  source_id: string | null;
  last_learned_at: string | null;
};

export type KnowledgeGraph = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  counts: { nodes: number; edges: number; by_type: Record<string, number> };
  truncated: boolean;
};

export const NODE_TYPE_LABELS: Record<GraphNodeType, string> = {
  datasource: "Fuente",
  entity: "Entidad",
  field: "Campo",
  metric: "Métrica",
  dimension: "Dimensión",
  rule: "Regla",
  synonym: "Sinónimo",
  verified_question: "Pregunta verificada",
};

export const NODE_TYPE_COLORS: Record<GraphNodeType, string> = {
  datasource: "var(--color-muted)",
  entity: "var(--color-accent)",
  field: "var(--color-info, var(--color-muted))",
  metric: "var(--color-ok)",
  dimension: "var(--color-warn)",
  rule: "var(--color-ok)",
  synonym: "var(--color-faint)",
  verified_question: "var(--color-accent)",
};

export function provenanceColor(provenance: string): string {
  if (provenance === "OBSERVED") return "var(--color-ok)";
  if (provenance === "APPROVED") return "var(--color-accent)";
  if (provenance === "REJECTED") return "var(--color-danger)";
  return "var(--color-warn)";
}

export function fetchKnowledgeGraph(params: {
  sourceId?: string;
  nodeTypes?: string[];
  q?: string;
  limitNodes?: number;
  limitEdges?: number;
}): Promise<KnowledgeGraph> {
  const query = new URLSearchParams();
  if (params.sourceId) query.set("source_id", params.sourceId);
  if (params.nodeTypes?.length) query.set("node_types", params.nodeTypes.join(","));
  if (params.q) query.set("q", params.q);
  query.set("limit_nodes", String(params.limitNodes ?? 200));
  query.set("limit_edges", String(params.limitEdges ?? 500));
  return api<KnowledgeGraph>(`/api/v1/knowledge/learning/graph?${query.toString()}`);
}

// ---------------------------------------------------------------------------
// Layout determinista (fuerzas simples, sin animación por frame)
// ---------------------------------------------------------------------------

export type PositionedNode = GraphNode & { x: number; y: number };

type LayoutOptions = {
  width?: number;
  height?: number;
  iterations?: number;
};

function hashUnit(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return ((hash >>> 0) % 1000) / 1000;
}

export function computeLayout(
  nodes: GraphNode[],
  edges: GraphEdge[],
  options: LayoutOptions = {}
): PositionedNode[] {
  const width = options.width ?? 960;
  const height = options.height ?? 620;
  const iterations = options.iterations ?? 90;
  if (nodes.length === 0) return [];

  const centerX = width / 2;
  const centerY = height / 2;
  const positions = new Map<string, { x: number; y: number }>();

  const entities = nodes.filter((node) => node.type === "entity");
  const entityIds = new Set(entities.map((entity) => entity.id));
  let entityCursor = 0;

  nodes.forEach((node, index) => {
    const jitterX = (hashUnit(node.id) - 0.5) * 40;
    const jitterY = (hashUnit(`${node.id}:y`) - 0.5) * 40;
    if (node.type === "datasource") {
      positions.set(node.id, { x: 90 + jitterX, y: centerY + jitterY });
      return;
    }
    if (node.type === "entity") {
      const angle = (entityCursor / Math.max(entities.length, 1)) * Math.PI * 2;
      const radius = Math.min(width, height) * 0.26;
      entityCursor += 1;
      positions.set(node.id, {
        x: centerX + Math.cos(angle) * radius + jitterX,
        y: centerY + Math.sin(angle) * radius * 0.8 + jitterY,
      });
      return;
    }
    // Campos alrededor de su entidad; resto en anillo exterior.
    const parentEdge = edges.find(
      (edge) => edge.to === node.id && entityIds.has(edge.from)
    );
    const parent = parentEdge ? positions.get(parentEdge.from) : null;
    if (parent) {
      const angle = (hashUnit(node.id) * Math.PI * 2 + index) % (Math.PI * 2);
      positions.set(node.id, {
        x: parent.x + Math.cos(angle) * 46,
        y: parent.y + Math.sin(angle) * 46,
      });
      return;
    }
    const angle = (index / nodes.length) * Math.PI * 2;
    const radius = Math.min(width, height) * 0.42;
    positions.set(node.id, {
      x: centerX + Math.cos(angle) * radius + jitterX,
      y: centerY + Math.sin(angle) * radius * 0.85 + jitterY,
    });
  });

  const indexById = new Map(nodes.map((node, index) => [node.id, index]));
  const linkPairs: Array<[number, number]> = [];
  for (const edge of edges) {
    const from = indexById.get(edge.from);
    const to = indexById.get(edge.to);
    if (from !== undefined && to !== undefined) linkPairs.push([from, to]);
  }

  const area = width * height;
  const ideal = Math.sqrt(area / Math.max(nodes.length, 1)) * 0.55;
  const points = nodes.map((node) => {
    const position = positions.get(node.id) ?? { x: centerX, y: centerY };
    return { x: position.x, y: position.y };
  });
  const weights = nodes.map((node) => {
    if (node.type === "datasource") return 1.6;
    if (node.type === "entity") return 1.3;
    if (node.type === "field") return 0.7;
    return 0.9;
  });

  for (let step = 0; step < iterations; step += 1) {
    const cooling = 1 - step / iterations;
    const fx = new Array<number>(points.length).fill(0);
    const fy = new Array<number>(points.length).fill(0);

    for (let i = 0; i < points.length; i += 1) {
      for (let j = i + 1; j < points.length; j += 1) {
        let dx = points[i].x - points[j].x;
        let dy = points[i].y - points[j].y;
        let distance = Math.sqrt(dx * dx + dy * dy);
        if (distance < 0.01) {
          dx = (hashUnit(`${nodes[i].id}${nodes[j].id}`) - 0.5) || 0.5;
          dy = 0.5;
          distance = 0.7;
        }
        const force = ((ideal * ideal) / distance) * 0.02;
        const ux = dx / distance;
        const uy = dy / distance;
        fx[i] += ux * force;
        fy[i] += uy * force;
        fx[j] -= ux * force;
        fy[j] -= uy * force;
      }
    }

    for (const [from, to] of linkPairs) {
      const dx = points[to].x - points[from].x;
      const dy = points[to].y - points[from].y;
      const distance = Math.max(Math.sqrt(dx * dx + dy * dy), 0.01);
      const desired = nodes[from].type === "entity" && nodes[to].type === "field" ? 60 : 120;
      const force = (distance - desired) * 0.018;
      const ux = dx / distance;
      const uy = dy / distance;
      fx[from] += ux * force;
      fy[from] += uy * force;
      fx[to] -= ux * force;
      fy[to] -= uy * force;
    }

    for (let i = 0; i < points.length; i += 1) {
      const weight = weights[i];
      fx[i] += (centerX - points[i].x) * 0.006 * weight;
      fy[i] += (centerY - points[i].y) * 0.006 * weight;
      points[i].x += fx[i] * cooling;
      points[i].y += fy[i] * cooling;
      points[i].x = Math.max(30, Math.min(width - 30, points[i].x));
      points[i].y = Math.max(30, Math.min(height - 30, points[i].y));
    }
  }

  return nodes.map((node, index) => ({
    ...node,
    x: points[index].x,
    y: points[index].y,
  }));
}

export function nodeRadius(node: GraphNode): number {
  if (node.type === "entity") return 20;
  if (node.type === "datasource") return 16;
  if (node.type === "field") return 8;
  if (node.type === "rule" || node.type === "metric") return 13;
  return 11;
}
