// =============================================================================
// learningInsights — derivaciones puras de la sesión de aprendizaje
// =============================================================================
// Todo sale de eventos reales + detalle durable. Nada se inventa: si un dato
// no está en el evento o en el detalle, no se muestra.
// =============================================================================
import type {
  LearningSessionDetail,
  SessionEvent,
  SessionSource,
} from "../../lib/knowledgeSessions";

export type TaxonomyKey =
  | "new"
  | "reinforced"
  | "updated"
  | "related"
  | "conflicting"
  | "ignored";

export const TAXONOMY_KEYS: TaxonomyKey[] = [
  "new",
  "reinforced",
  "updated",
  "related",
  "conflicting",
  "ignored",
];

export function taxonomyCounts(
  delta: Record<string, number>
): Record<TaxonomyKey, number> {
  return {
    new:
      (delta.new_entities ?? 0) +
      (delta.new_facts ?? 0) +
      (delta.new_relationships ?? 0) +
      (delta.new_rules ?? 0) +
      (delta.new_evidence ?? 0),
    reinforced: (delta.reinforced_facts ?? 0) + (delta.enriched_entities ?? 0),
    updated: delta.updated ?? 0,
    related: delta.related ?? 0,
    conflicting: delta.conflicts ?? 0,
    ignored: delta.ignored ?? 0,
  };
}

// ---------------------------------------------------------------------------
// Momentos importantes (hitos): solo eventos de alto valor, deduplicados
// ---------------------------------------------------------------------------

export type MilestoneKind =
  | "discovery"
  | "connection"
  | "merge"
  | "version"
  | "conflict"
  | "rule"
  | "available"
  | "completed";

export interface Milestone {
  id: string;
  kind: MilestoneKind;
  title: string;
  detail?: string;
  at: string | null;
  severity: "info" | "success" | "warning";
}

function payloadOf(event: SessionEvent): Record<string, unknown> {
  return (event.payload ?? {}) as Record<string, unknown>;
}

function countOf(event: SessionEvent): number {
  return Math.max(1, Number(payloadOf(event).count ?? 1));
}

function firstString(data: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    const value = data[key];
    if (value !== undefined && value !== null && value !== "") return String(value);
  }
  return "";
}

/**
 * Hitos reales de la sesión. Deduplica por tipo y conserva el más
 * significativo (mayor conteo o más reciente), con un máximo de 4.
 */
