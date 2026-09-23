// =============================================================================
// ExecutionRef — una ejecución es una query, un agent run o un workflow run (§27)
// =============================================================================
// La historia y la memoria no dependen exclusivamente de `query_id`: el backend
// publica el flow por tipo de ejecución y Memory Events acepta `run_id`.
//
// Helpers puros y testeables: el drawer sólo los consume.
import type { ImpactItem, QueryImpact } from "./MemoryImpact";

export type ExecutionRef = {
  kind: "query" | "agent" | "workflow";
  id: string;
};

export function executionRefOf(input: {
  queryId?: string;
  runId?: string;
  method?: string;
}): ExecutionRef | null {
  if (input.runId) {
    return { kind: input.method === "workflow" ? "workflow" : "agent", id: input.runId };
  }
  if (input.queryId) return { kind: "query", id: input.queryId };
  return null;
}

export function executionFlowPath(ref: ExecutionRef): string {
  return `/api/v1/executions/${ref.kind}/${ref.id}/flow`;
}

/** Endpoint de memoria según el tipo de ejecución (mismo contrato de datos). */
export function memoryImpactPath(ref: ExecutionRef): string | null {
  if (ref.kind === "query") return `/api/v1/memory/queries/${ref.id}/impact`;
  if (ref.kind === "agent") return `/api/v1/memory/runs/${ref.id}/impact`;
  // El workflow todavía no registra eventos de memoria por run: se declara
  // "no disponible" en vez de mostrar 0.
  return null;
}

/**
 * Normaliza el impacto de un run (buckets con listas, sin `counts`) al shape del
 * inspector. Un 0 sólo aparece cuando la consulta respondió y el bucket está
 * vacío; si no hay datos, se devuelve null (el estado lo declara el drawer).
 */
export function normalizeRunImpact(body: unknown, ref: ExecutionRef): QueryImpact | null {
  if (!body || typeof body !== "object") return null;
  const raw = body as Record<string, unknown>;
  const looksLikeRunImpact =
    ("used" in raw || "created" in raw || "reinforced" in raw) && !("counts" in raw);
  if (!looksLikeRunImpact) {
    const query = body as QueryImpact;
    return query?.counts ? query : null;
  }
  const bucket = (key: string): ImpactItem[] =>
    Array.isArray(raw[key]) ? (raw[key] as ImpactItem[]) : [];
  const used = bucket("used");
  const created = bucket("created");
  const reinforced = bucket("reinforced");
  const contradicted = bucket("contradicted");
  return {
    query_id: ref.id,
    truncated: raw.truncated === true,
    counts: {
      used: used.length,
      created: created.length,
      reinforced: reinforced.length,
      contradicted: contradicted.length,
      validated: 0,
    },
    used,
    created,
    reinforced,
    contradicted,
    validated: [],
  };
}
