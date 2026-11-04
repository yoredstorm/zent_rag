import type { GraphNode } from "./workflowGraph";
import { nodeMeta } from "./workflowGraph";

export type NodeSearchHit = { node: GraphNode; label: string; typeLabel: string; score: number };

function fold(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

/**
 * Busca nodos del lienzo por nombre, tipo (técnico o de negocio) o id.
 * Coincidencia exacta o de prefijo pesa más que una subcadena.
 */
export function searchGraphNodes(nodes: GraphNode[], query: string, limit = 30): NodeSearchHit[] {
  const q = fold(query.trim());
  const hits: NodeSearchHit[] = [];
  for (const node of nodes) {
    const meta = nodeMeta(node.type);
    const label = node.label || meta.label;
    const fields: [string, number][] = [
      [fold(label), 3],
      [fold(meta.label), 2],
      [fold(node.type), 2],
      [fold(node.id), 1],
    ];
    let score = 0;
    if (!q) score = 1;
    else {
      for (const [value, weight] of fields) {
        if (value === q) score = Math.max(score, weight * 10);
        else if (value.startsWith(q)) score = Math.max(score, weight * 5);
        else if (value.includes(q)) score = Math.max(score, weight * 2);
      }
    }
    if (score > 0) hits.push({ node, label, typeLabel: meta.label, score });
  }
  hits.sort((a, b) => b.score - a.score || a.label.localeCompare(b.label));
  return hits.slice(0, limit);
}