export function deriveMilestones(
  events: SessionEvent[],
  detail: LearningSessionDetail | null,
  limit = 4
): Milestone[] {
  const candidates: Milestone[] = [];

  for (const event of events) {
    const data = payloadOf(event);
    const count = countOf(event);
    const at = event.created_at ?? null;
    switch (event.event_type) {
      case "ENTITY_DISCOVERED":
        if (count >= 20) {
          candidates.push({
            id: `discovery-${event.seq}`,
            kind: "discovery",
            title: `ZENT descubrió ${count.toLocaleString("es-PE")} entidades nuevas`,
            detail: "El conocimiento de tu empresa creció con esta fuente.",
            at,
            severity: "success",
          });
        }
        break;
      case "RELATIONSHIP_DISCOVERED":
        if (data.related === true) {
          const subject = firstString(data, "subject");
          const object = firstString(data, "object", "object_name");
          candidates.push({
            id: `connection-${event.seq}`,
            kind: "connection",
            title:
              subject && object
                ? `ZENT conectó dos áreas que ya conocía: ${subject} y ${object}`
                : "ZENT conectó dos áreas que ya conocía",
            detail: "Una relación nueva entre conocimiento existente.",
            at,
            severity: "success",
          });
        }
        break;
      case "ENTITY_MERGED": {
        const merged = firstString(data, "merged_alias", "name");
        const canonical = firstString(data, "canonical_name");
        candidates.push({
          id: `merge-${event.seq}`,
          kind: "merge",
          title:
            merged && canonical
              ? `ZENT consolidó ${merged} con ${canonical}`
              : "ZENT consolidó entidades duplicadas",
          detail: "No se duplicó conocimiento: se reforzó el nodo existente.",
          at,
          severity: "info",
        });
        break;
      }
      case "CONFLICT_DETECTED": {
        const type = firstString(data, "conflict_type");
        const isVersion = type === "VERSION_CHANGE" || type === "TEMPORAL_CHANGE";
        const subject = firstString(data, "subject", "subject_label");
        candidates.push({
          id: `conflict-${event.seq}`,
          kind: isVersion ? "version" : "conflict",
          title: isVersion
            ? subject
              ? `Nueva versión detectada: ${subject}`
              : "Nueva versión detectada"
            : subject
              ? `Posible inconsistencia en ${subject}`
              : "ZENT detectó una posible inconsistencia",
          detail: isVersion
            ? "ZENT compara versiones y deja la decisión a un humano."
            : "Queda en revisión; el resto del conocimiento está disponible.",
          at,
          severity: "warning",
        });
        break;
      }
      case "RULE_DISCOVERED":
        if (count >= 10) {
          candidates.push({
            id: `rule-${event.seq}`,
            kind: "rule",
            title: `ZENT aprendió ${count.toLocaleString("es-PE")} reglas de negocio`,
            detail: "Reglas verificables con evidencia de la fuente.",
            at,
            severity: "success",
          });
        }
        break;
      case "SOURCE_AVAILABLE": {
        const name = firstString(data, "name", "filename");
        candidates.push({
          id: `available-${event.seq}`,
          kind: "available",
          title: name
            ? `${name} ya puede responder preguntas`
            : "Una fuente ya puede responder preguntas",
          detail: "El conocimiento está disponible mientras ZENT sigue conectando.",
          at,
          severity: "success",
        });
        break;
      }
      default:
        break;
    }
  }

  if (detail && ["completed", "partial"].includes(detail.status)) {
    candidates.push({
      id: "completed",
      kind: "completed",
      title:
        detail.status === "partial"
          ? "ZENT aprendió esta información (con puntos por revisar)"
          : "ZENT aprendió esta información",
      detail: `${detail.completed_sources} de ${detail.source_count} fuentes comprendidas.`,
      at: detail.completed_at,
      severity: detail.status === "partial" ? "warning" : "success",
    });
  }

  const priority: Record<MilestoneKind, number> = {
    connection: 6,
    version: 5,
    conflict: 4,
    merge: 3,
    discovery: 2,
    rule: 2,
    available: 1,
    completed: 0,
  };
  const byKind = new Map<MilestoneKind, Milestone>();
  for (const milestone of candidates) {
    const previous = byKind.get(milestone.kind);
    if (!previous) {
      byKind.set(milestone.kind, milestone);
      continue;
    }
    const previousAt = previous.at ? Date.parse(previous.at) : 0;
    const nextAt = milestone.at ? Date.parse(milestone.at) : 0;
    if (nextAt >= previousAt) byKind.set(milestone.kind, milestone);
  }
  return [...byKind.values()]
    .sort((a, b) => {
      const pa = priority[a.kind] ?? 0;
      const pb = priority[b.kind] ?? 0;
      if (pa !== pb) return pb - pa;
      const ta = a.at ? Date.parse(a.at) : 0;
      const tb = b.at ? Date.parse(b.at) : 0;
      return tb - ta;
    })
    .slice(0, limit);
}

// ---------------------------------------------------------------------------
// Reencuentros con conocimiento existente
// ---------------------------------------------------------------------------

export interface KnowledgeMatch {
  id: string;
  name: string;
  entityType: string;
  kind: "matched" | "merged";
  canonical?: string;
  at: string | null;
}

export function deriveMatches(events: SessionEvent[]): {
  matches: KnowledgeMatch[];
  matched: number;
  merged: number;
} {
  const matches: KnowledgeMatch[] = [];
  let matched = 0;
  let merged = 0;
  for (const event of events) {
    const data = payloadOf(event);
    const count = countOf(event);
    if (event.event_type === "ENTITY_MATCHED") {
      matched += count;
      const items = Array.isArray(data.items)
        ? (data.items as Array<Record<string, unknown>>)
        : [data];
      for (const item of items.slice(0, 3)) {
        const name = firstString(item, "name");
        if (!name) continue;
        matches.push({
          id: `matched-${event.seq}-${name}`,
          name,
          entityType: firstString(item, "entity_type"),
          kind: "matched",
          at: event.created_at ?? null,
        });
      }
    }
    if (event.event_type === "ENTITY_MERGED") {
      merged += count;
      const merged_alias = firstString(data, "merged_alias", "name");
      if (merged_alias) {
        matches.push({
          id: `merged-${event.seq}-${merged_alias}`,
          name: merged_alias,
          entityType: firstString(data, "alias_type"),
          kind: "merged",
          canonical: firstString(data, "canonical_name") || undefined,
          at: event.created_at ?? null,
        });
      }
    }
  }
  const seen = new Set<string>();
  const unique = matches.filter((match) => {
    const key = `${match.kind}-${match.name}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  return { matches: unique.slice(-24).reverse(), matched, merged };
}

// ---------------------------------------------------------------------------
// Etapas cognitivas: estado + detalle técnico real
// ---------------------------------------------------------------------------

export interface StageItem {
  label: string;
  value: string;
}

export interface StageInsight {
  key: string;
  label: string;
  technical: string | null;
  state: "done" | "current" | "pending";
  items: StageItem[];
}

const STAGE_ORDER = [
  "reading",
  "understanding",
  "organizing",
  "connecting",
  "verifying",
  "learned",
];

const STAGE_ITEMS: Record<string, Array<[string, string]>> = {
  reading: [
    ["pages", "páginas"],
    ["sections", "secciones"],
    ["bytes", "bytes leídos"],
    ["records", "registros"],
  ],
  understanding: [["semantic_units", "unidades semánticas"]],
  organizing: [
    ["entities_new", "entidades nuevas"],
    ["tables", "tablas"],
    ["columns", "columnas"],
    ["sheets", "hojas"],
    ["candidate_keys", "claves candidatas"],
  ],
  connecting: [
    ["relationships", "relaciones"],
    ["relationships_related", "relaciones entre conocimiento existente"],
    ["merges", "fusiones"],
  ],
  verifying: [
    ["evidence", "evidencias"],
    ["conflicts", "conflictos"],
    ["duplicates", "duplicados"],
  ],
  learned: [
    ["chunks", "fragmentos organizados"],
    ["sources_available", "fuentes consultables"],
  ],
};

export function deriveStageInsights(
  stages: LearningSessionDetail["stages"],
  metrics: Record<string, number>,
  currentStage: string,
  finished: boolean
): StageInsight[] {
  const currentIndex = Math.max(0, STAGE_ORDER.indexOf(currentStage));
  return stages.map((stage) => {
    const index = STAGE_ORDER.indexOf(stage.key);
    const state =
      finished || (index >= 0 && index < currentIndex)
        ? "done"
        : index === currentIndex
          ? "current"
          : "pending";
    const items = (STAGE_ITEMS[stage.key] ?? [])
      .map(([key, label]) => ({
        label,
        value: (metrics[key] ?? 0).toLocaleString("es-PE"),
      }))
      .filter((item) => item.value !== "0");
    return {
      key: stage.key,
      label: stage.label,
      technical: stage.technical ?? null,
      state,
      items,
    };
  });
}

// ---------------------------------------------------------------------------
// Estructura tabular reconocida por fuente
// ---------------------------------------------------------------------------

export function deriveRecognizedTables(
  events: SessionEvent[],
  sourceId: string | null
): string[] {
  const names = new Set<string>();
  for (const event of events) {
    if (event.event_type !== "TABLE_DETECTED") continue;
    if (sourceId && event.source_id !== sourceId) continue;
    const data = payloadOf(event);
    const name = firstString(data, "table", "name");
    if (name && !/adicionales/i.test(name)) names.add(name);
  }
  return [...names].slice(0, 8);
}

// ---------------------------------------------------------------------------
// Resumen técnico
// ---------------------------------------------------------------------------

export function sessionDurationMs(
  detail: LearningSessionDetail | null
): number | null {
  if (!detail?.started_at) return null;
  const end = detail.completed_at
    ? Date.parse(detail.completed_at)
    : detail.updated_at
      ? Date.parse(detail.updated_at)
      : Date.now();
  const start = Date.parse(detail.started_at);
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return null;
  return end - start;
}

export function eventCountsByType(
  events: SessionEvent[]
): Array<{ type: string; count: number }> {
  const counts = new Map<string, number>();
  for (const event of events) {
    const total = countOf(event);
    counts.set(event.event_type, (counts.get(event.event_type) ?? 0) + total);
  }
  return [...counts.entries()]
    .map(([type, count]) => ({ type, count }))
    .sort((a, b) => b.count - a.count);
}

export function sourceTechnicalRows(sources: SessionSource[]): Array<{
  id: string;
  name: string;
  status: string;
  jobId: string | null;
  sourceId: string | null;
  error: string | null;
}> {
  return sources.map((source) => ({
    id: source.id,
    name: source.name,
    status: source.status,
    jobId: source.job_id,
    sourceId: source.source_id,
    error: source.error,
  }));
}
